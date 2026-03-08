"""
Domain models shared across backtest, paper, and live trading.
All strategy and execution logic use these types only.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


class Timeframe(str, Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"


@dataclass
class Candle:
    """OHLCV candle with timestamp and timeframe."""
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: datetime
    timeframe: Timeframe

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open


@dataclass
class Signal:
    """Trading signal from strategy (entry only)."""
    direction: Direction
    strength: float = 1.0
    reason_code: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    timeframe: Timeframe = Timeframe.M1
    symbol: str = ""


@dataclass
class OrderRequest:
    """Order request passed to broker interface."""
    symbol: str
    side: Direction
    quantity: float
    order_type: str  # "market", "stop_market", "take_profit_market"
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    reduce_only: bool = False
    client_order_id: Optional[str] = None


@dataclass
class Position:
    """Open position (from broker or paper state). 4-stage exit: SL, partial TP, trailing, time stop."""
    symbol: str
    side: Direction
    size: float
    entry_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    opened_at: datetime = field(default_factory=datetime.utcnow)
    unrealized_pnl: float = 0.0
    # 4-stage exit state
    tp1_hit: bool = False
    highest_price_since_entry: float = 0.0  # long: for trailing
    lowest_price_since_entry: float = 0.0   # short: for trailing
    bars_in_trade: int = 0


@dataclass
class TradeRecord:
    """Closed trade for logging and analysis. mode: paper / backtest / live."""
    symbol: str
    side: Direction
    size: float
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float
    pnl: float
    rr: float  # risk-reward realized
    reason_entry: str
    reason_exit: str
    opened_at: datetime
    closed_at: datetime
    approval_score: int = 0
    blocked_reason: Optional[str] = None  # None when entry was approved
    mode: str = "paper"  # paper | backtest | live (대시보드에서 구분용)


@dataclass
class ApprovalResult:
    """Result of approval engine: allowed or blocked with score breakdown."""
    allowed: bool
    total_score: int
    category_scores: dict  # e.g. {"regime_quality": 1, "trend_quality": 1, ...}
    blocked_reason: Optional[str] = None  # when not allowed


@dataclass
class ApprovalSettings:
    """Config-driven thresholds for approval engine (UI tuning)."""
    approval_threshold: int = 5  # entry if total_score >= this (max 7)
    # Per-category: 1 point when condition met (thresholds below)
    regime_adx_min: float = 10.0
    regime_score_min: int = 1
    trend_ema_aligned: bool = True
    trigger_pullback_ok: bool = True
    volume_multiplier_min: float = 1.2
    volume_expansion_required: bool = True
    ema_distance_threshold: float = 0.0006
    momentum_body_ratio: float = 0.5
    breakout_required: bool = True
    min_rr_ratio: float = 0.5  # reward/risk: e.g. potential target vs stop distance


@dataclass
class BlockedCandidateLog:
    """Logged when a candidate signal is blocked by approval engine."""
    symbol: str
    direction: Direction
    timestamp: datetime
    total_score: int
    blocked_reason: str
    category_scores: dict
    reason_entry: str = ""


@dataclass
class CandidateSignalRecord:
    """One row for Signal Distribution Analysis: all candidates (executed + blocked)."""
    timestamp: datetime
    entry_price: float
    regime: str  # e.g. TRENDING_UP, RANGING
    trend_direction: Direction
    approval_score: int
    feature_values: Dict[str, float]  # ema_distance, volume_ratio, rsi_5m
    trade_outcome: str  # "executed" | "blocked"
    blocked_reason: Optional[str] = None
    R_return: Optional[float] = None  # realized R (rr) when executed
    holding_time_bars: Optional[int] = None  # 1m bars in trade when executed
    symbol: str = ""
    signal_quality_score: Optional[float] = None  # 0..1 from ranking
    allocated_risk_pct: Optional[float] = None  # risk % used for position size
    kelly_fraction: Optional[float] = None  # raw Kelly fraction when Kelly allocator used


@dataclass
class SignalOutcome:
    """Outcome for a candidate signal: future R at N bars, tp/sl first, bars to outcome."""
    candidate_signal_id: int
    future_r_5: Optional[float] = None
    future_r_10: Optional[float] = None
    future_r_20: Optional[float] = None
    future_r_30: Optional[float] = None
    tp_hit_first: Optional[bool] = None
    sl_hit_first: Optional[bool] = None
    bars_to_outcome: Optional[int] = None
    computed_at: Optional[datetime] = None


@dataclass
class StrategySnapshot:
    """Current MTF state for logging/debugging."""
    bias_15m: Optional[Direction]  # None = neutral
    trend_5m: Optional[Direction]
    trigger_1m: Optional[Direction]
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RiskSettings:
    """Risk management parameters. Exit: initial SL(ATR), partial TP, trailing, time stop."""
    risk_per_trade_pct: float = 0.5
    atr_multiplier: float = 1.5
    atr_period: int = 14
    swing_lookback: int = 10
    # 4-stage exit
    partial_tp_R: float = 1.0      # +1R 도달 시 부분 익절
    partial_tp_size: float = 0.5   # 포지션 50% 청산
    trailing_atr_multiplier: float = 2.0  # 2=기본, 2.5~3=추세 유지 시도
    max_bars_in_trade: int = 30    # time stop (봉)
    ema_exit_confirm_bars: int = 1 # EMA 익절: 1=즉시, 2~3=N봉 연속 시만 (추세 유지)
    # daily / legacy
    rr_target: float = 2.0
    daily_loss_limit_r: float = -2.0
    daily_profit_limit_r: float = 3.0
    max_trades_per_day: int = 10
    cooldown_bars: int = 1


@dataclass
class LeverageSettings:
    """Regime-adaptive leverage: regime -> leverage multiplier, safety caps."""
    enabled: bool = True
    max_leverage: float = 5.0
    max_position_risk_pct: float = 1.0
    regime_leverage: Optional[Dict[str, float]] = None  # TRENDING_UP: 3, RANGE: 1.5, CHAOTIC: 0.5

    def __post_init__(self):
        if self.regime_leverage is None:
            self.regime_leverage = {
                "TRENDING_UP": 3.0,
                "TRENDING_DOWN": 3.0,
                "RANGE": 1.5,
                "RANGING": 1.5,
                "CHAOTIC": 0.5,
                "UNKNOWN": 1.0,
            }


@dataclass
class KellySettings:
    """Kelly criterion risk scaling: fractional Kelly and risk caps."""
    enabled: bool = True
    fractional_kelly: float = 0.25
    max_risk_per_trade_pct: float = 1.0
    min_risk_per_trade_pct: float = 0.25
    avg_win_R: float = 1.2
    avg_loss_R: float = -1.0


@dataclass
class CapitalAllocationSettings:
    """Signal quality ranking and dynamic capital allocation."""
    enabled: bool = True
    min_quality_threshold: float = 0.55
    tiers: Optional[List[tuple]] = None  # [(score_min, risk_pct), ...] e.g. [(0.75, 3.0), (0.65, 2.0), (0.55, 1.0)]
    max_portfolio_risk_pct: float = 6.0
    regime_multipliers: Optional[Dict[str, float]] = None  # TRENDING_UP: 1.2, CHAOTIC: 0.5, ...
    default_strategy_stability_score: float = 0.5

    def __post_init__(self):
        if self.tiers is None:
            self.tiers = [(0.75, 3.0), (0.65, 2.0), (0.55, 1.0)]
        if self.regime_multipliers is None:
            self.regime_multipliers = {
                "TRENDING_UP": 1.2,
                "TRENDING_DOWN": 1.2,
                "RANGING": 1.0,
                "CHAOTIC": 0.5,
            }


@dataclass
class StrategySettings:
    """MTF EMA Pullback strategy parameters. Signal Quality Filter + HTF RSI."""
    ema_fast: int = 8
    ema_mid: int = 21
    ema_slow: int = 50
    slope_threshold: float = 0.0001
    volume_ma_period: int = 20
    volume_multiplier: float = 1.2
    swing_lookback: int = 10
    # Signal Quality Filter
    ema_distance_threshold: float = 0.0006   # abs(EMA8-EMA21)/close > this
    momentum_body_ratio: float = 0.5         # body_size/range >= this
    signal_score_threshold: int = 3        # score >= this to enter (max 4)
    # HTF Momentum (5m RSI)
    rsi_period: int = 14
    rsi_long_min: float = 55.0   # 5m RSI > this for long
    rsi_short_max: float = 45.0  # 5m RSI < this for short
