"""
Decide when to run strategy evaluation: only on closed candle events.
No duplicate evaluation for the same bar.
"""
from datetime import datetime
from typing import Callable, Optional

from core.models import Candle, Timeframe


def should_evaluate_on_1m(
    bar_ts: datetime,
    last_eval_ts: Optional[datetime],
) -> bool:
    """True if we have not yet evaluated this 1m bar."""
    if last_eval_ts is None:
        return True
    return bar_ts > last_eval_ts
