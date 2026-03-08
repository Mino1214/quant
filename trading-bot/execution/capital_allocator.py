"""
Capital Allocation Engine: risk tiers by signal quality, regime multiplier, portfolio risk cap.
Sends position size to order executor (caller uses quantity from get_position_size).
"""
import logging
from typing import List, Optional, Tuple

from core.models import CapitalAllocationSettings, Direction, LeverageSettings, Position
from execution.leverage_manager import apply_leverage_safety, get_leverage_for_regime
from execution.signal_quality_ranking import rank_signals
from risk.position_size import position_size

logger = logging.getLogger(__name__)

# Max risk % after regime multiplier (cap to avoid over-leverage)
MAX_RISK_PCT_CAP = 5.0


def score_to_risk_pct(
    score: float,
    settings: CapitalAllocationSettings,
) -> float:
    """
    Map signal_quality_score to risk % (1/2/3% by tiers).
    score > 0.75 -> 3%, > 0.65 -> 2%, > 0.55 -> 1%, else 0.
    """
    if score <= settings.min_quality_threshold:
        return 0.0
    # Tiers are (score_min, risk_pct) descending: e.g. (0.75, 3), (0.65, 2), (0.55, 1)
    for score_min, risk_pct in sorted(settings.tiers, key=lambda x: -x[0]):
        if score > score_min:
            return float(risk_pct)
    return 0.0


def apply_regime_multiplier(
    risk_pct: float,
    regime: str,
    settings: CapitalAllocationSettings,
) -> float:
    """Apply regime-based risk multiplier; cap at MAX_RISK_PCT_CAP."""
    if not risk_pct:
        return 0.0
    mult = 1.0
    if settings.regime_multipliers:
        regime_upper = (regime or "").upper()
        mult = settings.regime_multipliers.get(regime_upper) or settings.regime_multipliers.get(regime) or 1.0
    out = risk_pct * mult
    return min(MAX_RISK_PCT_CAP, max(0.0, out))


def get_position_size(
    balance: float,
    entry: float,
    stop_loss: float,
    direction: Direction,
    score: float,
    regime: str,
    settings: CapitalAllocationSettings,
    current_open_risk_pct: float = 0.0,
    override_risk_pct: Optional[float] = None,
    leverage: float = 1.0,
    leverage_settings: Optional[LeverageSettings] = None,
) -> Tuple[float, float]:
    """
    Compute position size from signal quality (or override), portfolio risk limit, and optional leverage.
    When override_risk_pct is provided and > 0, use it instead of score-based tier (e.g. Kelly).
    If leverage_settings is provided and enabled, regime-adaptive leverage is applied (overrides leverage arg).
    Returns (quantity, allocated_risk_pct). quantity is 0 if below threshold or over portfolio cap.
    """
    if balance <= 0:
        return 0.0, 0.0
    stop_distance = abs(entry - stop_loss)
    if stop_distance <= 0:
        return 0.0, 0.0

    if override_risk_pct is not None and override_risk_pct > 0:
        risk_pct = override_risk_pct
    else:
        risk_pct = score_to_risk_pct(score, settings)
    if risk_pct <= 0:
        return 0.0, 0.0

    risk_pct = apply_regime_multiplier(risk_pct, regime, settings)
    if risk_pct <= 0:
        return 0.0, 0.0

    if current_open_risk_pct + risk_pct > settings.max_portfolio_risk_pct:
        logger.debug(
            "Capital allocator: skip (portfolio risk cap). current=%.2f%% + new=%.2f%% > max=%.2f%%",
            current_open_risk_pct, risk_pct, settings.max_portfolio_risk_pct,
        )
        return 0.0, 0.0

    if leverage_settings and getattr(leverage_settings, "enabled", False):
        lev = get_leverage_for_regime(
            regime,
            getattr(leverage_settings, "regime_leverage", None),
            getattr(leverage_settings, "max_leverage", 5.0),
        )
        lev = apply_leverage_safety(
            lev,
            risk_pct,
            max_leverage=getattr(leverage_settings, "max_leverage", 5.0),
            max_position_risk_pct=getattr(leverage_settings, "max_position_risk_pct", 1.0),
        )
    else:
        lev = 1.0 if leverage is None or leverage <= 0 else leverage
    qty = position_size(balance, risk_pct, entry, stop_distance, direction, leverage=lev)
    return qty, risk_pct


def get_total_open_risk_pct(
    positions: List[Position],
    balance: float,
) -> float:
    """
    Sum of (size * |entry - stop_loss|) / balance * 100 for all positions.
    Used to enforce max_portfolio_risk_pct.
    """
    if balance <= 0 or not positions:
        return 0.0
    total_risk = 0.0
    for pos in positions:
        if pos.stop_loss is not None:
            risk_amount = pos.size * abs(pos.entry_price - pos.stop_loss)
            total_risk += risk_amount
    return (total_risk / balance) * 100.0


async def get_current_open_risk_pct_async(broker, symbol: str, balance: float) -> float:
    """
    Get current open portfolio risk % for a broker (single symbol: one position).
    For multi-symbol, broker would need to return all positions; here we use get_open_position(symbol).
    """
    pos = await broker.get_open_position(symbol)
    if pos is None:
        return 0.0
    return get_total_open_risk_pct([pos], balance)


def allocate_capital_per_strategy(
    strategy_metrics: dict,
    total_capital: float,
) -> dict:
    """
    Multi-strategy: strategy_weight = profit_factor*0.5 + avg_R*0.3 + stability*0.2, then normalize.
    Returns dict strategy_id -> allocated_capital.
    """
    if not strategy_metrics or total_capital <= 0:
        return {}
    weights = {}
    for sid, m in strategy_metrics.items():
        pf = float(m.get("profit_factor") or 0)
        ar = float(m.get("avg_R") or 0)
        st = float(m.get("stability_score") or 0)
        w = pf * 0.5 + ar * 0.3 + st * 0.2
        weights[sid] = max(0.0, w)
    total_w = sum(weights.values())
    if total_w <= 0:
        return {sid: total_capital / len(weights) for sid in weights}
    return {
        sid: total_capital * (w / total_w)
        for sid, w in weights.items()
    }
