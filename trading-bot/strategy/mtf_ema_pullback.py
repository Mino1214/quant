"""
MTF EMA Pullback Continuation strategy.
Flow: Regime → Bias → Trend → Trigger → candidate_signal → approval_engine → Entry.
Trigger produces candidate only; approval engine scores and decides entry.
"""
from typing import List, Optional

from core.models import Candle, Direction, Signal, StrategySettings, Timeframe

from indicators.ema import ema, emas_from_candles
from indicators.slope import ema_slope
from indicators.volume import vma_from_candles


def bias_15m(candles_15m: List[Candle], settings: StrategySettings) -> Optional[Direction]:
    """
    Long: close > EMA50, EMA21 > EMA50, EMA50 slope > threshold.
    Short: close < EMA50, EMA21 < EMA50, EMA50 slope < -threshold.
    """
    if len(candles_15m) < settings.ema_slow:
        return None
    emas = emas_from_candles(candles_15m, [settings.ema_mid, settings.ema_slow])
    ema21 = emas.get(settings.ema_mid)
    ema50 = emas.get(settings.ema_slow)
    slope = ema_slope(candles_15m, settings.ema_slow, bars=1)
    if ema21 is None or ema50 is None or slope is None:
        return None
    close = candles_15m[-1].close
    if close > ema50 and ema21 > ema50 and slope > settings.slope_threshold:
        return Direction.LONG
    if close < ema50 and ema21 < ema50 and slope < -settings.slope_threshold:
        return Direction.SHORT
    return None


def trend_5m(candles_5m: List[Candle], settings: StrategySettings) -> Optional[Direction]:
    """
    Long: EMA8 > EMA21 > EMA50, close > EMA21.
    Short: EMA8 < EMA21 < EMA50, close < EMA21.
    """
    if len(candles_5m) < settings.ema_slow:
        return None
    emas = emas_from_candles(
        candles_5m, [settings.ema_fast, settings.ema_mid, settings.ema_slow]
    )
    ema8 = emas.get(settings.ema_fast)
    ema21 = emas.get(settings.ema_mid)
    ema50 = emas.get(settings.ema_slow)
    if ema8 is None or ema21 is None or ema50 is None:
        return None
    close = candles_5m[-1].close
    if ema8 > ema21 > ema50 and close > ema21:
        return Direction.LONG
    if ema8 < ema21 < ema50 and close < ema21:
        return Direction.SHORT
    return None


def trigger_1m(
    candles_1m: List[Candle], settings: StrategySettings, symbol: str = ""
) -> Optional[Signal]:
    """
    Long: low <= EMA8, close > EMA8, close > open, volume > VMA*mult AND volume > previous_volume.
    Short: high >= EMA8, close < EMA8, close < open, volume > VMA*mult AND volume > previous_volume.
    """
    if len(candles_1m) < max(settings.ema_fast, settings.volume_ma_period):
        return None
    ema8 = ema([c.close for c in candles_1m], settings.ema_fast)
    vma_val = vma_from_candles(candles_1m, settings.volume_ma_period)
    if ema8 is None or vma_val is None:
        return None
    c = candles_1m[-1]
    prev_vol = candles_1m[-2].volume
    vol_ok = c.volume > vma_val * settings.volume_multiplier and c.volume > prev_vol
    if not vol_ok:
        return None

    # Long trigger
    if c.low <= ema8 and c.close > ema8 and c.is_bullish:
        return Signal(
            direction=Direction.LONG,
            reason_code="1m_ema_pullback_long",
            timeframe=Timeframe.M1,
            symbol=symbol,
        )
    # Short trigger
    if c.high >= ema8 and c.close < ema8 and c.is_bearish:
        return Signal(
            direction=Direction.SHORT,
            reason_code="1m_ema_pullback_short",
            timeframe=Timeframe.M1,
            symbol=symbol,
        )
    return None


def evaluate_candidate(
    candles_15m: List[Candle],
    candles_5m: List[Candle],
    candles_1m: List[Candle],
    settings: StrategySettings,
    symbol: str = "",
) -> Optional[Signal]:
    """
    Regime → Bias → Trend → Trigger → candidate_signal.
    Returns candidate only when bias, trend, and trigger align. No approval here.
    """
    bias = bias_15m(candles_15m, settings)
    trend = trend_5m(candles_5m, settings)
    trigger = trigger_1m(candles_1m, settings, symbol)
    if bias is None or trend is None or trigger is None:
        return None
    if bias != trend or trend != trigger.direction:
        return None
    return trigger


def evaluate(
    candles_15m: List[Candle],
    candles_5m: List[Candle],
    candles_1m: List[Candle],
    settings: StrategySettings,
    symbol: str = "",
) -> Optional[Signal]:
    """Alias for evaluate_candidate for backward compatibility (caller should use approval_engine)."""
    return evaluate_candidate(candles_15m, candles_5m, candles_1m, settings, symbol)
