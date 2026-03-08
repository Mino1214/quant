"""
Edge decay / holding horizon analysis.

Uses future_r_5, future_r_10, future_r_20, future_r_30 to determine:
- Where edge is strongest after entry
- Whether holding longer destroys expectancy
- Preferred exit horizon for TP / trailing / max holding bars.

Use with rows that have future_r_* columns (e.g. from get_candidate_signals_with_outcomes).
"""
from typing import List

from analysis.stability_map import _get_float, metrics_for_rows

HORIZONS = [5, 10, 20, 30]
R_CAP = 20.0


def metrics_by_horizon(
    rows: List[dict],
    horizons: List[int] = None,
    r_cap: float = R_CAP,
) -> List[dict]:
    """
    For each horizon N, compute metrics using future_r_N.
    Returns list of dicts: horizon, trades, winrate, avg_R, profit_factor, max_drawdown.
    """
    if horizons is None:
        horizons = HORIZONS
    out = []
    for n in horizons:
        r_key = f"future_r_{n}"
        subset = [r for r in rows if r.get(r_key) is not None and r.get(r_key) != ""]
        m = metrics_for_rows(subset, r_key=r_key, r_cap=r_cap)
        out.append({
            "horizon": n,
            "trades": m["trades"],
            "winrate": m["winrate"],
            "avg_R": m["avg_R"],
            "profit_factor": m["profit_factor"],
            "max_drawdown": m["max_drawdown"],
        })
    return out


def apply_trend_filter(rows: List[dict]) -> List[dict]:
    """
    LONG: ema20 > ema50 and ema50_slope > 0.
    SHORT: ema20 < ema50 and ema50_slope < 0.
    """
    filtered = []
    for r in rows:
        ema20_gt = _get_float(r, "ema20_gt_ema50")
        slope = _get_float(r, "ema50_slope")
        side = (r.get("side") or r.get("trend_direction") or "long").lower()
        if "long" in side:
            if ema20_gt >= 0.5 and slope > 0:
                filtered.append(r)
        else:
            if ema20_gt < 0.5 and slope < 0:
                filtered.append(r)
    return filtered


def edge_decay_report(
    rows: List[dict],
    by_regime: bool = True,
    with_trend_filter: bool = False,
    horizons: List[int] = None,
) -> dict:
    """
    Full report: overall + per regime, optionally trend-filtered.
    Returns dict with keys: overall, overall_trend_filtered (if with_trend_filter),
    by_regime: { regime: metrics_list }, by_regime_trend_filtered (if with_trend_filter).
    """
    if horizons is None:
        horizons = HORIZONS
    report = {
        "overall": metrics_by_horizon(rows, horizons=horizons),
    }
    if with_trend_filter:
        trend_rows = apply_trend_filter(rows)
        report["overall_trend_filtered"] = metrics_by_horizon(trend_rows, horizons=horizons)

    if by_regime:
        regimes = ["TRENDING_UP", "TRENDING_DOWN", "RANGING"]
        report["by_regime"] = {}
        for reg in regimes:
            subset = [r for r in rows if (r.get("regime") or "").upper() == reg]
            report["by_regime"][reg] = metrics_by_horizon(subset, horizons=horizons)
        if with_trend_filter:
            report["by_regime_trend_filtered"] = {}
            for reg in regimes:
                subset = [r for r in rows if (r.get("regime") or "").upper() == reg]
                trend_subset = apply_trend_filter(subset)
                report["by_regime_trend_filtered"][reg] = metrics_by_horizon(trend_subset, horizons=horizons)

    return report
