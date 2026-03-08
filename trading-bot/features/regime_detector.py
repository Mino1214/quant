"""
Regime detector for leverage: ADX, EMA slope, NATR.
Outputs regime (TRENDING_UP, TRENDING_DOWN, RANGE, CHAOTIC), trend_direction, volatility_level.
"""
from dataclasses import dataclass
from typing import List

from core.models import Candle

from indicators.adx import adx
from indicators.atr import atr
from indicators.ema import ema_series, _closes


@dataclass
class RegimeDetectorResult:
    """Regime classification for leverage and filtering."""
    regime: str  # TRENDING_UP, TRENDING_DOWN, RANGE, CHAOTIC
    trend_direction: str  # "up", "down", "neutral"
    volatility_level: str  # "low", "medium", "high"
    adx: float
    natr: float
    slope_pct: float


def _ema_slope_pct(closes: List[float], period: int, lookback: int) -> float | None:
    """(EMA_now - EMA_prev) / EMA_now * 100."""
    if len(closes) < period + lookback:
        return None
    series = ema_series(closes, period)
    valid = [v for v in series if v is not None]
    if len(valid) < lookback + 1:
        return None
    ema_now = valid[-1]
    ema_prev = valid[-1 - lookback]
    if ema_now == 0:
        return None
    return (ema_now - ema_prev) / ema_now * 100.0


def _natr_value(candles: List[Candle], period: int) -> float | None:
    """NATR = ATR / close * 100 for last candle."""
    if len(candles) < period + 1:
        return None
    atr_val = atr(candles, period)
    if atr_val is None:
        return None
    close = candles[-1].close
    if close <= 0:
        return None
    return atr_val / close * 100.0


def detect_regime(
    candles_15m: List[Candle],
    adx_len: int = 14,
    adx_trend_threshold: float = 25.0,
    adx_range_threshold: float = 15.0,
    ema_slow_len: int = 50,
    slope_lookback: int = 5,
    atr_len: int = 14,
    natr_chaotic_threshold: float = 1.0,
    natr_high: float = 0.6,
    natr_low: float = 0.15,
) -> RegimeDetectorResult:
    """
    Classify regime from 15m candles. No future data: uses only past/completed candles.
    Rules: NATR high -> CHAOTIC; ADX > 25 -> TREND; ADX < 15 -> RANGE.
    """
    regime = "RANGE"
    trend_direction = "neutral"
    volatility_level = "medium"
    adx_val = 0.0
    natr_val = 0.0
    slope_pct = 0.0

    min_len = max(ema_slow_len + slope_lookback, adx_len * 3, atr_len + 1)
    if not candles_15m or len(candles_15m) < min_len:
        return RegimeDetectorResult(
            regime="RANGE",
            trend_direction="neutral",
            volatility_level="medium",
            adx=0.0,
            natr=0.0,
            slope_pct=0.0,
        )

    closes = _closes(candles_15m)
    adx_val = adx(candles_15m, adx_len) or 0.0
    natr_val = _natr_value(candles_15m, atr_len) or 0.0
    slope_pct = _ema_slope_pct(closes, ema_slow_len, slope_lookback) or 0.0

    # Volatility level from NATR
    if natr_val >= natr_high:
        volatility_level = "high"
    elif natr_val <= natr_low:
        volatility_level = "low"
    else:
        volatility_level = "medium"

    # CHAOTIC: NATR too high
    if natr_val > natr_chaotic_threshold:
        return RegimeDetectorResult(
            regime="CHAOTIC",
            trend_direction="neutral",
            volatility_level=volatility_level,
            adx=adx_val,
            natr=natr_val,
            slope_pct=slope_pct,
        )

    # TREND: ADX > threshold
    if adx_val > adx_trend_threshold:
        ema_series_val = ema_series(closes, ema_slow_len)
        ema_valid = [v for v in ema_series_val if v is not None]
        ema_now = ema_valid[-1] if ema_valid else None
        close = candles_15m[-1].close
        if ema_now is not None:
            if close > ema_now:
                regime = "TRENDING_UP"
                trend_direction = "up"
            else:
                regime = "TRENDING_DOWN"
                trend_direction = "down"
        return RegimeDetectorResult(
            regime=regime,
            trend_direction=trend_direction,
            volatility_level=volatility_level,
            adx=adx_val,
            natr=natr_val,
            slope_pct=slope_pct,
        )

    # RANGE: ADX < threshold
    if adx_val < adx_range_threshold:
        return RegimeDetectorResult(
            regime="RANGE",
            trend_direction="neutral",
            volatility_level=volatility_level,
            adx=adx_val,
            natr=natr_val,
            slope_pct=slope_pct,
        )

    # Between thresholds: use slope for direction hint, still RANGE
    return RegimeDetectorResult(
        regime="RANGE",
        trend_direction="up" if slope_pct > 0 else "down" if slope_pct < 0 else "neutral",
        volatility_level=volatility_level,
        adx=adx_val,
        natr=natr_val,
        slope_pct=slope_pct,
    )
