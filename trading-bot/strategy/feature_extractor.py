"""
Extract numeric features from candles for feature_store_1m.
Strategy-independent feature set for research platform.

확장 내용:
- 1m / 5m / 15m EMA(20/50/200), slope, spread, distance
- RSI 1m/5m/15m + delta/slope
- ATR/NATR 1m/5m/15m + ATR ratio
- volume_ma20 / volume_ratio / volume_ratio_5m / volume_ratio_15m / zscore / spike
- candle structure / positioning / breakout / pullback
- ADX(14), regime_score, regime_label, regime_tradable
"""

from typing import Dict, List, Optional

from core.models import StrategySettings

from indicators.atr import atr
from indicators.ema import ema
from indicators.rsi import rsi
from indicators.volume import vma_from_candles


def _safe_div(a: float, b: float) -> float:
    if b is None or abs(b) < 1e-12:
        return 0.0
    return a / b


def _safe_pct_diff(a: float, b: float) -> float:
    if b is None or abs(b) < 1e-12:
        return 0.0
    return (a - b) / b * 100.0


def _ema_last_and_prev(series: List[float], period: int):
    if len(series) < period:
        return None, None

    alpha = 2.0 / (period + 1)
    ema_val = sum(series[:period]) / period
    prev_ema = None

    for i in range(period, len(series)):
        if i == len(series) - 1:
            prev_ema = ema_val
        ema_val = (series[i] - ema_val) * alpha + ema_val

    return ema_val, prev_ema


def _calc_slope_ratio(series: List[float], period: int) -> float:
    if len(series) < period + 1:
        return 0.0

    cur, prev = _ema_last_and_prev(series, period)

    if cur is None or prev is None or abs(prev) < 1e-12:
        return 0.0

    return (cur - prev) / prev
    """
    마지막 값과 직전 값의 상대 변화율.
    """
    if len(series) < period + 1:
        return 0.0
    cur = ema(series, period)
    prev = ema(series[:-1], period)
    if cur is None or prev is None or abs(prev) < 1e-12:
        return 0.0
    return (cur - prev) / prev


from typing import Dict, Optional, List


def extract_feature_values_research_minimal(
    candles_1m: list,
    candles_5m: list,
    settings: StrategySettings,
    candles_15m: Optional[List] = None,
) -> Dict[str, float]:
    """
    Minimal feature extractor for research/backtest hot path.
    Only computes the fields needed by mtf_trend_pullback_research strict/base logic
    and regime-threshold experiments.
    """
    out: Dict[str, float] = {
        "ema20_slope_1m": 0.0,
        "ema20_slope_5m": 0.0,
        "ema20_slope_15m": 0.0,
        "rsi_1m": 0.0,
        "rsi_5m": 0.0,
        "pullback_depth_pct": 0.0,
        # optional quality filters
        "adx_14": 0.0,
        "volume_ratio": 0.0,
    }

    if not candles_1m or not candles_5m:
        return out

    # close 배열은 한 번만 만든다
    closes_1m = [c.close for c in candles_1m if getattr(c, "close", None) is not None]
    closes_5m = [c.close for c in candles_5m if getattr(c, "close", None) is not None]

    # EMA20 slope (fast helper reuse)
    ema20_1m_cur, ema20_1m_prev = _ema_last_and_prev(closes_1m, 20)
    if ema20_1m_cur is not None and ema20_1m_prev is not None and abs(ema20_1m_prev) > 1e-12:
        out["ema20_slope_1m"] = (ema20_1m_cur - ema20_1m_prev) / ema20_1m_prev

    ema20_5m_cur, ema20_5m_prev = _ema_last_and_prev(closes_5m, 20)
    if ema20_5m_cur is not None and ema20_5m_prev is not None and abs(ema20_5m_prev) > 1e-12:
        out["ema20_slope_5m"] = (ema20_5m_cur - ema20_5m_prev) / ema20_5m_prev

    if candles_15m:
        closes_15m = [c.close for c in candles_15m if getattr(c, "close", None) is not None]
        ema20_15m_cur, ema20_15m_prev = _ema_last_and_prev(closes_15m, 20)
        if ema20_15m_cur is not None and ema20_15m_prev is not None and abs(ema20_15m_prev) > 1e-12:
            out["ema20_slope_15m"] = (ema20_15m_cur - ema20_15m_prev) / ema20_15m_prev

    # RSI (strict/base logic에 필요한 것만)
    rsi_period = getattr(settings, "rsi_period", 14)
    if len(closes_1m) >= rsi_period + 1:
        rsi_1m_val = rsi(closes_1m, rsi_period)
        if rsi_1m_val is not None:
            out["rsi_1m"] = rsi_1m_val

    if len(closes_5m) >= rsi_period + 1:
        rsi_5m_val = rsi(closes_5m, rsi_period)
        if rsi_5m_val is not None:
            out["rsi_5m"] = rsi_5m_val

    # Pullback depth
    lookback = getattr(settings, "swing_lookback", 10)
    if len(candles_1m) >= lookback + 1:
        window = candles_1m[-(lookback + 1):-1]  # 현재 봉 제외
        if window:
            recent_high = max(k.high for k in window)
            recent_low = min(k.low for k in window)
            close = candles_1m[-1].close
            rng = recent_high - recent_low
            if rng > 1e-12:
                out["pullback_depth_pct"] = (recent_high - close) / rng

    # Optional quality filters
    out["adx_14"] = _calc_adx(candles_1m, 14)

    vol_period = getattr(settings, "volume_ma_period", 20)
    if len(candles_1m) >= vol_period:
        vma_val = vma_from_candles(candles_1m, vol_period)
        last_vol = getattr(candles_1m[-1], "volume", 0.0) or 0.0
        if vma_val is not None and vma_val > 1e-12:
            out["volume_ratio"] = last_vol / vma_val

    return out


def _calc_adx(candles: List, period: int = 14) -> float:
    """
    간단한 ADX 구현.
    candles 길이가 충분하지 않으면 0 반환.
    """
    if len(candles) < period * 2:
        return 0.0

    trs: List[float] = []
    plus_dm: List[float] = []
    minus_dm: List[float] = []

    for i in range(1, len(candles)):
        cur = candles[i]
        prev = candles[i - 1]

        high_diff = cur.high - prev.high
        low_diff = prev.low - cur.low

        pdm = high_diff if high_diff > low_diff and high_diff > 0 else 0.0
        mdm = low_diff if low_diff > high_diff and low_diff > 0 else 0.0

        tr = max(
            cur.high - cur.low,
            abs(cur.high - prev.close),
            abs(cur.low - prev.close),
        )

        trs.append(tr)
        plus_dm.append(pdm)
        minus_dm.append(mdm)

    if len(trs) < period:
        return 0.0

    # Wilder 스타일 근사
    tr14 = sum(trs[:period])
    pdm14 = sum(plus_dm[:period])
    mdm14 = sum(minus_dm[:period])

    dxs: List[float] = []

    for i in range(period, len(trs)):
        tr14 = tr14 - (tr14 / period) + trs[i]
        pdm14 = pdm14 - (pdm14 / period) + plus_dm[i]
        mdm14 = mdm14 - (mdm14 / period) + minus_dm[i]

        if tr14 <= 1e-12:
            continue

        pdi = 100.0 * (pdm14 / tr14)
        mdi = 100.0 * (mdm14 / tr14)
        denom = pdi + mdi
        dx = 0.0 if denom <= 1e-12 else 100.0 * abs(pdi - mdi) / denom
        dxs.append(dx)

    if not dxs:
        return 0.0

    if len(dxs) < period:
        return sum(dxs) / len(dxs)

    adx_seed = sum(dxs[:period]) / period
    adx_val = adx_seed
    for dx in dxs[period:]:
        adx_val = ((adx_val * (period - 1)) + dx) / period
    return adx_val


def extract_feature_values(
    candles_1m: list,
    candles_5m: list,
    settings: StrategySettings,
    candles_15m: Optional[List] = None,
) -> Dict[str, float]:
    out: Dict[str, float] = {
        # legacy / existing
        "ema_distance": 0.0,
        "volume_ratio": 0.0,
        "rsi_5m": 0.0,
        "momentum_ratio": 0.0,
        "ema20": 0.0,   # legacy alias for ema20_5m
        "ema50": 0.0,   # legacy alias for ema50_5m
        "ema20_gt_ema50": 0.0,
        "ema50_slope": 0.0,  # legacy alias for ema50_slope_5m
        "trend_bias": 0.0,
        "pullback_depth_pct": 0.0,
        "breakout_confirmation": 0.0,
        "lower_wick_ratio": 0.0,
        "upper_wick_ratio": 0.0,
        "atr_1m": 0.0,
        "atr_5m": 0.0,
        "natr_1m": 0.0,
        "natr_5m": 0.0,
        "range_pct": 0.0,
        "body_pct": 0.0,
        "dist_from_20ema_pct": 0.0,
        "dist_from_50ema_pct": 0.0,
        "dist_from_recent_high_pct": 0.0,
        "dist_from_recent_low_pct": 0.0,
        "close_in_recent_range": 0.0,
        "ema20_5m_gt_ema50_5m": 0.0,
        "ema50_slope_5m": 0.0,
        "ema20_15m_gt_ema50_15m": 0.0,
        "ema50_slope_15m": 0.0,
        "rsi_15m": 0.0,
        "volume_zscore": 0.0,
        "volume_change_pct": 0.0,
        "volume_ratio_5m": 0.0,
        "body_to_range_ratio": 0.0,
        "close_near_high": 0.0,
        "close_near_low": 0.0,
        "atr_ratio": 0.0,
        "distance_from_high_20": 0.0,
        "candle_strength": 0.0,
        "close_position_in_candle": 0.0,
        "volume_spike": 0.0,

        # extended for feature_store_1m
        "ema20_1m": 0.0,
        "ema50_1m": 0.0,
        "ema200_1m": 0.0,
        "ema20_5m": 0.0,
        "ema50_5m": 0.0,
        "ema200_5m": 0.0,
        "ema20_15m": 0.0,
        "ema50_15m": 0.0,
        "ema200_15m": 0.0,

        "ema20_slope_1m": 0.0,
        "ema50_slope_1m": 0.0,
        "ema200_slope_1m": 0.0,
        "ema20_slope_5m": 0.0,
        "ema200_slope_5m": 0.0,
        "ema20_slope_15m": 0.0,
        "ema200_slope_15m": 0.0,

        "dist_from_ema20_pct": 0.0,
        "dist_from_ema50_pct": 0.0,
        "dist_from_ema200_pct": 0.0,

        "ema20_50_spread_pct": 0.0,
        "ema50_200_spread_pct": 0.0,
        "ema20_200_spread_pct": 0.0,

        "ema50_gt_ema200": 0.0,
        "ema_stack_score": 0.0,

        "rsi_1m": 0.0,
        "rsi_delta": 0.0,
        "rsi_slope": 0.0,

        "atr_15m": 0.0,
        "natr_15m": 0.0,
        "atr_ratio_1m_5m": 0.0,
        "atr_ratio_5m_15m": 0.0,
        "range_ma20": 0.0,
        "range_zscore": 0.0,

        "volume_ma20": 0.0,
        "volume_ratio_15m": 0.0,

        "recent_high_20": 0.0,
        "recent_low_20": 0.0,
        "close_in_range_pct": 0.0,

        "breakout_strength": 0.0,

        "adx_14": 0.0,
        "ema50_slope_pct": 0.0,
        "natr_regime": "LOW",
        "regime_score": 0.0,
        "regime_label": "RANGING",
        "regime_tradable": 0.0,
    }

    if not candles_1m or not candles_5m:
        return out

    c1 = candles_1m[-1]
    close_1m = c1.close if c1.close else 0.0

    # ------------------------------------------------------------------
    # Candle structure (1m)
    # ------------------------------------------------------------------
    rng_1m = c1.high - c1.low
    body_1m = abs(c1.close - c1.open)

    if rng_1m > 0:
        out["momentum_ratio"] = body_1m / rng_1m
        out["body_to_range_ratio"] = body_1m / rng_1m
        out["candle_strength"] = body_1m / rng_1m

        # 의미상 이름은 유지하되 값은 "위/아래에 얼마나 가까운가"로 맞춤
        out["close_near_high"] = (c1.close - c1.low) / rng_1m
        out["close_near_low"] = (c1.high - c1.close) / rng_1m
        out["close_position_in_candle"] = (c1.close - c1.low) / rng_1m

        low_wick = min(c1.open, c1.close) - c1.low
        up_wick = c1.high - max(c1.open, c1.close)
        out["lower_wick_ratio"] = low_wick / rng_1m
        out["upper_wick_ratio"] = up_wick / rng_1m

    if close_1m > 0:
        if rng_1m > 0:
            out["range_pct"] = rng_1m / close_1m * 100.0
        out["body_pct"] = body_1m / close_1m * 100.0

    # range 통계
    if len(candles_1m) >= 20:
        ranges = [(x.high - x.low) for x in candles_1m[-20:]]
        range_ma20 = sum(ranges) / len(ranges)
        out["range_ma20"] = range_ma20
        variance = sum((r - range_ma20) ** 2 for r in ranges) / len(ranges)
        std_range = variance ** 0.5
        if std_range > 1e-12:
            out["range_zscore"] = (ranges[-1] - range_ma20) / std_range

    # ------------------------------------------------------------------
    # Recent high/low positioning
    # ------------------------------------------------------------------
    if len(candles_1m) >= 21:
        window20 = candles_1m[-21:-1]
        recent_high = max(k.high for k in window20)
        recent_low = min(k.low for k in window20)
        out["recent_high_20"] = recent_high
        out["recent_low_20"] = recent_low

        if close_1m > 0:
            out["distance_from_high_20"] = (recent_high - close_1m) / close_1m * 100.0
            out["dist_from_recent_high_pct"] = (recent_high - close_1m) / close_1m * 100.0
            out["dist_from_recent_low_pct"] = (close_1m - recent_low) / close_1m * 100.0

        recent_rng = recent_high - recent_low
        if recent_rng > 1e-12:
            pos = (close_1m - recent_low) / recent_rng
            out["close_in_recent_range"] = pos
            out["close_in_range_pct"] = pos
            out["pullback_depth_pct"] = (recent_high - close_1m) / recent_rng

            if close_1m > recent_high:
                out["breakout_confirmation"] = 1.0
                out["breakout_strength"] = (close_1m - recent_high) / recent_rng
            elif close_1m < recent_low:
                out["breakout_confirmation"] = -1.0
                out["breakout_strength"] = (recent_low - close_1m) / recent_rng

    # ------------------------------------------------------------------
    # ATR / NATR
    # ------------------------------------------------------------------
    atr_period = 14

    if len(candles_1m) >= atr_period + 1:
        atr_1m_val = atr(candles_1m, atr_period)
        if atr_1m_val is not None:
            out["atr_1m"] = atr_1m_val
            if close_1m > 0:
                out["natr_1m"] = atr_1m_val / close_1m * 100.0

    if len(candles_5m) >= atr_period + 1:
        atr_5m_val = atr(candles_5m, atr_period)
        if atr_5m_val is not None:
            out["atr_5m"] = atr_5m_val
            c5 = candles_5m[-1]
            if c5.close and c5.close > 0:
                out["natr_5m"] = atr_5m_val / c5.close * 100.0

    if candles_15m and len(candles_15m) >= atr_period + 1:
        atr_15m_val = atr(candles_15m, atr_period)
        if atr_15m_val is not None:
            out["atr_15m"] = atr_15m_val
            c15 = candles_15m[-1]
            if c15.close and c15.close > 0:
                out["natr_15m"] = atr_15m_val / c15.close * 100.0

    # ATR compression / ratio
    if out["atr_5m"] > 0:
        out["atr_ratio_1m_5m"] = out["atr_1m"] / out["atr_5m"]
    if out["atr_15m"] > 0:
        out["atr_ratio_5m_15m"] = out["atr_5m"] / out["atr_15m"]

    # legacy alias
    if len(candles_5m) >= 51:
        atr_5 = atr(candles_5m, 5)
        atr_50 = atr(candles_5m, 50)
        if atr_5 is not None and atr_50 is not None and atr_50 > 0:
            out["atr_ratio"] = atr_5 / atr_50

    # ------------------------------------------------------------------
    # EMA / trend (1m)
    # ------------------------------------------------------------------
    closes_1m = [x.close for x in candles_1m]

    if len(closes_1m) >= 20:
        e20_1m = ema(closes_1m, 20)
        if e20_1m is not None:
            out["ema20_1m"] = e20_1m

    if len(closes_1m) >= 50:
        e50_1m = ema(closes_1m, 50)
        if e50_1m is not None:
            out["ema50_1m"] = e50_1m

    if len(closes_1m) >= 200:
        e200_1m = ema(closes_1m, 200)
        if e200_1m is not None:
            out["ema200_1m"] = e200_1m

    out["ema20_slope_1m"] = _calc_slope_ratio(closes_1m, 20)
    out["ema50_slope_1m"] = _calc_slope_ratio(closes_1m, 50)
    out["ema200_slope_1m"] = _calc_slope_ratio(closes_1m, 200)

    if close_1m > 0:
        if out["ema20_1m"] > 0:
            out["dist_from_20ema_pct"] = (close_1m - out["ema20_1m"]) / close_1m * 100.0
            out["dist_from_ema20_pct"] = out["dist_from_20ema_pct"]
        if out["ema50_1m"] > 0:
            out["dist_from_50ema_pct"] = (close_1m - out["ema50_1m"]) / close_1m * 100.0
            out["dist_from_ema50_pct"] = out["dist_from_50ema_pct"]
        if out["ema200_1m"] > 0:
            out["dist_from_ema200_pct"] = (close_1m - out["ema200_1m"]) / close_1m * 100.0

    if out["ema50_1m"] > 0:
        out["ema20_50_spread_pct"] = _safe_pct_diff(out["ema20_1m"], out["ema50_1m"])
    if out["ema200_1m"] > 0:
        out["ema50_200_spread_pct"] = _safe_pct_diff(out["ema50_1m"], out["ema200_1m"])
        out["ema20_200_spread_pct"] = _safe_pct_diff(out["ema20_1m"], out["ema200_1m"])

    out["ema20_gt_ema50"] = 1.0 if out["ema20_1m"] > out["ema50_1m"] else 0.0
    out["ema50_gt_ema200"] = 1.0 if out["ema50_1m"] > out["ema200_1m"] else 0.0

    if out["ema20_1m"] > out["ema50_1m"] > out["ema200_1m"]:
        out["ema_stack_score"] = 2.0
    elif out["ema20_1m"] > out["ema50_1m"]:
        out["ema_stack_score"] = 1.0
    elif out["ema20_1m"] < out["ema50_1m"] < out["ema200_1m"]:
        out["ema_stack_score"] = -2.0
    elif out["ema20_1m"] < out["ema50_1m"]:
        out["ema_stack_score"] = -1.0
    else:
        out["ema_stack_score"] = 0.0

    # legacy ema_distance (EMA fast/mid, usually 8/21)
    if len(closes_1m) >= settings.ema_mid:
        e_fast = ema(closes_1m, settings.ema_fast)
        e_mid = ema(closes_1m, settings.ema_mid)
        if e_fast is not None and e_mid is not None and close_1m > 0:
            out["ema_distance"] = abs(e_fast - e_mid) / close_1m

    # ------------------------------------------------------------------
    # RSI
    # ------------------------------------------------------------------
    rsi_period = getattr(settings, "rsi_period", 14)

    if len(closes_1m) >= rsi_period + 1:
        rsi_1m_val = rsi(closes_1m, rsi_period)
        if rsi_1m_val is not None:
            out["rsi_1m"] = rsi_1m_val

        if len(closes_1m) >= rsi_period + 2:
            rsi_1m_prev = rsi(closes_1m[:-1], rsi_period)
            if rsi_1m_prev is not None:
                out["rsi_delta"] = out["rsi_1m"] - rsi_1m_prev
                out["rsi_slope"] = out["rsi_delta"]

    # ------------------------------------------------------------------
    # Volume
    # ------------------------------------------------------------------
    if len(candles_1m) >= settings.volume_ma_period:
        vma_val = vma_from_candles(candles_1m, settings.volume_ma_period)
        if vma_val is not None and vma_val > 0:
            out["volume_ratio"] = candles_1m[-1].volume / vma_val

    if len(candles_1m) >= 20:
        vma20 = vma_from_candles(candles_1m, 20)
        if vma20 is not None and vma20 > 0:
            out["volume_ma20"] = vma20
            out["volume_spike"] = candles_1m[-1].volume / vma20

    if len(candles_1m) >= settings.volume_ma_period:
        vols = [x.volume for x in candles_1m[-settings.volume_ma_period:]]
        last_vol = vols[-1]
        mean_vol = sum(vols) / len(vols)
        variance = sum((v - mean_vol) ** 2 for v in vols) / len(vols)
        std_vol = variance ** 0.5
        if std_vol > 1e-12:
            out["volume_zscore"] = (last_vol - mean_vol) / std_vol

    if len(candles_1m) >= 2:
        prev_vol = candles_1m[-2].volume
        if prev_vol and prev_vol > 0:
            out["volume_change_pct"] = (candles_1m[-1].volume - prev_vol) / prev_vol * 100.0

    # ------------------------------------------------------------------
    # 5m trend / RSI / volume
    # ------------------------------------------------------------------
    closes_5m = [c.close for c in candles_5m]

    if len(closes_5m) >= 20:
        e20_5m = ema(closes_5m, 20)
        if e20_5m is not None:
            out["ema20_5m"] = e20_5m

    if len(closes_5m) >= 50:
        e50_5m = ema(closes_5m, 50)
        if e50_5m is not None:
            out["ema50_5m"] = e50_5m

    if len(closes_5m) >= 200:
        e200_5m = ema(closes_5m, 200)
        if e200_5m is not None:
            out["ema200_5m"] = e200_5m

    out["ema20_slope_5m"] = _calc_slope_ratio(closes_5m, 20)
    out["ema50_slope_5m"] = _calc_slope_ratio(closes_5m, 50)
    out["ema200_slope_5m"] = _calc_slope_ratio(closes_5m, 200)

    if len(closes_5m) >= rsi_period + 1:
        rsi_val = rsi(closes_5m, rsi_period)
        if rsi_val is not None:
            out["rsi_5m"] = rsi_val

    if out["ema20_5m"] > out["ema50_5m"]:
        out["ema20_5m_gt_ema50_5m"] = 1.0

    # legacy aliases: 기존 분석 코드 호환용
    out["ema20"] = out["ema20_5m"]
    out["ema50"] = out["ema50_5m"]
    out["ema50_slope"] = out["ema50_slope_5m"]

    if len(candles_5m) >= 20:
        vma_5m = vma_from_candles(candles_5m, min(20, len(candles_5m)))
        if vma_5m is not None and vma_5m > 0:
            out["volume_ratio_5m"] = candles_5m[-1].volume / vma_5m

    # trend_bias
    if out["ema20_5m"] > out["ema50_5m"] and out["ema50_slope_5m"] > 0:
        out["trend_bias"] = 1.0
    elif out["ema20_5m"] < out["ema50_5m"] and out["ema50_slope_5m"] < 0:
        out["trend_bias"] = -1.0
    else:
        out["trend_bias"] = 0.0

    # ------------------------------------------------------------------
    # 15m trend / RSI / volume
    # ------------------------------------------------------------------
    if candles_15m:
        closes_15m = [x.close for x in candles_15m]

        if len(closes_15m) >= 20:
            e20_15m = ema(closes_15m, 20)
            if e20_15m is not None:
                out["ema20_15m"] = e20_15m

        if len(closes_15m) >= 50:
            e50_15m = ema(closes_15m, 50)
            if e50_15m is not None:
                out["ema50_15m"] = e50_15m

        if len(closes_15m) >= 200:
            e200_15m = ema(closes_15m, 200)
            if e200_15m is not None:
                out["ema200_15m"] = e200_15m

        out["ema20_slope_15m"] = _calc_slope_ratio(closes_15m, 20)
        out["ema50_slope_15m"] = _calc_slope_ratio(closes_15m, 50)
        out["ema200_slope_15m"] = _calc_slope_ratio(closes_15m, 200)

        if out["ema20_15m"] > out["ema50_15m"]:
            out["ema20_15m_gt_ema50_15m"] = 1.0

        if len(closes_15m) >= rsi_period + 1:
            rsi_15m_val = rsi(closes_15m, rsi_period)
            if rsi_15m_val is not None:
                out["rsi_15m"] = rsi_15m_val

        if len(candles_15m) >= 20:
            vma_15m = vma_from_candles(candles_15m, min(20, len(candles_15m)))
            if vma_15m is not None and vma_15m > 0:
                out["volume_ratio_15m"] = candles_15m[-1].volume / vma_15m

    # ------------------------------------------------------------------
    # ADX / regime
    # ------------------------------------------------------------------
    out["adx_14"] = _calc_adx(candles_1m, 14)
    out["ema50_slope_pct"] = out["ema50_slope_1m"]

    adx_min = float(getattr(settings, "regime_adx_min", 14.0))
    slope_threshold_pct = float(getattr(settings, "regime_slope_threshold_pct", 0.02))
    natr_min = float(getattr(settings, "regime_natr_min", 0.02))
    natr_max = float(getattr(settings, "regime_natr_max", 1.20))
    score_threshold = float(getattr(settings, "regime_score_threshold", 1.0))

    # natr regime string
    if out["natr_5m"] > natr_max:
        out["natr_regime"] = "CHAOTIC"
    elif out["natr_5m"] >= natr_min:
        out["natr_regime"] = "MID"
    else:
        out["natr_regime"] = "LOW"

    score = 0.0
    if out["adx_14"] >= adx_min:
        score += 1.0
    if abs(out["ema50_slope_pct"]) >= slope_threshold_pct:
        score += 1.0
    if out["natr_5m"] >= natr_min:
        score += 1.0

    out["regime_score"] = score

    if out["natr_5m"] > natr_max:
        out["regime_label"] = "CHAOTIC"
        out["regime_tradable"] = 0.0
    elif score < score_threshold:
        out["regime_label"] = "RANGING"
        out["regime_tradable"] = 0.0
    else:
        if close_1m > out["ema50_1m"]:
            out["regime_label"] = "TRENDING_UP"
        else:
            out["regime_label"] = "TRENDING_DOWN"
        out["regime_tradable"] = 1.0

    return out