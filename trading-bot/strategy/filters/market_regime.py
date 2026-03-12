"""
Market Regime Filter: Score 방식. Hard filter(하나라도 fail → 금지) 대신
ADX / EMA slope / NATR 각각 점수 부여 → score >= threshold 이면 거래 허용.
Continuation 전략에 맞게 3개 조건 중 2개 이상 만족하면 TRENDING 인정.
"""
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

from core.models import Candle

from indicators.adx import adx
from indicators.atr import atr
from indicators.ema import ema_series
from indicators.ema import _closes


class MarketRegime(str, Enum):
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    CHAOTIC = "CHAOTIC"
    UNKNOWN = "UNKNOWN"


# Blocked reason codes for logging/UI
BLOCK_REGIME_RANGE = "BLOCK_REGIME_RANGE"
BLOCK_REGIME_CHAOTIC = "BLOCK_REGIME_CHAOTIC"
BLOCK_REGIME_SCORE = "BLOCK_REGIME_SCORE"  # score < threshold
BLOCK_REGIME_NATR_TOO_HIGH = "BLOCK_REGIME_NATR_TOO_HIGH"
BLOCK_REGIME_INSUFFICIENT_DATA = "BLOCK_REGIME_INSUFFICIENT_DATA"


@dataclass
class RegimeSettings:
    """Score 방식: adx/slope/natr 각 +1, score >= score_threshold 이면 허용."""
    enabled: bool = True
    ema_slow_len: int = 50
    slope_lookback: int = 5
    slope_threshold_pct: float = 0.03
    adx_len: int = 14
    adx_min: float = 18.0
    atr_len: int = 14
    natr_min: float = 0.03
    natr_max: float = 1.20
    score_threshold: int = 2  # 3개 중 2개 이상 만족 시 거래 허용, 미만이면 RANGING


@dataclass
class MarketRegimeResult:
    """Result of regime evaluation."""
    regime: MarketRegime
    allow_trading: bool
    can_long: bool
    can_short: bool
    blocked_reason: Optional[str]
    adx: float
    natr: float
    slope_pct: float
    score: int = 0  # 0~3, 진단용


def _ema50_slope_pct(candles: List[Candle], period: int, lookback: int) -> Optional[float]:
    """(EMA50_now - EMA50_prev_n) / EMA50_now * 100."""
    if len(candles) < period + lookback:
        return None
    closes = _closes(candles)
    series = ema_series(closes, period)
    valid = [v for v in series if v is not None]
    if len(valid) < lookback + 1:
        return None
    ema_now = valid[-1]
    ema_prev = valid[-1 - lookback]
    if ema_now == 0:
        return None
    return (ema_now - ema_prev) / ema_now * 100.0


def _natr(candles: List[Candle], period: int) -> tuple[Optional[float], Optional[float]]:
    """Returns (ATR, NATR) for last candle. NATR = ATR / close * 100."""
    if len(candles) < period + 1:
        return None, None
    atr_val = atr(candles, period)
    if atr_val is None:
        return None, None
    close = candles[-1].close
    if close <= 0:
        return atr_val, None
    natr_val = atr_val / close * 100.0
    return atr_val, natr_val


class MarketRegimeFilter:
    """
    Evaluates market regime on 15m (or given) candles.
    Use before bias/trend/trigger: if allow_trading is False, block entry.
    """

    def __init__(self, settings: RegimeSettings):
        self.settings = settings

    def evaluate(self, candles: List[Candle]) -> MarketRegimeResult:
        """
        Classify regime from candles (typically 15m).
        Returns result with allow_trading, can_long, can_short, blocked_reason.
        """
        s = self.settings
        if not candles:
            return MarketRegimeResult(
                regime=MarketRegime.UNKNOWN,
                allow_trading=False,
                can_long=False,
                can_short=False,
                blocked_reason=BLOCK_REGIME_INSUFFICIENT_DATA,
                adx=0.0,
                natr=0.0,
                slope_pct=0.0,
            )

        # 15m 최소 봉 수 (EMA50+slope=55, ADX~42, ATR 15) → 55봉 미만이면 UNKNOWN
        min_len = max(
            s.ema_slow_len + s.slope_lookback,  # 50+5=55
            s.adx_len * 3,
            s.atr_len + 1,
        )
        if len(candles) < min_len:
            return MarketRegimeResult(
                regime=MarketRegime.UNKNOWN,
                allow_trading=False,
                can_long=False,
                can_short=False,
                blocked_reason=BLOCK_REGIME_INSUFFICIENT_DATA,
                adx=0.0,
                natr=0.0,
                slope_pct=0.0,
            )

        close = candles[-1].close
        ema50 = ema_series(_closes(candles), s.ema_slow_len)
        ema50_valid = [v for v in ema50 if v is not None]
        ema50_now = ema50_valid[-1] if ema50_valid else None

        slope_pct = _ema50_slope_pct(candles, s.ema_slow_len, s.slope_lookback)
        adx_val = adx(candles, s.adx_len)
        _, natr_val = _natr(candles, s.atr_len)

        if slope_pct is None:
            slope_pct = 0.0
        if adx_val is None:
            adx_val = 0.0
        if natr_val is None:
            natr_val = 0.0

        # 1) CHAOTIC: NATR 너무 높으면 무조건 차단 (변동성 과다)
        if natr_val > s.natr_max:
            return MarketRegimeResult(
                regime=MarketRegime.CHAOTIC,
                allow_trading=False,
                can_long=False,
                can_short=False,
                blocked_reason=BLOCK_REGIME_NATR_TOO_HIGH,
                adx=adx_val,
                natr=natr_val,
                slope_pct=slope_pct,
            )

        # 2) Score: 3개 중 몇 개 만족하는지 (2개 이상이면 거래 허용)
        score = 0
        if adx_val >= s.adx_min:
            score += 1
        if abs(slope_pct) >= s.slope_threshold_pct:
            score += 1
        if natr_val >= s.natr_min:
            score += 1

        if score < s.score_threshold:
            return MarketRegimeResult(
                regime=MarketRegime.RANGING,
                allow_trading=False,
                can_long=False,
                can_short=False,
                blocked_reason=BLOCK_REGIME_SCORE,
                adx=adx_val,
                natr=natr_val,
                slope_pct=slope_pct,
                score=score,
            )

        # 3) Score 통과 → 방향만 close vs EMA50으로 판정
        if ema50_now is None:
            return MarketRegimeResult(
                regime=MarketRegime.RANGING,
                allow_trading=False,
                can_long=False,
                can_short=False,
                blocked_reason=BLOCK_REGIME_SCORE,
                adx=adx_val,
                natr=natr_val,
                slope_pct=slope_pct,
                score=score,
            )
        if close > ema50_now:
            return MarketRegimeResult(
                regime=MarketRegime.TRENDING_UP,
                allow_trading=True,
                can_long=True,
                can_short=False,
                blocked_reason=None,
                adx=adx_val,
                natr=natr_val,
                slope_pct=slope_pct,
                score=score,
            )
        return MarketRegimeResult(
            regime=MarketRegime.TRENDING_DOWN,
            allow_trading=True,
            can_short=True,
            can_long=False,
            blocked_reason=None,
            adx=adx_val,
            natr=natr_val,
            slope_pct=slope_pct,
            score=score,
        )
