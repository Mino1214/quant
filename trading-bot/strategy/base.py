"""Strategy base: common interface for Meta Strategy Engine."""
from dataclasses import dataclass
from typing import Any, List, Optional

from core.models import Candle, Signal


@dataclass
class StrategyContext:
    candles_15m: List[Candle]
    candles_5m: List[Candle]
    candles_1m: List[Candle]
    settings: Any
    symbol: str = ""


def evaluate(context: StrategyContext) -> Optional[Signal]:
    raise NotImplementedError
