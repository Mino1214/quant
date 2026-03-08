"""
Extract numeric features from ApprovalContext for Signal Distribution Analysis.
Same data source as approval_engine (ema, vma, rsi) for consistent scoring.
Trend: ema20/ema50 on 5m, slope, bias for scan/backtest.
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
    Compute ema_distance, volume_ratio, rsi_5m, momentum_ratio, and trend (ema20, ema50, slope, bias).
    Returns dict; trend fields for long filter: ema20 > ema50 and ema50_slope > 0.
    """
    out: Dict[str, float] = {
        "ema_distance": 0.0,
        "volume_ratio": 0.0,
        "rsi_5m": 0.0,
        "momentum_ratio": 0.0,
        "ema20": 0.0,
        "ema50": 0.0,
        "ema20_gt_ema50": 0.0,  # 1.0 = True, 0.0 = False (for scan)
        "ema50_slope": 0.0,
        "trend_bias": 0.0,  # 1 = long bias, -1 = short bias, 0 = neutral
        # Entry quality (for stricter candidate filtering / scan)
        "pullback_depth_pct": 0.0,   # how much price pulled back from recent high/low (0..1)
        "breakout_confirmation": 0.0,  # 1.0 if close beyond recent high/low, else 0
        "lower_wick_ratio": 0.0,   # lower wick / range of last candle
        "upper_wick_ratio": 0.0,   # upper wick / range of last candle
    }

    if not candles_1m or not candles_5m:
        return out

    # momentum_ratio: body_size / range for last 1m candle
    c = candles_1m[-1]
    rng = c.high - c.low
    if rng and rng > 0:
        body = abs(c.close - c.open)
        out["momentum_ratio"] = body / rng
        # Wick structure: lower wick = min(open,close)-low, upper = high - max(open,close)
        low_wick = min(c.open, c.close) - c.low
        up_wick = c.high - max(c.open, c.close)
        out["lower_wick_ratio"] = low_wick / rng
        out["upper_wick_ratio"] = up_wick / rng

    # Pullback depth + breakout confirmation (recent high/low over lookback)
    lookback = getattr(settings, "swing_lookback", 10)
    if len(candles_1m) >= lookback + 1:
        window = candles_1m[-(lookback + 1) : -1]  # exclude current bar for recent high/low
        if window:
            recent_high = max(k.high for k in window)
            recent_low = min(k.low for k in window)
            close = candles_1m[-1].close
            rng = recent_high - recent_low
            if rng and rng > 0:
                out["pullback_depth_pct"] = (recent_high - close) / rng
            if close > recent_high:
                out["breakout_confirmation"] = 1.0  # long breakout
            elif close < recent_low:
                out["breakout_confirmation"] = -1.0  # short breakout

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

    # Trend on 5m: ema20, ema50, ema50_slope, trend_bias (long: ema20>ema50 and slope>0; short: ema20<ema50 and slope<0)
    if len(candles_5m) >= 50:
        closes_5m = [x.close for x in candles_5m]
        e20 = ema(closes_5m, 20)
        e50 = ema(closes_5m, 50)
        if e20 is not None and e50 is not None:
            out["ema20"] = e20
            out["ema50"] = e50
            out["ema20_gt_ema50"] = 1.0 if e20 > e50 else 0.0
        if len(closes_5m) >= 51:
            e50_prev = ema(closes_5m[:-1], 50)
            if e50 is not None and e50_prev is not None and e50_prev and abs(e50_prev) > 1e-12:
                out["ema50_slope"] = (e50 - e50_prev) / e50_prev
                slope = out["ema50_slope"]
                gt = out.get("ema20_gt_ema50", 0)
                if gt > 0.5 and slope > 0:
                    out["trend_bias"] = 1.0
                elif gt < 0.5 and slope < 0:
                    out["trend_bias"] = -1.0

    return out
