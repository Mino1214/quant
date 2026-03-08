"""
Log candidate signals to DB for continuous signal dataset (Phase 1).
Outcomes are filled later by build_signal_dataset or scheduled outcome job.
"""
import logging
from typing import Optional

from core.models import CandidateSignalRecord, SignalOutcome
from storage.database import SessionLocal, init_db
from storage.repositories import create_candidate_signal, create_signal_outcome

logger = logging.getLogger(__name__)


def log_candidate_signal(record: CandidateSignalRecord) -> Optional[int]:
    """Persist candidate signal to candidate_signals table. Returns id or None on error."""
    try:
        init_db()
        db = SessionLocal()
        try:
            row = create_candidate_signal(db, record)
            logger.debug(
                "Candidate signal logged: id=%s %s time=%s outcome=%s",
                row.id, record.symbol, record.timestamp, record.trade_outcome,
            )
            return row.id
        finally:
            db.close()
    except Exception as e:
        logger.exception("Failed to log candidate signal: %s", e)
        return None


def save_signal_outcome(outcome: SignalOutcome) -> Optional[int]:
    """Persist signal outcome to signal_outcomes table. Returns id or None on error."""
    try:
        init_db()
        db = SessionLocal()
        try:
            row = create_signal_outcome(db, outcome)
            logger.debug("Signal outcome saved: id=%s candidate_signal_id=%s", row.id, outcome.candidate_signal_id)
            return row.id
        finally:
            db.close()
    except Exception as e:
        logger.exception("Failed to save signal outcome: %s", e)
        return None
