"""
단순 바이바 시뮬레이터: Entry는 연구 전략(evaluate_strict), Exit은 timeout / TP / SL 조합.
실험용: exit grid, cooldown, regime 필터, partial TP + trend-follow exit 테스트.

핵심 설계:
  - build_precomputed_state()  : feature extraction + rolling array를 1회만 수행
  - simulate_old_from_state()  : precomputed state 재사용 → 고정 TP/SL Numba 시뮬
  - simulate_partial_from_state(): precomputed state 재사용 → partial TP Numba 시뮬
  - _run_simulator()           : 하위호환 thin wrapper
"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from core.models import Candle

import numpy as np

try:
    from numba import njit
    NUMBA_AVAILABLE = True
except Exception:  # pragma: no cover
    NUMBA_AVAILABLE = False

    def njit(*args, **kwargs):
        def _decorator(fn):
            return fn
        return _decorator


from backtest.backtest_runner import (
    N_15M,
    _slice_5m_15m_from_db,
    rolling_5m_15m,
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SimpleTrade:
    """실험용 단일 거래 결과."""
    entry_ts: Any
    exit_ts: Any
    entry_price: float
    exit_price: float
    bars_held: int
    exit_reason: str  # "tp" | "sl" | "timeout"
                      # partial TP: "tp1_then_sl" | "tp1_then_runner" | "tp1_then_ema20"
                      #             | "tp1_then_slope5m" | "tp1_then_timeout"
    pnl_pct: float    # 전체 포지션 가중평균 gross pnl
    net_pct: float    # 수수료 반영 후
    tp1_hit: bool = False


@dataclass
class SimulatorConfig:
    timeout_bars: int = 30
    tp_pct: float = 0.6       # deprecated — use_partial_tp=False 시만 사용
    sl_pct: float = 0.3
    fee_bps: float = 4.0
    cooldown_bars: int = 0
    regime_threshold: Optional[float] = None  # ema20_slope_15m > threshold 시만 진입
    trend_strength_threshold: Optional[float] = None
    # partial TP + trend-follow exit
    use_partial_tp: bool = True
    tp1_pct: float = 0.8
    tp1_size: float = 0.5
    runner_lookback_bars: int = 5
    use_ema20_exit: bool = True
    use_slope5m_exit: bool = True
    use_runner_exit: bool = True


@dataclass
class PrecomputedState:
    """
    feature extraction + rolling array를 1회만 계산한 결과.
    regime_threshold / exit 방식 무관하게 여러 실험에 재사용한다.
    """
    close_arr: np.ndarray
    high_arr: np.ndarray
    low_arr: np.ndarray
    ts_arr: np.ndarray
    entry_candidate_arr: np.ndarray   # regime slope 필터 적용 전 entry 신호
    ema20_slope_15m_arr: np.ndarray   # regime threshold 필터용
    ema20_1m_arr: np.ndarray          # partial exit: close < ema20_1m
    ema20_slope_5m_arr: np.ndarray    # partial exit: ema20_slope_5m <= 0
    runner_low_5_arr: np.ndarray      # partial exit: 최근 5봉 저점 min(low[i-5:i])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_unix_seconds(ts: Any) -> float:
    if isinstance(ts, datetime):
        return ts.timestamp()
    if hasattr(ts, "timestamp"):
        try:
            return ts.timestamp()
        except Exception:
            pass
    return 0.0


def _apply_regime(state: PrecomputedState, threshold: Optional[float]) -> np.ndarray:
    """regime_threshold를 적용해 entry_ok_arr 반환. threshold=None이면 필터 없음."""
    if threshold is None:
        return state.entry_candidate_arr.copy()
    return state.entry_candidate_arr & (state.ema20_slope_15m_arr > threshold)


def _reason_code_to_str(code: int) -> str:
    if code == 1:
        return "tp"
    if code == 2:
        return "sl"
    if code == 3:
        return "timeout"
    if code == 4:
        return "tp1_then_sl"
    if code == 5:
        return "tp1_then_runner"
    if code == 6:
        return "tp1_then_ema20"
    if code == 7:
        return "tp1_then_slope5m"
    if code == 8:
        return "tp1_then_timeout"
    return "unknown"


# ---------------------------------------------------------------------------
# Vectorized indicator helpers — O(n) 1회 계산용
# ---------------------------------------------------------------------------

def _vec_ema(closes: np.ndarray, period: int) -> np.ndarray:
    """SMA seed → EMA 전체 배열. indicators/ema.py의 ema()와 동일 알고리즘."""
    n = len(closes)
    result = np.zeros(n, dtype=np.float64)
    if n < period:
        return result
    alpha = 2.0 / (period + 1)
    result[period - 1] = float(np.mean(closes[:period]))
    for i in range(period, n):
        result[i] = closes[i] * alpha + result[i - 1] * (1.0 - alpha)
    return result


def _vec_ema_slope(ema_arr: np.ndarray) -> np.ndarray:
    """(ema[i] - ema[i-1]) / ema[i-1] — feature_extractor의 _ema_last_and_prev slope와 동일."""
    n = len(ema_arr)
    result = np.zeros(n, dtype=np.float64)
    prev = ema_arr[:-1]
    valid = prev > 1e-12
    with np.errstate(divide="ignore", invalid="ignore"):
        slope = np.where(valid, np.diff(ema_arr) / prev, 0.0)
    result[1:] = slope
    return result


def _vec_rsi_simple(closes: np.ndarray, period: int = 14) -> np.ndarray:
    """
    SMA-RSI: indicators/rsi.py의 rsi()와 동일 알고리즘.
    각 bar i에서 마지막 period개 변화의 단순 평균을 사용.
    """
    n = len(closes)
    result = np.zeros(n, dtype=np.float64)
    if n < period + 1:
        return result
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    # cumsum trick으로 rolling sum → O(n)
    cum_g = np.concatenate([[0.0], np.cumsum(gains)])
    cum_l = np.concatenate([[0.0], np.cumsum(losses)])
    for i in range(period, n):
        g = (cum_g[i] - cum_g[i - period]) / period
        l = (cum_l[i] - cum_l[i - period]) / period
        if l < 1e-12:
            result[i] = 100.0
        else:
            result[i] = 100.0 - 100.0 / (1.0 + g / l)
    return result


def _vec_adx(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """
    Wilder ADX 전체 배열. feature_extractor._calc_adx()와 동일 알고리즘.
    adx_arr[i] = i번째 봉까지의 데이터로 계산한 ADX.
    """
    n = len(high)
    result = np.zeros(n, dtype=np.float64)
    if n < 2 * period + 2:
        return result

    h_diff = np.diff(high)
    l_diff_inv = -np.diff(low)
    pdm = np.where((h_diff > l_diff_inv) & (h_diff > 0), h_diff, 0.0)
    mdm = np.where((l_diff_inv > h_diff) & (l_diff_inv > 0), l_diff_inv, 0.0)
    tr1 = high[1:] - low[1:]
    tr2 = np.abs(high[1:] - close[:-1])
    tr3 = np.abs(low[1:] - close[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))

    tr14 = float(np.sum(tr[:period]))
    pdm14 = float(np.sum(pdm[:period]))
    mdm14 = float(np.sum(mdm[:period]))

    dx_list: List[float] = []
    for j in range(period, len(tr)):
        tr14 = tr14 - tr14 / period + float(tr[j])
        pdm14 = pdm14 - pdm14 / period + float(pdm[j])
        mdm14 = mdm14 - mdm14 / period + float(mdm[j])
        if tr14 > 1e-12:
            pdi = 100.0 * pdm14 / tr14
            mdi = 100.0 * mdm14 / tr14
            denom = pdi + mdi
            dx = 0.0 if denom <= 1e-12 else 100.0 * abs(pdi - mdi) / denom
        else:
            dx = 0.0
        dx_list.append(dx)

    if len(dx_list) < period:
        return result

    adx_val = sum(dx_list[:period]) / period
    # dx_list[k] → original bar index = period + 1 + k
    result[2 * period] = adx_val
    for k in range(period, len(dx_list)):
        adx_val = (adx_val * (period - 1) + dx_list[k]) / period
        result[2 * period + (k - period) + 1] = adx_val

    return result


def _vec_volume_ratio(volume: np.ndarray, period: int = 20) -> np.ndarray:
    """rolling mean volume 대비 현재 volume 비율."""
    n = len(volume)
    result = np.zeros(n, dtype=np.float64)
    if n < period:
        return result
    cum = np.concatenate([[0.0], np.cumsum(volume)])
    for i in range(period - 1, n):
        vma = (cum[i + 1] - cum[i - period + 1]) / period
        if vma > 1e-12:
            result[i] = volume[i] / vma
    return result


def _vec_pullback_depth(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    lookback: int = 10,
) -> np.ndarray:
    """
    feature_extractor의 pullback_depth_pct와 동일.
    bar i → high/low 창 = [i-lookback, i) (현재 봉 제외).
    """
    n = len(close)
    result = np.zeros(n, dtype=np.float64)
    for i in range(lookback, n):
        recent_high = float(np.max(high[i - lookback:i]))
        recent_low = float(np.min(low[i - lookback:i]))
        rng = recent_high - recent_low
        if rng > 1e-12:
            result[i] = (recent_high - close[i]) / rng
    return result


def _align_mtf_to_1m(
    ts_1m: np.ndarray,
    ts_mtf: np.ndarray,
    indicator: np.ndarray,
) -> np.ndarray:
    """
    각 1m 봉에 가장 최근의 MTF 지표값을 forward-fill.
    ts_mtf[j] <= ts_1m[i] < ts_mtf[j+1] 인 j의 indicator[j]를 사용.
    """
    idx = np.searchsorted(ts_mtf, ts_1m, side="right") - 1
    result = np.zeros(len(ts_1m), dtype=np.float64)
    valid = idx >= 0
    result[valid] = indicator[idx[valid]]
    return result


# ---------------------------------------------------------------------------
# Numba 시뮬레이터 (1) 기존 고정 TP/SL
# exit_reason 인코딩: 1=tp, 2=sl, 3=timeout
# ---------------------------------------------------------------------------

@njit(cache=True)
def _simulate_long_only_numba(
    close_arr: np.ndarray,
    high_arr: np.ndarray,
    low_arr: np.ndarray,
    ts_arr: np.ndarray,
    entry_ok_arr: np.ndarray,
    tp_pct: float,
    sl_pct: float,
    timeout_bars: int,
    cooldown_bars: int,
    fee_pct: float,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = len(close_arr)

    entry_ts_out = np.empty(n, dtype=np.float64)
    exit_ts_out = np.empty(n, dtype=np.float64)
    entry_price_out = np.empty(n, dtype=np.float64)
    exit_price_out = np.empty(n, dtype=np.float64)
    bars_held_out = np.empty(n, dtype=np.int64)
    exit_reason_out = np.empty(n, dtype=np.int64)
    pnl_net_out = np.empty(n, dtype=np.float64)

    trade_count = 0
    position = 0
    entry_price = 0.0
    entry_idx = -1
    entry_ts = 0.0
    cooldown_until_bar = -1

    tp_mult = 1.0 + tp_pct / 100.0
    sl_mult = 1.0 - sl_pct / 100.0

    for i in range(n):
        close = close_arr[i]
        high = high_arr[i]
        low = low_arr[i]
        ts_val = ts_arr[i]

        if position == 1:
            bars_held = i - entry_idx
            tp_price = entry_price * tp_mult
            sl_price = entry_price * sl_mult

            reason = 0
            exit_price = close

            if high >= tp_price:
                reason = 1
                exit_price = tp_price
            elif low <= sl_price:
                reason = 2
                exit_price = sl_price
            elif bars_held >= timeout_bars:
                reason = 3
                exit_price = close

            if reason != 0:
                pnl_pct = (exit_price - entry_price) / entry_price * 100.0
                net_pct = pnl_pct - fee_pct

                entry_ts_out[trade_count] = entry_ts
                exit_ts_out[trade_count] = ts_val
                entry_price_out[trade_count] = entry_price
                exit_price_out[trade_count] = exit_price
                bars_held_out[trade_count] = bars_held
                exit_reason_out[trade_count] = reason
                pnl_net_out[trade_count] = net_pct
                trade_count += 1

                position = 0
                entry_price = 0.0
                entry_idx = -1
                entry_ts = 0.0
                cooldown_until_bar = i + cooldown_bars
                continue

        if position == 0:
            if i < cooldown_until_bar:
                continue
            if entry_ok_arr[i]:
                position = 1
                entry_price = close
                entry_idx = i
                entry_ts = ts_val

    return (
        entry_ts_out[:trade_count],
        exit_ts_out[:trade_count],
        entry_price_out[:trade_count],
        exit_price_out[:trade_count],
        bars_held_out[:trade_count],
        exit_reason_out[:trade_count],
        pnl_net_out[:trade_count],
    )


# ---------------------------------------------------------------------------
# Numba 시뮬레이터 (2) Partial TP + trend-follow exit
# exit_reason 인코딩:
#   2 = "sl"               (TP1 전 손절)
#   3 = "timeout"          (TP1 전 타임아웃)
#   4 = "tp1_then_sl"      (TP1 후 손절)
#   5 = "tp1_then_runner"  (TP1 후 최근 5봉 저점 이탈)
#   6 = "tp1_then_ema20"   (TP1 후 close < ema20_1m)
#   7 = "tp1_then_slope5m" (TP1 후 ema20_slope_5m <= 0)
#   8 = "tp1_then_timeout" (TP1 후 타임아웃)
# ---------------------------------------------------------------------------

@njit(cache=True)
def _simulate_long_only_numba_partial(
    close_arr: np.ndarray,
    high_arr: np.ndarray,
    low_arr: np.ndarray,
    ts_arr: np.ndarray,
    entry_ok_arr: np.ndarray,
    ema20_1m_arr: np.ndarray,
    ema20_slope_5m_arr: np.ndarray,
    runner_low_5_arr: np.ndarray,
    tp1_pct: float,
    sl_pct: float,
    timeout_bars: int,
    cooldown_bars: int,
    fee_pct: float,
    tp1_size: float,
    use_ema20_exit: bool,
    use_slope5m_exit: bool,
    use_runner_exit: bool,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = len(close_arr)

    entry_ts_out = np.empty(n, dtype=np.float64)
    exit_ts_out = np.empty(n, dtype=np.float64)
    entry_price_out = np.empty(n, dtype=np.float64)
    exit_price_out = np.empty(n, dtype=np.float64)
    bars_held_out = np.empty(n, dtype=np.int64)
    exit_reason_out = np.empty(n, dtype=np.int64)
    pnl_net_out = np.empty(n, dtype=np.float64)
    tp1_hit_out = np.empty(n, dtype=np.bool_)

    trade_count = 0
    position = 0
    position_size = 0.0
    tp1_hit = False
    partial_pnl = 0.0
    entry_price = 0.0
    entry_idx = -1
    entry_ts = 0.0
    cooldown_until_bar = -1

    sl_mult = 1.0 - sl_pct / 100.0
    tp1_mult = 1.0 + tp1_pct / 100.0
    runner_size = 1.0 - tp1_size

    for i in range(n):
        close = close_arr[i]
        high = high_arr[i]
        low = low_arr[i]
        ts_val = ts_arr[i]

        if position == 1:
            bars_held = i - entry_idx
            sl_price = entry_price * sl_mult

            reason = 0
            exit_price = close

            # 1. SL 체크 (tp1_hit 여부 무관)
            if low <= sl_price:
                exit_price = sl_price
                reason = 4 if tp1_hit else 2

            # 2. TP1 체크 (tp1_hit == False)
            if reason == 0 and not tp1_hit:
                if high >= entry_price * tp1_mult:
                    tp1_hit = True
                    position_size = runner_size
                    partial_pnl = tp1_size * tp1_pct

            # 3. Runner exit 체크 (tp1_hit == True)
            if reason == 0 and tp1_hit:
                if use_runner_exit and runner_low_5_arr[i] < 1e17 and low <= runner_low_5_arr[i]:
                    reason = 5
                    exit_price = runner_low_5_arr[i]
                elif use_ema20_exit and ema20_1m_arr[i] > 0.0 and close < ema20_1m_arr[i]:
                    reason = 6
                    exit_price = close
                elif use_slope5m_exit and ema20_slope_5m_arr[i] <= 0.0:
                    reason = 7
                    exit_price = close

            # 4. Timeout 체크
            if reason == 0 and bars_held >= timeout_bars:
                reason = 8 if tp1_hit else 3
                exit_price = close

            if reason != 0:
                runner_pnl = position_size * (exit_price - entry_price) / entry_price * 100.0
                total_pnl = partial_pnl + runner_pnl
                net_pct = total_pnl - fee_pct

                entry_ts_out[trade_count] = entry_ts
                exit_ts_out[trade_count] = ts_val
                entry_price_out[trade_count] = entry_price
                exit_price_out[trade_count] = exit_price
                bars_held_out[trade_count] = bars_held
                exit_reason_out[trade_count] = reason
                pnl_net_out[trade_count] = net_pct
                tp1_hit_out[trade_count] = tp1_hit
                trade_count += 1

                position = 0
                position_size = 0.0
                tp1_hit = False
                partial_pnl = 0.0
                entry_price = 0.0
                entry_idx = -1
                entry_ts = 0.0
                cooldown_until_bar = i + cooldown_bars
                continue

        if position == 0:
            if i < cooldown_until_bar:
                continue
            if entry_ok_arr[i]:
                position = 1
                position_size = 1.0
                tp1_hit = False
                partial_pnl = 0.0
                entry_price = close
                entry_idx = i
                entry_ts = ts_val

    return (
        entry_ts_out[:trade_count],
        exit_ts_out[:trade_count],
        entry_price_out[:trade_count],
        exit_price_out[:trade_count],
        bars_held_out[:trade_count],
        exit_reason_out[:trade_count],
        pnl_net_out[:trade_count],
        tp1_hit_out[:trade_count],
    )


# ---------------------------------------------------------------------------
# Precompute: 공통 feature extraction (1회만 수행)
# ---------------------------------------------------------------------------

def build_precomputed_state(
    candles_1m: List[Candle],
    candles_5m_full: Optional[List[Candle]],
    candles_15m_full: Optional[List[Candle]],
    symbol: str,
    evaluate_fn: Any,
    get_settings: Any,
) -> PrecomputedState:
    """
    [VECTORIZED] Feature extraction 1회만 수행. O(n²) → O(n).

    핵심 변경:
    - 봉마다 feature 함수 호출하는 Python 루프 완전 제거
    - EMA / RSI / ADX / volume_ratio / pullback_depth 배열을 numpy로 1회 계산
    - 5m/15m 지표는 searchsorted로 1m 타임라인에 정렬

    evaluate_fn == evaluate_strict 인 경우 완전 벡터화 (fast path).
    그 외 evaluate_fn은 per-bar fallback (slow path, 하위 호환성).

    entry_candidate_arr : regime slope 필터 적용 전 entry 신호
    ema20_slope_15m_arr : _apply_regime()에서 threshold 비교에 사용
    ema20_1m_arr        : partial exit — close < ema20_1m (EMA 값)
    ema20_slope_5m_arr  : partial exit — slope <= 0
    runner_low_5_arr    : partial exit — min(low[i-5:i])
    """
    settings = get_settings()
    evaluate_name = getattr(evaluate_fn, "__name__", "")
    n = len(candles_1m)

    if n == 0:
        empty = np.zeros(0, dtype=np.float64)
        return PrecomputedState(
            close_arr=empty, high_arr=empty, low_arr=empty, ts_arr=empty,
            entry_candidate_arr=np.zeros(0, dtype=np.bool_),
            ema20_slope_15m_arr=empty,
            ema20_1m_arr=empty,
            ema20_slope_5m_arr=empty,
            runner_low_5_arr=empty,
        )

    print(f"[build_precomputed_state] n={n}, extracting arrays...")

    # ------------------------------------------------------------------
    # 1. 원시 배열 추출
    # ------------------------------------------------------------------
    close_arr = np.array([c.close for c in candles_1m], dtype=np.float64)
    high_arr = np.array([c.high for c in candles_1m], dtype=np.float64)
    low_arr = np.array([c.low for c in candles_1m], dtype=np.float64)
    volume_arr = np.array(
        [getattr(c, "volume", 0.0) or 0.0 for c in candles_1m], dtype=np.float64
    )
    ts_arr = np.array([_to_unix_seconds(c.timestamp) for c in candles_1m], dtype=np.float64)

    # ------------------------------------------------------------------
    # 2. 1m 지표 — 벡터 연산 1회
    # ------------------------------------------------------------------
    print("[build_precomputed_state] computing 1m indicators...")
    ema20_1m_arr = _vec_ema(close_arr, 20)
    ema20_slope_1m_arr = _vec_ema_slope(ema20_1m_arr)
    rsi_1m_arr = _vec_rsi_simple(close_arr, 14)
    adx_14_arr = _vec_adx(high_arr, low_arr, close_arr, 14)

    vol_period = int(getattr(settings, "volume_ma_period", 20))
    volume_ratio_arr = _vec_volume_ratio(volume_arr, vol_period)

    swing_lookback = int(getattr(settings, "swing_lookback", 10))
    pullback_depth_arr = _vec_pullback_depth(high_arr, low_arr, close_arr, swing_lookback)

    # runner_low_5: min(low[i-5:i]) — partial exit용
    runner_low_5_arr = np.full(n, np.inf, dtype=np.float64)
    if n > 5:
        from numpy.lib.stride_tricks import sliding_window_view
        min_vals = np.min(sliding_window_view(low_arr, 5), axis=1)  # length n-4
        runner_low_5_arr[5:] = min_vals[: n - 5]

    # ------------------------------------------------------------------
    # 3. 5m/15m 지표 — 벡터 연산 후 1m 타임라인으로 정렬
    # ------------------------------------------------------------------
    print("[build_precomputed_state] computing 5m/15m indicators...")

    if candles_5m_full:
        close_5m = np.array([c.close for c in candles_5m_full], dtype=np.float64)
        ts_5m = np.array(
            [_to_unix_seconds(c.timestamp) for c in candles_5m_full], dtype=np.float64
        )
        ema20_5m_full = _vec_ema(close_5m, 20)
        slope_5m_full = _vec_ema_slope(ema20_5m_full)
        rsi_5m_full = _vec_rsi_simple(close_5m, 14)

        ema20_slope_5m_arr = _align_mtf_to_1m(ts_arr, ts_5m, slope_5m_full)
        rsi_5m_arr = _align_mtf_to_1m(ts_arr, ts_5m, rsi_5m_full)
    else:
        ema20_slope_5m_arr = np.zeros(n, dtype=np.float64)
        rsi_5m_arr = np.zeros(n, dtype=np.float64)

    if candles_15m_full:
        close_15m = np.array([c.close for c in candles_15m_full], dtype=np.float64)
        ts_15m = np.array(
            [_to_unix_seconds(c.timestamp) for c in candles_15m_full], dtype=np.float64
        )
        ema20_15m_full = _vec_ema(close_15m, 20)
        slope_15m_full = _vec_ema_slope(ema20_15m_full)

        ema20_slope_15m_arr = _align_mtf_to_1m(ts_arr, ts_15m, slope_15m_full)
    else:
        ema20_slope_15m_arr = np.zeros(n, dtype=np.float64)

    # ------------------------------------------------------------------
    # 4. Entry candidate 배열 생성
    # ------------------------------------------------------------------
    print("[build_precomputed_state] building entry candidates...")

    if evaluate_name == "evaluate_strict":
        # Fast path: evaluate_strict_features 조건을 numpy 불리언 연산으로 직접 적용
        # _long_candidate_2 조건 (mtf_trend_pullback_research.py와 동일):
        #   ema20_slope_5m  > 0.000094
        #   ema20_slope_1m  < -0.000018
        #   rsi_1m          < 38.0
        #   rsi_5m          > 54.0
        #   pullback_depth  > 0.6
        #   adx_14          >= 18.0  (quality filter)
        #   volume_ratio    >= 1.2   (quality filter)
        entry_candidate_arr = (
            (ema20_slope_5m_arr > 0.000094)
            & (ema20_slope_1m_arr < -0.000018)
            & (rsi_1m_arr < 38.0)
            & (rsi_5m_arr > 54.0)
            & (pullback_depth_arr > 0.6)
            & (adx_14_arr >= 18.0)
            & (volume_ratio_arr >= 1.2)
        )
    else:
        # Fallback: 기타 evaluate_fn은 per-bar slow path (하위 호환성)
        from strategy.base import StrategyContext
        from strategy.feature_extractor import extract_feature_values_research_minimal

        entry_candidate_arr = np.zeros(n, dtype=np.bool_)
        window_1m: List[Candle] = []
        idx_5m = 0
        idx_15m = 0

        for i in range(n):
            if i % 10000 == 0:
                print(f"[build_precomputed_state] fallback per-bar {i}/{n}")
            bar = candles_1m[i]
            window_1m.append(bar)

            if candles_5m_full and candles_15m_full:
                while (
                    idx_5m + 1 < len(candles_5m_full)
                    and candles_5m_full[idx_5m + 1].timestamp <= bar.timestamp
                ):
                    idx_5m += 1
                while (
                    idx_15m + 1 < len(candles_15m_full)
                    and candles_15m_full[idx_15m + 1].timestamp <= bar.timestamp
                ):
                    idx_15m += 1
                c5m = candles_5m_full[max(0, idx_5m - N_15M + 1): idx_5m + 1]
                c15m = candles_15m_full[max(0, idx_15m - N_15M + 1): idx_15m + 1]
            else:
                c5m, c15m = rolling_5m_15m(window_1m, n_bars=N_15M)

            if len(c5m) < 50 or len(c15m) < 55:
                continue

            ctx = StrategyContext(
                candles_15m=c15m,
                candles_5m=c5m,
                candles_1m=window_1m,
                settings=settings,
                symbol=symbol,
            )
            signal = evaluate_fn(ctx)
            if signal is not None:
                entry_candidate_arr[i] = True

    print(f"[build_precomputed_state] done. entry candidates={int(entry_candidate_arr.sum())}")
    return PrecomputedState(
        close_arr=close_arr,
        high_arr=high_arr,
        low_arr=low_arr,
        ts_arr=ts_arr,
        entry_candidate_arr=entry_candidate_arr,
        ema20_slope_15m_arr=ema20_slope_15m_arr,
        ema20_1m_arr=ema20_1m_arr,
        ema20_slope_5m_arr=ema20_slope_5m_arr,
        runner_low_5_arr=runner_low_5_arr,
    )


# ---------------------------------------------------------------------------
# Simulate: precomputed state 재사용
# ---------------------------------------------------------------------------

def simulate_old_from_state(
    state: PrecomputedState,
    config: SimulatorConfig,
) -> List[SimpleTrade]:
    """고정 TP/SL 시뮬레이션. precomputed state 재사용."""
    fee_pct = 2 * config.fee_bps / 10000 * 100
    entry_ok_arr = _apply_regime(state, config.regime_threshold)

    (
        entry_ts_out, exit_ts_out, entry_price_out, exit_price_out,
        bars_held_out, exit_reason_out, net_pct_out,
    ) = _simulate_long_only_numba(
        close_arr=state.close_arr,
        high_arr=state.high_arr,
        low_arr=state.low_arr,
        ts_arr=state.ts_arr,
        entry_ok_arr=entry_ok_arr,
        tp_pct=float(config.tp_pct),
        sl_pct=float(config.sl_pct),
        timeout_bars=int(config.timeout_bars),
        cooldown_bars=int(config.cooldown_bars),
        fee_pct=float(fee_pct),
    )

    trades: List[SimpleTrade] = []
    for i in range(len(entry_ts_out)):
        entry_price = float(entry_price_out[i])
        exit_price = float(exit_price_out[i])
        pnl_pct = (exit_price - entry_price) / entry_price * 100.0
        net_pct = float(net_pct_out[i])
        trades.append(SimpleTrade(
            entry_ts=datetime.fromtimestamp(float(entry_ts_out[i])),
            exit_ts=datetime.fromtimestamp(float(exit_ts_out[i])),
            entry_price=entry_price,
            exit_price=exit_price,
            bars_held=int(bars_held_out[i]),
            exit_reason=_reason_code_to_str(int(exit_reason_out[i])),
            pnl_pct=pnl_pct,
            net_pct=net_pct,
            tp1_hit=False,
        ))
    return trades


def simulate_partial_from_state(
    state: PrecomputedState,
    config: SimulatorConfig,
) -> List[SimpleTrade]:
    """Partial TP + trend-follow exit 시뮬레이션. precomputed state 재사용."""
    fee_pct = 2 * config.fee_bps / 10000 * 100
    entry_ok_arr = _apply_regime(state, config.regime_threshold)

    (
        entry_ts_out, exit_ts_out, entry_price_out, exit_price_out,
        bars_held_out, exit_reason_out, pnl_net_out, tp1_hit_out,
    ) = _simulate_long_only_numba_partial(
        close_arr=state.close_arr,
        high_arr=state.high_arr,
        low_arr=state.low_arr,
        ts_arr=state.ts_arr,
        entry_ok_arr=entry_ok_arr,
        ema20_1m_arr=state.ema20_1m_arr,
        ema20_slope_5m_arr=state.ema20_slope_5m_arr,
        runner_low_5_arr=state.runner_low_5_arr,
        tp1_pct=float(config.tp1_pct),
        sl_pct=float(config.sl_pct),
        timeout_bars=int(config.timeout_bars),
        cooldown_bars=int(config.cooldown_bars),
        fee_pct=float(fee_pct),
        tp1_size=float(config.tp1_size),
        use_ema20_exit=bool(config.use_ema20_exit),
        use_slope5m_exit=bool(config.use_slope5m_exit),
        use_runner_exit=bool(config.use_runner_exit),
    )

    trades: List[SimpleTrade] = []
    for i in range(len(entry_ts_out)):
        entry_price = float(entry_price_out[i])
        exit_price = float(exit_price_out[i])
        net_pct = float(pnl_net_out[i])
        pnl_pct = net_pct + float(fee_pct)
        trades.append(SimpleTrade(
            entry_ts=datetime.fromtimestamp(float(entry_ts_out[i])),
            exit_ts=datetime.fromtimestamp(float(exit_ts_out[i])),
            entry_price=entry_price,
            exit_price=exit_price,
            bars_held=int(bars_held_out[i]),
            exit_reason=_reason_code_to_str(int(exit_reason_out[i])),
            pnl_pct=pnl_pct,
            net_pct=net_pct,
            tp1_hit=bool(tp1_hit_out[i]),
        ))
    return trades


def _simulate_from_state(
    state: PrecomputedState,
    config: SimulatorConfig,
) -> List[SimpleTrade]:
    """config.use_partial_tp에 따라 시뮬레이터 선택."""
    if config.use_partial_tp:
        return simulate_partial_from_state(state, config)
    return simulate_old_from_state(state, config)


# ---------------------------------------------------------------------------
# 하위호환 wrapper
# ---------------------------------------------------------------------------

def _run_simulator(
    candles_1m: List[Candle],
    candles_5m_full: Optional[List[Candle]],
    candles_15m_full: Optional[List[Candle]],
    symbol: str,
    config: SimulatorConfig,
    evaluate_fn: Any,
    get_settings: Any,
) -> List[SimpleTrade]:
    """하위호환 thin wrapper: build_precomputed_state 후 단건 시뮬레이션."""
    state = build_precomputed_state(
        candles_1m, candles_5m_full, candles_15m_full,
        symbol, evaluate_fn, get_settings,
    )
    return _simulate_from_state(state, config)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def metrics_from_simple_trades(trades: List[SimpleTrade]) -> Dict[str, Any]:
    """SimpleTrade 리스트에서 메트릭 계산."""
    n = len(trades)
    if n == 0:
        return {
            "n_trades": 0,
            "win_rate_pct": 0.0,
            "mean_net_pct": 0.0,
            "mean_raw_pct": 0.0,
            "profit_factor": 0.0,
            "pf_net": 0.0,
            "tp1_rate_pct": 0.0,
            "exit_reasons": {},
        }
    wins = sum(1 for t in trades if t.net_pct > 0)
    win_rate_pct = wins / n * 100
    mean_net_pct = sum(t.net_pct for t in trades) / n
    mean_raw_pct = sum(t.pnl_pct for t in trades) / n
    gross_profit = sum(t.net_pct for t in trades if t.net_pct > 0)
    gross_loss = abs(sum(t.net_pct for t in trades if t.net_pct < 0))
    pf_net = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)

    tp1_hit_count = sum(1 for t in trades if t.tp1_hit)
    tp1_rate_pct = tp1_hit_count / n * 100
    exit_reasons = dict(Counter(t.exit_reason for t in trades))

    return {
        "n_trades": n,
        "win_rate_pct": round(win_rate_pct, 2),
        "mean_net_pct": round(mean_net_pct, 4),
        "mean_raw_pct": round(mean_raw_pct, 4),
        "profit_factor": round(pf_net, 4),
        "pf_net": round(pf_net, 4),
        "tp1_rate_pct": round(tp1_rate_pct, 2),
        "exit_reasons": exit_reasons,
    }
