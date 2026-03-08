"""
Regime-adaptive leverage: map regime to leverage multiplier, apply safety limits.
Kelly controls risk_pct; leverage controls exposure multiplier.
position_size = (equity * risk_pct * leverage) / stop_distance
"""
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Default regime -> leverage (exposure multiplier)
DEFAULT_REGIME_LEVERAGE: Dict[str, float] = {
    "TRENDING_UP": 3.0,
    "TRENDING_DOWN": 3.0,
    "RANGE": 1.5,
    "RANGING": 1.5,
    "CHAOTIC": 0.5,
    "UNKNOWN": 1.0,
}


def get_leverage_for_regime(
    regime: str,
    regime_leverage_map: Optional[Dict[str, float]] = None,
    max_leverage: float = 5.0,
) -> float:
    """
    Return leverage multiplier for regime. Capped at max_leverage.
    """
    mapping = regime_leverage_map or DEFAULT_REGIME_LEVERAGE
    key = (regime or "").upper().strip()
    leverage = mapping.get(key) or mapping.get("RANGE") or 1.0
    return min(max(0.0, leverage), max_leverage)


def apply_leverage_safety(
    leverage: float,
    risk_pct: float,
    max_leverage: float = 5.0,
    max_position_risk_pct: float = 1.0,
) -> float:
    """
    Cap effective exposure: leverage is already capped; ensure risk_pct * leverage
    does not exceed max_position_risk_pct (e.g. 1%).
    Returns leverage to use (possibly reduced so risk_pct * leverage <= max_position_risk_pct).
    """
    leverage = min(max(0.0, leverage), max_leverage)
    if risk_pct <= 0:
        return 0.0
    effective = risk_pct * leverage
    if effective > max_position_risk_pct:
        leverage = max_position_risk_pct / risk_pct
        leverage = min(leverage, max_leverage)
    return leverage
