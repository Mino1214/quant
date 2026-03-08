"""
MySQL connection via SQLAlchemy. DATABASE_URL from environment.
"""
import logging
import os
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from storage.models import Base
from config.loader import get_database_url

logger = logging.getLogger(__name__)

_url = os.environ.get("DATABASE_URL") or get_database_url()
engine = create_engine(
    _url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _migrate_trade_records() -> None:
    """Add approval_score, blocked_reason to trade_records if missing (기존 DB 호환)."""
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE trade_records ADD COLUMN approval_score INT NULL DEFAULT 0"))
            conn.commit()
        except Exception as e:
            if "Duplicate column" in str(e) or "1060" in str(e):
                pass
            else:
                logger.warning("Migration approval_score: %s", e)
        try:
            conn.execute(text("ALTER TABLE trade_records ADD COLUMN blocked_reason VARCHAR(128) NULL"))
            conn.commit()
        except Exception as e:
            if "Duplicate column" in str(e) or "1060" in str(e):
                pass
            else:
                logger.warning("Migration blocked_reason: %s", e)
        try:
            conn.execute(text("ALTER TABLE trade_records ADD COLUMN mode VARCHAR(16) NULL DEFAULT 'paper'"))
            conn.commit()
        except Exception as e:
            if "Duplicate column" in str(e) or "1060" in str(e):
                pass
            else:
                logger.warning("Migration mode: %s", e)


def _migrate_candidate_signals() -> None:
    """Add missing columns to candidate_signals to match CandidateSignalModel (기존 DB 호환)."""
    columns = [
        ("`time`", "DATETIME NULL"),
        ("close", "DECIMAL(20,8) NULL"),
        ("side", "VARCHAR(8) NULL"),
        ("regime", "VARCHAR(32) NULL"),
        ("trend_direction", "VARCHAR(8) NULL"),
        ("approval_score", "INT NULL"),
        ("ema_distance", "DOUBLE NULL"),
        ("volume_ratio", "DOUBLE NULL"),
        ("rsi", "DOUBLE NULL"),
        ("trade_outcome", "VARCHAR(16) NULL"),
        ("blocked_reason", "VARCHAR(128) NULL"),
        ("created_at", "DATETIME NULL"),
        ("feature_values_ext", "TEXT NULL"),
    ]
    with engine.connect() as conn:
        for col_name, col_def in columns:
            try:
                conn.execute(text("ALTER TABLE candidate_signals ADD COLUMN %s %s" % (col_name, col_def)))
                conn.commit()
                logger.info("Migration candidate_signals: added column %s", col_name.strip("`"))
            except Exception as e:
                if "Duplicate column" in str(e) or "1060" in str(e):
                    pass
                else:
                    logger.warning("Migration candidate_signals %s: %s", col_name, e)
        # 기존 테이블에 timestamp NOT NULL 컬럼이 있으면 한 번만 NULL 허용 (로그 중복 방지)
        try:
            r = conn.execute(text(
                "SELECT IS_NULLABLE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'candidate_signals' AND COLUMN_NAME = 'timestamp'"
            ))
            row = r.fetchone()
            if row and row[0] == "NO":
                conn.execute(text("ALTER TABLE candidate_signals MODIFY COLUMN timestamp DATETIME NULL"))
                conn.commit()
                logger.info("Migration candidate_signals: timestamp nullable")
        except Exception as e:
            if "1054" in str(e) or "Unknown column" in str(e):
                pass  # timestamp 컬럼 없음
            else:
                logger.warning("Migration candidate_signals timestamp: %s", e)


def _migrate_signal_outcomes() -> None:
    """Add missing columns to signal_outcomes to match SignalOutcomeModel (기존 DB 호환)."""
    columns = [
        ("candidate_signal_id", "INT NULL"),
        ("future_r_5", "DOUBLE NULL"),
        ("future_r_10", "DOUBLE NULL"),
        ("future_r_20", "DOUBLE NULL"),
        ("future_r_30", "DOUBLE NULL"),
        ("tp_hit_first", "TINYINT(1) NULL"),
        ("sl_hit_first", "TINYINT(1) NULL"),
        ("bars_to_outcome", "INT NULL"),
        ("computed_at", "DATETIME NULL"),
    ]
    with engine.connect() as conn:
        for col_name, col_def in columns:
            try:
                conn.execute(text("ALTER TABLE signal_outcomes ADD COLUMN %s %s" % (col_name, col_def)))
                conn.commit()
                logger.info("Migration signal_outcomes: added column %s", col_name)
            except Exception as e:
                if "Duplicate column" in str(e) or "1060" in str(e):
                    pass
                else:
                    logger.warning("Migration signal_outcomes %s: %s", col_name, e)


def init_db() -> None:
    """Create tables if they do not exist. Migrate trade_records, candidate_signals if needed."""
    Base.metadata.create_all(bind=engine)
    try:
        _migrate_trade_records()
    except Exception as e:
        logger.warning("Migration skip (table may not exist yet): %s", e)
    try:
        _migrate_candidate_signals()
    except Exception as e:
        logger.warning("Migration candidate_signals skip (table may not exist yet): %s", e)
    try:
        _migrate_signal_outcomes()
    except Exception as e:
        logger.warning("Migration signal_outcomes skip (table may not exist yet): %s", e)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
