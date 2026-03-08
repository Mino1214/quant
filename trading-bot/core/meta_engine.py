"""
Meta Strategy Engine: select top strategies by regime and performance metrics.
strategy_score = profit_factor * 0.4 + avg_R * 0.3 + stability_score * 0.2 - drawdown * 0.1
"""
from typing import Dict, List, Optional

# Registry: strategy_id -> list of regimes where allowed (empty = all)
STRATEGY_REGIMES: Dict[str, List[str]] = {
    "trend_breakout": ["TRENDING_UP", "TRENDING_DOWN"],
    "trend_pullback": ["TRENDING_UP", "TRENDING_DOWN"],
    "range_mean_reversion": ["RANGING"],
    "volatility_expansion": ["CHAOTIC", "TRENDING_UP", "TRENDING_DOWN"],
}

WEIGHTS = {"profit_factor": 0.4, "avg_R": 0.3, "stability_score": 0.2, "drawdown": -0.1}


def strategy_score(metrics: Dict[str, float]) -> float:
    """Compute single score from metrics."""
    pf = metrics.get("profit_factor") or 0
    ar = metrics.get("avg_R") or 0
    st = metrics.get("stability_score") or 0
    dd = metrics.get("drawdown") or 0
    return pf * WEIGHTS["profit_factor"] + ar * WEIGHTS["avg_R"] + st * WEIGHTS["stability_score"] - dd * WEIGHTS["drawdown"]


def get_active_strategies(
    regime: str,
    strategy_metrics: Dict[str, Dict[str, float]],
    top_n: int = 2,
) -> List[str]:
    """
    Filter strategies allowed in this regime, rank by score, return top N strategy ids.
    strategy_metrics: {strategy_id: {profit_factor, avg_R, drawdown, stability_score}}
    """
    allowed = []
    for sid, regimes in STRATEGY_REGIMES.items():
        if not regimes or regime in regimes or regime.upper() in [r.upper() for r in regimes]:
            m = strategy_metrics.get(sid, {})
            if m:
                allowed.append((sid, strategy_score(m)))
    allowed.sort(key=lambda x: -x[1])
    return [sid for sid, _ in allowed[:top_n]]


def get_strategy_evaluate(strategy_id: str):
    """Return the evaluate function for strategy_id."""
    if strategy_id == "trend_pullback":
        from strategy.strategies.trend_pullback import evaluate
        return evaluate
    if strategy_id == "trend_breakout":
        from strategy.strategies.trend_breakout import evaluate
        return evaluate
    if strategy_id == "range_mean_reversion":
        from strategy.strategies.range_mean_reversion import evaluate
        return evaluate
    if strategy_id == "volatility_expansion":
        from strategy.strategies.volatility_expansion import evaluate
        return evaluate
    return None
