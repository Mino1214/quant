"""
Baseline metrics for experiment comparison.

Load baseline_metrics.json produced by run_baseline so any experiment
can compare total_trades, winrate, avg_R, profit_factor, max_drawdown, sharpe.
"""
import json
from pathlib import Path
from typing import Optional


def get_baseline_metrics_path(output_dir: Optional[Path] = None) -> Path:
    root = Path(__file__).resolve().parent.parent
    if output_dir is None:
        output_dir = root / "analysis" / "output"
    return Path(output_dir) / "baseline_metrics.json"


def load_baseline_metrics(output_dir: Optional[Path] = None) -> Optional[dict]:
    """
    Load baseline metrics from analysis/output/baseline_metrics.json.
    Returns dict with total_trades, winrate, avg_R, profit_factor, max_drawdown, sharpe, etc.
    """
    path = get_baseline_metrics_path(output_dir)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def compare_to_baseline(experiment_metrics: dict, output_dir: Optional[Path] = None) -> dict:
    """
    Compare experiment metrics to baseline. Returns dict with deltas and baseline values.
    experiment_metrics: dict with keys total_trades, winrate, avg_R, profit_factor, max_drawdown, sharpe
    """
    baseline = load_baseline_metrics(output_dir)
    if not baseline:
        return {"baseline": None, "deltas": None}
    keys = ["total_trades", "winrate", "avg_R", "profit_factor", "max_drawdown", "sharpe"]
    deltas = {}
    for k in keys:
        a = baseline.get(k)
        b = experiment_metrics.get(k)
        if a is not None and b is not None:
            if k == "max_drawdown":
                # lower is better; delta = experiment - baseline (negative = improvement)
                deltas[k] = b - a
            else:
                deltas[k] = b - a
    return {"baseline": baseline, "deltas": deltas}
