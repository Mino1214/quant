# Run: python -m scheduler.research_pipeline
# Cron: 0 4 * * * cd /path/to/trading-bot && python -m scheduler.research_pipeline
import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def step_sync(symbol="BTCUSDT"):
    from storage.binance_sync import sync_binance_to_db
    sync_binance_to_db(symbol)


def step_build_dataset(symbol="BTCUSDT", table="btc1m", limit=5000):
    from storage.candle_loader import load_1m_from_db
    from scripts.build_signal_dataset import build_dataset
    from config.loader import load_config
    config = load_config()
    candles = load_1m_from_db(table=table, limit=limit, symbol=symbol)
    if candles:
        build_dataset(candles, symbol, config, skip_existing_times=set())


def step_outcomes(symbol="BTCUSDT", limit=200):
    """아웃컴이 비어 있는 candidate_signals에 future_r_30 등 계산해 signal_outcomes에 저장."""
    from storage.database import SessionLocal, init_db
    from storage.repositories import get_candidate_signals_without_outcome
    from storage.signal_outcome import compute_outcome_for_signal
    from storage.signal_dataset_logger import save_signal_outcome
    from storage.candle_loader import load_1m_from_db
    from core.models import Direction
    init_db()
    db = SessionLocal()
    try:
        for r in get_candidate_signals_without_outcome(db, symbol=symbol, limit=limit):
            candles = load_1m_from_db(table="btc1m", start_ts=r.time, limit=35, symbol=symbol)
            if len(candles) <= 1:
                continue
            direction = Direction(r.side) if r.side in ("long", "short") else Direction.LONG
            sl = r.close - 0.01 * r.close if r.side == "long" else r.close + 0.01 * r.close
            outcome = compute_outcome_for_signal(r.id, candles[1:32], r.close, sl, direction)
            outcome.candidate_signal_id = r.id
            save_signal_outcome(outcome)
    finally:
        db.close()


def step_stability(output_dir="analysis/output"):
    from analysis.run_stability_scan import main as run_scan
    prev = sys.argv
    sys.argv = ["run_stability_scan", "--from-db", "--output-dir", output_dir]
    try:
        run_scan()
    except SystemExit:
        pass
    sys.argv = prev


def step_walk_forward():
    from analysis.walk_forward import default_folds, run_walk_forward, save_walk_forward_results
    save_walk_forward_results(run_walk_forward(default_folds()))


def step_ml(limit=10000):
    from storage.database import SessionLocal, init_db
    from storage.repositories import get_candidate_signals_with_outcomes
    from ml.train import train_models
    init_db()
    db = SessionLocal()
    try:
        rows = get_candidate_signals_with_outcomes(db, limit=limit)
        if len(rows) >= 50:
            train_models(rows, model_dir="ml/models", r_key="future_r_30")
    finally:
        db.close()


def step_online_ml(
    symbol=None,
    model_dir="ml/models",
    min_signals=50_000,
    max_rows=500_000,
    deploy_if_better=True,
    deploy_policy="expected_R_corr",
):
    """
    Online learning: load dataset from DB, time-based split, train, evaluate, version, deploy if better.
    Run on 24h cron or when new signals exceed threshold (e.g. 5000 since last run).
    """
    from ml.online_training import run_online_training
    result = run_online_training(
        symbol=symbol,
        model_dir=model_dir,
        min_signals=min_signals,
        max_rows=max_rows,
        deploy_if_better=deploy_if_better,
        deploy_policy=deploy_policy,
    )
    logger.info("step_online_ml result: %s", result)
    return result


def run_pipeline(symbol="BTCUSDT", output_dir="analysis/output", **skips):
    base = Path(output_dir)
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    run_dir = base / run_ts
    run_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Pipeline run folder: %s", run_dir)

    if not skips.get("skip_sync"):
        step_sync(symbol)
    if not skips.get("skip_build"):
        step_build_dataset(symbol=symbol)
    if not skips.get("skip_outcomes"):
        step_outcomes(symbol=symbol)
    if not skips.get("skip_stability"):
        step_stability(str(run_dir))
    if not skips.get("skip_walk_forward"):
        step_walk_forward()
    if not skips.get("skip_ml"):
        step_ml()
    if not skips.get("skip_online_ml"):
        step_online_ml(symbol=symbol)

    p = run_dir / ("report_%s.txt" % datetime.now(timezone.utc).strftime("%Y%m%d"))
    p.write_text("Pipeline run at %s\n" % datetime.now(timezone.utc).isoformat())
    logger.info("Pipeline done. Report: %s", p)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--output-dir", default="analysis/output")
    ap.add_argument("--skip-sync", action="store_true")
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--skip-outcomes", action="store_true")
    ap.add_argument("--skip-stability", action="store_true")
    ap.add_argument("--skip-walk-forward", action="store_true")
    ap.add_argument("--skip-ml", action="store_true")
    ap.add_argument("--skip-online-ml", action="store_true")
    a = ap.parse_args()
    run_pipeline(
        symbol=a.symbol,
        output_dir=a.output_dir,
        skip_sync=a.skip_sync,
        skip_build=a.skip_build,
        skip_outcomes=a.skip_outcomes,
        skip_stability=a.skip_stability,
        skip_walk_forward=a.skip_walk_forward,
        skip_ml=a.skip_ml,
        skip_online_ml=a.skip_online_ml,
    )
