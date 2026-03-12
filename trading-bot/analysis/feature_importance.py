"""
Feature importance for signal dataset: univariate bin impact and model-based importance.

Exports feature_importance.csv and optional feature_impact_heatmaps/.
"""
from typing import List, Optional, Any
import csv
import math

import numpy as np

# Default target and feature columns
TARGET_KEY = "future_r_30"
FALLBACK_TARGET = "R_return"
R_CAP = 20.0

FEATURE_KEYS = [
    "ema_distance", "volume_ratio", "rsi_5m", "rsi", "momentum_ratio",
    "pullback_depth_pct", "breakout_confirmation", "lower_wick_ratio", "upper_wick_ratio",
    "ema20_gt_ema50", "ema50_slope", "trend_bias",
    "body_to_range_ratio", "close_near_high", "close_near_low",
    "dist_from_20ema_pct", "dist_from_recent_high_pct", "close_in_recent_range",
]


def _get_float(r: dict, key: str, default: float = 0.0) -> float:
    v = r.get(key)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _cap_r(val: float, cap: float = R_CAP) -> float:
    if val != val or math.isnan(val):
        return 0.0
    return max(-cap, min(cap, val))


def univariate_bin_impact(
    rows: List[dict],
    feature_name: str,
    target_key: str = TARGET_KEY,
    n_bins: int = 5,
    r_cap: float = R_CAP,
) -> dict:
    """
    Bin rows by feature value (quantiles), compute avg_R and winrate per bin.
    Returns dict with feature_name, bin_edges, avg_R_by_bin, winrate_by_bin, importance_score.
    """
    vals = []
    for r in rows:
        x = _get_float(r, feature_name, float("nan"))
        if math.isnan(x) and feature_name in ("ema20_gt_ema50", "breakout_confirmation"):
            x = 0.0
        if math.isnan(x):
            continue
        y = r.get(target_key) or r.get(FALLBACK_TARGET)
        if y is None or y == "":
            continue
        try:
            y = _cap_r(float(y), r_cap)
        except (TypeError, ValueError):
            continue
        vals.append((x, y))
    if len(vals) < n_bins * 2:
        return {
            "feature_name": feature_name,
            "avg_R_by_bin": "",
            "winrate_by_bin": "",
            "importance_score": 0.0,
            "n_samples": len(vals),
        }
    xs = np.array([v[0] for v in vals])
    ys = np.array([v[1] for v in vals])
    try:
        quantiles = np.percentile(xs, np.linspace(0, 100, n_bins + 1))
        quantiles[-1] += 1e-9
        bin_avg_r = []
        bin_winrate = []
        for i in range(n_bins):
            mask = (xs >= quantiles[i]) & (xs < quantiles[i + 1])
            if i == n_bins - 1:
                mask = (xs >= quantiles[i]) & (xs <= quantiles[i + 1])
            sub = ys[mask]
            if len(sub):
                bin_avg_r.append(float(np.mean(sub)))
                bin_winrate.append(100.0 * np.sum(sub > 0) / len(sub))
            else:
                bin_avg_r.append(0.0)
                bin_winrate.append(0.0)
        avg_r_arr = np.array(bin_avg_r)
        importance = float(np.std(avg_r_arr)) if len(avg_r_arr) > 1 else 0.0
        return {
            "feature_name": feature_name,
            "avg_R_by_bin": ",".join(f"{x:.4f}" for x in bin_avg_r),
            "winrate_by_bin": ",".join(f"{x:.1f}" for x in bin_winrate),
            "importance_score": round(importance, 6),
            "n_samples": len(vals),
        }
    except Exception:
        return {
            "feature_name": feature_name,
            "avg_R_by_bin": "",
            "winrate_by_bin": "",
            "importance_score": 0.0,
            "n_samples": len(vals),
        }


def model_importance(
    rows: List[dict],
    feature_cols: List[str],
    target_key: str = TARGET_KEY,
) -> Optional[dict]:
    """
    Fit RandomForestRegressor on features -> target, return feature_importances_ as dict.
    """
    try:
        from sklearn.ensemble import RandomForestRegressor
    except ImportError:
        return None
    X = []
    y = []
    for r in rows:
        yy = r.get(target_key) or r.get(FALLBACK_TARGET)
        if yy is None or yy == "":
            continue
        try:
            yy = _cap_r(float(yy), R_CAP)
        except (TypeError, ValueError):
            continue
        row_x = []
        skip = False
        for col in feature_cols:
            v = _get_float(r, col, float("nan"))
            if math.isnan(v):
                v = 0.0
            row_x.append(v)
        X.append(row_x)
        y.append(yy)
    if len(X) < 50:
        return None
    X = np.array(X)
    y = np.array(y)
    model = RandomForestRegressor(n_estimators=50, max_depth=6, random_state=42)
    model.fit(X, y)
    return {feature_cols[i]: float(model.feature_importances_[i]) for i in range(len(feature_cols))}


def run(
    rows: List[dict],
    target_key: str = TARGET_KEY,
    n_bins: int = 5,
    feature_keys: Optional[List[str]] = None,
    use_model: bool = True,
) -> List[dict]:
    """
    Run univariate bin impact for each feature. Optionally add model importance.
    Returns list of dicts for feature_importance.csv.
    """
    if feature_keys is None:
        feature_keys = [k for k in FEATURE_KEYS if any(r.get(k) is not None for r in rows[:100])]
    if not feature_keys:
        feature_keys = FEATURE_KEYS
    results = []
    for f in feature_keys:
        u = univariate_bin_impact(rows, f, target_key=target_key, n_bins=n_bins)
        results.append(u)
    if use_model:
        model_imp = model_importance(rows, feature_keys, target_key=target_key)
        if model_imp:
            for r in results:
                r["model_importance"] = model_imp.get(r["feature_name"], 0.0)
        else:
            for r in results:
                r["model_importance"] = ""
    else:
        for r in results:
            r["model_importance"] = ""
    return results


def plot_impact_heatmap(
    rows: List[dict],
    feature_x: str,
    feature_y: str,
    target_key: str = TARGET_KEY,
    n_bins: int = 5,
    output_path: Optional[str] = None,
) -> bool:
    """2D heatmap: feature_x x feature_y -> mean target (avg_R)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    data = []
    for r in rows:
        x = _get_float(r, feature_x, float("nan"))
        y = _get_float(r, feature_y, float("nan"))
        t = r.get(target_key) or r.get(FALLBACK_TARGET)
        if t is None or t == "" or (math.isnan(x) and math.isnan(y)):
            continue
        try:
            t = _cap_r(float(t), R_CAP)
        except (TypeError, ValueError):
            continue
        if math.isnan(x):
            x = 0.0
        if math.isnan(y):
            y = 0.0
        data.append((x, y, t))
    if len(data) < n_bins * n_bins:
        return False
    xs = np.array([d[0] for d in data])
    ys = np.array([d[1] for d in data])
    ts = np.array([d[2] for d in data])
    try:
        x_edges = np.percentile(xs, np.linspace(0, 100, n_bins + 1))
        y_edges = np.percentile(ys, np.linspace(0, 100, n_bins + 1))
        x_edges[-1] += 1e-9
        y_edges[-1] += 1e-9
        grid = np.full((n_bins, n_bins), np.nan)
        for i in range(n_bins):
            for j in range(n_bins):
                mx = (xs >= x_edges[i]) & (xs < x_edges[i + 1])
                my = (ys >= y_edges[j]) & (ys < y_edges[j + 1])
                mask = mx & my
                if np.any(mask):
                    grid[j, i] = np.mean(ts[mask])
        fig, ax = plt.subplots()
        im = ax.imshow(grid, aspect="auto", origin="lower", cmap="RdYlGn", vmin=-0.3, vmax=0.3)
        ax.set_xlabel(feature_x)
        ax.set_ylabel(feature_y)
        ax.set_title(f"Avg R: {feature_x} x {feature_y}")
        plt.colorbar(im, ax=ax, label="avg R")
        plt.tight_layout()
        if output_path:
            from pathlib import Path
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(output_path, dpi=100)
        plt.close()
        return True
    except Exception:
        return False
