"""
CLI: Run Edge Stability Map parameter scan and save results + heatmaps.
Usage:
  python -m analysis.run_stability_scan --candidates-csv path/to/candidates.csv [--output-dir out] [--save-db]
  python -m analysis.run_stability_scan --from-db [--symbol BTCUSDT] [--limit 10000] [--output-dir out] [--save-db]
"""
import argparse
import csv
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.stability_map import plot_heatmaps, run_parameter_scan

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_candidates_csv(path: Path) -> list:
    """Load candidate signals from CSV (e.g. from backtest --export-candidates)."""
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def load_candidates_db(symbol: str = "BTCUSDT", limit: int = 10000) -> list:
    """Load candidate_signals + signal_outcomes from DB."""
    from storage.database import SessionLocal, init_db
    from storage.repositories import get_candidate_signals_with_outcomes
    init_db()
    db = SessionLocal()
    try:
        return get_candidate_signals_with_outcomes(db, symbol=symbol, limit=limit)
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates-csv", type=str, default="", help="Path to candidates CSV")
    parser.add_argument("--from-db", action="store_true", help="Load from DB (candidate_signals + signal_outcomes)")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--output-dir", type=str, default="analysis/output", help="Directory for heatmaps and CSV")
    parser.add_argument("--save-db", action="store_true", help="Save scan results to parameter_scan_results")
    parser.add_argument("--ema-min", type=float, default=0.0002)
    parser.add_argument("--ema-max", type=float, default=0.0012)
    parser.add_argument("--ema-step", type=float, default=0.0002)
    parser.add_argument("--vol-min", type=float, default=0.8)
    parser.add_argument("--vol-max", type=float, default=1.6)
    parser.add_argument("--vol-step", type=float, default=0.2)
    parser.add_argument("--rsi-min", type=float, default=40)
    parser.add_argument("--rsi-max", type=float, default=60)
    parser.add_argument("--rsi-step", type=float, default=5)
    args = parser.parse_args()

    if args.candidates_csv:
        path = Path(args.candidates_csv)
        if not path.exists():
            logger.error("CSV not found: %s", path)
            sys.exit(1)
        rows = load_candidates_csv(path)
        r_key = "R_return"
    elif args.from_db:
        rows = load_candidates_db(symbol=args.symbol, limit=args.limit)
        r_key = "future_r_30"
    else:
        logger.error("Provide --candidates-csv or --from-db")
        sys.exit(1)

    if not rows:
        logger.warning("No rows loaded")
        sys.exit(0)

    ema_vals = []
    x = args.ema_min
    while x <= args.ema_max:
        ema_vals.append(round(x, 6))
        x += args.ema_step
    vol_vals = []
    x = args.vol_min
    while x <= args.vol_max:
        vol_vals.append(round(x, 2))
        x += args.vol_step
    rsi_vals = []
    x = args.rsi_min
    while x <= args.rsi_max:
        rsi_vals.append(x)
        x += args.rsi_step

    logger.info("Running parameter scan: ema=%d vol=%d rsi=%d combinations", len(ema_vals), len(vol_vals), len(rsi_vals))
    results = run_parameter_scan(rows, ema_vals, vol_vals, rsi_vals, r_key=r_key)
    logger.info("Scan done: %d result rows", len(results))

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scan_id = str(uuid.uuid4())[:8]

    if args.save_db:
        from storage.database import SessionLocal, init_db
        from storage.repositories import create_parameter_scan_result
        init_db()
        db = SessionLocal()
        try:
            for r in results:
                r["scan_id"] = scan_id
                r["created_at"] = datetime.utcnow()
                create_parameter_scan_result(db, r)
            logger.info("Saved %d rows to parameter_scan_results (scan_id=%s)", len(results), scan_id)
        finally:
            db.close()

    csv_path = out_dir / "parameter_scan_results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "ema_distance_threshold", "volume_ratio_threshold", "rsi_threshold",
            "trades", "winrate", "avg_R", "profit_factor", "max_drawdown", "scan_id",
        ])
        w.writeheader()
        for r in results:
            row = {k: r.get(k) for k in w.fieldnames}
            row["scan_id"] = scan_id
            w.writerow(row)
    logger.info("Wrote %s", csv_path)

    paths = plot_heatmaps(results, str(out_dir))
    for p in paths:
        logger.info("Heatmap: %s", p)


if __name__ == "__main__":
    main()
