"""
Load config from JSON and environment variables.
"""
import json
import os
from pathlib import Path
from typing import Any

from core.models import ApprovalSettings, CapitalAllocationSettings, KellySettings, LeverageSettings, RiskSettings, StrategySettings
from strategy.filters.market_regime import RegimeSettings


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "mysql+pymysql://mynolab_user:mynolab2026@180.230.8.65/tradebot?charset=utf8mb4",
    )


def load_config() -> dict:
    root = _project_root()
    config_path = root / "config" / "config.json"
    return load_json(config_path)


def load_symbols() -> list[str]:
    root = _project_root()
    symbols_path = root / "config" / "symbols.json"
    return load_json(symbols_path)


def get_strategy_settings(config: dict | None = None) -> StrategySettings:
    cfg = config or load_config()
    s = cfg.get("strategy", {})
    return StrategySettings(
        ema_fast=s.get("ema_fast", 8),
        ema_mid=s.get("ema_mid", 21),
        ema_slow=s.get("ema_slow", 50),
        slope_threshold=s.get("slope_threshold", 0.0001),
        volume_ma_period=s.get("volume_ma_period", 20),
        volume_multiplier=s.get("volume_multiplier", 1.2),
        swing_lookback=s.get("swing_lookback", 10),
        ema_distance_threshold=s.get("ema_distance_threshold", 0.0006),
        momentum_body_ratio=s.get("momentum_body_ratio", 0.5),
        signal_score_threshold=s.get("signal_score_threshold", 3),
        rsi_period=s.get("rsi_period", 14),
        rsi_long_min=s.get("rsi_long_min", 55.0),
        rsi_short_max=s.get("rsi_short_max", 45.0),
    )


def get_risk_settings(config: dict | None = None) -> RiskSettings:
    cfg = config or load_config()
    r = cfg.get("risk", {})
    return RiskSettings(
        risk_per_trade_pct=r.get("risk_per_trade_pct", 0.5),
        atr_multiplier=r.get("atr_multiplier", 1.5),
        atr_period=r.get("atr_period", 14),
        swing_lookback=r.get("swing_lookback", 10),
        partial_tp_R=r.get("partial_tp_R", 1.0),
        partial_tp_size=r.get("partial_tp_size", 0.5),
        trailing_atr_multiplier=r.get("trailing_atr_multiplier", 2.0),
        max_bars_in_trade=r.get("max_bars_in_trade", 30),
        ema_exit_confirm_bars=r.get("ema_exit_confirm_bars", 1),
        rr_target=r.get("rr_target", 2.0),
        daily_loss_limit_r=r.get("daily_loss_limit_r", -2.0),
        daily_profit_limit_r=r.get("daily_profit_limit_r", 3.0),
        max_trades_per_day=r.get("max_trades_per_day", 10),
        cooldown_bars=r.get("cooldown_bars", 1),
    )


def get_approval_settings(config: dict | None = None) -> ApprovalSettings:
    cfg = config or load_config()
    a = cfg.get("approval", {})
    return ApprovalSettings(
        approval_threshold=a.get("approval_threshold", 5),
        regime_adx_min=a.get("regime_adx_min", 10.0),
        regime_score_min=a.get("regime_score_min", 1),
        trend_ema_aligned=a.get("trend_ema_aligned", True),
        trigger_pullback_ok=a.get("trigger_pullback_ok", True),
        volume_multiplier_min=a.get("volume_multiplier_min", 1.2),
        volume_expansion_required=a.get("volume_expansion_required", True),
        ema_distance_threshold=a.get("ema_distance_threshold", 0.0006),
        momentum_body_ratio=a.get("momentum_body_ratio", 0.5),
        breakout_required=a.get("breakout_required", True),
        min_rr_ratio=a.get("min_rr_ratio", 0.5),
    )


def get_ml_settings(config: dict | None = None) -> dict:
    """ML gate: enabled, model_path, threshold_win_prob, threshold_expected_r."""
    cfg = config or load_config()
    m = cfg.get("ml", {})
    return {
        "enabled": m.get("enabled", False),
        "model_path": m.get("model_path", "ml/models"),
        "threshold_win_prob": float(m.get("threshold_win_prob", 0.58)),
        "threshold_expected_r": float(m.get("threshold_expected_r", 0.25)),
    }


def get_leverage_settings(config: dict | None = None) -> LeverageSettings:
    """Regime-adaptive leverage: max_leverage, regime_leverage map."""
    cfg = config or load_config()
    lev = cfg.get("leverage", {})
    return LeverageSettings(
        enabled=lev.get("enabled", True),
        max_leverage=float(lev.get("max_leverage", 5.0)),
        max_position_risk_pct=float(lev.get("max_position_risk_pct", 1.0)),
        regime_leverage=lev.get("regime_leverage"),
    )


def get_kelly_settings(config: dict | None = None) -> KellySettings:
    """Kelly criterion: enabled, fractional_kelly, risk caps, avg_win_R, avg_loss_R."""
    cfg = config or load_config()
    k = cfg.get("kelly", {})
    return KellySettings(
        enabled=k.get("enabled", True),
        fractional_kelly=float(k.get("fractional_kelly", 0.25)),
        max_risk_per_trade_pct=float(k.get("max_risk_per_trade_pct", 1.0)),
        min_risk_per_trade_pct=float(k.get("min_risk_per_trade_pct", 0.25)),
        avg_win_R=float(k.get("avg_win_R", 1.2)),
        avg_loss_R=float(k.get("avg_loss_R", -1.0)),
    )


def get_capital_allocation_settings(config: dict | None = None) -> CapitalAllocationSettings:
    """Capital allocation: min_quality_threshold, tiers, max_portfolio_risk_pct, regime_multipliers."""
    cfg = config or load_config()
    ca = cfg.get("capital_allocation", {})
    tiers = ca.get("tiers")
    if tiers is not None:
        tiers = [tuple(t) for t in tiers]
    return CapitalAllocationSettings(
        enabled=ca.get("enabled", True),
        min_quality_threshold=float(ca.get("min_quality_threshold", 0.55)),
        tiers=tiers,
        max_portfolio_risk_pct=float(ca.get("max_portfolio_risk_pct", 6.0)),
        regime_multipliers=ca.get("regime_multipliers"),
        default_strategy_stability_score=float(ca.get("default_strategy_stability_score", 0.5)),
    )


def get_regime_settings(config: dict | None = None) -> RegimeSettings:
    cfg = config or load_config()
    r = cfg.get("regime", {})
    return RegimeSettings(
        enabled=r.get("enabled", True),
        ema_slow_len=r.get("ema_slow_len", 50),
        slope_lookback=r.get("slope_lookback", 5),
        slope_threshold_pct=r.get("slope_threshold_pct", 0.008),
        adx_len=r.get("adx_len", 14),
        adx_min=r.get("adx_min", 10.0),
        atr_len=r.get("atr_len", 14),
        natr_min=r.get("natr_min", 0.02),
        natr_max=r.get("natr_max", 1.20),
        score_threshold=r.get("score_threshold", 1),
    )
