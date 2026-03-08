"""
Export CandidateSignalRecord list to CSV for Signal Distribution Analysis.
"""
import csv
import logging
from pathlib import Path
from typing import List

from core.models import CandidateSignalRecord

logger = logging.getLogger(__name__)

CSV_COLUMNS = [
    "timestamp",
    "entry_price",
    "regime",
    "trend_direction",
    "approval_score",
    "ema_distance",
    "volume_ratio",
    "rsi_5m",
    "trade_outcome",
    "blocked_reason",
    "R_return",
    "holding_time_bars",
    "symbol",
]


def export_candidate_signals(records: List[CandidateSignalRecord], path: Path) -> None:
    """
    Write candidate signals to CSV. Flattens feature_values into ema_distance, volume_ratio, rsi_5m.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in records:
            row = {
                "timestamp": r.timestamp.isoformat() if r.timestamp else "",
                "entry_price": r.entry_price,
                "regime": r.regime,
                "trend_direction": r.trend_direction.value if hasattr(r.trend_direction, "value") else str(r.trend_direction),
                "approval_score": r.approval_score,
                "ema_distance": r.feature_values.get("ema_distance", 0.0),
                "volume_ratio": r.feature_values.get("volume_ratio", 0.0),
                "rsi_5m": r.feature_values.get("rsi_5m", 0.0),
                "trade_outcome": r.trade_outcome,
                "blocked_reason": r.blocked_reason or "",
                "R_return": r.R_return if r.R_return is not None else "",
                "holding_time_bars": r.holding_time_bars if r.holding_time_bars is not None else "",
                "symbol": r.symbol,
            }
            w.writerow(row)
    logger.info("Exported %d candidate signals to %s", len(records), path)
