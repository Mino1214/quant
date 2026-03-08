"""MTF EMA Pullback wrapped for strategy pool."""
from typing import Optional
from strategy.base import StrategyContext
from strategy.mtf_ema_pullback import evaluate_candidate
from core.models import Signal


def evaluate(context: StrategyContext) -> Optional[Signal]:
    return evaluate_candidate(
        context.candles_15m, context.candles_5m, context.candles_1m,
        context.settings, context.symbol,
    )
