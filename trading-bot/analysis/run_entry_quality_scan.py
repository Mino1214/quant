"""
Phase 4 — Entry quality tuning: scan over momentum, pullback, wick, breakout filters.

Uses baseline ema/vol/rsi; varies entry-quality thresholds and records
total_candidates, after_momentum_filter, after_pullback_filter, after_wick_filter,
after_breakout_filter, final_trades plus metrics (trades, winrate, avg_R, PF, max_dd).

Usage:
  python -m analysis.run_entry_quality_scan --from-db [--output-dir analysis/output]
  python -m analysis.run_entry_quality_scan --candidates-csv path/to/candidates.csv

Outputs:
  {output_dir}/entry_quality_scan.csv
  {output_dir}/entry_quality_debug.csv
  {output_dir}/entry_quality_heatmaps/  (2D slices: avg_R by momentum vs pullback, etc.)
"""
import argparse
import csv
import sys
from pathlib import Path

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.stability_map import (
    _filter_by_thresholds_with_debug,
    metrics_for_rows,
)
from analysis.store_loader import load_rows_from_store


# Baseline from Phase 1 (fixed for entry-quality scan)
BASELINE_EMA = 0.0004
BASELINE_VOL = 1.4
BASELINE_RSI = 45.0


def load_candidates_csv(path: Path) -> list:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def load_candidates_db(symbol: str = "BTCUSDT", limit: int = 10000, signals_table: str = "candidate_signals") -> list:
    """Load rows from feature_store_1m + outcome_store_1m if available, else candidate_signals."""
    try:
        rows = load_rows_from_store(symbol=symbol, limit=limit, feature_version=1)
        if rows:
            return rows
    except Exception:
        pass
    from storage.database import SessionLocal, init_db
    from storage.repositories import get_candidate_signals_with_outcomes

    init_db()
    db = SessionLocal()
    try:
        return get_candidate_signals_with_outcomes(db, symbol=symbol, limit=limit, signals_table=signals_table)
    finally:
        db.close()


def run_entry_quality_scan(
    rows: list,
    momentum_values: list,
    pullback_min_values: list,
    pullback_max_values: list,
    upper_wick_values: list,
    lower_wick_values: list,
    breakout_values: list,
    r_key: str = "future_r_30",
    r_cap: float = 20.0,
) -> tuple[list, list]:
    """
    Scan over entry-quality params (baseline ema/vol/rsi fixed). Returns (scan_results, debug_rows).
    """
    ema_t, vol_t, rsi_t = BASELINE_EMA, BASELINE_VOL, BASELINE_RSI
    scan_results = []
    debug_rows = []
    for momentum_t in momentum_values:
        for pullback_min in pullback_min_values:
            for pullback_max in pullback_max_values:
                for upper_wick_max in upper_wick_values:
                    for lower_wick_max in lower_wick_values:
                        for breakout_req in breakout_values:
                            filtered, debug = _filter_by_thresholds_with_debug(
                                rows, ema_t, vol_t, rsi_t,
                                use_trend_filter=False,
                                momentum_ratio_threshold=momentum_t,
                                pullback_depth_min=pullback_min,
                                pullback_depth_max=pullback_max,
                                upper_wick_ratio_max=upper_wick_max,
                                lower_wick_ratio_max=lower_wick_max,
                                breakout_confirmation_required=breakout_req,
                            )
                            m = metrics_for_rows(filtered, r_key=r_key, r_cap=r_cap)
                            scan_results.append({
                                "momentum_ratio_threshold": momentum_t,
                                "pullback_depth_min": pullback_min,
                                "pullback_depth_max": pullback_max,
                                "upper_wick_ratio_max": upper_wick_max,
                                "lower_wick_ratio_max": lower_wick_max,
                                "breakout_confirmation_required": breakout_req,
                                "trades": m["trades"],
                                "winrate": m["winrate"],
                                "avg_R": m["avg_R"],
                                "profit_factor": m["profit_factor"],
                                "max_drawdown": m["max_drawdown"],
                            })
                            debug_rows.append({
                                "momentum_ratio_threshold": momentum_t,
                                "pullback_depth_min": pullback_min,
                                "pullback_depth_max": pullback_max,
                                "upper_wick_ratio_max": upper_wick_max,
                                "lower_wick_ratio_max": lower_wick_max,
                                "breakout_confirmation_required": breakout_req,
                                "total_candidates": debug["total_candidates"],
                                "after_momentum_filter": debug["after_momentum_filter"],
                                "after_pullback_filter": debug["after_pullback_filter"],
                                "after_wick_filter": debug["after_wick_filter"],
                                "after_breakout_filter": debug["after_breakout_filter"],
                                "final_trades": debug["final_trades"],
                            })
    return scan_results, debug_rows


def write_heatmaps(scan_results: list, out_dir: Path) -> None:
    """Write 2D heatmaps (avg_R) to entry_quality_heatmaps/."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        return
    hm_dir = out_dir / "entry_quality_heatmaps"
    hm_dir.mkdir(parents=True, exist_ok=True)
    # Slice: momentum_ratio_threshold vs pullback_depth_min (fix others at first value)
    if not scan_results:
        return
    r0 = scan_results[0]
    vol_fix = r0.get("pullback_depth_max"), r0.get("upper_wick_ratio_max"), r0.get("lower_wick_ratio_max"), r0.get("breakout_confirmation_required")
    momentum_vals = sorted({r["momentum_ratio_threshold"] for r in scan_results})
    pullback_vals = sorted({r["pullback_depth_min"] for r in scan_results if r.get("pullback_depth_min") is not None})
    if momentum_vals and pullback_vals:
        grid = []
        for pm in pullback_vals:
            row = []
            for mom in momentum_vals:
                cell = [r for r in scan_results if r["momentum_ratio_threshold"] == mom and r.get("pullback_depth_min") == pm]
                if cell and len(cell) == 1:
                    row.append(cell[0]["avg_R"])
                else:
                    row.append(float("nan"))
            grid.append(row)
        if grid:
            fig, ax = plt.subplots()
            im = ax.imshow(grid, aspect="auto", origin="lower", cmap="RdYlGn", vmin=-0.1, vmax=0.1)
            ax.set_xticks(range(len(momentum_vals)))
            ax.set_yticks(range(len(pullback_vals)))
            ax.set_xticklabels([f"{x:.2f}" for x in momentum_vals])
            ax.set_yticklabels([f"{y}" for y in pullback_vals])
            ax.set_xlabel("momentum_ratio_threshold")
            ax.set_ylabel("pullback_depth_min")
            ax.set_title("Entry quality: avg_R (momentum vs pullback_min)")
            plt.colorbar(im, ax=ax, label="avg_R")
            plt.tight_layout()
            fig.savefig(hm_dir / "heatmap_momentum_vs_pullback_min.png", dpi=100)
            plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Entry quality parameter scan")
    parser.add_argument("--candidates-csv", type=str, default="", help="Path to candidates CSV")
    parser.add_argument("--from-db", action="store_true", help="Load from DB")
    parser.add_argument("--signals-table", type=str, default="candidate_signals", help="DB signals table/view name (default: candidate_signals)")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--output-dir", type=str, default="analysis/output")
    args = parser.parse_args()

    if args.candidates_csv:
        path = Path(args.candidates_csv)
        if not path.exists():
            print("CSV not found:", path, file=sys.stderr)
            sys.exit(1)
        rows = load_candidates_csv(path)
        r_key = "R_return"
    elif args.from_db:
        rows = load_candidates_db(symbol=args.symbol, limit=args.limit, signals_table=args.signals_table)
        r_key = "future_r_30"
    else:
        print("Provide --candidates-csv or --from-db", file=sys.stderr)
        sys.exit(1)

    if not rows:
        print("No rows loaded", file=sys.stderr)
        sys.exit(0)

    # Default grid: momentum, pullback range, wick, breakout (Phase 4 spec)
    momentum_values = [0.90, 0.95, 1.00, 1.05]
    pullback_min_values = [None, -3.0, -2.5, -2.0, -1.5, -1.0]
    pullback_max_values = [None]
    upper_wick_values = [None, 0.2, 0.3, 0.4]
    lower_wick_values = [None, 0.5, 0.6, 0.7]
    breakout_values = [False, True]

    scan_results, debug_rows = run_entry_quality_scan(
        rows,
        momentum_values=momentum_values,
        pullback_min_values=pullback_min_values,
        pullback_max_values=pullback_max_values,
        upper_wick_values=upper_wick_values,
        lower_wick_values=lower_wick_values,
        breakout_values=breakout_values,
        r_key=r_key,
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    scan_path = out_dir / "entry_quality_scan.csv"
    with open(scan_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "momentum_ratio_threshold", "pullback_depth_min", "pullback_depth_max",
            "upper_wick_ratio_max", "lower_wick_ratio_max", "breakout_confirmation_required",
            "trades", "winrate", "avg_R", "profit_factor", "max_drawdown",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(scan_results)
    print(f"Wrote {scan_path} ({len(scan_results)} rows)")

    debug_path = out_dir / "entry_quality_debug.csv"
    with open(debug_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "momentum_ratio_threshold", "pullback_depth_min", "pullback_depth_max",
            "upper_wick_ratio_max", "lower_wick_ratio_max", "breakout_confirmation_required",
            "total_candidates", "after_momentum_filter", "after_pullback_filter",
            "after_wick_filter", "after_breakout_filter", "final_trades",
        ])
        w.writeheader()
        w.writerows(debug_rows)
    print(f"Wrote {debug_path}")

    write_heatmaps(scan_results, out_dir)
    hm_dir = out_dir / "entry_quality_heatmaps"
    if hm_dir.exists():
        print(f"Wrote heatmaps to {hm_dir}")


if __name__ == "__main__":
    main()
