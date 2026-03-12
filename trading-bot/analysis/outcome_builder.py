"""
Simple outcome builder for `outcome_store_1m`.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Set, Tuple

import logging
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from core.models import Candle
from storage.candle_loader import load_1m_from_db
from storage.database import engine
from storage.models import OutcomeStore1mModel, ResearchPipelineStateModel

logger = logging.getLogger(__name__)

BATCH_SIZE = 5000
COMMIT_EVERY_N_BATCHES = 10
# future_r_240까지 계산하므로 충분히 겹쳐서 다시 읽어야 함
OVERLAP_MINUTES = 300

HORIZONS_RETURN = [1, 2, 3, 5, 8, 10, 15, 20, 30, 45, 60, 90, 120, 180, 240]
HORIZONS_MFE_MAE = [3, 5, 10, 20, 30, 60]
HORIZONS_WIN = [3, 5, 10, 20, 30]

DEBUG_EXTRA_COLS = [
    "future_r_2",
    "future_r_8",
    "future_r_15",
    "future_r_45",
    "future_r_60",
    "future_r_90",
    "future_r_120",
    "future_r_180",
    "future_r_240",
    "mfe_3",
    "mfe_5",
    "mfe_10",
    "mfe_20",
    "mfe_30",
    "mfe_60",
    "mae_3",
    "mae_5",
    "mae_10",
    "mae_20",
    "mae_30",
    "mae_60",
]


def _get_or_create_state(db: Session) -> ResearchPipelineStateModel:
    state = db.get(ResearchPipelineStateModel, 1)
    if state is None:
        state = ResearchPipelineStateModel(
            id=1,
            last_feature_timestamp=None,
            last_outcome_timestamp=None,
        )
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def _load_candles_for_symbol(
    symbol: str,
    start_ts: Optional[datetime],
    end_ts: Optional[datetime],
) -> List[Candle]:
    return load_1m_from_db(
        table="btc1m",
        start_ts=start_ts,
        end_ts=end_ts,
        symbol=symbol,
    )


def _simple_return(future: Optional[float], current: Optional[float]) -> Optional[float]:
    if current is None or current == 0 or future is None:
        return None
    return (future - current) / current


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _get_candle_attr(candle: Candle, *names):
    for name in names:
        if hasattr(candle, name):
            v = getattr(candle, name)
            if v is not None:
                return v
    return None


def _dedup_candles(candles: List[Candle]) -> List[Candle]:
    if not candles:
        return candles

    dedup: List[Candle] = []
    seen_ts: Set[datetime] = set()

    for c in candles:
        ts = c.timestamp.replace(microsecond=0)
        if ts in seen_ts:
            continue
        seen_ts.add(ts)
        c.timestamp = ts
        dedup.append(c)

    return dedup


def _window_mfe_mae(
    highs: List[Optional[float]],
    lows: List[Optional[float]],
    current_close: Optional[float],
    start_idx: int,
    horizon: int,
) -> Tuple[Optional[float], Optional[float]]:
    if current_close is None or current_close == 0:
        return None, None

    end_idx = start_idx + horizon
    if end_idx >= len(highs):
        return None, None

    future_highs = [x for x in highs[start_idx + 1 : end_idx + 1] if x is not None]
    future_lows = [x for x in lows[start_idx + 1 : end_idx + 1] if x is not None]

    if not future_highs or not future_lows:
        return None, None

    max_high = max(future_highs)
    min_low = min(future_lows)

    mfe = (max_high - current_close) / current_close
    mae = (min_low - current_close) / current_close
    return mfe, mae


def _build_row(
    symbol: str,
    idx: int,
    timestamps: List[datetime],
    closes: List[Optional[float]],
    highs: List[Optional[float]],
    lows: List[Optional[float]],
) -> dict:
    ts = timestamps[idx]
    current = closes[idx]

    row = {
        "symbol": symbol,
        "timestamp": ts,
    }

    # future_r_*
    for h in HORIZONS_RETURN:
        future_price = closes[idx + h] if idx + h < len(closes) else None
        row[f"future_r_{h}"] = _simple_return(future_price, current)

    # win_*
    for h in HORIZONS_WIN:
        r = row.get(f"future_r_{h}")
        row[f"win_{h}"] = None if r is None else (r > 0.0)

    # mfe_* / mae_*
    for h in HORIZONS_MFE_MAE:
        mfe, mae = _window_mfe_mae(
            highs=highs,
            lows=lows,
            current_close=current,
            start_idx=idx,
            horizon=h,
        )
        row[f"mfe_{h}"] = mfe
        row[f"mae_{h}"] = mae

    # 아직 미구현
    row["tp_03_sl_02_hit"] = None
    row["tp_05_sl_03_hit"] = None
    row["tp_10_sl_05_hit"] = None

    return row


def _bulk_insert_rows(db: Session, rows: List[dict]) -> int:
    if not rows:
        return 0

    stmt = mysql_insert(OutcomeStore1mModel).values(rows)

    update_cols = {
        "future_r_1": stmt.inserted.future_r_1,
        "future_r_2": stmt.inserted.future_r_2,
        "future_r_3": stmt.inserted.future_r_3,
        "future_r_5": stmt.inserted.future_r_5,
        "future_r_8": stmt.inserted.future_r_8,
        "future_r_10": stmt.inserted.future_r_10,
        "future_r_15": stmt.inserted.future_r_15,
        "future_r_20": stmt.inserted.future_r_20,
        "future_r_30": stmt.inserted.future_r_30,
        "future_r_45": stmt.inserted.future_r_45,
        "future_r_60": stmt.inserted.future_r_60,
        "future_r_90": stmt.inserted.future_r_90,
        "future_r_120": stmt.inserted.future_r_120,
        "future_r_180": stmt.inserted.future_r_180,
        "future_r_240": stmt.inserted.future_r_240,
        "mfe_3": stmt.inserted.mfe_3,
        "mfe_5": stmt.inserted.mfe_5,
        "mfe_10": stmt.inserted.mfe_10,
        "mfe_20": stmt.inserted.mfe_20,
        "mfe_30": stmt.inserted.mfe_30,
        "mfe_60": stmt.inserted.mfe_60,
        "mae_3": stmt.inserted.mae_3,
        "mae_5": stmt.inserted.mae_5,
        "mae_10": stmt.inserted.mae_10,
        "mae_20": stmt.inserted.mae_20,
        "mae_30": stmt.inserted.mae_30,
        "mae_60": stmt.inserted.mae_60,
        "win_3": stmt.inserted.win_3,
        "win_5": stmt.inserted.win_5,
        "win_10": stmt.inserted.win_10,
        "win_20": stmt.inserted.win_20,
        "win_30": stmt.inserted.win_30,
        "tp_03_sl_02_hit": stmt.inserted.tp_03_sl_02_hit,
        "tp_05_sl_03_hit": stmt.inserted.tp_05_sl_03_hit,
        "tp_10_sl_05_hit": stmt.inserted.tp_10_sl_05_hit,
    }
    stmt = stmt.on_duplicate_key_update(**update_cols)
    db.execute(stmt)
    return len(rows)


def _delete_symbol_outcomes(db: Session, symbol: str) -> int:
    deleted = (
        db.query(OutcomeStore1mModel)
        .filter(OutcomeStore1mModel.symbol == symbol)
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


def _build_outcomes_for_symbol(
    db: Session,
    symbol: str,
    start_ts: Optional[datetime],
    end_ts: Optional[datetime],
) -> Tuple[int, Optional[datetime]]:
    effective_start_ts = None
    if start_ts is not None:
        effective_start_ts = start_ts - timedelta(minutes=OVERLAP_MINUTES)

    candles = _load_candles_for_symbol(
        symbol=symbol,
        start_ts=effective_start_ts,
        end_ts=end_ts,
    )
    candles = _dedup_candles(candles)

    logger.info(
        "[outcome_store_1m] %s: loaded candles_1m=%d start_ts=%s effective_start_ts=%s",
        symbol,
        len(candles),
        start_ts,
        effective_start_ts,
    )

    if not candles:
        return 0, None

    timestamps = [c.timestamp for c in candles]
    closes = [_to_float(_get_candle_attr(c, "close", "c")) for c in candles]
    highs = [_to_float(_get_candle_attr(c, "high", "h")) for c in candles]
    lows = [_to_float(_get_candle_attr(c, "low", "l")) for c in candles]

    logger.info(
        "[outcome_store_1m] %s: sample prices first_close=%s first_high=%s first_low=%s mid_close=%s last_close=%s",
        symbol,
        closes[0] if closes else None,
        highs[0] if highs else None,
        lows[0] if lows else None,
        closes[len(closes) // 2] if closes else None,
        closes[-1] if closes else None,
    )

    latest_ts = timestamps[-1]
    n = len(candles)
    total_upserted = 0
    buf: List[dict] = []
    batch_count = 0

    try:
        for idx in range(n):
            row = _build_row(
                symbol=symbol,
                idx=idx,
                timestamps=timestamps,
                closes=closes,
                highs=highs,
                lows=lows,
            )
            buf.append(row)

            if idx in (0, min(100, n - 1), min(1000, n - 1)):
                logger.info(
                    "[outcome_store_1m] %s row_sample idx=%d ts=%s r2=%s r8=%s r15=%s r60=%s r120=%s mfe10=%s mae10=%s",
                    symbol,
                    idx,
                    row["timestamp"],
                    row.get("future_r_2"),
                    row.get("future_r_8"),
                    row.get("future_r_15"),
                    row.get("future_r_60"),
                    row.get("future_r_120"),
                    row.get("mfe_10"),
                    row.get("mae_10"),
                )

            if len(buf) >= BATCH_SIZE:
                non_null_counts = {
                    col: sum(1 for r in buf if r.get(col) is not None)
                    for col in DEBUG_EXTRA_COLS
                }

                logger.info(
                    "[outcome_store_1m] %s batch_non_null_counts=%s",
                    symbol,
                    non_null_counts,
                )

                upserted = _bulk_insert_rows(db, buf)
                total_upserted += upserted
                batch_count += 1

                logger.info(
                    "[outcome_store_1m] %s: batch_upserted=%d total=%d last_ts=%s",
                    symbol,
                    upserted,
                    total_upserted,
                    row["timestamp"],
                )

                buf.clear()

                if batch_count % COMMIT_EVERY_N_BATCHES == 0:
                    db.commit()

        if buf:
            non_null_counts = {
                col: sum(1 for r in buf if r.get(col) is not None)
                for col in DEBUG_EXTRA_COLS
            }

            logger.info(
                "[outcome_store_1m] %s final_batch_non_null_counts=%s",
                symbol,
                non_null_counts,
            )

            upserted = _bulk_insert_rows(db, buf)
            total_upserted += upserted
            buf.clear()

        db.commit()

    except Exception:
        db.rollback()
        raise

    logger.info(
        "[outcome_store_1m] %s: done total_upserted=%d latest_ts=%s",
        symbol,
        total_upserted,
        latest_ts,
    )
    return total_upserted, latest_ts


def update_outcome_store(
    symbols: Iterable[str],
    full_rebuild: bool = False,
) -> None:
    from storage.database import SessionLocal

    with engine.begin():
        pass

    db = SessionLocal()
    try:
        state = _get_or_create_state(db)
        start_ts = None if full_rebuild else state.last_outcome_timestamp
        symbols = list(symbols)

        logger.info(
            "[outcome_store_1m] update start start_ts=%s full_rebuild=%s symbols=%s",
            start_ts,
            full_rebuild,
            symbols,
        )

        max_latest_ts: Optional[datetime] = None if full_rebuild else state.last_outcome_timestamp

        for sym in symbols:
            if full_rebuild:
                deleted = _delete_symbol_outcomes(db, sym)
                logger.info("[outcome_store_1m] %s full_rebuild deleted=%d", sym, deleted)

            upserted, latest_ts = _build_outcomes_for_symbol(
                db=db,
                symbol=sym,
                start_ts=start_ts,
                end_ts=None,
            )

            logger.info(
                "[outcome_store_1m] %s: finished upserted=%d latest_ts=%s",
                sym,
                upserted,
                latest_ts,
            )

            if latest_ts and (max_latest_ts is None or latest_ts > max_latest_ts):
                max_latest_ts = latest_ts

        if max_latest_ts != state.last_outcome_timestamp:
            state.last_outcome_timestamp = max_latest_ts
            db.commit()
            logger.info(
                "[outcome_store_1m] state updated last_outcome_timestamp=%s",
                max_latest_ts,
            )
    finally:
        db.close()