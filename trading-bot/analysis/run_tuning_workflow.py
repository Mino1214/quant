"""
Tuning workflow: orchestrate coarse → trend compare → regime → edge decay → entry quality → fine → recommend.

Usage:
  python -m analysis.run_tuning_workflow --from-db [--output-dir analysis/output] [--symbol BTCUSDT]
  python -m analysis.run_tuning_workflow --from-db --stage coarse   # only coarse scan
  python -m analysis.run_tuning_workflow --from-db --stage fine --fine-from-csv analysis/output/YYYYMMDDHHmm/parameter_scan_results_clean.csv

Workflow order (see docs/Tuning_Workflow.md):
  1) Coarse scan: ema, volume_ratio, rsi (wide sparse grid)
  2) Trend filter comparison: baseline vs trend-filtered (--compare-trend)
  3) Regime-separated scans: TRENDING_UP, TRENDING_DOWN, RANGING, CHAOTIC
  4) Edge decay: per-parameter-combination summary + heatmap
  5) Entry quality: optional momentum/pullback/breakout/wick filters
  6) Fine scan: dense grid around best region from coarse (--stage fine --fine-from-csv)
  7) Recommended config: stable region + neighbors + regime_best + best_horizon
"""
import argparse
import logging
import subprocess
import sys
from pathlib import Path

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_coarse(
    from_db: bool = True,
    candidates_csv: str = "",
    output_dir: str = "analysis/output",
    symbol: str = "BTCUSDT",
    limit: int = 10000,
    compare_trend: bool = True,
    no_timestamp_dir: bool = False,
) -> Path:
    """Run coarse parameter scan (wide grid). Returns output directory path."""
    cmd = [sys.executable, "-m", "analysis.run_stability_scan"]
    if from_db:
        cmd += ["--from-db", "--symbol", symbol, "--limit", str(limit)]
    else:
        cmd += ["--candidates-csv", candidates_csv]
    cmd += ["--output-dir", output_dir]
    if compare_trend:
        cmd.append("--compare-trend")
    if no_timestamp_dir:
        cmd.append("--no-timestamp-dir")
    logger.info("Running coarse scan: %s", " ".join(cmd))
    subprocess.run(cmd, check=True)
    # Output dir is output_dir/YYYYMMDDHHmm unless no_timestamp_dir
    return Path(output_dir)


def run_fine(
    fine_from_csv: str,
    from_db: bool = True,
    output_dir: str = "analysis/output",
    symbol: str = "BTCUSDT",
    limit: int = 10000,
) -> None:
    """Run fine scan (dense grid) around best region from coarse CSV."""
    cmd = [
        sys.executable, "-m", "analysis.run_stability_scan",
        "--stage", "fine", "--fine-from-csv", fine_from_csv,
        "--output-dir", output_dir,
    ]
    if from_db:
        cmd += ["--from-db", "--symbol", symbol, "--limit", str(limit)]
    logger.info("Running fine scan: %s", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Strategy tuning workflow: coarse → fine → recommend")
    parser.add_argument("--from-db", action="store_true", help="Load candidates from DB")
    parser.add_argument("--candidates-csv", type=str, default="", help="Or path to candidates CSV")
    parser.add_argument("--output-dir", type=str, default="analysis/output")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--stage", type=str, default="coarse", choices=["coarse", "fine", "full"],
                        help="coarse=only coarse, fine=only fine (need --fine-from-csv), full=coarse then fine")
    parser.add_argument("--fine-from-csv", type=str, default="",
                        help="Path to parameter_scan_results_clean.csv for fine grid (required for stage=fine)")
    parser.add_argument("--no-compare-trend", action="store_true", help="Skip trend filter comparison in coarse")
    parser.add_argument("--no-timestamp-dir", action="store_true", help="Write directly into output-dir")
    args = parser.parse_args()

    if not args.from_db and not args.candidates_csv:
        logger.error("Provide --from-db or --candidates-csv")
        sys.exit(1)

    if args.stage == "fine":
        if not args.fine_from_csv or not Path(args.fine_from_csv).exists():
            logger.error("Stage fine requires --fine-from-csv pointing to parameter_scan_results_clean.csv")
            sys.exit(1)
        run_fine(
            args.fine_from_csv,
            from_db=args.from_db,
            output_dir=args.output_dir,
            symbol=args.symbol,
            limit=args.limit,
        )
        return

    if args.stage in ("coarse", "full"):
        out = run_coarse(
            from_db=args.from_db,
            candidates_csv=args.candidates_csv,
            output_dir=args.output_dir,
            symbol=args.symbol,
            limit=args.limit,
            compare_trend=not args.no_compare_trend,
            no_timestamp_dir=args.no_timestamp_dir,
        )
        if args.stage == "full":
            # Find latest run dir (timestamped) and run fine from its clean CSV
            clean_csv = None
            if args.no_timestamp_dir:
                clean_csv = Path(args.output_dir) / "parameter_scan_results_clean.csv"
            else:
                out_p = Path(args.output_dir)
                if out_p.exists():
                    subdirs = sorted([d for d in out_p.iterdir() if d.is_dir() and d.name.isdigit() and len(d.name) >= 12], key=lambda p: p.name, reverse=True)
                    for d in subdirs:
                        c = d / "parameter_scan_results_clean.csv"
                        if c.exists():
                            clean_csv = c
                            break
            if clean_csv and clean_csv.exists():
                run_fine(
                    str(clean_csv),
                    from_db=args.from_db,
                    output_dir=args.output_dir,
                    symbol=args.symbol,
                    limit=args.limit,
                )
            else:
                logger.warning("Full stage: no parameter_scan_results_clean.csv found to run fine scan")


if __name__ == "__main__":
    main()
