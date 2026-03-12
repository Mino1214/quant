"""
Volatility Compression Breakout strategy.

아이디어:
- 1) 변동성 압축 구간 (ATR/Range 낮음)
- 2) 거래량 스파이크 (volume_spike, volume_zscore)
- 3) 박스 상단/하단 브레이크아웃 (recent high/low 돌파 + 강한 캔들 구조)
- 4) 레짐 방향과 일치하는 방향으로만 진입 (TRENDING_UP: 롱, TRENDING_DOWN: 숏)

이 모듈은 "candidate signal"만 생성하고, approval_engine / risk는 기존 파이프라인을 그대로 사용한다.
"""
from __future__ import annotations

from typing import List, Optional

from core.models import Candle, CandidateSignalRecord, Direction, StrategySettings


def _recent_high_low(candles_1m: List[Candle], lookback: int) -> tuple[float, float] | None:
    if len(candles_1m) < lookback + 1:
        return None
    window = candles_1m[-(lookback + 1) : -1]
    if not window:
        return None
    recent_high = max(c.high for c in window)
    recent_low = min(c.low for c in window)
    return recent_high, recent_low


def evaluate_vol_breakout(
    candles_1m: List[Candle],
    candles_5m: List[Candle],
    candles_15m: List[Candle],
    features: dict,
    regime: Optional[str],
    settings: StrategySettings,
    symbol: str = "",
) -> Optional[CandidateSignalRecord]:
    """
    Volatility compression breakout candidate.

    입력:
      - candles_1m/5m/15m: 현재까지 윈도우
      - features: feature_extractor.extract_feature_values() 결과
      - regime: MarketRegimeResult.regime.value (또는 None)
    출력:
      - 조건 만족 시 CandidateSignalRecord, 아니면 None
    """
    if not candles_1m or not candles_5m:
        return None

    c = candles_1m[-1]

    # 1) 변동성 압축: atr_1m / atr_5m <= 0.5 (또는 atr_ratio_5/50 낮음)
    atr_1m = float(features.get("atr_1m") or 0.0)
    atr_5m = float(features.get("atr_5m") or 0.0)
    compression_ok = False
    if atr_1m > 0 and atr_5m > 0:
        atr_ratio_1m_5m = atr_1m / atr_5m
        compression_ok = atr_ratio_1m_5m <= 0.5
    # 보조: range_pct도 너무 크지 않은지 (상단 클램프)
    range_pct = float(features.get("range_pct") or 0.0)
    if not compression_ok and range_pct > 0:
        # 최근 봉의 range_pct가 과도하게 크지 않은 경우에만 허용 (하위 ~50% 정도)
        compression_ok = range_pct <= 1.5  # 1.5% 이내
    if not compression_ok:
        return None

    # 2) 거래량 스파이크: volume_spike >= 3.0 또는 volume_zscore >= 2.0
    vol_spike = float(features.get("volume_spike") or 0.0)
    vol_z = float(features.get("volume_zscore") or 0.0)
    if vol_spike < 3.0 and vol_z < 2.0:
        return None

    # 3) 박스 브레이크아웃 + 캔들 구조
    hl = _recent_high_low(candles_1m, getattr(settings, "swing_lookback", 20))
    if hl is None:
        return None
    recent_high, recent_low = hl

    close = c.close
    high = c.high
    low = c.low
    if high <= low:
        return None

    close_pos = float(features.get("close_position_in_candle") or 0.0)
    upper_wick = float(features.get("upper_wick_ratio") or 0.0)
    lower_wick = float(features.get("lower_wick_ratio") or 0.0)

    long_break = close > recent_high and close_pos >= 0.7 and upper_wick <= 0.2
    short_break = close < recent_low and close_pos <= 0.3 and lower_wick <= 0.2
    if not long_break and not short_break:
        return None

    # 4) 레짐 / 트렌드 방향 정렬
    trend_bias = float(features.get("trend_bias") or 0.0)
    direction: Optional[Direction] = None

    if long_break:
        if regime and regime not in ("TRENDING_UP", "UNKNOWN"):
            return None
        if trend_bias < 0.0:
            return None
        direction = Direction.LONG
    elif short_break:
        if regime and regime not in ("TRENDING_DOWN", "UNKNOWN"):
            return None
        if trend_bias > 0.0:
            return None
        direction = Direction.SHORT

    if direction is None:
        return None

    # CandidateSignalRecord 생성 (approval/리스크는 기존 파이프라인 사용)
    regime_str = regime or "UNKNOWN"
    record = CandidateSignalRecord(
        timestamp=c.timestamp,
        entry_price=close,
        regime=regime_str,
        trend_direction=direction,
        approval_score=0,
        feature_values=features,
        trade_outcome="executed",  # 실제 엔트리 여부는 approval/risk에서 결정
        blocked_reason=None,
        symbol=symbol,
    )
    return record

