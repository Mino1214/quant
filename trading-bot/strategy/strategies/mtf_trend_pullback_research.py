"""
MTF Trend Pullback strategy (research-derived).

EDA에서 찾은 조건을 그대로 옮긴 전략:
- 15m / 5m EMA20 slope 양수 (상위 추세 상승)
- 1m EMA20 slope 음수 (단기 눌림)
- 1m RSI 낮고, 5m RSI 높음
- 깊이 있는 pullback_depth_pct (strict 버전)

두 버전:
- evaluate_base  : CANDIDATE_1_정석형
- evaluate_strict: CANDIDATE_2_강한필터
"""

from typing import Optional

from strategy.base import StrategyContext
from strategy.feature_extractor import extract_feature_values_research_minimal
from core.models import Signal, Direction, Timeframe


REQUIRED_BASE_FEATURES = (
    "ema20_slope_15m",
    "ema20_slope_5m",
    "ema20_slope_1m",
    "rsi_1m",
    "rsi_5m",
)


REQUIRED_STRICT_FEATURES = REQUIRED_BASE_FEATURES + (
    "pullback_depth_pct",
)

OPTIONAL_QUALITY_FEATURES = (
    "adx_14",
    "volume_ratio",
)


def _compute_features(ctx: StrategyContext) -> dict:
    """
    연구 전략용 경량 6개 피처만 계산 (백테스트 속도용).
    EDA와 동일 조건: ema20_slope_15m/5m/1m, rsi_1m/5m, pullback_depth_pct.
    """
    return extract_feature_values_research_minimal(
        candles_1m=ctx.candles_1m,
        candles_5m=ctx.candles_5m,
        settings=ctx.settings,
        candles_15m=ctx.candles_15m,
    )


def _has_required_features(feats: dict, required_keys: tuple[str, ...]) -> bool:
    for key in required_keys:
        value = feats.get(key)
        if value is None:
            return False
    return True


def _build_signal(
    context: StrategyContext,
    reason_code: str,
    strength: float,
) -> Signal:
    return Signal(
        direction=Direction.LONG,
        strength=strength,
        reason_code=reason_code,
        timeframe=Timeframe.M1,
        symbol=context.symbol,
    )


def _long_candidate_1(feats: dict) -> bool:
    """
    CANDIDATE_1_정석형

    조건:
    - ema20_slope_15m > 0.000163
    - ema20_slope_5m  > 0.000046
    - ema20_slope_1m  < 0
    - rsi_1m          < 40
    - rsi_5m          > 50
    """
    if not _has_required_features(feats, REQUIRED_BASE_FEATURES):
        return False

    return (
        feats["ema20_slope_15m"] > 0.000163
        and feats["ema20_slope_5m"] > 0.000046
        and feats["ema20_slope_1m"] < 0.0
        and feats["rsi_1m"] < 40.0
        and feats["rsi_5m"] > 50.0
    )


def _long_candidate_2(feats: dict) -> bool:
    """
    CANDIDATE_2_강한필터

    조건:
    - ema20_slope_15m > 0.000285
    - ema20_slope_5m  > 0.000094
    - ema20_slope_1m  < -0.000018
    - rsi_1m          < 38
    - rsi_5m          > 54
    - pullback_depth_pct > 0.6
    """
    if not _has_required_features(feats, REQUIRED_STRICT_FEATURES):
        return False

    base_condition = (
        # feats["ema20_slope_15m"] > 0.000285
        # and feats["ema20_slope_5m"] > 0.000094
        # and feats["ema20_slope_1m"] < -0.000018
        # and feats["rsi_1m"] < 38.0
        # and feats["rsi_5m"] > 54.0
        # and feats["pullback_depth_pct"] > 0.6
        feats.get("ema20_slope_5m", 0.0) > 0.000094
        and feats.get("ema20_slope_1m", 0.0) < -0.000018
        and feats.get("rsi_1m", 0.0) < 38.0
        and feats.get("rsi_5m", 0.0) > 54.0
        and feats.get("pullback_depth_pct", 0.0) > 0.6
    )

    if not base_condition:
        return False

    # Optional quality filters (used if feature exists in dataset)
    adx = feats.get("adx_14")
    if adx is not None and adx < 18:
        return False

    volume_ratio = feats.get("volume_ratio")
    if volume_ratio is not None and volume_ratio < 1.2:
        return False

    return True


# === Fast-path public helpers for simulation/research (from precomputed feature dicts) ===
def evaluate_base_features(feats: dict) -> bool:
    """
    Fast-path helper for simulators/research code.
    Returns only whether the base long entry condition is satisfied,
    without constructing StrategyContext / Signal objects.
    """
    if not feats:
        return False
    return _long_candidate_1(feats)


def evaluate_strict_features(feats: dict) -> bool:
    """
    Fast-path helper for simulators/research code.
    Returns only whether the strict long entry condition is satisfied,
    without constructing StrategyContext / Signal objects.
    """
    if not feats:
        return False
    return _long_candidate_2(feats)


def evaluate_base(context: StrategyContext) -> Optional[Signal]:
    """
    Base 버전: CANDIDATE_1_정석형.

    메인 롱 전략의 완화 버전 (표본수 많음, edge는 중간 수준).
    """
    if not context.candles_1m or not context.candles_5m or not context.candles_15m:
        return None

    feats = _compute_features(context)
    if not _long_candidate_1(feats):
        return None

    return _build_signal(
        context=context,
        reason_code="mtf_trend_pb_base",
        strength=0.8,
    )


def evaluate_strict(context: StrategyContext) -> Optional[Signal]:
    """
    Strict 버전: CANDIDATE_2_강한필터.

    edge 최상, 표본수는 적은 편. 메인 후보.
    """

    if not context.candles_1m or not context.candles_5m or not context.candles_15m:
        return None

    feats = _compute_features(context)
    if not feats:
        return None

    # 필수 feature 존재 확인
    required = (
        "ema20_slope_15m",
        "ema20_slope_5m",
        "ema20_slope_1m",
        "rsi_1m",
        "rsi_5m",
        "pullback_depth_pct",
    )

    for k in required:
        if feats.get(k) is None:
            return None

    if not _long_candidate_2(feats):
        return None

    return _build_signal(
        context=context,
        reason_code="mtf_trend_pb_strict",
        strength=1.0,
    )


def evaluate(context: StrategyContext) -> Optional[Signal]:
    """
    기본 evaluate는 strict 버전을 사용.

    필요하면 아래처럼 fallback도 가능:
    1) strict 먼저 시도
    2) strict 없으면 base 시도
    """
    signal = evaluate_strict(context)
    if signal is not None:
        return signal

    return None