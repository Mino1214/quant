"""
Extract numeric features from ApprovalContext for Signal Distribution Analysis.
Same data source as approval_engine (ema, vma, rsi) for consistent scoring.
Trend: ema20/ema50 on 5m, slope, bias for scan/backtest.
"""
from typing import Dict, List, Optional

from core.models import StrategySettings

from indicators.atr import atr
from indicators.ema import ema
from indicators.rsi import rsi
from indicators.volume import vma_from_candles


def extract_feature_values(
    candles_1m: list,
    candles_5m: list,
    settings: StrategySettings,
    candles_15m: Optional[List] = None,
) -> Dict[str, float]:
    """
    Compute ema_distance, volume_ratio, rsi_5m, momentum_ratio, trend, volatility,
    positioning, multi-timeframe alignment, volume structure, and candle structure features.
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
        # Volatility
        "atr_1m": 0.0,
        "atr_5m": 0.0,
        "natr_1m": 0.0,
        "natr_5m": 0.0,
        "range_pct": 0.0,
        "body_pct": 0.0,
        # Positioning
        "dist_from_20ema_pct": 0.0,
        "dist_from_50ema_pct": 0.0,
        "dist_from_recent_high_pct": 0.0,
        "dist_from_recent_low_pct": 0.0,
        "close_in_recent_range": 0.0,
        # Multi-timeframe alignment (5m aliases set from existing; 15m when candles_15m provided)
        "ema20_5m_gt_ema50_5m": 0.0,
        "ema50_slope_5m": 0.0,
        "ema20_15m_gt_ema50_15m": 0.0,
        "ema50_slope_15m": 0.0,
        "rsi_15m": 0.0,
        # Volume structure
        "volume_zscore": 0.0,
        "volume_change_pct": 0.0,
        "volume_ratio_5m": 0.0,
        # Candle structure
        "body_to_range_ratio": 0.0,
        "close_near_high": 0.0,
        "close_near_low": 0.0,
    }

    if not candles_1m or not candles_5m:
        return out

    # momentum_ratio and candle structure: body_size / range for last 1m candle
    c = candles_1m[-1]
    rng = c.high - c.low
    body = abs(c.close - c.open)
    if rng and rng > 0:
        out["momentum_ratio"] = body / rng
        out["body_to_range_ratio"] = body / rng
        # Candle structure: close position within range
        out["close_near_high"] = (c.high - c.close) / rng
        out["close_near_low"] = (c.close - c.low) / rng
        # Wick structure: lower wick = min(open,close)-low, upper = high - max(open,close)
        low_wick = min(c.open, c.close) - c.low
        up_wick = c.high - max(c.open, c.close)
        out["lower_wick_ratio"] = low_wick / rng
        out["upper_wick_ratio"] = up_wick / rng
    # Volatility (1m): range_pct, body_pct
    if c.close and c.close > 0:
        if rng and rng > 0:
            out["range_pct"] = (rng / c.close) * 100.0
        out["body_pct"] = (body / c.close) * 100.0

    # Pullback depth + breakout confirmation + positioning (recent high/low over lookback)
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
                out["close_in_recent_range"] = (close - recent_low) / rng
            if close > recent_high:
                out["breakout_confirmation"] = 1.0  # long breakout
            elif close < recent_low:
                out["breakout_confirmation"] = -1.0  # short breakout
            # Positioning: distance from recent high/low as pct of price
            if close and close > 0:
                out["dist_from_recent_high_pct"] = (recent_high - close) / close * 100.0
                out["dist_from_recent_low_pct"] = (close - recent_low) / close * 100.0

    # Volatility: ATR(14) and NATR on 1m and 5m
    atr_period = 14
    if len(candles_1m) >= atr_period + 1:
        atr_1m_val = atr(candles_1m, atr_period)
        if atr_1m_val is not None:
            out["atr_1m"] = atr_1m_val
            if c.close and c.close > 0:
                out["natr_1m"] = atr_1m_val / c.close * 100.0
    if len(candles_5m) >= atr_period + 1:
        atr_5m_val = atr(candles_5m, atr_period)
        if atr_5m_val is not None:
            out["atr_5m"] = atr_5m_val
            c5 = candles_5m[-1]
            if c5.close and c5.close > 0:
                out["natr_5m"] = atr_5m_val / c5.close * 100.0

    # Positioning: distance from EMA20/50 on 1m (pct of price)
    if len(candles_1m) >= 50:
        closes_1m = [x.close for x in candles_1m]
        e20_1m = ema(closes_1m, 20)
        e50_1m = ema(closes_1m, 50)
        close = candles_1m[-1].close
        if close and close > 0 and e20_1m is not None:
            out["dist_from_20ema_pct"] = (close - e20_1m) / close * 100.0
        if close and close > 0 and e50_1m is not None:
            out["dist_from_50ema_pct"] = (close - e50_1m) / close * 100.0

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

    # Volume structure: z-score of last 1m volume over lookback; change vs prev bar
    v_period = settings.volume_ma_period
    if len(candles_1m) >= v_period:
        vols = [x.volume for x in candles_1m[-v_period:]]
        last_vol = vols[-1]
        mean_vol = sum(vols) / len(vols)
        variance = sum((v - mean_vol) ** 2 for v in vols) / len(vols)
        std_vol = variance ** 0.5 if variance > 0 else 0.0
        if std_vol and std_vol > 0:
            out["volume_zscore"] = (last_vol - mean_vol) / std_vol
    if len(candles_1m) >= 2:
        prev_vol = candles_1m[-2].volume
        if prev_vol and prev_vol > 0:
            out["volume_change_pct"] = (candles_1m[-1].volume - prev_vol) / prev_vol * 100.0

    # rsi_5m: RSI on 5m closes
    if len(candles_5m) >= settings.rsi_period + 1:
        closes_5m = [c.close for c in candles_5m]
        rsi_val = rsi(closes_5m, settings.rsi_period)
        if rsi_val is not None:
            out["rsi_5m"] = rsi_val

    # Trend on 5m: ema20, ema50, ema50_slope, trend_bias; MTF 5m aliases; volume_ratio_5m
    if len(candles_5m) >= 50:
        closes_5m = [x.close for x in candles_5m]
        e20 = ema(closes_5m, 20)
        e50 = ema(closes_5m, 50)
        if e20 is not None and e50 is not None:
            out["ema20"] = e20
            out["ema50"] = e50
            out["ema20_gt_ema50"] = 1.0 if e20 > e50 else 0.0
            out["ema20_5m_gt_ema50_5m"] = out["ema20_gt_ema50"]
        if len(closes_5m) >= 51:
            e50_prev = ema(closes_5m[:-1], 50)
            if e50 is not None and e50_prev is not None and e50_prev and abs(e50_prev) > 1e-12:
                out["ema50_slope"] = (e50 - e50_prev) / e50_prev
                out["ema50_slope_5m"] = out["ema50_slope"]
                slope = out["ema50_slope"]
                gt = out.get("ema20_gt_ema50", 0)
                if gt > 0.5 and slope > 0:
                    out["trend_bias"] = 1.0
                elif gt < 0.5 and slope < 0:
                    out["trend_bias"] = -1.0
        # Volume structure: 5m volume / VMA(5m volumes)
        v_period_5m = min(20, len(candles_5m))
        if v_period_5m >= 1:
            vma_5m = vma_from_candles(candles_5m, v_period_5m)
            if vma_5m is not None and vma_5m > 0:
                out["volume_ratio_5m"] = candles_5m[-1].volume / vma_5m

    # Multi-timeframe 15m: ema20_15m_gt_ema50_15m, ema50_slope_15m, rsi_15m
    if candles_15m and len(candles_15m) >= 50:
        closes_15m = [x.close for x in candles_15m]
        e20_15m = ema(closes_15m, 20)
        e50_15m = ema(closes_15m, 50)
        if e20_15m is not None and e50_15m is not None:
            out["ema20_15m_gt_ema50_15m"] = 1.0 if e20_15m > e50_15m else 0.0
        if len(closes_15m) >= 51:
            e50_15m_prev = ema(closes_15m[:-1], 50)
            if e50_15m is not None and e50_15m_prev is not None and e50_15m_prev and abs(e50_15m_prev) > 1e-12:
                out["ema50_slope_15m"] = (e50_15m - e50_15m_prev) / e50_15m_prev
        rsi_period = getattr(settings, "rsi_period", 14)
        if len(candles_15m) >= rsi_period + 1:
            rsi_15m_val = rsi(closes_15m, rsi_period)
            if rsi_15m_val is not None:
                out["rsi_15m"] = rsi_15m_val

    return out
