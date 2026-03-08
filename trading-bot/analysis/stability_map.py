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


def _filter_by_thresholds(
    rows: List[dict],
    ema_t: float,
    vol_t: float,
    rsi_t: float,
) -> List[dict]:
    """Keep rows that pass virtual thresholds. Long: rsi >= rsi_t; Short: rsi <= 100 - rsi_t."""
    filtered = []
    for r in rows:
        try:
            ema_d = float(r.get("ema_distance") or r.get("ema_distance", 0) or 0)
            vol_r = float(r.get("volume_ratio") or 0)
            rsi = float(r.get("rsi") or r.get("rsi_5m") or 50)
        except (TypeError, ValueError):
            continue
        if ema_d < ema_t or vol_r < vol_t:
            continue
        side = (r.get("side") or r.get("trend_direction") or "long").lower()
        if "long" in side:
            if rsi < rsi_t:
                continue
        else:
            if rsi > (100 - rsi_t):
                continue
        filtered.append(r)
    return filtered


def metrics_for_rows(rows: List[dict], r_key: str = "R_return") -> dict:
    """Compute trades, winrate, avg_R, profit_factor, max_drawdown from rows with R."""
    r_vals = _r_values(rows, r_key=r_key)
    if not r_vals:
        return {"trades": 0, "winrate": 0.0, "avg_R": 0.0, "profit_factor": 0.0, "max_drawdown": 0.0}
    n = len(r_vals)
    wins = [x for x in r_vals if x > 0]
    losses = [x for x in r_vals if x <= 0]
    winrate = (len(wins) / n * 100) if n else 0.0
    avg_R = sum(r_vals) / n
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    if profit_factor != float("inf") and profit_factor > 100:
        profit_factor = 100.0
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
) -> List[dict]:
    """Run full grid; return list of {ema_distance_threshold, volume_ratio_threshold, rsi_threshold, trades, winrate, avg_R, profit_factor, max_drawdown}."""
    results = []
    for ema_t in ema_values:
        for vol_t in volume_ratio_values:
            for rsi_t in rsi_values:
                filtered = _filter_by_thresholds(rows, ema_t, vol_t, rsi_t)
                m = metrics_for_rows(filtered, r_key=r_key)
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


def plot_heatmaps(
    results: List[dict],
    output_dir: str,
    rsi_fix: Optional[float] = None,
    ema_fix: Optional[float] = None,
    vol_fix: Optional[float] = None,
) -> List[str]:
    """Generate 3 heatmaps; return list of saved file paths."""
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
            results, x_key, y_key, value_key="avg_R", fix_key=fix_key, fix_value=fix_val
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
        path = out / fname
        plt.savefig(path, dpi=100)
        plt.close()
        saved.append(str(path))

    if rsi_fix is not None:
        _plot_one("ema_distance_threshold", "volume_ratio_threshold", "rsi_threshold", rsi_fix,
                  f"ema_distance vs volume_ratio (rsi={rsi_fix})", "heatmap_ema_vs_volume.png")
        _plot_one("ema_distance_threshold", "rsi_threshold", "volume_ratio_threshold", vol_fix or 1.0,
                  f"ema_distance vs rsi (vol={vol_fix or 1.0})", "heatmap_ema_vs_rsi.png")
        _plot_one("volume_ratio_threshold", "rsi_threshold", "ema_distance_threshold", ema_fix or 0.0005,
                  f"volume_ratio vs rsi (ema={ema_fix or 0.0005})", "heatmap_volume_vs_rsi.png")
    else:
        # Use first value of third param as fix
        rsi_vals = sorted({r["rsi_threshold"] for r in results})
        ema_vals = sorted({r["ema_distance_threshold"] for r in results})
        vol_vals = sorted({r["volume_ratio_threshold"] for r in results})
        rsi_fix = rsi_vals[len(rsi_vals) // 2] if rsi_vals else 50.0
        ema_fix = ema_vals[len(ema_vals) // 2] if ema_vals else 0.0006
        vol_fix = vol_vals[len(vol_vals) // 2] if vol_vals else 1.2
        _plot_one("ema_distance_threshold", "volume_ratio_threshold", "rsi_threshold", rsi_fix,
                  f"ema_distance vs volume_ratio (rsi={rsi_fix})", "heatmap_ema_vs_volume.png")
        _plot_one("ema_distance_threshold", "rsi_threshold", "volume_ratio_threshold", vol_fix,
                  f"ema_distance vs rsi (vol={vol_fix})", "heatmap_ema_vs_rsi.png")
        _plot_one("volume_ratio_threshold", "rsi_threshold", "ema_distance_threshold", ema_fix,
                  f"volume_ratio vs rsi (ema={ema_fix})", "heatmap_volume_vs_rsi.png")
    return saved
