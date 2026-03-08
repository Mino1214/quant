"""
CLI for Signal Distribution Analysis: load candidate signals CSV, run analyses, print tables, generate charts.
Usage:
  python -m analysis.run_signal_analysis --candidates-csv path/to/candidates.csv --output-dir analysis/output
  Or from backtest: --export-candidates out.csv --run-analysis (writes CSV then runs this).
"""
import argparse
import csv
import logging
import sys
from pathlib import Path

# Ensure project root (trading-bot) is on path when run as __main__
if __name__ == "__main__":
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

from analysis.distributions import (
    feature_impact_ema_distance,
    feature_impact_volume_ratio,
    holding_time_impact,
    r_distribution,
    regime_performance,
    score_vs_outcome,
    time_of_day_impact,
)
from analysis.charts import generate_all_charts

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def load_candidates_csv(path: Path) -> list:
    """Load candidate signals from CSV; return list of dicts."""
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def _cell(r: dict, h: str) -> str:
    v = r.get(h, "")
    if isinstance(v, float):
        return "%.2f" % v if h == "avg_R" else "%.1f" % v if h == "winrate" else str(v)
    return str(v)


def print_table(title: str, rows: list, headers: list) -> None:
    """Print a simple text table."""
    if not rows:
        logger.info("%s: (no data)", title)
        return
    logger.info("%s", title)
    col_widths = [max(len(str(h)), max((len(_cell(r, h)) for r in rows), default=0)) for h in headers]
    fmt = "  ".join("%%-%ds" % w for w in col_widths)
    logger.info(fmt % tuple(headers))
    for r in rows:
        logger.info(fmt % tuple(_cell(r, h) for h in headers))
    logger.info("")


def run_analysis(rows: list, output_dir: Path) -> None:
    """Run all distribution analyses, print tables, generate charts."""
    from analysis.distributions import _executed_rows
    executed = _executed_rows(rows)
    logger.info("Total candidate rows: %d | Executed (with R_return): %d", len(rows), len(executed))
    if not executed:
        logger.info("No executed trades with R_return; charts will be empty.")
    logger.info("")

    # Score vs outcome
    score_data = score_vs_outcome(rows)
    print_table("Signal Quality vs Score (approval_score | trades | winrate | avg_R)",
                score_data, ["approval_score", "trades", "winrate", "avg_R"])

    # Feature impact
    ema_data = feature_impact_ema_distance(rows)
    print_table("Feature: EMA distance (ema_distance_range | trades | avg_R)",
                ema_data, ["ema_distance_range", "trades", "avg_R"])
    vol_data = feature_impact_volume_ratio(rows)
    print_table("Feature: Volume ratio (volume_ratio | trades | avg_R)",
                vol_data, ["volume_ratio", "trades", "avg_R"])

    # Regime
    regime_data = regime_performance(rows)
    print_table("Regime performance (regime | trades | winrate | avg_R)",
                regime_data, ["regime", "trades", "winrate", "avg_R"])

    # Holding time
    hold_data = holding_time_impact(rows)
    print_table("Holding time vs profit (holding_bars | avg_R)",
                hold_data, ["holding_bars", "avg_R"])

    # Time of day
    tod_data = time_of_day_impact(rows)
    print_table("Time of day UTC (hour | trades | avg_R)",
                tod_data, ["hour", "trades", "avg_R"])

    generate_all_charts(rows, output_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description="Signal Distribution Analysis")
    parser.add_argument("--candidates-csv", type=Path, required=True, help="Path to candidate signals CSV")
    parser.add_argument("--output-dir", type=Path, default=Path("analysis/output"), help="Directory for chart images")
    args = parser.parse_args()
    if not args.candidates_csv.exists():
        logger.error("File not found: %s", args.candidates_csv)
        return 1
    rows = load_candidates_csv(args.candidates_csv)
    if not rows:
        logger.warning("No rows in CSV")
        return 0
    run_analysis(rows, args.output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
