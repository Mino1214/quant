"""
Realtime engine: 1m closed -> buffer -> strategy -> candidate -> approval_engine -> entry.
Two-stage: trigger produces candidate; approval engine scores and decides entry.
"""
import asyncio
import logging
from datetime import datetime
from typing import List, Optional

from core.models import BlockedCandidateLog, Candle, CandidateSignalRecord, CapitalAllocationSettings, Direction, Timeframe
from core.state import EngineState
from strategy.mtf_ema_pullback import evaluate_candidate, bias_15m, trend_5m, trigger_1m
from strategy.filters.market_regime import MarketRegimeFilter
from strategy.approval_engine import ApprovalContext, score as approval_score
from strategy.feature_extractor import extract_feature_values
from risk.risk_manager import RiskManager, compute_stop_loss, compute_quantity, ema_exit_triggered
from indicators.atr import atr
from indicators.ema import ema
from execution.base_broker import BaseBroker
from execution.capital_allocator import get_current_open_risk_pct_async, get_position_size
from execution.paper_broker import PaperBroker
from storage.trade_logger import log_blocked_candidate, log_trade
from storage.signal_dataset_logger import log_candidate_signal

logger = logging.getLogger(__name__)


def _log_task_exception(task: asyncio.Task) -> None:
    """페이퍼 평가 태스크 예외 로깅 (예외 삼켜짐 방지)."""
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.exception("Paper evaluate_and_trade failed: %s", e)


class TradingEngine:
    def __init__(
        self,
        state: EngineState,
        broker: BaseBroker,
        risk_manager: RiskManager,
        strategy_settings,
        risk_settings,
        symbol: str,
        balance: float = 10000.0,
        regime_filter: Optional[MarketRegimeFilter] = None,
        approval_settings=None,
        ml_settings: Optional[dict] = None,
        capital_allocation_settings: Optional[CapitalAllocationSettings] = None,
        kelly_settings=None,
        leverage_settings=None,
        use_trend_filter: bool = False,
    ):
        self.state = state
        self.broker = broker
        self.risk_manager = risk_manager
        self.strategy_settings = strategy_settings
        self.risk_settings = risk_settings
        self.symbol = symbol
        self.balance = balance
        self.regime_filter = regime_filter
        self.approval_settings = approval_settings
        self._ml_settings: dict = ml_settings or {}
        self.use_trend_filter = use_trend_filter
        self._capital_allocation: Optional[CapitalAllocationSettings] = capital_allocation_settings
        self._kelly_settings = kelly_settings
        self._leverage_settings = leverage_settings
        self._last_approval_score: int = 0
        self._last_scheduled_bar_ts: Optional[datetime] = None  # 같은 봉 두 번 평가 스케줄 방지

    def _on_1m_closed(self, c: Candle, quiet: bool = False) -> bool:
        """1m 봉 추가 처리. 추가했으면 True, 중복으로 스킵했으면 False (이때만 평가 스케줄)."""
        # 이미 같은 분 봉이 있으면 넣지 않음 (갭 필로 채운 뒤 소켓 중복 방지)
        if self.state.last_1m_ts is not None:
            t = c.timestamp.replace(second=0, microsecond=0)
            last = self.state.last_1m_ts.replace(second=0, microsecond=0)
            if t <= last:
                if not quiet:
                    logger.info("Skip duplicate 1m bar ts=%s (already have up to %s)", t, last)
                return False
        self.state.add_1m(c)
        try:
            from storage.candle_persistence import save_candle_1m
            save_candle_1m(c, symbol=self.symbol)
        except Exception as e:
            logger.warning("Save 1m to DB failed: %s", e)
        buf = self.state.get_1m_list()
        if len(buf) >= 5 and c.timestamp.minute % 5 == 0:
            from market.timeframe_aggregator import aggregate_candles
            c5 = aggregate_candles(buf[-5:], 5)
            if c5:
                self.state.add_5m(c5)
                try:
                    from storage.candle_persistence import save_candle_5m
                    save_candle_5m(c5, symbol=self.symbol)
                except Exception as e:
                    logger.warning("Save 5m to DB failed: %s", e)
        if len(buf) >= 15 and c.timestamp.minute % 15 == 0:
            from market.timeframe_aggregator import aggregate_candles
            c15 = aggregate_candles(buf[-15:], 15)
            if c15:
                self.state.add_15m(c15)
                try:
                    from storage.candle_persistence import save_candle_15m
                    save_candle_15m(c15, symbol=self.symbol)
                except Exception as e:
                    logger.warning("Save 15m to DB failed: %s", e)
        if not quiet:
            logger.info("Candle close 1m ts=%s", c.timestamp)
        return True

    def warm_up(self, candles_1m: List[Candle]) -> None:
        """과거 1m만으로 버퍼 채움(5m/15m은 1m에서 집계). DB에 5m/15m 테이블 없을 때."""
        for c in candles_1m:
            self._on_1m_closed(c, quiet=True)
        logger.info("Warm-up done: 1m=%s 5m=%s 15m=%s",
                    len(self.state.get_1m_list()),
                    len(self.state.get_5m_list()),
                    len(self.state.get_15m_list()))

    def rebuild_5m_15m_from_1m(self) -> None:
        """
        현재 1m 버퍼 전체로 5m/15m을 다시 만든다.
        서버 재시작 후 갭 필 후 호출하면, DB 3시간 전 + 갭 필로 이어진 1m 기준으로
        5m/15m이 연속적으로 맞게 된다.
        """
        from market.timeframe_aggregator import aggregate_candles
        buf = self.state.get_1m_list()
        if len(buf) < 15:
            return
        new_5m: List[Candle] = []
        new_15m: List[Candle] = []
        for i in range(0, len(buf) - 4, 5):
            block = buf[i : i + 5]
            if len(block) == 5:
                c5 = aggregate_candles(block, 5)
                if c5:
                    new_5m.append(c5)
        for i in range(0, len(buf) - 14, 15):
            block = buf[i : i + 15]
            if len(block) == 15:
                c15 = aggregate_candles(block, 15)
                if c15:
                    new_15m.append(c15)
        self.state.candles_5m.clear()
        self.state.candles_5m.extend(new_5m)
        self.state.candles_15m.clear()
        self.state.candles_15m.extend(new_15m)
        if new_5m:
            self.state.last_5m_ts = new_5m[-1].timestamp
        if new_15m:
            self.state.last_15m_ts = new_15m[-1].timestamp
        logger.info("Rebuilt 5m/15m from 1m: 5m=%s 15m=%s", len(new_5m), len(new_15m))

    def seed_from_db(
        self,
        candles_1m: List[Candle],
        candles_5m: List[Candle],
        candles_15m: List[Candle],
    ) -> None:
        """btc1m, btc5m, btc15m 각 테이블에서 불러온 봉으로 버퍼 직접 채움. 집계 없음."""
        for c in candles_1m:
            self.state.add_1m(c)
        for c in candles_5m:
            self.state.add_5m(c)
        for c in candles_15m:
            self.state.add_15m(c)
        logger.info("Seed from DB: 1m=%s 5m=%s 15m=%s",
                    len(self.state.get_1m_list()),
                    len(self.state.get_5m_list()),
                    len(self.state.get_15m_list()))

    def update_display_state(self) -> None:
        """현재 버퍼로 bias/trend/trigger/regime만 계산해 state에 넣음 (UI 표시용)."""
        candles_15m = self.state.get_15m_list(60)
        candles_5m = self.state.get_5m_list(60)
        candles_1m = self.state.get_1m_list(200)
        if len(candles_15m) < 50 or len(candles_5m) < 50 or len(candles_1m) < 50:
            return
        self.state.last_bias = bias_15m(candles_15m, self.strategy_settings)
        self.state.last_trend = trend_5m(candles_5m, self.strategy_settings)
        trigger_sig = trigger_1m(candles_1m, self.strategy_settings, self.symbol)
        self.state.last_trigger = trigger_sig.direction if trigger_sig else None
        if self.regime_filter and self.regime_filter.settings.enabled:
            regime_result = self.regime_filter.evaluate(candles_15m)
            self.state.last_regime = regime_result.regime.value
            self.state.last_regime_blocked = regime_result.blocked_reason

    async def _evaluate_and_trade(self, c_1m: Candle) -> None:
        """Run strategy and optionally place order. Only on 1m close; no duplicate."""
        from core.scheduler import should_evaluate_on_1m

        if not should_evaluate_on_1m(c_1m.timestamp, self.state.last_signal_bar_ts):
            return
        candles_15m = self.state.get_15m_list(60)
        candles_5m = self.state.get_5m_list(60)
        candles_1m = self.state.get_1m_list(200)
        if len(candles_15m) < 50 or len(candles_5m) < 50 or len(candles_1m) < 50:
            return

        # Log bias / trend / trigger state
        self.state.last_bias = bias_15m(candles_15m, self.strategy_settings)
        self.state.last_trend = trend_5m(candles_5m, self.strategy_settings)
        trigger_sig = trigger_1m(candles_1m, self.strategy_settings, self.symbol)
        self.state.last_trigger = trigger_sig.direction if trigger_sig else None
        logger.info(
            "Bias=%s trend=%s trigger=%s",
            self.state.last_bias,
            self.state.last_trend,
            self.state.last_trigger,
        )

        # Check existing position: 4-stage exit (paper only)
        pos = await self.broker.get_open_position(self.symbol)
        if pos is not None and isinstance(self.broker, PaperBroker):
            atr_val = atr(candles_1m, self.risk_settings.atr_period) or 0.0
            closes = [c.close for c in candles_1m]
            ema8 = ema(closes, 8) if len(closes) >= 8 else None
            ema21 = ema(closes, 21) if len(closes) >= 21 else None
            confirm = getattr(self.risk_settings, "ema_exit_confirm_bars", 1)
            ema_triggered = ema_exit_triggered(
                candles_1m, pos.side, confirm,
                self.strategy_settings.ema_fast, self.strategy_settings.ema_mid,
            )
            closed_list = self.broker.check_stop_tp(
                c_1m.low, c_1m.high, c_1m.close,
                atr_val, ema8, ema21, self.risk_settings,
                closed_at=c_1m.timestamp,
                ema_exit_triggered=ema_triggered,
            )
            for closed in closed_list:
                closed.approval_score = self._last_approval_score
                closed.blocked_reason = None
                closed.mode = "paper"
                self.balance += closed.pnl
                self.risk_manager.record_trade(closed)
                self.risk_manager.set_last_trade_time(c_1m.timestamp)
                log_trade(closed)
                logger.info("Trade closed: %s pnl=%.2f %s approval_score=%s", closed.reason_exit, closed.pnl, closed.size, closed.approval_score)
            if closed_list:
                return
        if pos is not None:
            return

        # Market regime filter (first): block if not tradeable
        regime_result = None
        if self.regime_filter and self.regime_filter.settings.enabled:
            regime_result = self.regime_filter.evaluate(candles_15m)
            self.state.last_regime = regime_result.regime.value
            self.state.last_regime_blocked = regime_result.blocked_reason
            if not regime_result.allow_trading:
                logger.info("Regime block: %s (ADX=%.2f NATR=%.2f slope_pct=%.3f)",
                    regime_result.blocked_reason, regime_result.adx, regime_result.natr, regime_result.slope_pct)
                return
            candidate = evaluate_candidate(
                candles_15m, candles_5m, candles_1m,
                self.strategy_settings, self.symbol,
            )
            if candidate is not None:
                if candidate.direction == Direction.LONG and not regime_result.can_long:
                    logger.info("Regime block: long not allowed (regime=%s)", regime_result.regime.value)
                    return
                if candidate.direction == Direction.SHORT and not regime_result.can_short:
                    logger.info("Regime block: short not allowed (regime=%s)", regime_result.regime.value)
                    return
        else:
            candidate = evaluate_candidate(
                candles_15m, candles_5m, candles_1m,
                self.strategy_settings, self.symbol,
            )

        if candidate is None:
            return

        entry = c_1m.close
        stop_loss = compute_stop_loss(
            entry, candidate.direction, candles_1m, self.risk_settings
        )
        regime_str = regime_result.regime.value if regime_result is not None else "UNKNOWN"
        features = extract_feature_values(candles_1m, candles_5m, self.strategy_settings, candles_15m=candles_15m)
        if len(candles_15m) >= 50:
            try:
                from features.multi_tf_feature_builder import build_multi_tf_features
                multi_tf = build_multi_tf_features(
                    candles_1m, candles_5m, candles_15m,
                    c_1m.timestamp, self.strategy_settings,
                )
                features = {**features, **multi_tf}
            except Exception:
                pass
        try:
            from features.cross_market_feature_builder import build_cross_market_features
            features = build_cross_market_features(
                c_1m.timestamp, features, self.strategy_settings, eth_candles=None,
            )
        except Exception:
            pass

        # Trend filter: LONG only if ema20>ema50 and ema50_slope>0, SHORT only if opposite
        if self.use_trend_filter:
            bias = float(features.get("trend_bias", 0) or 0)
            if candidate.direction == Direction.LONG and bias < 0.5:
                logger.debug("Trend filter block: long but trend_bias=%.2f", bias)
                return
            if candidate.direction == Direction.SHORT and bias > -0.5:
                logger.debug("Trend filter block: short but trend_bias=%.2f", bias)
                return

        def _log_candidate_snapshot(
            trade_outcome: str,
            approval_score_val: int,
            blocked_reason: Optional[str] = None,
            signal_quality_score: Optional[float] = None,
            allocated_risk_pct: Optional[float] = None,
            kelly_fraction: Optional[float] = None,
        ) -> None:
            record = CandidateSignalRecord(
                timestamp=c_1m.timestamp,
                entry_price=entry,
                regime=regime_str,
                trend_direction=candidate.direction,
                approval_score=approval_score_val,
                feature_values=features,
                trade_outcome=trade_outcome,
                blocked_reason=blocked_reason,
                symbol=self.symbol,
                signal_quality_score=signal_quality_score,
                allocated_risk_pct=allocated_risk_pct,
                kelly_fraction=kelly_fraction,
            )
            try:
                log_candidate_signal(record)
            except Exception:
                pass

        # Approval engine: score candidate; log if blocked
        if self.approval_settings is not None:
            ctx = ApprovalContext(
                candles_1m=candles_1m,
                candles_5m=candles_5m,
                candles_15m=candles_15m,
                entry_price=entry,
                stop_loss=stop_loss,
                regime_result=regime_result,
            )
            result = approval_score(
                candidate, ctx, self.approval_settings,
                self.strategy_settings, self.risk_settings,
            )
            if not result.allowed:
                log_blocked_candidate(BlockedCandidateLog(
                    symbol=self.symbol,
                    direction=candidate.direction,
                    timestamp=c_1m.timestamp,
                    total_score=result.total_score,
                    blocked_reason=result.blocked_reason or "approval",
                    category_scores=result.category_scores,
                    reason_entry=candidate.reason_code,
                ))
                _log_candidate_snapshot("blocked", result.total_score, result.blocked_reason or "approval")
                logger.info("Approval block: score=%s threshold=%s %s", result.total_score, self.approval_settings.approval_threshold, result.blocked_reason)
                return
            self._last_approval_score = result.total_score

        # ML gate (optional): win_probability and expected_R thresholds
        pred = None
        if getattr(self, "_ml_settings", None) and self._ml_settings.get("enabled"):
            try:
                from ml.predictor import predict_signal
                fd = {**features, "trend_direction": candidate.direction.value, "regime": regime_str}
                pred = predict_signal(fd, model_dir=self._ml_settings.get("model_path", "ml/models"))
                if pred is not None:
                    t_wp = self._ml_settings.get("threshold_win_prob", 0.58)
                    t_er = self._ml_settings.get("threshold_expected_r", 0.25)
                    if pred["win_probability"] < t_wp or pred["expected_R"] < t_er:
                        _log_candidate_snapshot("blocked", self._last_approval_score, "ml_gate")
                        logger.info("ML block: win_prob=%.2f expected_R=%.2f", pred["win_probability"], pred["expected_R"])
                        return
            except Exception as e:
                logger.debug("ML predictor skip: %s", e)

        check = self.risk_manager.can_trade(
            c_1m.timestamp, self.risk_settings.cooldown_bars
        )
        if not check.allowed:
            _log_candidate_snapshot("blocked", self._last_approval_score, check.reason_code)
            logger.info("Risk block: %s", check.reason_code)
            return

        cap = getattr(self, "_capital_allocation", None)
        use_allocator = cap is not None and getattr(cap, "enabled", False)

        if use_allocator:
            from execution.signal_quality_ranking import compute_signal_quality_score
            win_prob = pred["win_probability"] if pred is not None else 0.5
            expected_r = pred["expected_R"] if pred is not None else 0.25
            stability = getattr(cap, "default_strategy_stability_score", 0.5)
            signal_quality_score = compute_signal_quality_score(win_prob, expected_r, stability)
            if signal_quality_score <= cap.min_quality_threshold:
                _log_candidate_snapshot(
                    "blocked", self._last_approval_score, "signal_quality_threshold",
                    signal_quality_score=signal_quality_score,
                )
                logger.info("Capital allocation block: signal_quality_score=%.2f <= threshold=%.2f", signal_quality_score, cap.min_quality_threshold)
                return
            kelly = getattr(self, "_kelly_settings", None)
            use_kelly = kelly is not None and getattr(kelly, "enabled", False)
            override_risk_pct = None
            kelly_fraction = None
            if use_kelly:
                from execution.kelly_allocator import compute_kelly_risk
                avg_win_R = getattr(kelly, "avg_win_R", 1.2)
                avg_loss_R = getattr(kelly, "avg_loss_R", -1.0)
                kelly_result = compute_kelly_risk(
                    win_prob, avg_win_R, avg_loss_R, kelly,
                    signal_quality_score=signal_quality_score,
                    expected_R=expected_r,
                )
                kelly_fraction = kelly_result.get("kelly_fraction")
                if kelly_result.get("skip"):
                    _log_candidate_snapshot(
                        "blocked", self._last_approval_score, "kelly_skip",
                        signal_quality_score=signal_quality_score,
                        kelly_fraction=kelly_fraction,
                    )
                    logger.info("Kelly block: raw_kelly<=0 (skip trade)")
                    return
                override_risk_pct = kelly_result.get("final_risk_pct")
            current_risk_pct = await get_current_open_risk_pct_async(self.broker, self.symbol, self.balance)
            qty, allocated_risk_pct = get_position_size(
                self.balance, entry, stop_loss, candidate.direction,
                signal_quality_score, regime_str, cap, current_risk_pct,
                override_risk_pct=override_risk_pct,
                leverage_settings=getattr(self, "_leverage_settings", None),
            )
            if qty <= 0:
                _log_candidate_snapshot(
                    "blocked", self._last_approval_score, "portfolio_risk_cap_or_tier",
                    signal_quality_score=signal_quality_score,
                    kelly_fraction=kelly_fraction,
                )
                return
            _log_candidate_snapshot(
                "executed", self._last_approval_score, None,
                signal_quality_score=signal_quality_score,
                allocated_risk_pct=allocated_risk_pct,
                kelly_fraction=kelly_fraction,
            )
        else:
            qty = compute_quantity(
                self.balance, entry, stop_loss, candidate.direction, self.risk_settings
            )
            if qty <= 0:
                _log_candidate_snapshot("blocked", self._last_approval_score, "qty<=0")
                return
            _log_candidate_snapshot("executed", self._last_approval_score, None)

        oid = await self.broker.place_market_order(
            self.symbol, candidate.direction, qty, reduce_only=False
        )
        if oid is None:
            return
        if isinstance(self.broker, PaperBroker):
            self.broker.set_fill_price(entry, stop_loss, None, opened_at=c_1m.timestamp)
        await self.broker.place_stop_loss_order(
            self.symbol, candidate.direction, qty, stop_loss, reduce_only=True
        )
        await self.broker.place_take_profit_order(
            self.symbol, candidate.direction, qty, entry, reduce_only=True
        )  # no fixed TP in 4-stage exit; pass entry so order exists
        self.state.last_signal_bar_ts = c_1m.timestamp
        self.state.last_order_at = c_1m.timestamp  # 대시보드/확인용
        logger.info(
            "Order executed %s %s @ %s sl=%s reason=%s approval_score=%s",
            self.symbol, candidate.direction.value, entry, stop_loss, candidate.reason_code,
            getattr(self, "_last_approval_score", 0),
        )

    def on_1m_closed(self, c: Candle) -> None:
        """Called when 1m candle closes. 버퍼에 없으면 추가. 같은 봉은 한 번만 평가 스케줄."""
        added = self._on_1m_closed(c)
        bar_ts = c.timestamp.replace(second=0, microsecond=0)
        if self._last_scheduled_bar_ts is not None and bar_ts <= self._last_scheduled_bar_ts:
            return  # 이미 이 봉으로 스케줄함 (WS 중복 수신 방지)
        self._last_scheduled_bar_ts = bar_ts
        if not added:
            logger.info("1m bar ts=%s already in buffer → scheduling evaluation", c.timestamp)
        task = asyncio.create_task(self._evaluate_and_trade(c))
        task.add_done_callback(_log_task_exception)
