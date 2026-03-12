"""
Average Directional Index (ADX). Measures trend strength.
"""
from typing import List, Optional

from core.models import Candle

from indicators.atr import _hlc, true_range


def _dm_components(candles: List[Candle]) -> List[tuple[float, float, float]]:
    """Returns (tr, plus_dm, minus_dm) per bar (first bar skipped)."""
    hlc = _hlc(candles)
    out = []
    for i in range(1, len(hlc)):
        h, l, c = hlc[i]
        ph, pl, pc = hlc[i - 1]
        tr = true_range(h, l, pc)
        up = h - ph
        down = pl - l
        plus_dm = up if up > down and up > 0 else 0.0
        minus_dm = down if down > up and down > 0 else 0.0
        out.append((tr, plus_dm, minus_dm))
    return out


def adx(candles: List[Candle], period: int = 14) -> Optional[float]:
    """
    ADX of the last bar. Uses Wilder smoothing.
    Returns None if not enough data (need period*2+ bars).
    """
    if len(candles) < period + 2:
        return None
    components = _dm_components(candles)
    if len(components) < period:
        return None

    # Wilder smoothing: smoothed = prev - prev/period + new
    def smooth(series: List[float], period: int) -> List[float]:
        out = [sum(series[:period]) / period]
        for i in range(period, len(series)):
            out.append(out[-1] - out[-1] / period + series[i])
        return out

    tr_list = [x[0] for x in components]
    plus_dm_list = [x[1] for x in components]
    minus_dm_list = [x[2] for x in components]

    atr_smooth = smooth(tr_list, period)
    plus_di_smooth = smooth(plus_dm_list, period)
    minus_di_smooth = smooth(minus_dm_list, period)

    # +DI = 100 * smoothed(+DM) / ATR, -DI = 100 * smoothed(-DM) / ATR
    # DX = 100 * |+DI - -DI| / (+DI + -DI), ADX = smoothed(DX)
    dx_list = []
    for i in range(period - 1, len(atr_smooth)):
        atr_val = atr_smooth[i]
        if atr_val <= 1e-12:
            dx_list.append(0.0)
            continue
        pdi = 100.0 * plus_di_smooth[i] / atr_val
        mdi = 100.0 * minus_di_smooth[i] / atr_val
        # Clamp DI to avoid DX > 100 from numerical issues
        pdi = min(pdi, 100.0)
        mdi = min(mdi, 100.0)
        di_sum = pdi + mdi
        if di_sum <= 0:
            dx_list.append(0.0)
            continue
        dx_list.append(100.0 * abs(pdi - mdi) / di_sum)
    if len(dx_list) < period:
        return None
    adx_smooth = smooth(dx_list, period)
    return min(100.0, max(0.0, adx_smooth[-1]))
