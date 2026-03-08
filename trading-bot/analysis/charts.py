"""
Signal Distribution Analysis: generate charts (R histogram, score vs R, feature bins, regime, holding time).
"""
import logging
from pathlib import Path
from typing import List

from analysis.distributions import (  # noqa: E402
    feature_impact_ema_distance,
    feature_impact_volume_ratio,
    holding_time_impact,
    r_distribution,
    regime_performance,
    score_vs_outcome,
    time_of_day_impact,
)

logger = logging.getLogger(__name__)


def _ensure_matplotlib():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        return plt
    except ImportError:
        logger.warning("matplotlib not installed; charts will be skipped. pip install matplotlib")
        return None


def plot_r_distribution(rows: List[dict], output_path: Path) -> bool:
    """R_return histogram. Returns True if saved."""
    plt = _ensure_matplotlib()
    if plt is None:
        return False
    bins, counts = r_distribution(rows)
    if not bins or not counts:
        return False
    # use bin centers for bar positions
    centers = [(bins[i] + bins[i + 1]) / 2 for i in range(len(bins) - 1)]
    widths = [bins[i + 1] - bins[i] for i in range(len(bins) - 1)]
    fig, ax = plt.subplots()
    ax.bar(centers, counts, width=[w * 0.9 for w in widths], align="center", edgecolor="gray")
    ax.set_xlabel("R return")
    ax.set_ylabel("Count")
    ax.set_title("R Distribution (executed trades)")
    fig.tight_layout()
    fig.savefig(output_path, dpi=100)
    plt.close(fig)
    return True


def plot_score_vs_r(rows: List[dict], output_path: Path) -> bool:
    """Approval score vs avg_R and winrate (twin axis)."""
    plt = _ensure_matplotlib()
    if plt is None:
        return False
    data = score_vs_outcome(rows)
    if not data:
        return False
    scores = [d["approval_score"] for d in data]
    avg_r = [d["avg_R"] for d in data]
    winrate = [d["winrate"] for d in data]
    fig, ax1 = plt.subplots()
    ax1.bar([s - 0.2 for s in scores], avg_r, width=0.4, label="avg_R", color="steelblue")
    ax1.set_xlabel("Approval score")
    ax1.set_ylabel("avg R")
    ax2 = ax1.twinx()
    ax2.plot(scores, winrate, "o-", color="darkgreen", label="winrate %")
    ax2.set_ylabel("Winrate %")
    ax1.legend(loc="upper left")
    ax2.legend(loc="upper right")
    ax1.set_title("Signal Quality vs Score")
    fig.tight_layout()
    fig.savefig(output_path, dpi=100)
    plt.close(fig)
    return True


def plot_feature_bins(rows: List[dict], output_path: Path) -> bool:
    """EMA distance and volume ratio bins vs avg_R (two subplots)."""
    plt = _ensure_matplotlib()
    if plt is None:
        return False
    ema_data = feature_impact_ema_distance(rows)
    vol_data = feature_impact_volume_ratio(rows)
    if not ema_data and not vol_data:
        return False
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    if ema_data:
        labels = [d["ema_distance_range"] for d in ema_data]
        avg_r = [d["avg_R"] for d in ema_data]
        axes[0].bar(labels, avg_r, color="steelblue", edgecolor="gray")
        axes[0].set_xlabel("EMA distance range")
        axes[0].set_ylabel("avg R")
        axes[0].set_title("Feature: EMA distance")
        axes[0].tick_params(axis="x", rotation=15)
    if vol_data:
        labels = [d["volume_ratio"] for d in vol_data]
        avg_r = [d["avg_R"] for d in vol_data]
        axes[1].bar(labels, avg_r, color="coral", edgecolor="gray")
        axes[1].set_xlabel("Volume ratio range")
        axes[1].set_ylabel("avg R")
        axes[1].set_title("Feature: Volume ratio")
        axes[1].tick_params(axis="x", rotation=15)
    fig.suptitle("Feature Impact on avg R")
    fig.tight_layout()
    fig.savefig(output_path, dpi=100)
    plt.close(fig)
    return True


def plot_regime_performance(rows: List[dict], output_path: Path) -> bool:
    """Regime vs avg_R bar chart."""
    plt = _ensure_matplotlib()
    if plt is None:
        return False
    data = regime_performance(rows)
    if not data:
        return False
    labels = [d["regime"] for d in data]
    avg_r = [d["avg_R"] for d in data]
    fig, ax = plt.subplots()
    ax.bar(labels, avg_r, color="steelblue", edgecolor="gray")
    ax.set_xlabel("Regime")
    ax.set_ylabel("avg R")
    ax.set_title("Regime Performance")
    ax.axhline(y=0, color="gray", linestyle="-", linewidth=0.5)
    ax.tick_params(axis="x", rotation=20)
    fig.tight_layout()
    fig.savefig(output_path, dpi=100)
    plt.close(fig)
    return True


def plot_holding_time(rows: List[dict], output_path: Path) -> bool:
    """Holding time bins vs avg_R."""
    plt = _ensure_matplotlib()
    if plt is None:
        return False
    data = holding_time_impact(rows)
    if not data:
        return False
    labels = [d["holding_bars"] for d in data]
    avg_r = [d["avg_R"] for d in data]
    fig, ax = plt.subplots()
    ax.bar(labels, avg_r, color="seagreen", edgecolor="gray")
    ax.set_xlabel("Holding time (1m bars)")
    ax.set_ylabel("avg R")
    ax.set_title("Holding Time vs Profit")
    ax.axhline(y=0, color="gray", linestyle="-", linewidth=0.5)
    fig.tight_layout()
    fig.savefig(output_path, dpi=100)
    plt.close(fig)
    return True


def plot_time_of_day(rows: List[dict], output_path: Path) -> bool:
    """UTC hour slot vs avg_R."""
    plt = _ensure_matplotlib()
    if plt is None:
        return False
    data = time_of_day_impact(rows)
    if not data:
        return False
    labels = [d["hour"] for d in data]
    avg_r = [d["avg_R"] for d in data]
    fig, ax = plt.subplots()
    ax.bar(labels, avg_r, color="mediumpurple", edgecolor="gray")
    ax.set_xlabel("UTC hour")
    ax.set_ylabel("avg R")
    ax.set_title("Time of Day (UTC) vs avg R")
    ax.axhline(y=0, color="gray", linestyle="-", linewidth=0.5)
    fig.tight_layout()
    fig.savefig(output_path, dpi=100)
    plt.close(fig)
    return True


def generate_all_charts(rows: List[dict], output_dir: Path) -> None:
    """Generate all 5 (plus time-of-day) charts into output_dir."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    plot_r_distribution(rows, output_dir / "r_distribution.png")
    plot_score_vs_r(rows, output_dir / "approval_score_vs_r.png")
    plot_feature_bins(rows, output_dir / "feature_impact.png")
    plot_regime_performance(rows, output_dir / "regime_performance.png")
    plot_holding_time(rows, output_dir / "holding_time_vs_profit.png")
    plot_time_of_day(rows, output_dir / "time_of_day.png")
    logger.info("Charts written to %s", output_dir)
