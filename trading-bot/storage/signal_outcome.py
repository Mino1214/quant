"""
Compute outcome for a candidate signal: future R at N bars, tp_hit_first, sl_hit_first, bars_to_outcome.
Used to backfill signal_outcomes from historical 1m candles.
"""
from datetime import datetime
from typing import List, Optional

from core.models import Candle, Direction, SignalOutcome


# Cap R to avoid explosion when stop distance is tiny (e.g. numerical error or bad data)
R_CAP = 20.0


def _r_at_price(entry: float, exit_price: float, risk: float, direction: Direction) -> float:
    """
    Return R for a single exit price. risk = abs(entry - stop_loss).
    If risk is too small (< entry * 1e-5), R is capped to avoid hundreds/thousands.
    All R values are capped to [-R_CAP, R_CAP] for scan sanity.
    """
    if risk <= 0:
        return 0.0
    min_risk = abs(entry) * 1e-5
    if risk < min_risk:
        risk = min_risk
    if direction == Direction.LONG:
        r = (exit_price - entry) / risk
    else:
        r = (entry - exit_price) / risk
    return max(-R_CAP, min(R_CAP, r))


def compute_outcome_for_signal(
    candidate_signal_id: int,
    candles_1m_after_signal: List[Candle],
    entry_price: float,
    stop_loss: float,
    direction: Direction,
    tp_r: float = 1.0,
) -> SignalOutcome:
    """
    Compute outcome for one candidate signal given 1m bars after the signal bar.
    candles_1m_after_signal[0] = first bar after signal close.
    future_r_N = R at close of N-th bar after signal (1R = entry - stop distance).
    tp_hit_first / sl_hit_first: which was hit first when iterating bars; bars_to_outcome = bar index (1-based) of that hit.
    """
    risk = abs(entry_price - stop_loss)
    tp_price = entry_price + tp_r * risk if direction == Direction.LONG else entry_price - tp_r * risk

    future_r_5: Optional[float] = None
    future_r_10: Optional[float] = None
    future_r_20: Optional[float] = None
    future_r_30: Optional[float] = None
    tp_hit_first: Optional[bool] = None
    sl_hit_first: Optional[bool] = None
    bars_to_outcome: Optional[int] = None

    if risk <= 0:
        return SignalOutcome(
            candidate_signal_id=candidate_signal_id,
            future_r_5=future_r_5,
            future_r_10=future_r_10,
            future_r_20=future_r_20,
            future_r_30=future_r_30,
            tp_hit_first=tp_hit_first,
            sl_hit_first=sl_hit_first,
            bars_to_outcome=bars_to_outcome,
            computed_at=datetime.utcnow(),
        )

    n = len(candles_1m_after_signal)
    for i, c in enumerate([5, 10, 20, 30]):
        idx = c - 1  # 0-based index for c-th bar
        if n > idx:
            close = candles_1m_after_signal[idx].close
            r_val = _r_at_price(entry_price, close, risk, direction)
            if i == 0:
                future_r_5 = r_val
            elif i == 1:
                future_r_10 = r_val
            elif i == 2:
                future_r_20 = r_val
            else:
                future_r_30 = r_val

    # Determine first hit: TP or SL, and bar index (1-based)
    for bar_idx, c in enumerate(candles_1m_after_signal):
        if direction == Direction.LONG:
            sl_first_this_bar = c.low <= stop_loss
            tp_first_this_bar = c.high >= tp_price
        else:
            sl_first_this_bar = c.high >= stop_loss
            tp_first_this_bar = c.low <= tp_price

        if sl_first_this_bar and tp_first_this_bar:
            # Same bar: assume SL checked first (conservative)
            sl_hit_first = True
            tp_hit_first = False
            bars_to_outcome = bar_idx + 1
            break
        if sl_first_this_bar:
            sl_hit_first = True
            tp_hit_first = False
            bars_to_outcome = bar_idx + 1
            break
        if tp_first_this_bar:
            tp_hit_first = True
            sl_hit_first = False
            bars_to_outcome = bar_idx + 1
            break
    else:
        # No hit within available bars; cap at 30 for bars_to_outcome if we have 30+ bars
        if n >= 30:
            bars_to_outcome = 30
            close_30 = candles_1m_after_signal[29].close
            future_r_30 = _r_at_price(entry_price, close_30, risk, direction)

    return SignalOutcome(
        candidate_signal_id=candidate_signal_id,
        future_r_5=future_r_5,
        future_r_10=future_r_10,
        future_r_20=future_r_20,
        future_r_30=future_r_30,
        tp_hit_first=tp_hit_first,
        sl_hit_first=sl_hit_first,
        bars_to_outcome=bars_to_outcome,
        computed_at=datetime.utcnow(),
    )
