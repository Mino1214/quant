"""
Mean Reversion / Reversal strategy.

아이디어:
- 급등/급락 + 과매수/과매도 + 유동성 레벨(최근 high/low) 근처에서 되돌림만 스캘핑.
- 추세 추종이 아니라 "과한 움직임 후 평균회귀"만 노린다.

이 모듈은 candidate 신호만 생성하고, approval_engine / risk / regime 필터는
기존 파이프라인을 그대로 사용한다.
"""
from __future__ import annotations

from typing import List, Optional

from core.models import Candle, CandidateSignalRecord, Direction, StrategySettings


def _recent_return_pct(candles_1m: List[Candle], lookback: int) -> Optional[float]:
    """최근 lookback 봉의 퍼센트 수익률 (close_now / close_past - 1) * 100."""
    if len(candles_1m) < lookback + 1:
        return None
    now = candles_1m[-1].close
    past = candles_1m[-1 - lookback].close
    if past <= 0:
        return None
    return (now / past - 1.0) * 100.0


def evaluate_mean_reversion(
    candles_1m: List[Candle],
    candles_5m: List[Candle],
    candles_15m: List[Candle],
    features: dict,
    regime: Optional[str],
    settings: StrategySettings,
    symbol: str = "",
) -> Optional[CandidateSignalRecord]:
    """
    Mean reversion / reversal candidate.

    Conditions (초기 버전):
      Long:
        - recent_return_10 <= -2.0%
        - rsi_5m <= 35
        - dist_from_recent_low_pct <= 1.0
        - lower_wick_ratio >= 0.4
      Short 는 반대.

    Regime는 CHAOTIC/RANGING 필터는 바깥에서 이미 처리했다고 가정.
    여기서는 추가로 방향을 강하게 제한하지 않고, 과도한 움직임 자체만 본다.
    """
    if not candles_1m or not candles_5m:
        return None

    c = candles_1m[-1]

    # 최근 N봉 수익률
    lookback = getattr(settings, "mr_return_lookback", 10)
    ret_pct = _recent_return_pct(candles_1m, lookback)
    if ret_pct is None:
        return None

    rsi_5m = float(features.get("rsi_5m") or 0.0)
    dist_low = float(features.get("dist_from_recent_low_pct") or 0.0)
    dist_high = float(features.get("dist_from_recent_high_pct") or 0.0)
    lower_wick = float(features.get("lower_wick_ratio") or 0.0)
    upper_wick = float(features.get("upper_wick_ratio") or 0.0)

    direction: Optional[Direction] = None

    # Long mean reversion: 급락 + 과매도 + 저점 근처 + 아래꼬리
    if ret_pct <= -2.0 and rsi_5m <= 35 and dist_low <= 1.0 and lower_wick >= 0.4:
        direction = Direction.LONG

    # Short mean reversion: 급등 + 과매수 + 고점 근처 + 윗꼬리
    if ret_pct >= 2.0 and rsi_5m >= 65 and dist_high <= 1.0 and upper_wick >= 0.4:
        # 양쪽 조건이 동시에 참일 가능성은 거의 없지만, short가 우선되도록 덮어씀.
        direction = Direction.SHORT

    if direction is None:
        return None

    regime_str = regime or "UNKNOWN"
    record = CandidateSignalRecord(
        timestamp=c.timestamp,
        entry_price=c.close,
        regime=regime_str,
        trend_direction=direction,
        approval_score=0,
        feature_values=features,
        trade_outcome="executed",  # 실제 엔트리 여부는 approval/risk에서 결정
        blocked_reason=None,
        symbol=symbol,
    )
    return record

