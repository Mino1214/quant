"""
Signal Quality Filter: EMA distance, volume expansion, momentum candle, breakout.
HTF Momentum: 5m RSI filter (long only when RSI > 55, short only when RSI < 45).
"""
from typing import List

from core.models import Candle, Direction, StrategySettings

from indicators.ema import ema
from indicators.rsi import rsi
from indicators.volume import vma_from_candles


def _ema_distance_ok(candles_1m: List[Candle], settings: StrategySettings) -> bool:
    """EMA distance > threshold → 횡보장에서 EMA가 붙어 있으면 진입 금지 해제(멀어져 있을 때만 진입)."""
    if len(candles_1m) < settings.ema_mid:
        return False
    closes = [c.close for c in candles_1m]
    ema8_val = ema(closes, settings.ema_fast)
    ema21_val = ema(closes, settings.ema_mid)
    if ema8_val is None or ema21_val is None:
        return False
    close = candles_1m[-1].close
    if close <= 0:
        return False
    ema_distance = abs(ema8_val - ema21_val) / close
    return ema_distance >= settings.ema_distance_threshold


def _volume_expansion_ok(candles_1m: List[Candle], settings: StrategySettings) -> bool:
    """volume > VMA*mult (trigger에서 이미 체크) AND volume > previous_volume."""
    if len(candles_1m) < 2:
        return False
    c = candles_1m[-1]
    prev = candles_1m[-2]
    vma_val = vma_from_candles(candles_1m, settings.volume_ma_period)
    if vma_val is None:
        return False
    vol_ok = c.volume > vma_val * settings.volume_multiplier
    expansion = c.volume > prev.volume
    return vol_ok and expansion


def _momentum_candle_ok(candles_1m: List[Candle], settings: StrategySettings) -> bool:
    """body_size / candle_range >= momentum_body_ratio (몸통이 전체의 50% 이상)."""
    if not candles_1m:
        return False
    c = candles_1m[-1]
    body_size = abs(c.close - c.open)
    candle_range = c.high - c.low
    if candle_range <= 0:
        return False
    return (body_size / candle_range) >= settings.momentum_body_ratio


def _breakout_ok(candles_1m: List[Candle], direction: Direction) -> bool:
    """Long: close > previous_high. Short: close < previous_low."""
    if len(candles_1m) < 2:
        return False
    c = candles_1m[-1]
    prev = candles_1m[-2]
    if direction == Direction.LONG:
        return c.close > prev.high
    return c.close < prev.low


def signal_quality_score(
    candles_1m: List[Candle],
    direction: Direction,
    settings: StrategySettings,
) -> int:
    """
    Score 0..4: EMA distance (+1), volume expansion (+1), momentum candle (+1), breakout (+1).
    """
    score = 0
    if _ema_distance_ok(candles_1m, settings):
        score += 1
    if _volume_expansion_ok(candles_1m, settings):
        score += 1
    if _momentum_candle_ok(candles_1m, settings):
        score += 1
    if _breakout_ok(candles_1m, direction):
        score += 1
    return score


def htf_rsi_allows(
    candles_5m: List[Candle],
    direction: Direction,
    settings: StrategySettings,
) -> bool:
    """
    HTF Momentum: 5m RSI > 55 → long만 허용, 5m RSI < 45 → short만 허용.
    RSI in [45, 55] → 진입 불가.
    """
    if len(candles_5m) < settings.rsi_period + 1:
        return False
    closes = [c.close for c in candles_5m]
    rsi_val = rsi(closes, settings.rsi_period)
    if rsi_val is None:
        return False
    if direction == Direction.LONG:
        return rsi_val > settings.rsi_long_min
    return rsi_val < settings.rsi_short_max


def signal_quality_pass(
    candles_1m: List[Candle],
    candles_5m: List[Candle],
    direction: Direction,
    settings: StrategySettings,
) -> bool:
    """Score >= threshold and HTF RSI allows direction."""
    score = signal_quality_score(candles_1m, direction, settings)
    if score < settings.signal_score_threshold:
        return False
    return htf_rsi_allows(candles_5m, direction, settings)
