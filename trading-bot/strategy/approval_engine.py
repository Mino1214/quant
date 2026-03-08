"""
Two-stage entry: candidate_signal → approval_engine → entry.
Scores candidate on 7 categories; entry only if total_score >= approval_threshold.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.models import (
    ApprovalResult,
    ApprovalSettings,
    Candle,
    Direction,
    RiskSettings,
    Signal,
    StrategySettings,
)

from indicators.ema import ema, emas_from_candles
from indicators.volume import vma_from_candles


@dataclass
class ApprovalContext:
    """Context passed to approval engine for scoring."""
    candles_1m: List[Candle]
    candles_5m: List[Candle]
    candles_15m: List[Candle]
    entry_price: float
    stop_loss: float
    regime_result: Optional[Any] = None  # MarketRegimeResult when regime enabled


def _regime_quality(ctx: ApprovalContext, settings: ApprovalSettings) -> int:
    """1 if regime allows trading and meets adx/score threshold."""
    if ctx.regime_result is None:
        return 1  # no regime filter → pass
    r = ctx.regime_result
    if not getattr(r, "allow_trading", False):
        return 0
    adx = getattr(r, "adx", 0) or 0
    score = getattr(r, "score", 0) or 0
    if adx >= settings.regime_adx_min or score >= settings.regime_score_min:
        return 1
    return 0


def _trend_quality(
    ctx: ApprovalContext,
    direction: Direction,
    strat: StrategySettings,
    settings: ApprovalSettings,
) -> int:
    """1 if 5m EMAs aligned with direction."""
    if not settings.trend_ema_aligned or len(ctx.candles_5m) < strat.ema_slow:
        return 1
    emas = emas_from_candles(
        ctx.candles_5m, [strat.ema_fast, strat.ema_mid, strat.ema_slow]
    )
    e8 = emas.get(strat.ema_fast)
    e21 = emas.get(strat.ema_mid)
    e50 = emas.get(strat.ema_slow)
    if e8 is None or e21 is None or e50 is None:
        return 0
    close = ctx.candles_5m[-1].close
    if direction == Direction.LONG:
        return 1 if (e8 > e21 > e50 and close > e21) else 0
    return 1 if (e8 < e21 < e50 and close < e21) else 0


def _trigger_quality(
    ctx: ApprovalContext,
    direction: Direction,
    strat: StrategySettings,
    settings: ApprovalSettings,
) -> int:
    """1 if 1m pullback trigger conditions hold."""
    if not settings.trigger_pullback_ok or len(ctx.candles_1m) < strat.ema_fast:
        return 1
    c = ctx.candles_1m[-1]
    closes = [x.close for x in ctx.candles_1m]
    ema8 = ema(closes, strat.ema_fast)
    if ema8 is None:
        return 0
    if direction == Direction.LONG:
        return 1 if (c.low <= ema8 and c.close > ema8 and c.is_bullish) else 0
    return 1 if (c.high >= ema8 and c.close < ema8 and c.is_bearish) else 0


def _volume_quality(
    ctx: ApprovalContext,
    strat: StrategySettings,
    settings: ApprovalSettings,
) -> int:
    """1 if volume > VMA*mult and (if required) volume > prev_volume."""
    if len(ctx.candles_1m) < strat.volume_ma_period:
        return 0
    c = ctx.candles_1m[-1]
    vma_val = vma_from_candles(ctx.candles_1m, strat.volume_ma_period)
    if vma_val is None:
        return 0
    if c.volume <= vma_val * settings.volume_multiplier_min:
        return 0
    if settings.volume_expansion_required and len(ctx.candles_1m) >= 2:
        if c.volume <= ctx.candles_1m[-2].volume:
            return 0
    return 1


def _ema_spacing_quality(
    ctx: ApprovalContext,
    strat: StrategySettings,
    settings: ApprovalSettings,
) -> int:
    """1 if abs(EMA8-EMA21)/close >= ema_distance_threshold."""
    if len(ctx.candles_1m) < strat.ema_mid:
        return 0
    closes = [x.close for x in ctx.candles_1m]
    e8 = ema(closes, strat.ema_fast)
    e21 = ema(closes, strat.ema_mid)
    if e8 is None or e21 is None:
        return 0
    close = ctx.candles_1m[-1].close
    if close <= 0:
        return 0
    dist = abs(e8 - e21) / close
    return 1 if dist >= settings.ema_distance_threshold else 0


def _breakout_quality(
    ctx: ApprovalContext,
    direction: Direction,
    settings: ApprovalSettings,
) -> int:
    """1 if long: close > prev_high, short: close < prev_low."""
    if not settings.breakout_required or len(ctx.candles_1m) < 2:
        return 1
    c = ctx.candles_1m[-1]
    prev = ctx.candles_1m[-2]
    if direction == Direction.LONG:
        return 1 if c.close > prev.high else 0
    return 1 if c.close < prev.low else 0


def _reward_risk_quality(
    ctx: ApprovalContext,
    risk_settings: RiskSettings,
    settings: ApprovalSettings,
) -> int:
    """1 if stop is valid and potential RR >= min_rr_ratio."""
    risk_dist = abs(ctx.entry_price - ctx.stop_loss)
    if risk_dist <= 0:
        return 0
    rr = getattr(risk_settings, "rr_target", 2.0)
    return 1 if rr >= settings.min_rr_ratio else 0


def score(
    candidate: Signal,
    ctx: ApprovalContext,
    approval_settings: ApprovalSettings,
    strategy_settings: StrategySettings,
    risk_settings: RiskSettings,
) -> ApprovalResult:
    """
    Score candidate on 7 categories. Each category 0 or 1. total_score 0..7.
    allowed = total_score >= approval_threshold.
    """
    cat: Dict[str, int] = {}
    cat["regime_quality"] = _regime_quality(ctx, approval_settings)
    cat["trend_quality"] = _trend_quality(ctx, candidate.direction, strategy_settings, approval_settings)
    cat["trigger_quality"] = _trigger_quality(ctx, candidate.direction, strategy_settings, approval_settings)
    cat["volume_quality"] = _volume_quality(ctx, strategy_settings, approval_settings)
    cat["ema_spacing_quality"] = _ema_spacing_quality(ctx, strategy_settings, approval_settings)
    cat["breakout_quality"] = _breakout_quality(ctx, candidate.direction, approval_settings)
    cat["reward_risk_quality"] = _reward_risk_quality(ctx, risk_settings, approval_settings)

    total = sum(cat.values())
    allowed = total >= approval_settings.approval_threshold
    blocked_reason = None if allowed else f"approval_score_{total}_below_{approval_settings.approval_threshold}"
    return ApprovalResult(
        allowed=allowed,
        total_score=total,
        category_scores=cat,
        blocked_reason=blocked_reason,
    )
