"""
Edge decay / holding horizon analysis.

Uses future_r_5, future_r_10, future_r_20, future_r_30 to determine:
- Where edge is strongest after entry
- Whether holding longer destroys expectancy
- Preferred exit horizon for TP / trailing / max holding bars.

Use with rows that have future_r_* columns (e.g. from get_candidate_signals_with_outcomes).
"""
from typing import List, Optional, Any

import numpy as np

from analysis.stability_map import (
    REGIMES_ALL,
    _get_float,
    _normalize_regime,
    metrics_for_rows,
    _filter_by_thresholds,
)

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


def edge_decay_per_parameter_combinations(
    rows: List[dict],
    ema_values: List[float],
    volume_ratio_values: List[float],
    rsi_values: List[float],
    horizons: List[int] = None,
    r_cap: float = R_CAP,
    use_trend_filter: bool = False,
    **scan_kw: Any,
) -> List[dict]:
    """
    For each (ema_t, vol_t, rsi_t) combination, filter rows and compute horizon-level stats.
    Returns list of dicts with ema_distance_threshold, volume_ratio_threshold, rsi_threshold,
    avg_future_r_5, avg_future_r_10, avg_future_r_20, avg_future_r_30, best_horizon, edge_decay_slope.
    """
    if horizons is None:
        horizons = HORIZONS
    out = []
    for ema_t in ema_values:
        for vol_t in volume_ratio_values:
            for rsi_t in rsi_values:
                filtered = _filter_by_thresholds(
                    rows, ema_t, vol_t, rsi_t, use_trend_filter=use_trend_filter, **scan_kw
                )
                avg_by_h = {}
                for n in horizons:
                    r_key = f"future_r_{n}"
                    vals = []
                    for r in filtered:
                        v = r.get(r_key)
                        if v is not None and v != "":
                            try:
                                v = float(v)
                                v = max(-r_cap, min(r_cap, v))
                                vals.append(v)
                            except (TypeError, ValueError):
                                pass
                    avg_by_h[n] = (sum(vals) / len(vals)) if vals else float("nan")
                if not avg_by_h:
                    best_horizon = horizons[0]
                    edge_decay_slope = float("nan")
                else:
                    best_horizon = max(avg_by_h.keys(), key=lambda h: avg_by_h[h] if avg_by_h[h] == avg_by_h[h] else -1e9)
                    # slope: (avg_R at last horizon - avg_R at first) / (last - first) in bars
                    h_min, h_max = min(horizons), max(horizons)
                    if h_max > h_min:
                        edge_decay_slope = (avg_by_h[h_max] - avg_by_h[h_min]) / (h_max - h_min)
                    else:
                        edge_decay_slope = 0.0
                row = {
                    "ema_distance_threshold": ema_t,
                    "volume_ratio_threshold": vol_t,
                    "rsi_threshold": rsi_t,
                    "best_horizon": best_horizon,
                    "edge_decay_slope": edge_decay_slope,
                }
                for n in horizons:
                    row[f"avg_future_r_{n}"] = avg_by_h[n]
                out.append(row)
    return out


def plot_edge_decay_heatmap(
    summary_rows: List[dict],
    output_path: str,
    rsi_fix: Optional[float] = None,
    value_key: str = "best_horizon",
) -> bool:
    """
    Plot 2D heatmap: ema_distance_threshold vs volume_ratio_threshold (rsi fixed), color = value_key.
    value_key can be 'best_horizon', 'edge_decay_slope', or 'avg_future_r_30' etc.
    Returns True if plot was saved.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    from pathlib import Path
    if rsi_fix is not None:
        summary_rows = [r for r in summary_rows if r.get("rsi_threshold") == rsi_fix]
    if not summary_rows:
        return False
    ema_vals = sorted({r["ema_distance_threshold"] for r in summary_rows})
    vol_vals = sorted({r["volume_ratio_threshold"] for r in summary_rows})
    ema_idx = {v: i for i, v in enumerate(ema_vals)}
    vol_idx = {v: i for i, v in enumerate(vol_vals)}
    grid = np.full((len(vol_vals), len(ema_vals)), np.nan)
    for r in summary_rows:
        i = vol_idx.get(r["volume_ratio_threshold"])
        j = ema_idx.get(r["ema_distance_threshold"])
        if i is not None and j is not None:
            v = r.get(value_key)
            if v is not None and isinstance(v, float) and (np.isnan(v) or v != v):
                continue
            grid[i, j] = float(v) if v is not None else np.nan
    fig, ax = plt.subplots()
    im = ax.imshow(grid, aspect="auto", origin="lower", cmap="viridis")
    ax.set_xticks(range(len(ema_vals)))
    ax.set_yticks(range(len(vol_vals)))
    ax.set_xticklabels([f"{x:.4f}" for x in ema_vals], rotation=45)
    ax.set_yticklabels([f"{y:.2f}" for y in vol_vals])
    ax.set_xlabel("ema_distance_threshold")
    ax.set_ylabel("volume_ratio_threshold")
    ax.set_title(f"Edge decay: {value_key}" + (f" (rsi={rsi_fix})" if rsi_fix is not None else ""))
    plt.colorbar(im, ax=ax, label=value_key)
    plt.tight_layout()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=100)
    plt.close()
    return True


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
        report["by_regime"] = {}
        for reg in REGIMES_ALL:
            subset = [r for r in rows if _normalize_regime(r.get("regime") or "") == reg]
            report["by_regime"][reg] = metrics_by_horizon(subset, horizons=horizons)
        if with_trend_filter:
            report["by_regime_trend_filtered"] = {}
            for reg in REGIMES_ALL:
                subset = [r for r in rows if _normalize_regime(r.get("regime") or "") == reg]
                trend_subset = apply_trend_filter(subset)
                report["by_regime_trend_filtered"][reg] = metrics_by_horizon(trend_subset, horizons=horizons)

    return report
