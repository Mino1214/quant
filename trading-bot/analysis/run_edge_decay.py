"""
CLI: Edge decay / holding horizon analysis.

Uses future_r_5, future_r_10, future_r_20, future_r_30 to find:
- Where edge is strongest after entry
- Whether holding longer destroys expectancy
- Preferred exit horizon for TP / trailing / max holding bars.

Usage:
  python -m analysis.run_edge_decay --from-db [--symbol BTCUSDT] [--limit 10000] [--output-dir out]
  python -m analysis.run_edge_decay --candidates-csv path/to/candidates.csv [--output-dir out]

CSV must have columns future_r_5, future_r_10, future_r_20, future_r_30 (e.g. from DB export).
If CSV has only R_return/future_r_30, only horizon 30 is reported.
"""
import argparse
import csv
import sys
from pathlib import Path

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.edge_decay import edge_decay_report

def load_candidates_csv(path: Path) -> list:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def load_candidates_db(symbol: str = "BTCUSDT", limit: int = 10000) -> list:
    from storage.database import SessionLocal, init_db
    from storage.repositories import get_candidate_signals_with_outcomes
    init_db()
    db = SessionLocal()
    try:
        return get_candidate_signals_with_outcomes(db, symbol=symbol, limit=limit)
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Edge decay / holding horizon analysis")
    parser.add_argument("--candidates-csv", type=str, default="", help="Path to candidates CSV (should have future_r_5/10/20/30)")
    parser.add_argument("--from-db", action="store_true", help="Load from DB (candidate_signals + signal_outcomes)")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--output-dir", type=str, default="analysis/output", help="Output directory")
    parser.add_argument("--no-regime", action="store_true", help="Skip per-regime breakdown")
    parser.add_argument("--no-trend-compare", action="store_true", help="Do not run with trend filter for comparison")
    args = parser.parse_args()

    if args.candidates_csv:
        path = Path(args.candidates_csv)
        if not path.exists():
            print("CSV not found:", path, file=sys.stderr)
            sys.exit(1)
        rows = load_candidates_csv(path)
    elif args.from_db:
        rows = load_candidates_db(symbol=args.symbol, limit=args.limit)
    else:
        print("Provide --candidates-csv or --from-db", file=sys.stderr)
        sys.exit(1)

    if not rows:
        print("No rows loaded")
        sys.exit(0)

    # Determine available horizons from first row
    sample = rows[0]
    horizons = [5, 10, 20, 30]
    available = [h for h in horizons if sample.get(f"future_r_{h}") is not None and sample.get(f"future_r_{h}") != ""]
    if not available:
        # Fallback: only future_r_30 or R_return
        if sample.get("future_r_30") is not None or sample.get("R_return") is not None:
            available = [30]
        else:
            print("No future_r_* or R_return in data", file=sys.stderr)
            sys.exit(1)

    report = edge_decay_report(
        rows,
        by_regime=not args.no_regime,
        with_trend_filter=not args.no_trend_compare,
        horizons=available,
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Overall metrics by horizon -> CSV
    csv_path = out_dir / "edge_decay_by_horizon.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["horizon", "trades", "winrate", "avg_R", "profit_factor", "max_drawdown"])
        w.writeheader()
        for r in report["overall"]:
            w.writerow(r)
    print("Wrote", csv_path)

    # Trend-filtered comparison
    if "overall_trend_filtered" in report:
        csv_trend = out_dir / "edge_decay_by_horizon_trend_filtered.csv"
        with open(csv_trend, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["horizon", "trades", "winrate", "avg_R", "profit_factor", "max_drawdown"])
            w.writeheader()
            for r in report["overall_trend_filtered"]:
                w.writerow(r)
        print("Wrote", csv_trend)

    # Per-regime CSVs
    if "by_regime" in report:
        for reg, metrics in report["by_regime"].items():
            fname = f"edge_decay_by_horizon_{reg.lower()}.csv"
            p = out_dir / fname
            with open(p, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["horizon", "trades", "winrate", "avg_R", "profit_factor", "max_drawdown"])
                w.writeheader()
                for r in metrics:
                    w.writerow(r)
            print("Wrote", p)
        if "by_regime_trend_filtered" in report:
            for reg, metrics in report["by_regime_trend_filtered"].items():
                fname = f"edge_decay_by_horizon_{reg.lower()}_trend_filtered.csv"
                p = out_dir / fname
                with open(p, "w", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=["horizon", "trades", "winrate", "avg_R", "profit_factor", "max_drawdown"])
                    w.writeheader()
                    for r in metrics:
                        w.writerow(r)
                print("Wrote", p)

    # Summary text
    summary_path = out_dir / "edge_decay_summary.txt"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("Edge decay / holding horizon summary\n")
        f.write("====================================\n\n")
        f.write("Overall (all candidates):\n")
        for r in report["overall"]:
            f.write(f"  Horizon {r['horizon']}: trades={r['trades']} winrate={r['winrate']:.1f}% avg_R={r['avg_R']:.3f} PF={r['profit_factor']:.2f}\n")
        if "overall_trend_filtered" in report:
            f.write("\nWith trend filter (long: ema20>ema50 & slope>0, short: opposite):\n")
            for r in report["overall_trend_filtered"]:
                f.write(f"  Horizon {r['horizon']}: trades={r['trades']} winrate={r['winrate']:.1f}% avg_R={r['avg_R']:.3f} PF={r['profit_factor']:.2f}\n")
        if "by_regime" in report:
            f.write("\nBy regime:\n")
            for reg, metrics in report["by_regime"].items():
                f.write(f"  {reg}:\n")
                for r in metrics:
                    f.write(f"    Horizon {r['horizon']}: trades={r['trades']} avg_R={r['avg_R']:.3f}\n")
    print("Wrote", summary_path)


if __name__ == "__main__":
    main()
