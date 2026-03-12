"""
CLI: Feature importance from signal dataset (univariate + optional RandomForest).

Usage:
  python -m analysis.run_feature_importance --from-db [--symbol BTCUSDT] [--limit 10000] [--output-dir analysis/output]
  python -m analysis.run_feature_importance --candidates-csv path/to/candidates.csv [--output-dir analysis/output]
"""
import argparse
import csv
import sys
from pathlib import Path

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.feature_importance import run, plot_impact_heatmap, TARGET_KEY


def load_from_db(symbol: str = "BTCUSDT", limit: int = 10000) -> list:
    from storage.database import SessionLocal, init_db
    from storage.repositories import get_candidate_signals_with_outcomes
    init_db()
    db = SessionLocal()
    try:
        return get_candidate_signals_with_outcomes(db, symbol=symbol, limit=limit)
    finally:
        db.close()


def load_from_csv(path: Path) -> list:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Feature importance (univariate + model)")
    parser.add_argument("--from-db", action="store_true")
    parser.add_argument("--candidates-csv", type=str, default="")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--output-dir", type=str, default="analysis/output")
    parser.add_argument("--n-bins", type=int, default=5)
    parser.add_argument("--no-model", action="store_true", help="Skip RandomForest importance")
    parser.add_argument("--heatmaps", action="store_true", help="Generate 2D impact heatmaps for feature pairs")
    args = parser.parse_args()

    if args.from_db:
        rows = load_from_db(symbol=args.symbol, limit=args.limit)
        target_key = "future_r_30"
    elif args.candidates_csv:
        path = Path(args.candidates_csv)
        if not path.exists():
            print("CSV not found:", path, file=sys.stderr)
            sys.exit(1)
        rows = load_from_csv(path)
        target_key = "R_return" if "R_return" in (rows[0] or {}) else "future_r_30"
    else:
        print("Provide --from-db or --candidates-csv", file=sys.stderr)
        sys.exit(1)

    if not rows:
        print("No rows loaded", file=sys.stderr)
        sys.exit(0)

    results = run(
        rows,
        target_key=target_key,
        n_bins=args.n_bins,
        use_model=not args.no_model,
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "feature_importance.csv"
    fieldnames = ["feature_name", "importance_score", "n_samples", "avg_R_by_bin", "winrate_by_bin"]
    if results and "model_importance" in results[0]:
        fieldnames.append("model_importance")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)
    print("Wrote", csv_path)

    if args.heatmaps:
        heatmap_dir = out_dir / "feature_impact_heatmaps"
        heatmap_dir.mkdir(parents=True, exist_ok=True)
        pairs = [("ema_distance", "volume_ratio"), ("ema_distance", "rsi_5m"), ("volume_ratio", "rsi_5m"), ("momentum_ratio", "rsi_5m")]
        for fx, fy in pairs:
            path = heatmap_dir / f"heatmap_{fx}_vs_{fy}.png"
            if plot_impact_heatmap(rows, fx, fy, target_key=target_key, n_bins=args.n_bins, output_path=str(path)):
                print("Wrote", path)


if __name__ == "__main__":
    main()
