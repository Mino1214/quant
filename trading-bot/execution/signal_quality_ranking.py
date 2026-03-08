"""
Signal Quality Ranking: score each signal and rank by edge.
Formula: signal_quality_score = win_probability * 0.4 + expected_R_norm * 0.4 + strategy_stability_score * 0.2
"""
from typing import List, Tuple, Union

# Weights for composite score (plan: win_prob 0.4, expected_R 0.4, stability 0.2)
WEIGHT_WIN_PROB = 0.4
WEIGHT_EXPECTED_R = 0.4
WEIGHT_STABILITY = 0.2

# expected_R from ML is in R units (e.g. -0.5 .. 1.5); normalize to [0, 1] for scoring
EXPECTED_R_MIN = -0.5
EXPECTED_R_MAX = 1.5


def normalize_expected_r(
    expected_r: float,
    min_r: float = EXPECTED_R_MIN,
    max_r: float = EXPECTED_R_MAX,
) -> float:
    """Clip and normalize expected_R to [0, 1] for use in quality score."""
    if max_r <= min_r:
        return 0.5
    r = max(min_r, min(max_r, expected_r))
    return (r - min_r) / (max_r - min_r)


def compute_signal_quality_score(
    win_probability: float,
    expected_r: float,
    strategy_stability_score: float,
    recent_strategy_performance: float = None,
) -> float:
    """
    Composite signal quality score in [0, 1].
    score = win_probability * 0.4 + expected_R_norm * 0.4 + strategy_stability_score * 0.2
    Optional recent_strategy_performance is not in the base formula; can be used in extensions.
    """
    r_norm = normalize_expected_r(expected_r)
    score = (
        win_probability * WEIGHT_WIN_PROB
        + r_norm * WEIGHT_EXPECTED_R
        + max(0.0, min(1.0, strategy_stability_score)) * WEIGHT_STABILITY
    )
    if recent_strategy_performance is not None:
        # Optional: blend in recent performance (e.g. 0..1) without changing base weights
        perf = max(0.0, min(1.0, recent_strategy_performance))
        score = 0.9 * score + 0.1 * perf
    return max(0.0, min(1.0, score))


def rank_signals(
    signals_with_scores: List[Union[Tuple[str, float], dict]],
) -> List[Union[Tuple[str, float], dict]]:
    """
    Sort signals by signal_quality_score descending (highest edge first).
    Each item is (signal_id, score) or a dict with 'signal_id' and 'signal_quality_score'.
    Returns new sorted list; input list is not modified.
    """
    def key_fn(item):
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            return -item[1]
        if isinstance(item, dict):
            return -float(item.get("signal_quality_score", item.get("score", 0)))
        return 0

    return sorted(signals_with_scores, key=key_fn)
