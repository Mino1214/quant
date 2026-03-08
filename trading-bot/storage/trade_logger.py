"""
Log closed trades and blocked candidates to MySQL via repositories.
"""
import logging
from typing import Optional

from core.models import BlockedCandidateLog, TradeRecord
from storage.database import SessionLocal, init_db
from storage.repositories import create_blocked_candidate, create_trade

logger = logging.getLogger(__name__)


def log_trade(trade: TradeRecord) -> Optional[int]:
    """Persist trade to DB. Returns record id or None on error."""
    try:
        init_db()
        db = SessionLocal()
        try:
            row = create_trade(db, trade)
            logger.info(
                "Trade logged: id=%s %s %s pnl=%.2f approval_score=%s",
                row.id, trade.symbol, trade.side.value, trade.pnl,
                getattr(trade, "approval_score", 0),
            )
            return row.id
        finally:
            db.close()
    except Exception as e:
        logger.exception("Failed to log trade: %s", e)
        return None


def log_blocked_candidate(log: BlockedCandidateLog) -> Optional[int]:
    """Persist blocked candidate to DB. Returns record id or None on error."""
    try:
        init_db()
        db = SessionLocal()
        try:
            row = create_blocked_candidate(db, log)
            logger.info(
                "Blocked candidate logged: id=%s %s %s score=%s %s",
                row.id, log.symbol, log.direction.value, log.total_score, log.blocked_reason,
            )
            return row.id
        finally:
            db.close()
    except Exception as e:
        logger.exception("Failed to log blocked candidate: %s", e)
        return None
