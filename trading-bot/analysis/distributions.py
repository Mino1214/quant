"""
Signal Distribution Analysis: R distribution, score vs outcome, feature impact, regime, holding time, time-of-day.
Input: list of row dicts (from CSV or CandidateSignalRecord converted to dict).
"""
from collections import defaultdict
from datetime import datetime
from typing import Any, List, Optional, Tuple


def _executed_rows(rows: List[dict]) -> List[dict]:
    """Filter rows with trade_outcome=='executed' and R_return not null/empty."""
    out = []
    for r in rows:
        if r.get("trade_outcome") != "executed":
            continue
        rr = r.get("R_return")
        if rr is None or rr == "":
            continue
        try:
            r["_R"] = float(rr)
        except (TypeError, ValueError):
            continue
        out.append(r)
    return out


def r_distribution(rows: List[dict], bins: Optional[List[float]] = None) -> Tuple[List[float], List[int]]:
    """
    R_return histogram data. Returns (bin_edges, counts). counts[i] = values in [bins[i], bins[i+1]).
    Default bins: -1.5 to 5R with step 0.5.
    """
    executed = _executed_rows(rows)
    if not executed:
        return [], []
    values = [r["_R"] for r in executed]
    if bins is None:
        bins = [x * 0.5 for x in range(-3, 11)]  # -1.5 to 5.0
    n_bins = len(bins) - 1 if len(bins) > 1 else 0
    counts = [0] * n_bins
    for v in values:
        for i in range(n_bins):
            if bins[i] <= v < bins[i + 1]:
                counts[i] += 1
                break
        else:
            if n_bins > 0 and v >= bins[-1]:
                counts[-1] += 1
    return bins, counts


def score_vs_outcome(rows: List[dict]) -> List[dict]:
    """approval_score별 trades, winrate, avg_R. Executed only."""
    executed = _executed_rows(rows)
    if not executed:
        return []
    by_score: dict = defaultdict(list)
    for r in executed:
        by_score[r.get("approval_score", 0)].append(r["_R"])
    result = []
    for score in sorted(by_score.keys()):
        vals = by_score[score]
        n = len(vals)
        wins = sum(1 for v in vals if v > 0)
        winrate = (wins / n * 100) if n else 0
        avg_r = sum(vals) / n if n else 0
        result.append({"approval_score": score, "trades": n, "winrate": winrate, "avg_R": avg_r})
    return result


def _bin_value(v: float, boundaries: List[Tuple[float, float, str]]) -> str:
    for lo, hi, label in boundaries:
        if lo <= v < hi:
            return label
    return boundaries[-1][2] if boundaries else ""


def feature_impact_ema_distance(rows: List[dict]) -> List[dict]:
    """ema_distance 구간별 trades, avg_R. Executed only."""
    executed = _executed_rows(rows)
    if not executed:
        return []
    boundaries = [(0, 0.0003, "<0.0003"), (0.0003, 0.001, "0.0003-0.001"), (0.001, 10.0, ">0.001")]
    by_bin: dict = defaultdict(list)
    for r in executed:
        try:
            ed = float(r.get("ema_distance", 0) or 0)
        except (TypeError, ValueError):
            ed = 0
        label = _bin_value(ed, boundaries)
        by_bin[label].append(r["_R"])
    result = []
    for label in [b[2] for b in boundaries]:
        if label not in by_bin:
            continue
        vals = by_bin[label]
        n = len(vals)
        result.append({"ema_distance_range": label, "trades": n, "avg_R": sum(vals) / n})
    return result


def feature_impact_volume_ratio(rows: List[dict]) -> List[dict]:
    """volume_ratio 구간별 trades, avg_R. Executed only."""
    executed = _executed_rows(rows)
    if not executed:
        return []
    boundaries = [(0, 1.0, "<1.0"), (1.0, 1.5, "1.0-1.5"), (1.5, 100.0, ">1.5")]
    by_bin: dict = defaultdict(list)
    for r in executed:
        try:
            vr = float(r.get("volume_ratio", 0) or 0)
        except (TypeError, ValueError):
            vr = 0
        label = _bin_value(vr, boundaries)
        by_bin[label].append(r["_R"])
    result = []
    for label in [b[2] for b in boundaries]:
        if label not in by_bin:
            continue
        vals = by_bin[label]
        n = len(vals)
        result.append({"volume_ratio": label, "trades": n, "avg_R": sum(vals) / n})
    return result


def regime_performance(rows: List[dict]) -> List[dict]:
    """regime별 trades, winrate, avg_R. Executed only."""
    executed = _executed_rows(rows)
    if not executed:
        return []
    by_regime: dict = defaultdict(list)
    for r in executed:
        reg = r.get("regime") or "UNKNOWN"
        by_regime[reg].append(r["_R"])
    result = []
    for reg, vals in sorted(by_regime.items()):
        n = len(vals)
        wins = sum(1 for v in vals if v > 0)
        result.append({
            "regime": reg,
            "trades": n,
            "winrate": (wins / n * 100) if n else 0,
            "avg_R": sum(vals) / n if n else 0,
        })
    return result


def holding_time_impact(rows: List[dict]) -> List[dict]:
    """holding_time_bars 구간별 avg_R. Executed only."""
    executed = _executed_rows(rows)
    if not executed:
        return []
    boundaries = [(0, 5, "1-5"), (5, 10, "5-10"), (10, 30, "10-30"), (30, 10**6, "30+")]
    by_bin: dict = defaultdict(list)
    for r in executed:
        try:
            ht = int(r.get("holding_time_bars") or 0)
        except (TypeError, ValueError):
            ht = 0
        label = _bin_value(ht, boundaries)
        by_bin[label].append(r["_R"])
    result = []
    for label in [b[2] for b in boundaries]:
        if label not in by_bin:
            continue
        vals = by_bin[label]
        result.append({"holding_bars": label, "avg_R": sum(vals) / len(vals)})
    return result


def time_of_day_impact(rows: List[dict]) -> List[dict]:
    """UTC hour 구간별 trades, avg_R. Executed only."""
    executed = _executed_rows(rows)
    if not executed:
        return []
    hour_ranges = [(0, 4, "00-04"), (4, 8, "04-08"), (8, 12, "08-12"), (12, 16, "12-16"), (16, 20, "16-20"), (20, 24, "20-24")]
    by_slot: dict = defaultdict(list)
    for r in executed:
        ts = r.get("timestamp")
        if isinstance(ts, str):
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                dt = None
        else:
            dt = ts
        hour = dt.hour if dt else 0
        label = "00-04"
        for lo, hi, L in hour_ranges:
            if lo <= hour < hi:
                label = L
                break
        by_slot[label].append(r["_R"])
    result = []
    for label in [x[2] for x in hour_ranges]:
        if label not in by_slot:
            continue
        vals = by_slot[label]
        result.append({"hour": label, "trades": len(vals), "avg_R": sum(vals) / len(vals)})
    return result
