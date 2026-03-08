"""
Edge Stability Map: parameter grid scan (ema_distance, volume_ratio, rsi thresholds).
For each combination compute trades, winrate, avg_R, profit_factor, max_drawdown.
Generate 2D heatmaps (third parameter fixed).
"""
from datetime import datetime
from typing import List, Optional, Tuple

import numpy as np


def _r_values(rows: List[dict], r_key: str = "R_return") -> List[float]:
    """Extract R values; use future_r_30 if R_return missing."""
    out = []
    for r in rows:
        val = r.get(r_key)
        if val is None or val == "":
            val = r.get("future_r_30")
        if val is None or val == "":
            continue
        try:
            out.append(float(val))
        except (TypeError, ValueError):
            continue
    return out


def _get_float(r: dict, key: str, default: float = 0.0) -> float:
    val = r.get(key)
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def filter_by_entry_quality(
    rows: List[dict],
    min_pullback_depth_pct: Optional[float] = None,
    max_pullback_depth_pct: Optional[float] = None,
    require_breakout: bool = False,
    min_momentum_ratio: Optional[float] = None,
    max_upper_wick_ratio_long: Optional[float] = None,
    max_lower_wick_ratio_short: Optional[float] = None,
) -> List[dict]:
    """
    Keep only rows that pass optional entry-quality constraints.
    Use after loading candidates, before threshold scan, to reduce low-quality signals.
    - pullback_depth_pct: long pullback = (recent_high - close)/range (0..1). Constrain range.
    - require_breakout: long requires close > recent_high (breakout_confirmation > 0), short < recent_low (< 0).
    - min_momentum_ratio: body/range of last candle (strong body).
    - max_upper_wick_ratio_long: filter longs with large upper wick (rejection).
    - max_lower_wick_ratio_short: filter shorts with large lower wick.
    """
    out = []
    for r in rows:
        side = (r.get("side") or r.get("trend_direction") or "long").lower()
        pullback = _get_float(r, "pullback_depth_pct", -1.0)
        breakout = _get_float(r, "breakout_confirmation", 0.0)
        momentum = _get_float(r, "momentum_ratio", 0.0)
        upper_wick = _get_float(r, "upper_wick_ratio", 1.0)
        lower_wick = _get_float(r, "lower_wick_ratio", 1.0)

        if min_pullback_depth_pct is not None and pullback < min_pullback_depth_pct:
            continue
        if max_pullback_depth_pct is not None and pullback > max_pullback_depth_pct:
            continue
        if require_breakout:
            if "long" in side and breakout <= 0:
                continue
            if "short" in side and breakout >= 0:
                continue
        if min_momentum_ratio is not None and momentum < min_momentum_ratio:
            continue
        if max_upper_wick_ratio_long is not None and "long" in side and upper_wick > max_upper_wick_ratio_long:
            continue
        if max_lower_wick_ratio_short is not None and "short" in side and lower_wick > max_lower_wick_ratio_short:
            continue
        out.append(r)
    return out


def _filter_by_thresholds(
    rows: List[dict],
    ema_t: float,
    vol_t: float,
    rsi_t: float,
    use_trend_filter: bool = False,
) -> List[dict]:
    """Keep rows that pass virtual thresholds. Long: rsi >= rsi_t; Short: rsi <= 100 - rsi_t. Optional trend filter."""
    filtered = []
    for r in rows:
        try:
            ema_d = _get_float(r, "ema_distance")
            vol_r = _get_float(r, "volume_ratio")
            rsi_val = _get_float(r, "rsi", 50.0)
            if rsi_val == 0 and (r.get("rsi_5m") is not None or r.get("rsi") is not None):
                rsi_val = _get_float(r, "rsi_5m", 50.0) or _get_float(r, "rsi", 50.0)
            if rsi_val == 0:
                rsi_val = 50.0
        except (TypeError, ValueError):
            continue
        if ema_d < ema_t:
            continue
        if vol_r < vol_t:
            continue
        side = (r.get("side") or r.get("trend_direction") or "long").lower()
        if "long" in side:
            if rsi_val < rsi_t:
                continue
        else:
            if rsi_val > (100 - rsi_t):
                continue
        if use_trend_filter:
            ema20_gt = _get_float(r, "ema20_gt_ema50")
            slope = _get_float(r, "ema50_slope")
            if "long" in side:
                if ema20_gt < 0.5 or slope <= 0:
                    continue
            else:
                if ema20_gt >= 0.5 or slope >= 0:
                    continue
        filtered.append(r)
    return filtered


def _filter_by_thresholds_with_debug(
    rows: List[dict],
    ema_t: float,
    vol_t: float,
    rsi_t: float,
    use_trend_filter: bool = False,
) -> tuple[List[dict], dict]:
    """Same as _filter_by_thresholds but also return counts after each stage for parameter_scan_debug.csv."""
    total = len(rows)
    after_ema = []
    for r in rows:
        ema_d = _get_float(r, "ema_distance")
        if ema_d >= ema_t:
            after_ema.append(r)
    after_vol = []
    for r in after_ema:
        vol_r = _get_float(r, "volume_ratio")
        if vol_r >= vol_t:
            after_vol.append(r)
    after_rsi = []
    for r in after_vol:
        rsi_val = _get_float(r, "rsi", 50.0) or _get_float(r, "rsi_5m", 50.0) or 50.0
        side = (r.get("side") or r.get("trend_direction") or "long").lower()
        if "long" in side and rsi_val >= rsi_t:
            after_rsi.append(r)
        elif "short" in side and rsi_val <= (100 - rsi_t):
            after_rsi.append(r)
    final = after_rsi if not use_trend_filter else []
    if use_trend_filter:
        for r in after_rsi:
            ema20_gt = _get_float(r, "ema20_gt_ema50")
            slope = _get_float(r, "ema50_slope")
            side = (r.get("side") or r.get("trend_direction") or "long").lower()
            if "long" in side and ema20_gt >= 0.5 and slope > 0:
                final.append(r)
            elif "short" in side and ema20_gt < 0.5 and slope < 0:
                final.append(r)
    else:
        final = list(after_rsi)
    debug = {
        "total_candidates": total,
        "after_ema_filter": len(after_ema),
        "after_volume_filter": len(after_vol),
        "after_rsi_filter": len(after_rsi),
        "final_trades": len(final),
    }
    return final, debug


def _cap_r(val: float, cap: float = 20.0) -> float:
    """Cap R to [-cap, cap] to avoid absurd scan metrics from tiny stop distance or bad data."""
    if val != val:
        return 0.0
    return max(-cap, min(cap, val))


def metrics_for_rows(rows: List[dict], r_key: str = "R_return", r_cap: float = 20.0) -> dict:
    """
    Compute trades, winrate, avg_R, profit_factor, max_drawdown from rows with R.
    R values are capped to [-r_cap, r_cap] before averaging.
    profit_factor is capped at 10.0 when gross_loss is near zero to avoid misleading 100/inf.
    """
    r_vals = _r_values(rows, r_key=r_key)
    if not r_vals:
        return {"trades": 0, "winrate": 0.0, "avg_R": 0.0, "profit_factor": 0.0, "max_drawdown": 0.0}
    r_vals = [_cap_r(float(x), r_cap) for x in r_vals]
    n = len(r_vals)
    wins = [x for x in r_vals if x > 0]
    losses = [x for x in r_vals if x <= 0]
    winrate = (len(wins) / n * 100) if n else 0.0
    avg_R = sum(r_vals) / n
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    if profit_factor == float("inf") or profit_factor > 10.0:
        profit_factor = 10.0  # Cap to avoid misleading 100/inf when gross_loss near zero
    # Max drawdown: cumulative R curve
    cum = np.cumsum(r_vals)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    max_drawdown = float(np.max(dd)) if len(dd) else 0.0
    return {
        "trades": n,
        "winrate": winrate,
        "avg_R": avg_R,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
    }


def run_parameter_scan(
    rows: List[dict],
    ema_values: List[float],
    volume_ratio_values: List[float],
    rsi_values: List[float],
    r_key: str = "R_return",
    r_cap: float = 20.0,
    use_trend_filter: bool = False,
) -> List[dict]:
    """Run full grid; optional trend filter (long: ema20>ema50 and slope>0, short: opposite)."""
    results = []
    for ema_t in ema_values:
        for vol_t in volume_ratio_values:
            for rsi_t in rsi_values:
                filtered = _filter_by_thresholds(rows, ema_t, vol_t, rsi_t, use_trend_filter=use_trend_filter)
                m = metrics_for_rows(filtered, r_key=r_key, r_cap=r_cap)
                results.append({
                    "ema_distance_threshold": ema_t,
                    "volume_ratio_threshold": vol_t,
                    "rsi_threshold": rsi_t,
                    "trades": m["trades"],
                    "winrate": m["winrate"],
                    "avg_R": m["avg_R"],
                    "profit_factor": m["profit_factor"],
                    "max_drawdown": m["max_drawdown"],
                })
    return results


def run_parameter_scan_with_debug(
    rows: List[dict],
    ema_values: List[float],
    volume_ratio_values: List[float],
    rsi_values: List[float],
    r_key: str = "R_return",
    r_cap: float = 20.0,
    use_trend_filter: bool = False,
) -> tuple[List[dict], List[dict]]:
    """Run full grid and return (results, debug_rows). debug_rows for parameter_scan_debug.csv."""
    results = []
    debug_rows = []
    for ema_t in ema_values:
        for vol_t in volume_ratio_values:
            for rsi_t in rsi_values:
                filtered, debug = _filter_by_thresholds_with_debug(
                    rows, ema_t, vol_t, rsi_t, use_trend_filter=use_trend_filter
                )
                m = metrics_for_rows(filtered, r_key=r_key, r_cap=r_cap)
                results.append({
                    "ema_distance_threshold": ema_t,
                    "volume_ratio_threshold": vol_t,
                    "rsi_threshold": rsi_t,
                    "trades": m["trades"],
                    "winrate": m["winrate"],
                    "avg_R": m["avg_R"],
                    "profit_factor": m["profit_factor"],
                    "max_drawdown": m["max_drawdown"],
                })
                debug_rows.append({
                    "ema_distance_threshold": ema_t,
                    "volume_ratio_threshold": vol_t,
                    "rsi_threshold": rsi_t,
                    "total_candidates": debug["total_candidates"],
                    "after_ema_filter": debug["after_ema_filter"],
                    "after_volume_filter": debug["after_volume_filter"],
                    "after_rsi_filter": debug["after_rsi_filter"],
                    "final_trades": debug["final_trades"],
                })
    return results, debug_rows


def run_parameter_scan_by_regime(
    rows: List[dict],
    ema_values: List[float],
    volume_ratio_values: List[float],
    rsi_values: List[float],
    r_key: str = "R_return",
    r_cap: float = 20.0,
    use_trend_filter: bool = False,
) -> dict[str, List[dict]]:
    """Run scan per regime (TRENDING_UP, TRENDING_DOWN, RANGING). Returns {regime: results}."""
    regimes = ["TRENDING_UP", "TRENDING_DOWN", "RANGING"]
    out = {}
    for reg in regimes:
        subset = [r for r in rows if (r.get("regime") or "").upper() == reg]
        out[reg] = run_parameter_scan(
            subset, ema_values, volume_ratio_values, rsi_values,
            r_key=r_key, r_cap=r_cap, use_trend_filter=use_trend_filter,
        )
    return out


# Sanity thresholds for scan result filtering
SANITY_ABS_AVG_R_MAX = 5.0
SANITY_PROFIT_FACTOR_MAX = 10.0
SANITY_MIN_TRADES = 30
# Stable region recommendation (edge recovery: broad stable region)
STABLE_MIN_TRADES = 200
STABLE_MIN_PROFIT_FACTOR = 1.02
STABLE_MIN_AVG_R = 0.0
# Heatmap: only rows with enough trades and valid
HEATMAP_MIN_TRADES = 200


def flag_suspicious_rows(results: List[dict]) -> List[dict]:
    """Add flags to each row: suspicious_abs_avg_r, suspicious_pf, suspicious_low_trades, valid."""
    out = []
    for r in results:
        trades = r.get("trades") or 0
        avg_r = r.get("avg_R")
        pf = r.get("profit_factor")
        if avg_r is None:
            avg_r = 0.0
        if pf is None:
            pf = 0.0
        suspicious_abs_avg_r = abs(avg_r) > SANITY_ABS_AVG_R_MAX
        suspicious_pf = pf > SANITY_PROFIT_FACTOR_MAX
        suspicious_low_trades = trades < SANITY_MIN_TRADES
        valid = not (suspicious_abs_avg_r or suspicious_pf or suspicious_low_trades)
        out.append({
            **r,
            "suspicious_abs_avg_r": suspicious_abs_avg_r,
            "suspicious_pf": suspicious_pf,
            "suspicious_low_trades": suspicious_low_trades,
            "valid": valid,
        })
    return out


def get_cleaned_scan_results(results: List[dict]) -> List[dict]:
    """Return only rows that pass sanity: abs(avg_R) <= 5, profit_factor <= 10, trades >= 30."""
    flagged = flag_suspicious_rows(results)
    return [r for r in flagged if r.get("valid") is True]


def heatmap_data_2d(
    results: List[dict],
    x_key: str,
    y_key: str,
    value_key: str = "avg_R",
    fix_key: Optional[str] = None,
    fix_value: Optional[float] = None,
) -> Tuple[List[float], List[float], np.ndarray]:
    """
    Build 2D grid for heatmap. If fix_key is set, only use rows where fix_key == fix_value.
    Returns (x_unique, y_unique, 2D array of value_key).
    """
    if fix_key and fix_value is not None:
        results = [r for r in results if r.get(fix_key) == fix_value]
    x_vals = sorted({r[x_key] for r in results})
    y_vals = sorted({r[y_key] for r in results})
    x_idx = {v: i for i, v in enumerate(x_vals)}
    y_idx = {v: i for i, v in enumerate(y_vals)}
    grid = np.full((len(y_vals), len(x_vals)), np.nan)
    for r in results:
        i = y_idx.get(r[y_key])
        j = x_idx.get(r[x_key])
        if i is not None and j is not None:
            val = r.get(value_key)
            if val == float("inf"):
                val = 100.0
            grid[i, j] = val
    return x_vals, y_vals, grid


def _results_for_heatmap(results: List[dict], min_trades: int = HEATMAP_MIN_TRADES, require_valid: bool = True) -> List[dict]:
    """Filter to rows with trades >= min_trades and (if require_valid) valid=True."""
    if require_valid:
        flagged = flag_suspicious_rows(results)
        subset = [r for r in flagged if r.get("valid") is True and (r.get("trades") or 0) >= min_trades]
    else:
        subset = [r for r in results if (r.get("trades") or 0) >= min_trades]
    return subset


def plot_heatmaps(
    results: List[dict],
    output_dir: str,
    rsi_fix: Optional[float] = None,
    ema_fix: Optional[float] = None,
    vol_fix: Optional[float] = None,
    min_trades: int = HEATMAP_MIN_TRADES,
    require_valid: bool = True,
    suffix: str = "",
) -> List[str]:
    """Generate 3 heatmaps from rows with trades>=min_trades and valid. suffix e.g. _trending_up for regime."""
    use = _results_for_heatmap(results, min_trades=min_trades, require_valid=require_valid)
    if not use:
        use = results  # fallback to all for empty
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []

    from pathlib import Path
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    saved = []

    def _plot_one(x_key: str, y_key: str, fix_key: str | None, fix_val: float | None, title: str, fname: str):
        x_vals, y_vals, grid = heatmap_data_2d(
            use, x_key, y_key, value_key="avg_R", fix_key=fix_key, fix_value=fix_val
        )
        if not x_vals or not y_vals:
            return
        fig, ax = plt.subplots()
        im = ax.imshow(grid, aspect="auto", origin="lower", cmap="RdYlGn", vmin=-0.5, vmax=0.5)
        ax.set_xticks(range(len(x_vals)))
        ax.set_yticks(range(len(y_vals)))
        ax.set_xticklabels([f"{x:.4f}" if x_key == "ema_distance_threshold" else f"{x:.2f}" for x in x_vals], rotation=45)
        ax.set_yticklabels([f"{y:.2f}" for y in y_vals])
        ax.set_xlabel(x_key)
        ax.set_ylabel(y_key)
        plt.colorbar(im, ax=ax, label="avg_R")
        ax.set_title(title)
        plt.tight_layout()
        path = out / (fname.replace(".png", "") + suffix + ".png")
        plt.savefig(path, dpi=100)
        plt.close()
        saved.append(str(path))

    if rsi_fix is not None:
        _plot_one("ema_distance_threshold", "volume_ratio_threshold", "rsi_threshold", rsi_fix,
                  f"ema_distance vs volume_ratio (rsi={rsi_fix})" + (f" {suffix}" if suffix else ""), "heatmap_ema_vs_volume")
        _plot_one("ema_distance_threshold", "rsi_threshold", "volume_ratio_threshold", vol_fix or 1.0,
                  f"ema_distance vs rsi (vol={vol_fix or 1.0})" + (f" {suffix}" if suffix else ""), "heatmap_ema_vs_rsi")
        _plot_one("volume_ratio_threshold", "rsi_threshold", "ema_distance_threshold", ema_fix or 0.0005,
                  f"volume_ratio vs rsi (ema={ema_fix or 0.0005})" + (f" {suffix}" if suffix else ""), "heatmap_volume_vs_rsi")
    else:
        rsi_vals = sorted({r["rsi_threshold"] for r in use})
        ema_vals = sorted({r["ema_distance_threshold"] for r in use})
        vol_vals = sorted({r["volume_ratio_threshold"] for r in use})
        rsi_fix = rsi_vals[len(rsi_vals) // 2] if rsi_vals else 50.0
        ema_fix = ema_vals[len(ema_vals) // 2] if ema_vals else 0.0006
        vol_fix = vol_vals[len(vol_vals) // 2] if vol_vals else 1.2
        _plot_one("ema_distance_threshold", "volume_ratio_threshold", "rsi_threshold", rsi_fix,
                  f"ema_distance vs volume_ratio (rsi={rsi_fix})" + (f" {suffix}" if suffix else ""), "heatmap_ema_vs_volume")
        _plot_one("ema_distance_threshold", "rsi_threshold", "volume_ratio_threshold", vol_fix,
                  f"ema_distance vs rsi (vol={vol_fix})" + (f" {suffix}" if suffix else ""), "heatmap_ema_vs_rsi")
        _plot_one("volume_ratio_threshold", "rsi_threshold", "ema_distance_threshold", ema_fix,
                  f"volume_ratio vs rsi (ema={ema_fix})" + (f" {suffix}" if suffix else ""), "heatmap_volume_vs_rsi")
    return saved
