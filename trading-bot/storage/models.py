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


class FeatureStore1mModel(Base):
    """Feature store on 1m grid: strategy-agnostic feature set for research."""

    __tablename__ = "feature_store_1m"

    symbol = Column(String(32), primary_key=True, index=True)
    timestamp = Column(DateTime, primary_key=True, index=True)
    # Feature versioning for reproducibility
    feature_version = Column(Integer, nullable=False, default=1, index=True)

    # Price / basic
    open = Column(Float, nullable=True)
    high = Column(Float, nullable=True)
    low = Column(Float, nullable=True)
    close = Column(Float, nullable=True)
    volume = Column(Float, nullable=True)
    quote_volume = Column(Float, nullable=True)
    trade_count = Column(Integer, nullable=True)
    taker_buy_volume = Column(Float, nullable=True)
    taker_buy_quote_volume = Column(Float, nullable=True)

    # Trend (EMA levels)
    ema20_1m = Column(Float, nullable=True)
    ema50_1m = Column(Float, nullable=True)
    ema200_1m = Column(Float, nullable=True)
    ema20_5m = Column(Float, nullable=True)
    ema50_5m = Column(Float, nullable=True)
    ema200_5m = Column(Float, nullable=True)
    ema20_15m = Column(Float, nullable=True)
    ema50_15m = Column(Float, nullable=True)
    ema200_15m = Column(Float, nullable=True)

    # Trend slopes
    ema20_slope_1m = Column(Float, nullable=True)
    ema50_slope_1m = Column(Float, nullable=True)
    ema200_slope_1m = Column(Float, nullable=True)
    ema20_slope_5m = Column(Float, nullable=True)
    ema50_slope_5m = Column(Float, nullable=True)
    ema200_slope_5m = Column(Float, nullable=True)
    ema20_slope_15m = Column(Float, nullable=True)
    ema50_slope_15m = Column(Float, nullable=True)
    ema200_slope_15m = Column(Float, nullable=True)

    # EMA distance / spread
    dist_from_ema20_pct = Column(Float, nullable=True)
    dist_from_ema50_pct = Column(Float, nullable=True)
    dist_from_ema200_pct = Column(Float, nullable=True)
    ema20_50_spread_pct = Column(Float, nullable=True)
    ema50_200_spread_pct = Column(Float, nullable=True)
    ema20_200_spread_pct = Column(Float, nullable=True)

    # Trend structure
    ema20_gt_ema50 = Column(Float, nullable=True)
    ema50_gt_ema200 = Column(Float, nullable=True)
    ema_stack_score = Column(Float, nullable=True)

    # Momentum
    rsi_1m = Column(Float, nullable=True)
    rsi_5m = Column(Float, nullable=True)
    rsi_15m = Column(Float, nullable=True)
    rsi_delta = Column(Float, nullable=True)
    rsi_slope = Column(Float, nullable=True)
    momentum_ratio = Column(Float, nullable=True)

    # Candle strength / structure
    body_pct = Column(Float, nullable=True)
    range_pct = Column(Float, nullable=True)
    body_to_range_ratio = Column(Float, nullable=True)
    upper_wick_ratio = Column(Float, nullable=True)
    lower_wick_ratio = Column(Float, nullable=True)
    close_near_high = Column(Float, nullable=True)
    close_near_low = Column(Float, nullable=True)
    close_in_range_pct = Column(Float, nullable=True)

    # Volatility (ATR/NATR)
    atr_1m = Column(Float, nullable=True)
    atr_5m = Column(Float, nullable=True)
    atr_15m = Column(Float, nullable=True)
    natr_1m = Column(Float, nullable=True)
    natr_5m = Column(Float, nullable=True)
    natr_15m = Column(Float, nullable=True)
    atr_ratio_1m_5m = Column(Float, nullable=True)
    atr_ratio_5m_15m = Column(Float, nullable=True)
    range_ma20 = Column(Float, nullable=True)
    range_zscore = Column(Float, nullable=True)

    # Volume
    volume_ma20 = Column(Float, nullable=True)
    volume_ratio = Column(Float, nullable=True)
    volume_zscore = Column(Float, nullable=True)
    volume_change_pct = Column(Float, nullable=True)
    volume_ratio_5m = Column(Float, nullable=True)
    volume_ratio_15m = Column(Float, nullable=True)

    # Position features
    recent_high_20 = Column(Float, nullable=True)
    recent_low_20 = Column(Float, nullable=True)
    dist_from_recent_high_pct = Column(Float, nullable=True)
    dist_from_recent_low_pct = Column(Float, nullable=True)
    close_in_recent_range = Column(Float, nullable=True)

    # Pullback / breakout features
    pullback_depth_pct = Column(Float, nullable=True)
    breakout_confirmation = Column(Float, nullable=True)
    breakout_strength = Column(Float, nullable=True)

    # Regime features
    adx_14 = Column(Float, nullable=True)
    ema50_slope_pct = Column(Float, nullable=True)
    natr_regime = Column(String(16), nullable=True)
    regime_score = Column(Float, nullable=True)
    regime_label = Column(String(32), nullable=True, index=True)
    regime_tradable = Column(Boolean, nullable=True)


class OutcomeStore1mModel(Base):
    """Outcome store on 1m grid: future returns, MFE/MAE, barrier labels."""

    __tablename__ = "outcome_store_1m"

    symbol = Column(String(32), primary_key=True, index=True)
    timestamp = Column(DateTime, primary_key=True, index=True)

    # Future returns (R or simple return)
    future_r_1 = Column(Float, nullable=True)
    future_r_2 = Column(Float, nullable=True)
    future_r_3 = Column(Float, nullable=True)
    future_r_5 = Column(Float, nullable=True)
    future_r_8 = Column(Float, nullable=True)
    future_r_10 = Column(Float, nullable=True)
    future_r_15 = Column(Float, nullable=True)
    future_r_20 = Column(Float, nullable=True)
    future_r_30 = Column(Float, nullable=True)
    future_r_45 = Column(Float, nullable=True)
    future_r_60 = Column(Float, nullable=True)
    future_r_90 = Column(Float, nullable=True)
    future_r_120 = Column(Float, nullable=True)
    future_r_180 = Column(Float, nullable=True)
    future_r_240 = Column(Float, nullable=True)

    # Maximum favorable/adverse excursion
    mfe_3 = Column(Float, nullable=True)
    mfe_5 = Column(Float, nullable=True)
    mfe_10 = Column(Float, nullable=True)
    mfe_20 = Column(Float, nullable=True)
    mfe_30 = Column(Float, nullable=True)
    mfe_60 = Column(Float, nullable=True)

    mae_3 = Column(Float, nullable=True)
    mae_5 = Column(Float, nullable=True)
    mae_10 = Column(Float, nullable=True)
    mae_20 = Column(Float, nullable=True)
    mae_30 = Column(Float, nullable=True)
    mae_60 = Column(Float, nullable=True)

    # Binary win labels (R > 0 at horizon)
    win_3 = Column(Boolean, nullable=True)
    win_5 = Column(Boolean, nullable=True)
    win_10 = Column(Boolean, nullable=True)
    win_20 = Column(Boolean, nullable=True)
    win_30 = Column(Boolean, nullable=True)

    # Barrier labels (which barrier hit first, if any)
    tp_03_sl_02_hit = Column(String(16), nullable=True)
    tp_05_sl_03_hit = Column(String(16), nullable=True)
    tp_10_sl_05_hit = Column(String(16), nullable=True)


class ResearchPipelineStateModel(Base):
    """Incremental compute state for feature/outcome builders."""

    __tablename__ = "research_pipeline_state"

    id = Column(Integer, primary_key=True, autoincrement=False, default=1)
    last_feature_timestamp = Column(DateTime, nullable=True)
    last_outcome_timestamp = Column(DateTime, nullable=True)


class DatasetSnapshotModel(Base):
    """Snapshot of a research dataset (symbol, period, feature_version)."""

    __tablename__ = "dataset_snapshot"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id = Column(String(128), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, nullable=False)
    feature_version = Column(Integer, nullable=False)
    symbol = Column(String(32), nullable=False)
    start_timestamp = Column(DateTime, nullable=True)
    end_timestamp = Column(DateTime, nullable=True)
    row_count = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)


class ResearchExperimentModel(Base):
    """Top-level experiment tracking for research runs."""

    __tablename__ = "research_experiments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    experiment_id = Column(String(128), nullable=False, unique=True, index=True)
    strategy_name = Column(String(64), nullable=True)
    dataset_id = Column(String(128), nullable=True)
    parameters_json = Column(Text, nullable=True)
    result_pf = Column(Float, nullable=True)
    result_sharpe = Column(Float, nullable=True)
    result_drawdown = Column(Float, nullable=True)
    result_trades = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False)


class DatasetStatsModel(Base):
    """Aggregate stats for a dataset snapshot (balance, regimes, etc.)."""

    __tablename__ = "dataset_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dataset_id = Column(String(128), nullable=False, index=True)
    regime_distribution = Column(Text, nullable=True)  # JSON
    year_distribution = Column(Text, nullable=True)    # JSON
    trade_count = Column(Integer, nullable=True)


class FeatureMetadataModel(Base):
    """Metadata for features (description, category, formula)."""

    __tablename__ = "feature_metadata"

    id = Column(Integer, primary_key=True, autoincrement=True)
    feature_name = Column(String(64), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    category = Column(String(32), nullable=True)
    timeframe = Column(String(16), nullable=True)
    formula = Column(Text, nullable=True)


class StrategyConfigModel(Base):
    """Strategy configuration: filters and ranking definition."""

    __tablename__ = "strategy_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_name = Column(String(64), nullable=False, unique=True, index=True)
    filters_json = Column(Text, nullable=True)
    ranking_json = Column(Text, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)


class PipelineLogModel(Base):
    """Pipeline stage logs for monitoring."""

    __tablename__ = "pipeline_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stage = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False)
    duration = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)
    timestamp = Column(DateTime, nullable=False)
