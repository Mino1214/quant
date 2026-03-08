"""
SQLAlchemy ORM models for trade logging and signal dataset.
"""
import json
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class TradeRecordModel(Base):
    __tablename__ = "trade_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False, index=True)
    side = Column(String(8), nullable=False)  # long, short
    size = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    take_profit = Column(Float, nullable=False)
    pnl = Column(Float, nullable=False)
    rr = Column(Float, nullable=False)
    reason_entry = Column(String(64), nullable=True)
    reason_exit = Column(String(64), nullable=True)
    opened_at = Column(DateTime, nullable=False, index=True)
    closed_at = Column(DateTime, nullable=False, index=True)
    approval_score = Column(Integer, nullable=True, default=0)
    blocked_reason = Column(String(128), nullable=True)
    mode = Column(String(16), nullable=True, default="paper")  # paper | backtest | live


class BlockedCandidateModel(Base):
    __tablename__ = "blocked_candidates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False, index=True)
    side = Column(String(8), nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    total_score = Column(Integer, nullable=False)
    blocked_reason = Column(String(128), nullable=False)
    category_scores = Column(Text, nullable=True)  # JSON
    reason_entry = Column(String(64), nullable=True)


class CandidateSignalModel(Base):
    """Continuous signal dataset: snapshot at signal time (executed + blocked)."""
    __tablename__ = "candidate_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False, index=True)
    time = Column(DateTime, nullable=False, index=True)  # bar timestamp (주 사용 컬럼)
    timestamp = Column("timestamp", DateTime, nullable=True, index=True, quote=True)  # MySQL 예약어 → 백틱으로 저장
    close = Column(Float, nullable=False)
    side = Column(String(8), nullable=False)  # long, short
    regime = Column(String(32), nullable=True)
    trend_direction = Column(String(8), nullable=True)
    approval_score = Column(Integer, nullable=True)
    ema_distance = Column(Float, nullable=True)
    volume_ratio = Column(Float, nullable=True)
    rsi = Column(Float, nullable=True)  # 5m RSI
    trade_outcome = Column(String(16), nullable=False)  # executed, blocked
    blocked_reason = Column(String(128), nullable=True)
    created_at = Column(DateTime, nullable=True)
    feature_values_ext = Column(Text, nullable=True)  # JSON: full feature dict (multi-TF + cross-market) for ML


class SignalOutcomeModel(Base):
    """Outcome for one candidate signal: future R, tp/sl first, bars to outcome."""
    __tablename__ = "signal_outcomes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(Integer, nullable=True, index=True)  # legacy: DB에 NOT NULL FK 있으면 INSERT 시 candidate_signal_id와 동일 값 설정
    candidate_signal_id = Column(Integer, ForeignKey("candidate_signals.id"), nullable=False, index=True)
    future_r_5 = Column(Float, nullable=True)
    future_r_10 = Column(Float, nullable=True)
    future_r_20 = Column(Float, nullable=True)
    future_r_30 = Column(Float, nullable=True)
    tp_hit_first = Column(Boolean, nullable=True)
    sl_hit_first = Column(Boolean, nullable=True)
    bars_to_outcome = Column(Integer, nullable=True)
    computed_at = Column(DateTime, nullable=True)


class ParameterScanResultModel(Base):
    """Edge Stability Map: one row per parameter combination."""
    __tablename__ = "parameter_scan_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ema_distance_threshold = Column(Float, nullable=False)
    volume_ratio_threshold = Column(Float, nullable=False)
    rsi_threshold = Column(Float, nullable=False)
    trades = Column(Integer, nullable=False)
    winrate = Column(Float, nullable=True)
    avg_R = Column(Float, nullable=True)
    profit_factor = Column(Float, nullable=True)
    max_drawdown = Column(Float, nullable=True)
    scan_id = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, nullable=True)


class WalkForwardResultModel(Base):
    """Walk-forward validation: one row per train/test fold."""
    __tablename__ = "walk_forward_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    train_start = Column(DateTime, nullable=True)
    train_end = Column(DateTime, nullable=True)
    test_start = Column(DateTime, nullable=True)
    test_end = Column(DateTime, nullable=True)
    profit_factor = Column(Float, nullable=True)
    avg_R = Column(Float, nullable=True)
    drawdown = Column(Float, nullable=True)
    stability_score = Column(Float, nullable=True)
    strategy_name = Column(String(64), nullable=True, default="mtf_ema_pullback")
    created_at = Column(DateTime, nullable=True)


class MLModelVersionModel(Base):
    """ML model version history: one row per trained model for online learning deployment."""
    __tablename__ = "ml_models"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version_id = Column(String(64), nullable=False, index=True)  # e.g. timestamp or uuid
    train_start_time = Column(DateTime, nullable=True)
    train_end_time = Column(DateTime, nullable=True)
    accuracy = Column(Float, nullable=True)
    auc = Column(Float, nullable=True)
    expected_R_corr = Column(Float, nullable=True)
    model_path = Column(String(512), nullable=True)  # path to version dir or current
    created_at = Column(DateTime, nullable=True)
