"""
Volume ratio distribution report for scan debugging.
- Histogram of volume_ratio in the signal dataset
- Quantiles (10, 25, 50, 75, 90)
- Surviving trade counts for thresholds 0.8, 1.0, 1.2, 1.4, 1.6 (rows with volume_ratio >= t and valid R)

Usage:
  python -m analysis.volume_ratio_report --from-db [--symbol BTCUSDT --limit 50000]
  python -m analysis.volume_ratio_report --candidates-csv path/to/candidates.csv
  Output: analysis/output/volume_ratio_histogram.png, volume_ratio_report.txt
"""
import argparse
import csv
import sys
from pathlib import Path
from typing import List, Tuple

import numpy as np

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

VOLUME_THRESHOLDS = [0.8, 1.0, 1.2, 1.4, 1.6]
QUANTILES = [10, 25, 50, 75, 90]


def _get_float(r: dict, key: str, default: float = 0.0) -> float:
    val = r.get(key)
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _has_r(row: dict, r_key: str = "R_return") -> bool:
    val = row.get(r_key) or row.get("future_r_30")
    if val is None or val == "":
        return False
    try:
        float(val)
        return True
    except (TypeError, ValueError):
        return False


def compute_distribution(rows: list, r_key: str = "R_return") -> Tuple[List[float], List[dict]]:
    """Extract volume_ratio values and compute stats. Returns (values_list, list of {threshold, surviving_count})."""
    values = []
    for r in rows:
        v = _get_float(r, "volume_ratio")
        if v is not None and v >= 0:  # allow 0
            values.append(v)

    surviving = []
    for t in VOLUME_THRESHOLDS:
        count = sum(1 for r in rows if _get_float(r, "volume_ratio") >= t and _has_r(r, r_key))
        surviving.append({"threshold": t, "surviving_trades": count})
    return values, surviving


def run_report(rows: list, output_dir: Path, r_key: str = "R_return") -> None:
    """Generate histogram PNG and report TXT."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    values, surviving = compute_distribution(rows, r_key=r_key)
    arr = np.array(values) if values else np.array([0.0])

    # Quantiles
    q_vals = {}
    if len(arr) > 0:
        for q in QUANTILES:
            q_vals[q] = float(np.percentile(arr, q))

    # Report text
    lines = [
        "Volume ratio distribution report",
        "=" * 50,
        f"Total rows with volume_ratio: {len(values)}",
        "",
        "Quantiles (%)",
        "-" * 30,
    ]
    for q in QUANTILES:
        lines.append(f"  {q}%: {q_vals.get(q, 0):.4f}")
    lines.extend([
        "",
        "Surviving trade counts (rows with R_return/future_r_30 and volume_ratio >= threshold)",
        "-" * 30,
    ])
    for s in surviving:
        lines.append(f"  volume_ratio >= {s['threshold']}: {s['surviving_trades']} trades")
    lines.append("")
    if len(values) == 0:
        lines.append("No volume_ratio data — check that candidate signals have volume_ratio in feature_values_ext or columns.")
    elif q_vals.get(50, 0) < 0.8:
        lines.append("Median volume_ratio < 0.8 → most signals fail vol>=0.8; thresholds 0.8/1.0/1.2 may leave same subset.")
    else:
        lines.append("If surviving counts are identical across thresholds, volume_ratio may be missing or constant in dataset.")

    report_path = output_dir / "volume_ratio_report.txt"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {report_path}")

    # Histogram
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return

    fig, ax = plt.subplots()
    if len(arr) > 0:
        ax.hist(arr, bins=50, edgecolor="black", alpha=0.7)
        for t in VOLUME_THRESHOLDS:
            ax.axvline(t, color="red", linestyle="--", alpha=0.7)
    ax.set_xlabel("volume_ratio")
    ax.set_ylabel("Count")
    ax.set_title("Volume ratio distribution (red = thresholds 0.8, 1.0, 1.2, 1.4, 1.6)")
    hist_path = output_dir / "volume_ratio_histogram.png"
    plt.tight_layout()
    plt.savefig(hist_path, dpi=100)
    plt.close()
    print(f"Wrote {hist_path}")


def main():
    parser = argparse.ArgumentParser(description="Volume ratio distribution report for scan debugging")
    parser.add_argument("--from-db", action="store_true", help="Load from DB (candidate_signals + signal_outcomes)")
    parser.add_argument("--candidates-csv", type=str, default="", help="Path to candidates CSV")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--limit", type=int, default=50000)
    parser.add_argument("--output-dir", type=str, default="analysis/output")
    args = parser.parse_args()

    if args.from_db:
        from storage.database import SessionLocal, init_db
        from storage.repositories import get_candidate_signals_with_outcomes
        init_db()
        db = SessionLocal()
        try:
            rows = get_candidate_signals_with_outcomes(db, symbol=args.symbol, limit=args.limit)
        finally:
            db.close()
        r_key = "future_r_30"
    elif args.candidates_csv:
        path = Path(args.candidates_csv)
        if not path.exists():
            print(f"CSV not found: {path}", file=sys.stderr)
            sys.exit(1)
        rows = []
        with open(path, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows.append(r)
        r_key = "R_return"
    else:
        parser.error("Provide --from-db or --candidates-csv")
        return

    if not rows:
        print("No rows loaded.", file=sys.stderr)
        sys.exit(1)

    run_report(rows, Path(args.output_dir), r_key=r_key)


if __name__ == "__main__":
    main()
