"""
Extract numeric features from ApprovalContext for Signal Distribution Analysis.
Same data source as approval_engine (ema, vma, rsi) for consistent scoring.
"""
from typing import Dict

from core.models import StrategySettings

from indicators.ema import ema
from indicators.rsi import rsi
from indicators.volume import vma_from_candles


def extract_feature_values(
    candles_1m: list,
    candles_5m: list,
    settings: StrategySettings,
) -> Dict[str, float]:
    """
    Compute ema_distance, volume_ratio, rsi_5m from current context.
    Returns dict with keys ema_distance, volume_ratio, rsi_5m; missing values as 0.0.
    """
    out: Dict[str, float] = {"ema_distance": 0.0, "volume_ratio": 0.0, "rsi_5m": 0.0, "momentum_ratio": 0.0}

    if not candles_1m or not candles_5m:
        return out

    # momentum_ratio: body_size / range for last 1m candle (body/range)
    c = candles_1m[-1]
    rng = c.high - c.low
    if rng and rng > 0:
        body = abs(c.close - c.open)
        out["momentum_ratio"] = body / rng

    # ema_distance: abs(EMA8 - EMA21) / close on 1m
    if len(candles_1m) >= settings.ema_mid:
        closes_1m = [c.close for c in candles_1m]
        e8 = ema(closes_1m, settings.ema_fast)
        e21 = ema(closes_1m, settings.ema_mid)
        close = candles_1m[-1].close
        if e8 is not None and e21 is not None and close and close > 0:
            out["ema_distance"] = abs(e8 - e21) / close

    # volume_ratio: last 1m volume / VMA(volume_ma_period)
    if len(candles_1m) >= settings.volume_ma_period:
        vma_val = vma_from_candles(candles_1m, settings.volume_ma_period)
        if vma_val is not None and vma_val > 0:
            out["volume_ratio"] = candles_1m[-1].volume / vma_val

    # rsi_5m: RSI on 5m closes
    if len(candles_5m) >= settings.rsi_period + 1:
        closes_5m = [c.close for c in candles_5m]
        rsi_val = rsi(closes_5m, settings.rsi_period)
        if rsi_val is not None:
            out["rsi_5m"] = rsi_val

    return out
