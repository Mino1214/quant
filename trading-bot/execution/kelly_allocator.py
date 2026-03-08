"""
Kelly Criterion risk scaling: raw Kelly, fractional Kelly, and risk caps.
Outputs final_risk_pct for position sizing; does not override max_risk_per_trade or max_portfolio_risk.
"""
from typing import Any, Dict, Optional

from core.models import KellySettings


def raw_kelly_fraction(
    win_probability: float,
    avg_win_R: float,
    avg_loss_R: float,
) -> Optional[float]:
    """
    Compute raw Kelly fraction: p - (q / b), where b = avg_win_R / abs(avg_loss_R).
    Returns None if invalid (e.g. avg_loss_R == 0) or if result would be negative/invalid.
    """
    if avg_loss_R >= 0 or avg_win_R <= 0:
        return None
    b = avg_win_R / abs(avg_loss_R)
    if b <= 0:
        return None
    p = max(0.0, min(1.0, win_probability))
    q = 1.0 - p
    raw = p - (q / b)
    return raw if raw > 0 else None


def kelly_risk_pct(
    win_probability: float,
    avg_win_R: float,
    avg_loss_R: float,
    fractional: float = 0.25,
    min_risk_pct: float = 0.25,
    max_risk_pct: float = 1.0,
) -> float:
    """
    Quarter Kelly (or other fraction) with risk caps.
    Returns final risk in percent [min_risk_pct, max_risk_pct]; 0 means skip trade.
    """
    raw = raw_kelly_fraction(win_probability, avg_win_R, avg_loss_R)
    if raw is None or raw <= 0:
        return 0.0
    safe_kelly = raw * fractional
    # safe_kelly is a fraction (e.g. 0.075); convert to percent and cap
    safe_pct = safe_kelly * 100.0
    return min(max(safe_pct, min_risk_pct), max_risk_pct)


def compute_kelly_risk(
    win_probability: float,
    avg_win_R: float,
    avg_loss_R: float,
    settings: KellySettings,
    signal_quality_score: Optional[float] = None,
    expected_R: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Full Kelly pipeline: raw -> fractional -> caps.
    Returns dict: kelly_fraction (raw), safe_kelly_fraction, final_risk_pct, skip (bool).
    """
    raw = raw_kelly_fraction(win_probability, avg_win_R, avg_loss_R)
    if raw is None or raw <= 0:
        return {
            "kelly_fraction": 0.0,
            "safe_kelly_fraction": 0.0,
            "final_risk_pct": 0.0,
            "skip": True,
        }
    safe = raw * settings.fractional_kelly
    final_pct = min(
        max(safe * 100.0, settings.min_risk_per_trade_pct),
        settings.max_risk_per_trade_pct,
    )
    return {
        "kelly_fraction": raw,
        "safe_kelly_fraction": safe,
        "final_risk_pct": final_pct,
        "skip": False,
    }
