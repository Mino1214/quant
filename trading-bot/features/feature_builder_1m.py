"""
Highly optimized feature builder for feature_store_1m.

입력: raw candles_1m/5m/15m (DB)
출력: feature_store_1m 테이블에 1m 그리드 기준 feature row bulk insert.

최적화 포인트:
- 기존 feature 존재 여부를 row마다 조회하지 않고, 한 번에 timestamp set으로 로드
- db.merge() 대신 bulk_insert_mappings() 사용
- 1m/5m/15m candle DB 로딩 최소화
- 불필요한 슬라이싱/DB roundtrip 최소화
- state 기반 증분 계산 유지
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional, Set

import logging
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from config.loader import get_strategy_settings
from core.models import Candle
from storage.candle_loader import load_1m_from_db, load_5m_from_db, load_15m_from_db
from storage.database import engine
from storage.models import FeatureStore1mModel, ResearchPipelineStateModel

# 기존 feature_extractor 재사용
from strategy.feature_extractor import extract_feature_values

logger = logging.getLogger(__name__)

FEATURE_VERSION = 1

# bulk insert 단위
BATCH_SIZE = 5000

# feature 계산용 최소 lookback
# extract_feature_values 내부에서 충분히 안정적으로 계산되도록 여유를 둠
LOOKBACK_1M = 300
LOOKBACK_5M = 120
LOOKBACK_15M = 120


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


def _load_existing_feature_timestamps(
    db: Session,
    symbol: str,
    feature_version: int,
    start_ts: Optional[datetime] = None,
) -> Set[datetime]:
    """
    기존에 저장된 feature_store timestamp를 한 번에 가져온다.
    row마다 exists 조회하는 병목 제거.
    """
    stmt = select(FeatureStore1mModel.timestamp).where(
        FeatureStore1mModel.symbol == symbol,
        FeatureStore1mModel.feature_version == feature_version,
    )
    # 주의:
    # - ResearchPipelineState.last_feature_timestamp는 "마지막으로 처리한 timestamp"를 의미하지만,
    #   DB에는 그 이전 구간에만 존재하는 중복 row가 있을 수 있다.
    # - start_ts 이상만 조회하면 그런 중복과 충돌이 나므로, 여기서는 전체 symbol/version에 대해
    #   timestamp set을 불러와서 seen_ts 초기값으로 사용한다.
    rows = db.execute(stmt).all()
    return {r[0] for r in rows}


def _load_all_candles_for_symbol(
    symbol: str,
    start_ts: Optional[datetime],
    end_ts: Optional[datetime],
) -> tuple[List[Candle], List[Candle], List[Candle]]:
    """
    한 심볼의 1m/5m/15m를 한 번에 로드.
    기존처럼 청크마다 DB를 다시 때리는 구조 제거.
    """
    candles_1m = load_1m_from_db(
        table="btc1m",
        start_ts=start_ts,
        end_ts=end_ts,
        symbol=symbol,
    )
    candles_5m = load_5m_from_db(
        table="btc5m",
        start_ts=None,   # 1m 기준 최신 timestamp까지만 있으면 됨
        end_ts=end_ts,
        symbol=symbol,
    )
    candles_15m = load_15m_from_db(
        table="btc15m",
        start_ts=None,
        end_ts=end_ts,
        symbol=symbol,
    )
    return candles_1m, candles_5m, candles_15m


def _advance_index(candles: List[Candle], current_idx: int, ts: datetime) -> int:
    """
    current_idx 이후로 timestamp <= ts 인 마지막 인덱스까지 전진.
    """
    while current_idx + 1 < len(candles) and candles[current_idx + 1].timestamp <= ts:
        current_idx += 1
    return current_idx


def _row_dict_from_features(
    symbol: str,
    c: Candle,
    feats: dict,
) -> dict:
    """
    FeatureStore1mModel bulk_insert용 dict 생성.

    - legacy + 확장 feature 모두 매핑
    - 새 컬럼 추가 시 여기에만 키를 늘려주면 됨
    """
    return {
        # 기본 메타 (+ 원시 캔들 부가 정보)
        "symbol": symbol,
        "timestamp": c.timestamp,
        "feature_version": FEATURE_VERSION,
        "open": c.open,
        "high": c.high,
        "low": c.low,
        "close": c.close,
        "volume": c.volume,
        "quote_volume": getattr(c, "quote_volume", None),
        "trade_count": getattr(c, "trade_count", None),
        "taker_buy_volume": getattr(c, "taker_buy_volume", None),
        "taker_buy_quote_volume": getattr(c, "taker_buy_quote_volume", None),

        # Trend (EMA levels)
        "ema20_1m": feats.get("ema20_1m"),
        "ema50_1m": feats.get("ema50_1m"),
        "ema200_1m": feats.get("ema200_1m"),
        "ema20_5m": feats.get("ema20_5m"),
        "ema50_5m": feats.get("ema50_5m"),
        "ema200_5m": feats.get("ema200_5m"),
        "ema20_15m": feats.get("ema20_15m"),
        "ema50_15m": feats.get("ema50_15m"),
        "ema200_15m": feats.get("ema200_15m"),

        # Trend slopes
        "ema20_slope_1m": feats.get("ema20_slope_1m"),
        "ema50_slope_1m": feats.get("ema50_slope_1m"),
        "ema200_slope_1m": feats.get("ema200_slope_1m"),
        "ema20_slope_5m": feats.get("ema20_slope_5m"),
        "ema50_slope_5m": feats.get("ema50_slope_5m"),
        "ema200_slope_5m": feats.get("ema200_slope_5m"),
        "ema20_slope_15m": feats.get("ema20_slope_15m"),
        "ema50_slope_15m": feats.get("ema50_slope_15m"),
        "ema200_slope_15m": feats.get("ema200_slope_15m"),

        # EMA distance / spread
        "dist_from_ema20_pct": feats.get("dist_from_ema20_pct"),
        "dist_from_ema50_pct": feats.get("dist_from_ema50_pct"),
        "dist_from_ema200_pct": feats.get("dist_from_ema200_pct"),
        "ema20_50_spread_pct": feats.get("ema20_50_spread_pct"),
        "ema50_200_spread_pct": feats.get("ema50_200_spread_pct"),
        "ema20_200_spread_pct": feats.get("ema20_200_spread_pct"),

        # Trend structure
        "ema20_gt_ema50": feats.get("ema20_gt_ema50"),
        "ema50_gt_ema200": feats.get("ema50_gt_ema200"),
        "ema_stack_score": feats.get("ema_stack_score"),

        # Momentum / RSI
        "rsi_1m": feats.get("rsi_1m"),
        "rsi_5m": feats.get("rsi_5m"),
        "rsi_15m": feats.get("rsi_15m"),
        "rsi_delta": feats.get("rsi_delta"),
        "rsi_slope": feats.get("rsi_slope"),
        "momentum_ratio": feats.get("momentum_ratio"),

        # Candle strength / structure
        "body_pct": feats.get("body_pct"),
        "range_pct": feats.get("range_pct"),
        "body_to_range_ratio": feats.get("body_to_range_ratio"),
        "upper_wick_ratio": feats.get("upper_wick_ratio"),
        "lower_wick_ratio": feats.get("lower_wick_ratio"),
        "close_near_high": feats.get("close_near_high"),
        "close_near_low": feats.get("close_near_low"),
        "close_in_range_pct": feats.get("close_in_range_pct"),

        # Volatility (ATR/NATR)
        "atr_1m": feats.get("atr_1m"),
        "atr_5m": feats.get("atr_5m"),
        "atr_15m": feats.get("atr_15m"),
        "natr_1m": feats.get("natr_1m"),
        "natr_5m": feats.get("natr_5m"),
        "natr_15m": feats.get("natr_15m"),
        "atr_ratio_1m_5m": feats.get("atr_ratio_1m_5m"),
        "atr_ratio_5m_15m": feats.get("atr_ratio_5m_15m"),
        "range_ma20": feats.get("range_ma20"),
        "range_zscore": feats.get("range_zscore"),

        # Volume
        "volume_ma20": feats.get("volume_ma20"),
        "volume_ratio": feats.get("volume_ratio"),
        "volume_zscore": feats.get("volume_zscore"),
        "volume_change_pct": feats.get("volume_change_pct"),
        "volume_ratio_5m": feats.get("volume_ratio_5m"),
        "volume_ratio_15m": feats.get("volume_ratio_15m"),

        # Position features
        "recent_high_20": feats.get("recent_high_20"),
        "recent_low_20": feats.get("recent_low_20"),
        "dist_from_recent_high_pct": feats.get("dist_from_recent_high_pct"),
        "dist_from_recent_low_pct": feats.get("dist_from_recent_low_pct"),
        "close_in_recent_range": feats.get("close_in_recent_range"),

        # Pullback / breakout features
        "pullback_depth_pct": feats.get("pullback_depth_pct"),
        "breakout_confirmation": feats.get("breakout_confirmation"),
        "breakout_strength": feats.get("breakout_strength"),

        # Regime features
        "adx_14": feats.get("adx_14"),
        "ema50_slope_pct": feats.get("ema50_slope_pct"),
        "natr_regime": feats.get("natr_regime"),
        "regime_score": feats.get("regime_score"),
        "regime_label": feats.get("regime_label"),
        "regime_tradable": feats.get("regime_tradable"),
    }


def _bulk_insert_rows(db: Session, rows_buffer: List[dict]) -> int:
    if not rows_buffer:
        return 0
    db.bulk_insert_mappings(FeatureStore1mModel, rows_buffer)
    db.commit()
    inserted = len(rows_buffer)
    rows_buffer.clear()
    return inserted


def _build_features_for_symbol(
    db: Session,
    symbol: str,
    start_ts: Optional[datetime],
    end_ts: Optional[datetime],
) -> int:
    """
    한 심볼에 대해 feature_store를 구축.
    - candles 한 번 로드
    - existing timestamp 한 번 로드
    - bulk insert
    """
    strat_settings = get_strategy_settings()

    candles_1m, candles_5m, candles_15m = _load_all_candles_for_symbol(
        symbol=symbol,
        start_ts=start_ts,
        end_ts=end_ts,
    )

    if not candles_1m:
        logger.info("[feature_store_1m] %s: no 1m candles", symbol)
        return 0

    if len(candles_5m) < LOOKBACK_5M or len(candles_15m) < LOOKBACK_15M:
        logger.info(
            "[feature_store_1m] %s: skip (not enough 5m/15m candles) 5m=%d 15m=%d",
            symbol,
            len(candles_5m),
            len(candles_15m),
        )
        return 0

    existing_ts = _load_existing_feature_timestamps(
        db=db,
        symbol=symbol,
        feature_version=FEATURE_VERSION,
        start_ts=start_ts,
    )
    logger.info(
        "[feature_store_1m] %s: loaded candles_1m=%d candles_5m=%d candles_15m=%d existing=%d",
        symbol,
        len(candles_1m),
        len(candles_5m),
        len(candles_15m),
        len(existing_ts),
    )

    total_inserted = 0
    rows_buffer: List[dict] = []
    # BTC1m 테이블에 timestamp 중복 row가 있을 수 있으므로,
    # 이미 본 timestamp는 한 번만 feature row 생성 (PK 충돌 방지)
    seen_ts: Set[datetime] = set(existing_ts)

    i5 = 0
    i15 = 0

    # 1m 루프
    for idx, c in enumerate(candles_1m):
        ts = c.timestamp

        if ts in seen_ts:
            continue

        i5 = _advance_index(candles_5m, i5, ts)
        i15 = _advance_index(candles_15m, i15, ts)

        # 최소 lookback 확보
        if idx + 1 < LOOKBACK_1M:
            continue
        if i5 + 1 < LOOKBACK_5M:
            continue
        if i15 + 1 < LOOKBACK_15M:
            continue

        # 슬라이싱 범위를 최소화
        used_1m = candles_1m[max(0, idx + 1 - LOOKBACK_1M): idx + 1]
        used_5m = candles_5m[max(0, i5 + 1 - LOOKBACK_5M): i5 + 1]
        used_15m = candles_15m[max(0, i15 + 1 - LOOKBACK_15M): i15 + 1]

        try:
            feats = extract_feature_values(
                candles_1m=used_1m,
                candles_5m=used_5m,
                settings=strat_settings,
                candles_15m=used_15m,
            )
        except Exception as ex:
            logger.exception(
                "[feature_store_1m] %s: feature extraction failed at %s: %s",
                symbol,
                ts,
                ex,
            )
            continue

        rows_buffer.append(_row_dict_from_features(symbol=symbol, c=c, feats=feats))
        seen_ts.add(ts)

        if len(rows_buffer) >= BATCH_SIZE:
            inserted = _bulk_insert_rows(db, rows_buffer)
            total_inserted += inserted
            logger.info(
                "[feature_store_1m] %s: inserted=%d total=%d last_ts=%s",
                symbol,
                inserted,
                total_inserted,
                ts,
            )

    # flush remaining
    inserted = _bulk_insert_rows(db, rows_buffer)
    total_inserted += inserted

    logger.info("[feature_store_1m] %s: done total_inserted=%d", symbol, total_inserted)
    return total_inserted


def update_feature_store(symbols: Iterable[str]) -> None:
    """
    Entry point:
    - state.last_feature_timestamp 이후만 처리
    - 각 symbol에 대해 feature_store 증분 업데이트
    """
    with engine.begin():
        # metadata create는 앱 초기화 쪽에서 처리하는 게 바람직
        pass

    from storage.database import SessionLocal

    db = SessionLocal()
    try:
        state = _get_or_create_state(db)
        start_ts = state.last_feature_timestamp

        logger.info(
            "[feature_store_1m] update start feature_version=%s start_ts=%s symbols=%s",
            FEATURE_VERSION,
            start_ts,
            list(symbols),
        )

        max_latest_ts: Optional[datetime] = state.last_feature_timestamp

        for sym in symbols:
            inserted = _build_features_for_symbol(
                db=db,
                symbol=sym,
                start_ts=start_ts,
                end_ts=None,
            )

            if inserted > 0:
                latest_ts = db.execute(
                    select(func.max(FeatureStore1mModel.timestamp)).where(
                        FeatureStore1mModel.symbol == sym,
                        FeatureStore1mModel.feature_version == FEATURE_VERSION,
                    )
                ).scalar_one_or_none()

                if latest_ts and (max_latest_ts is None or latest_ts > max_latest_ts):
                    max_latest_ts = latest_ts

        if max_latest_ts and max_latest_ts != state.last_feature_timestamp:
            state.last_feature_timestamp = max_latest_ts
            db.commit()
            logger.info(
                "[feature_store_1m] state updated last_feature_timestamp=%s",
                max_latest_ts,
            )

    finally:
        db.close()