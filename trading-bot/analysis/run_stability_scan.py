"""
CLI: Run Edge Stability Map parameter scan and save results + heatmaps.

Structural research (run these first; threshold tuning is secondary):
  1) Trend alignment: run with --compare-trend to get no_trend vs trend_filtered CSVs.
     Goal: see if negative expectancy is mainly from counter-trend entries.
  2) Regime split: by default writes parameter_scan_results_trending_up/down/ranging.csv.
     Goal: find if the strategy has positive edge in specific regimes only.
  3) Edge decay: use analysis.run_edge_decay --from-db to get edge by horizon (5/10/20/30 bars).
     Goal: choose TP / trailing / max holding bars from data.

Usage:
  python -m analysis.run_stability_scan --candidates-csv path/to/candidates.csv [--output-dir out] [--save-db]
  python -m analysis.run_stability_scan --from-db [--symbol BTCUSDT] [--limit 10000] [--output-dir out] [--save-db]
  python -m analysis.run_stability_scan --from-db --compare-trend   # no_trend vs trend_filtered comparison
"""
import argparse
import csv
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.stability_map import (
    flag_suspicious_rows,
    filter_by_entry_quality,
    get_cleaned_scan_results,
    plot_heatmaps,
    run_parameter_scan,
    run_parameter_scan_by_regime,
    run_parameter_scan_with_debug,
)
from analysis.edge_decay import (
    edge_decay_per_parameter_combinations,
    plot_edge_decay_heatmap,
    HORIZONS,
)

from analysis.store_loader import load_rows_from_store

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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates-csv", type=str, default="", help="Path to candidates CSV")
    parser.add_argument("--from-db", action="store_true", help="Load from DB (candidate_signals + signal_outcomes)")
    parser.add_argument("--signals-table", type=str, default="candidate_signals", help="DB signals table/view name (default: candidate_signals)")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--output-dir", type=str, default="analysis/output", help="Base directory for output (default: analysis/output)")
    parser.add_argument("--no-timestamp-dir", action="store_true", help="Write directly into output-dir; if not set, creates output-dir/YYYYMMDDHHmm per run")
    parser.add_argument("--save-db", action="store_true", help="Save scan results to parameter_scan_results")
    parser.add_argument("--ema-min", type=float, default=0.0001)
    parser.add_argument("--ema-max", type=float, default=0.0005)
    parser.add_argument("--ema-step", type=float, default=0.0001)
    parser.add_argument("--vol-min", type=float, default=0.8)
    parser.add_argument("--vol-max", type=float, default=1.4)
    parser.add_argument("--vol-step", type=float, default=0.2)
    parser.add_argument("--rsi-min", type=float, default=45)
    parser.add_argument("--rsi-max", type=float, default=60)
    parser.add_argument("--rsi-step", type=float, default=5)
    parser.add_argument("--use-trend-filter", action="store_true", help="Apply trend filter (long: ema20>ema50 & slope>0, short: opposite)")
    parser.add_argument("--compare-trend", action="store_true", help="Run scan twice (no trend + with trend), write *_no_trend.csv and *_trend_filtered.csv for comparison")
    parser.add_argument("--no-regime-split", action="store_true", help="Skip regime-specific scan CSVs and heatmaps")
    parser.add_argument("--heatmap-min-trades", type=int, default=200, help="Min trades for heatmap rows (default 200)")
    parser.add_argument("--volume-report", action="store_true", help="Generate volume_ratio distribution report (histogram + quantiles + surviving counts)")
    # Entry quality (structural filter; use before threshold tuning)
    parser.add_argument("--min-pullback", type=float, default=None, help="Min pullback_depth_pct (0..1) to keep candidates")
    parser.add_argument("--max-pullback", type=float, default=None, help="Max pullback_depth_pct to keep candidates")
    parser.add_argument("--require-breakout", action="store_true", help="Keep only close > recent_high (long) or < recent_low (short)")
    parser.add_argument("--min-momentum-ratio", type=float, default=None, help="Min body/range (momentum_ratio) for last candle")
    parser.add_argument("--max-upper-wick-long", type=float, default=None, help="Max upper_wick_ratio for LONG (filter rejections)")
    parser.add_argument("--max-lower-wick-short", type=float, default=None, help="Max lower_wick_ratio for SHORT")
    # Scan-time entry/trend params (fixed value per run; applied in addition to pre-scan entry-quality filter)
    parser.add_argument("--momentum-threshold", type=float, default=None, help="Min momentum_ratio in scan (fixed)")
    parser.add_argument("--ema50-slope-min", type=float, default=None, help="Min |ema50_slope| for trend filter (fixed)")
    # Multi-stage tuning: coarse (wide grid) vs fine (dense grid around best from CSV)
    parser.add_argument("--stage", type=str, default="", choices=["coarse", "fine", "full"], help="coarse=wide grid, fine=dense around best (requires --fine-from-csv), full=coarse then fine")
    parser.add_argument("--fine-from-csv", type=str, default="", help="Path to parameter_scan_results_clean.csv to derive fine grid center")
    parser.add_argument("--fine-ema-step", type=float, default=0.00005, help="EMA step for fine scan")
    parser.add_argument("--fine-vol-step", type=float, default=0.1, help="Volume step for fine scan")
    parser.add_argument("--fine-rsi-step", type=float, default=2, help="RSI step for fine scan")
    parser.add_argument("--fine-top-pct", type=float, default=20.0, help="Use top pct of rows by avg_R to define fine grid range (default 20)")
    args = parser.parse_args()

    if args.candidates_csv:
        path = Path(args.candidates_csv)
        if not path.exists():
            logger.error("CSV not found: %s", path)
            sys.exit(1)
        rows = load_candidates_csv(path)
        r_key = "R_return"
    elif args.from_db:
        rows = load_candidates_db(symbol=args.symbol, limit=args.limit, signals_table=args.signals_table)
        r_key = "future_r_30"
    else:
        logger.error("Provide --candidates-csv or --from-db")
        sys.exit(1)

    if not rows:
        logger.warning("No rows loaded")
        sys.exit(0)

    # Optional entry-quality filter (structural; reduces candidate pool before threshold scan)
    if any([args.min_pullback is not None, args.max_pullback is not None, args.require_breakout,
            args.min_momentum_ratio is not None, args.max_upper_wick_long is not None, args.max_lower_wick_short is not None]):
        rows = filter_by_entry_quality(
            rows,
            min_pullback_depth_pct=args.min_pullback,
            max_pullback_depth_pct=args.max_pullback,
            require_breakout=args.require_breakout,
            min_momentum_ratio=args.min_momentum_ratio,
            max_upper_wick_ratio_long=args.max_upper_wick_long,
            max_lower_wick_ratio_short=args.max_lower_wick_short,
        )
        logger.info("After entry-quality filter: %d rows", len(rows))
        if not rows:
            logger.warning("No rows left after entry-quality filter")
            sys.exit(0)

    ema_vals = []
    vol_vals = []
    rsi_vals = []
    stage = getattr(args, "stage", "") or ""
    if stage == "fine" and getattr(args, "fine_from_csv", ""):
        # Dense grid around best region from prior coarse scan
        fine_path = Path(args.fine_from_csv)
        if not fine_path.exists():
            logger.error("Fine scan requires --fine-from-csv path to exist: %s", fine_path)
            sys.exit(1)
        with open(fine_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            coarse_rows = list(reader)
        for r in coarse_rows:
            for k in ("ema_distance_threshold", "volume_ratio_threshold", "rsi_threshold", "avg_R"):
                if k in r and r[k] != "":
                    try:
                        r[k] = float(r[k])
                    except (ValueError, TypeError):
                        r[k] = None
            if "trades" in r and r["trades"] != "":
                try:
                    r["trades"] = int(float(r["trades"]))
                except (ValueError, TypeError):
                    r["trades"] = 0
        valid = [r for r in coarse_rows if r.get("avg_R") is not None and (r.get("trades") or 0) >= 200]
        if not valid:
            logger.warning("No valid rows with avg_R and trades>=200 in coarse CSV; using default grid")
        else:
            valid.sort(key=lambda r: r.get("avg_R") or 0, reverse=True)
            top_pct = max(1, int(len(valid) * (getattr(args, "fine_top_pct", 20) / 100.0)))
            top = valid[:top_pct]
            ema_vals_s = sorted({r["ema_distance_threshold"] for r in top if r.get("ema_distance_threshold") is not None})
            vol_vals_s = sorted({r["volume_ratio_threshold"] for r in top if r.get("volume_ratio_threshold") is not None})
            rsi_vals_s = sorted({r["rsi_threshold"] for r in top if r.get("rsi_threshold") is not None})
            if ema_vals_s and vol_vals_s and rsi_vals_s:
                ema_lo, ema_hi = min(ema_vals_s), max(ema_vals_s)
                vol_lo, vol_hi = min(vol_vals_s), max(vol_vals_s)
                rsi_lo, rsi_hi = min(rsi_vals_s), max(rsi_vals_s)
                step_ema = getattr(args, "fine_ema_step", 0.00005)
                step_vol = getattr(args, "fine_vol_step", 0.1)
                step_rsi = getattr(args, "fine_rsi_step", 2)
                x = ema_lo
                while x <= ema_hi:
                    ema_vals.append(round(x, 6))
                    x += step_ema
                x = vol_lo
                while x <= vol_hi:
                    vol_vals.append(round(x, 2))
                    x += step_vol
                x = rsi_lo
                while x <= rsi_hi:
                    rsi_vals.append(x)
                    x += step_rsi
                logger.info("Fine grid from %s: ema %d, vol %d, rsi %d points", fine_path.name, len(ema_vals), len(vol_vals), len(rsi_vals))
    if not ema_vals or not vol_vals or not rsi_vals:
        x = args.ema_min
        while x <= args.ema_max:
            ema_vals.append(round(x, 6))
            x += args.ema_step
        x = args.vol_min
        while x <= args.vol_max:
            vol_vals.append(round(x, 2))
            x += args.vol_step
        x = args.rsi_min
        while x <= args.rsi_max:
            rsi_vals.append(x)
            x += args.rsi_step

    use_trend = getattr(args, "use_trend_filter", False)
    compare_trend = getattr(args, "compare_trend", False)
    scan_kw = {
        "momentum_ratio_threshold": getattr(args, "momentum_threshold", None) or args.min_momentum_ratio,
        "pullback_depth_min": args.min_pullback,
        "pullback_depth_max": args.max_pullback,
        "breakout_confirmation_required": args.require_breakout,
        "upper_wick_ratio_max": args.max_upper_wick_long,
        "lower_wick_ratio_max": args.max_lower_wick_short,
        "ema50_slope_min": getattr(args, "ema50_slope_min", None),
    }

    if compare_trend:
        logger.info("Running parameter scan (no trend) for comparison...")
        results, debug_rows = run_parameter_scan_with_debug(
            rows, ema_vals, vol_vals, rsi_vals, r_key=r_key, use_trend_filter=False, **scan_kw
        )
        results_no_trend = list(results)
        debug_no_trend = list(debug_rows)
        logger.info("Running parameter scan (with trend filter) for comparison...")
        results_trend, debug_trend = run_parameter_scan_with_debug(
            rows, ema_vals, vol_vals, rsi_vals, r_key=r_key, use_trend_filter=True, **scan_kw
        )
        results = results_no_trend  # main outputs use no-trend
        debug_rows = debug_no_trend
        logger.info("Scan done: no_trend=%d rows, with_trend=%d rows", len(results_no_trend), len(results_trend))
    else:
        logger.info("Running parameter scan: ema=%d vol=%d rsi=%d trend_filter=%s", len(ema_vals), len(vol_vals), len(rsi_vals), use_trend)
        results, debug_rows = run_parameter_scan_with_debug(
            rows, ema_vals, vol_vals, rsi_vals, r_key=r_key, use_trend_filter=use_trend, **scan_kw
        )
        logger.info("Scan done: %d result rows", len(results))

    base_dir = Path(args.output_dir)
    if getattr(args, "no_timestamp_dir", False):
        out_dir = base_dir
    else:
        run_ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
        out_dir = base_dir / run_ts
        logger.info("Run output folder: %s", out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scan_id = str(uuid.uuid4())[:8]

    # Sanity: flag suspicious rows (abs(avg_R)>5, profit_factor>10, trades<30)
    flagged = flag_suspicious_rows(results)
    n_suspicious = sum(1 for r in flagged if not r.get("valid", True))
    if n_suspicious:
        logger.warning("Flagged %d suspicious rows (abs(avg_R)>5 or profit_factor>10 or trades<30)", n_suspicious)

    # Full results with flags
    csv_path = out_dir / "parameter_scan_results.csv"
    flag_fields = ["suspicious_abs_avg_r", "suspicious_pf", "suspicious_low_trades", "valid"]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        base_fields = [
            "ema_distance_threshold", "volume_ratio_threshold", "rsi_threshold",
            "trades", "winrate", "avg_R", "profit_factor", "max_drawdown",
        ]
        w = csv.DictWriter(f, fieldnames=base_fields + flag_fields + ["scan_id"])
        w.writeheader()
        for r in flagged:
            row = {k: r.get(k) for k in base_fields}
            row["suspicious_abs_avg_r"] = r.get("suspicious_abs_avg_r", False)
            row["suspicious_pf"] = r.get("suspicious_pf", False)
            row["suspicious_low_trades"] = r.get("suspicious_low_trades", False)
            row["valid"] = r.get("valid", True)
            row["scan_id"] = scan_id
            w.writerow(row)
    logger.info("Wrote %s", csv_path)

    # parameter_scan_debug.csv: filter stage counts per combination
    debug_path = out_dir / "parameter_scan_debug.csv"
    debug_fields = [
        "ema_distance_threshold", "volume_ratio_threshold", "rsi_threshold",
        "total_candidates", "after_regime_filter", "after_ema_filter", "after_volume_filter", "after_rsi_filter",
        "after_momentum_filter", "after_pullback_filter", "after_breakout_filter", "after_trend_filter", "final_trades",
    ]
    with open(debug_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=debug_fields, extrasaction="ignore")
        w.writeheader()
        for r in debug_rows:
            w.writerow(r)
    logger.info("Wrote %s", debug_path)

    by_regime = {}
    if not getattr(args, "no_regime_split", False):
        by_regime = run_parameter_scan_by_regime(
            rows, ema_vals, vol_vals, rsi_vals, r_key=r_key, use_trend_filter=use_trend, **scan_kw
        )
        for reg, reg_results in by_regime.items():
            fname = f"parameter_scan_results_{reg.lower()}.csv"
            path_reg = out_dir / fname
            with open(path_reg, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=[
                    "ema_distance_threshold", "volume_ratio_threshold", "rsi_threshold",
                    "trades", "winrate", "avg_R", "profit_factor", "max_drawdown",
                ])
                w.writeheader()
                for r in reg_results:
                    w.writerow({k: r.get(k) for k in w.fieldnames})
            logger.info("Wrote %s (%d rows)", path_reg, len(reg_results))

    # Clean results only (valid rows) for heatmaps and stable region recommendation
    cleaned = get_cleaned_scan_results(results)
    clean_path = out_dir / "parameter_scan_results_clean.csv"
    with open(clean_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "ema_distance_threshold", "volume_ratio_threshold", "rsi_threshold",
            "trades", "winrate", "avg_R", "profit_factor", "max_drawdown", "scan_id",
        ])
        w.writeheader()
        for r in cleaned:
            row = {k: r.get(k) for k in w.fieldnames if k in r}
            row["scan_id"] = scan_id
            w.writerow(row)
    logger.info("Wrote %s (%d valid rows)", clean_path, len(cleaned))

    # Compare trend: write no_trend and trend_filtered clean CSVs for comparison
    if compare_trend:
        cleaned_no = get_cleaned_scan_results(results_no_trend)
        path_no = out_dir / "parameter_scan_results_clean_no_trend.csv"
        with open(path_no, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "ema_distance_threshold", "volume_ratio_threshold", "rsi_threshold",
                "trades", "winrate", "avg_R", "profit_factor", "max_drawdown", "scan_id",
            ])
            w.writeheader()
            for r in cleaned_no:
                row = {k: r.get(k) for k in w.fieldnames if k in r}
                row["scan_id"] = scan_id
                w.writerow(row)
        logger.info("Wrote %s (%d rows, no trend)", path_no, len(cleaned_no))
        cleaned_trend = get_cleaned_scan_results(results_trend)
        path_tr = out_dir / "parameter_scan_results_clean_trend_filtered.csv"
        with open(path_tr, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "ema_distance_threshold", "volume_ratio_threshold", "rsi_threshold",
                "trades", "winrate", "avg_R", "profit_factor", "max_drawdown", "scan_id",
            ])
            w.writeheader()
            for r in cleaned_trend:
                row = {k: r.get(k) for k in w.fieldnames if k in r}
                row["scan_id"] = scan_id
                w.writerow(row)
        logger.info("Wrote %s (%d rows, trend filter on)", path_tr, len(cleaned_trend))

    # Volume ratio distribution report (histogram, quantiles, surviving counts)
    if getattr(args, "volume_report", False):
        from analysis.volume_ratio_report import run_report
        run_report(rows, out_dir, r_key=r_key)
        logger.info("Volume ratio report written to %s", out_dir)

    # Heatmaps: trades >= heatmap_min_trades and valid
    hm_min = getattr(args, "heatmap_min_trades", 200)
    paths = plot_heatmaps(cleaned, str(out_dir), min_trades=hm_min, require_valid=True)
    for p in paths:
        logger.info("Heatmap: %s", p)

    # Regime heatmaps (trades>=min_trades, valid)
    if not getattr(args, "no_regime_split", False) and by_regime:
        for reg, reg_results in by_regime.items():
            reg_cleaned = get_cleaned_scan_results(reg_results)
            suffix = "_" + reg.lower()
            paths_reg = plot_heatmaps(reg_cleaned, str(out_dir), min_trades=hm_min, require_valid=True, suffix=suffix)
            for p in paths_reg:
                logger.info("Heatmap %s: %s", reg, p)

    # Edge decay per parameter combination (when future_r_* columns exist)
    edge_summary = None
    if rows and any(rows[0].get(f"future_r_{h}") is not None for h in HORIZONS):
        try:
            edge_summary = edge_decay_per_parameter_combinations(
                rows, ema_vals, vol_vals, rsi_vals, horizons=HORIZONS, use_trend_filter=use_trend, **scan_kw
            )
            edge_path = out_dir / "edge_decay_summary.csv"
            edge_cols = ["ema_distance_threshold", "volume_ratio_threshold", "rsi_threshold"] + [f"avg_future_r_{h}" for h in HORIZONS] + ["best_horizon", "edge_decay_slope"]
            with open(edge_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=edge_cols, extrasaction="ignore")
                w.writeheader()
                w.writerows(edge_summary)
            logger.info("Wrote %s", edge_path)
            rsi_mid = rsi_vals[len(rsi_vals) // 2] if rsi_vals else 50.0
            if plot_edge_decay_heatmap(edge_summary, str(out_dir / "edge_decay_heatmap.png"), rsi_fix=rsi_mid, value_key="best_horizon"):
                logger.info("Wrote edge_decay_heatmap.png")
        except Exception as e:
            logger.warning("Edge decay per-combo failed: %s", e)

    # Stable region 추천: trades>=200, pf>1.05, avg_R>0 → recommended_config.json + explanation
    from analysis.parameter_suggestion_engine import run as run_suggestion, write_explanation
    from analysis.stability_map import STABLE_MIN_TRADES, STABLE_MIN_PROFIT_FACTOR, STABLE_MIN_AVG_R
    rec = run_suggestion(
        cleaned,
        min_trades=STABLE_MIN_TRADES,
        min_profit_factor=STABLE_MIN_PROFIT_FACTOR,
        min_avg_r=STABLE_MIN_AVG_R,
        only_valid_rows=False,
        regime_results=by_regime if by_regime else None,
        edge_decay_rows=edge_summary,
    )
    if rec:
        rec_path = out_dir / "recommended_config.json"
        to_dump = {k: v for k, v in rec.items() if not k.startswith("_")}
        to_dump["_meta"] = rec.get("_meta", {})
        with open(rec_path, "w", encoding="utf-8") as f:
            json.dump(to_dump, f, indent=2, ensure_ascii=False)
        expl_path = out_dir / "recommended_config_explanation.txt"
        write_explanation(rec, expl_path, STABLE_MIN_TRADES, STABLE_MIN_PROFIT_FACTOR, STABLE_MIN_AVG_R)
        logger.info("Wrote %s and %s", rec_path, expl_path)
    else:
        logger.warning("No stable region found (trades>=200, pf>1.02, avg_R>0). Skip recommended_config.")

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


if __name__ == "__main__":
    main()
