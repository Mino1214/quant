"""
Multi-timeframe feature stack: 1m, 5m, 15m features aligned to signal timestamp.
Guarantees no future data leakage: all features use only candles with timestamp <= signal_timestamp.
"""
from datetime import datetime
from typing import Dict, List

# Ordered keys for ML training/inference when using multi-TF feature vector
MULTI_TF_FEATURE_KEYS = [
    "ema_distance_1m",
    "volume_ratio_1m",
    "rsi_1m",
    "momentum_body_ratio_1m",
    "ema_slope_5m",
    "trend_strength_5m",
    "volume_ratio_5m",
    "adx_5m",
    "ema_trend_15m",
    "adx_15m",
    "natr_15m",
    "volatility_state_15m",
]

from core.models import Candle, StrategySettings

from indicators.adx import adx
from indicators.atr import atr
from indicators.ema import ema, ema_series, _closes
from indicators.rsi import rsi
from indicators.volume import vma_from_candles


def _filter_past(candles: List[Candle], t: datetime) -> List[Candle]:
    """Return candles with timestamp <= t (no future data)."""
    return [c for c in candles if c.timestamp <= t]


def _last_completed(candles: List[Candle], t: datetime):
    """Last candle with timestamp <= t."""
    past = _filter_past(candles, t)
    return past[-1] if past else None


def _features_1m(candles_1m: List[Candle], settings: StrategySettings) -> Dict[str, float]:
    """1m features from current (last) 1m context. Uses only past data."""
    out = {
        "ema_distance_1m": 0.0,
        "volume_ratio_1m": 0.0,
        "rsi_1m": 0.0,
        "momentum_body_ratio_1m": 0.0,
    }
    if not candles_1m or len(candles_1m) < settings.ema_mid:
        return out
    c = candles_1m[-1]
    rng = c.high - c.low
    if rng and rng > 0:
        out["momentum_body_ratio_1m"] = abs(c.close - c.open) / rng
    closes = [x.close for x in candles_1m]
    e8 = ema(closes, settings.ema_fast)
    e21 = ema(closes, settings.ema_mid)
    if e8 is not None and e21 is not None and c.close > 0:
        out["ema_distance_1m"] = abs(e8 - e21) / c.close
    if len(candles_1m) >= settings.volume_ma_period:
        vma_val = vma_from_candles(candles_1m, settings.volume_ma_period)
        if vma_val and vma_val > 0:
            out["volume_ratio_1m"] = c.volume / vma_val
    if len(candles_1m) >= settings.rsi_period + 1:
        rsi_val = rsi(closes, settings.rsi_period)
        if rsi_val is not None:
            out["rsi_1m"] = rsi_val
    return out


def _features_5m(candles_5m: List[Candle], settings: StrategySettings) -> Dict[str, float]:
    """5m features: ema_slope, trend_strength, volume_ratio, adx. Uses only past data."""
    out = {
        "ema_slope_5m": 0.0,
        "trend_strength_5m": 0.0,
        "volume_ratio_5m": 0.0,
        "adx_5m": 0.0,
    }
    if not candles_5m or len(candles_5m) < 2:
        return out
    closes = _closes(candles_5m)
    period = min(20, len(closes) - 1)
    if period >= 2:
        series = ema_series(closes, period)
        valid = [v for v in series if v is not None]
        if len(valid) >= 2:
            out["ema_slope_5m"] = (valid[-1] - valid[-2]) / valid[-1] * 100.0 if valid[-1] else 0.0
    if len(candles_5m) >= 14:
        adx_val = adx(candles_5m, 14)
        if adx_val is not None:
            out["adx_5m"] = adx_val
        out["trend_strength_5m"] = out["adx_5m"]
    if len(candles_5m) >= settings.volume_ma_period:
        vma_val = vma_from_candles(candles_5m, settings.volume_ma_period)
        if vma_val and vma_val > 0:
            out["volume_ratio_5m"] = candles_5m[-1].volume / vma_val
    return out


def _features_15m(candles_15m: List[Candle], settings: StrategySettings) -> Dict[str, float]:
    """15m features: ema_trend, adx, natr, volatility_state. Uses only past data."""
    out = {
        "ema_trend_15m": 0.0,
        "adx_15m": 0.0,
        "natr_15m": 0.0,
        "volatility_state_15m": 0.0,
    }
    if not candles_15m or len(candles_15m) < settings.ema_slow:
        return out
    closes = _closes(candles_15m)
    ema_vals = ema_series(closes, settings.ema_slow)
    ema_valid = [v for v in ema_vals if v is not None]
    if ema_valid and candles_15m[-1].close and candles_15m[-1].close > 0:
        out["ema_trend_15m"] = (candles_15m[-1].close - ema_valid[-1]) / candles_15m[-1].close * 100.0
    if len(candles_15m) >= 14:
        adx_val = adx(candles_15m, 14)
        if adx_val is not None:
            out["adx_15m"] = adx_val
    if len(candles_15m) >= 14 + 1:
        atr_val = atr(candles_15m, 14)
        if atr_val is not None and candles_15m[-1].close and candles_15m[-1].close > 0:
            out["natr_15m"] = atr_val / candles_15m[-1].close * 100.0
    out["volatility_state_15m"] = out["natr_15m"]
    return out


def build_multi_tf_features(
    candles_1m: List[Candle],
    candles_5m: List[Candle],
    candles_15m: List[Candle],
    signal_timestamp: datetime,
    settings: StrategySettings,
) -> Dict[str, float]:
    """
    Build a single feature dict from 1m, 5m, 15m with alignment to signal_timestamp.
    Only candles with timestamp <= signal_timestamp are used (no future leakage).
    Returns merged dict with keys like ema_distance_1m, volume_ratio_1m, rsi_1m, momentum_body_ratio_1m,
    ema_slope_5m, trend_strength_5m, volume_ratio_5m, adx_5m, ema_trend_15m, adx_15m, natr_15m, volatility_state_15m.
    """
    t = signal_timestamp
    c1 = _filter_past(candles_1m, t)
    c5 = _filter_past(candles_5m, t)
    c15 = _filter_past(candles_15m, t)
    f1 = _features_1m(c1, settings) if c1 else {}
    f5 = _features_5m(c5, settings) if c5 else {}
    f15 = _features_15m(c15, settings) if c15 else {}
    out = {}
    out.update(f1)
    out.update(f5)
    out.update(f15)
    return out
