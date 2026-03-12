"""
MTF Trend Pullback 실전형 페이퍼 트레이더.

기존 main.py / TradingEngine과 완전히 독립적으로 동작.
research 전략(evaluate_strict) 기반, 복수 threshold variant 동시 실행.

특징:
  - 복수 threshold 동시 운영 (e.g. 0.0002, 0.000285)
  - DB warm-up → WebSocket 실시간 전환
  - 슬리피지 시뮬레이션 (entry/exit 각 N bps)
  - 진입 시 signal feature 전체 로깅 (ema20_slope_15m, 5m, 1m, rsi, adx 등)
  - trade 로그 CSV + 실시간 콘솔 출력

실행 예:
  python3 -m paper.run_paper_strategy \\
    --symbol BTCUSDT \\
    --thresholds 0.0002,0.000285 \\
    --exit-type old \\
    --tp 1.2 --sl 0.6 --timeout-bars 30 \\
    --initial-capital 1000 \\
    --notional-fraction 0.05 --leverage 2 \\
    --fee-bps 4 --slippage-bps 2

partial exit 예:
  python3 -m paper.run_paper_strategy \\
    --symbol BTCUSDT \\
    --thresholds 0.000285 \\
    --exit-type partial \\
    --tp1 0.8 --tp1-size 0.5 --sl 0.6 --timeout-bars 30 \\
    --notional-fraction 0.05 --leverage 2 \\
    --fee-bps 4
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import sys
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.loader import get_strategy_settings
from core.models import Candle, Timeframe
from market.binance_ws import run_binance_kline_ws
from storage.candle_loader import load_1m_from_db, load_5m_from_db, load_15m_from_db
from strategy.feature_extractor import (
    _ema_last_and_prev,
    extract_feature_values_research_minimal,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("paper")

# ---------------------------------------------------------------------------
# evaluate_strict 진입 조건 (mtf_trend_pullback_research._long_candidate_2 와 동일)
# ---------------------------------------------------------------------------
_STRICT = {
    "ema20_slope_5m_gt":    0.000094,
    "ema20_slope_1m_lt":   -0.000018,
    "rsi_1m_lt":            38.0,
    "rsi_5m_gt":            54.0,
    "pullback_depth_gt":     0.6,
    "adx_14_gte":           18.0,
    "volume_ratio_gte":      1.2,
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PaperConfig:
    symbol: str = "BTCUSDT"
    thresholds: List[float] = field(default_factory=lambda: [0.000285])
    exit_type: str = "old"        # "old" | "partial"
    tp_pct: float = 1.2           # old exit TP%
    tp1_pct: float = 0.8          # partial TP1%
    tp1_size: float = 0.5         # partial TP1 청산 비중
    sl_pct: float = 0.6
    timeout_bars: int = 30
    initial_capital: float = 1000.0
    notional_fraction: float = 0.05
    leverage: float = 2.0
    fee_bps: float = 4.0
    slippage_bps: float = 2.0     # 편도 슬리피지 (entry/exit 각각)
    warmup_hours: int = 20        # DB warm-up 구간 (시간)
    out_dir: str = ""             # 빈 문자열이면 paper/paper_results/ 사용
    stats_every: int = 5          # N 거래마다 콘솔 통계 출력


@dataclass
class TradeRecord:
    variant_id: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    exit_reason: str
    pnl_pct: float
    net_pct: float
    tp1_hit: bool
    equity_before: float
    position_notional: float
    pnl_usdt: float
    equity_after: float
    # 진입 시 signal features
    sig_slope_15m: float
    sig_slope_5m: float
    sig_slope_1m: float
    sig_rsi_1m: float
    sig_rsi_5m: float
    sig_pullback: float
    sig_adx: float
    sig_volume_ratio: float


@dataclass
class VariantState:
    """threshold 1개에 대한 런타임 상태."""
    threshold: float
    cfg: PaperConfig

    # 포지션 상태
    in_position: bool = False
    entry_price: float = 0.0
    entry_time: Optional[datetime] = None
    bars_held: int = 0
    tp1_hit: bool = False
    partial_pnl_pct: float = 0.0
    position_size: float = 1.0   # 1.0 = 전체, tp1 후 = 1-tp1_size
    entry_notional: float = 0.0
    equity_at_entry: float = 0.0

    # 진입 시 feature snapshot
    sig_slope_15m: float = 0.0
    sig_slope_5m: float = 0.0
    sig_slope_1m: float = 0.0
    sig_rsi_1m: float = 0.0
    sig_rsi_5m: float = 0.0
    sig_pullback: float = 0.0
    sig_adx: float = 0.0
    sig_volume_ratio: float = 0.0

    # 자본 / 통계
    equity: float = field(init=False)
    n_trades: int = 0
    n_wins: int = 0
    peak_equity: float = field(init=False)
    max_drawdown_pct: float = 0.0
    trade_log: List[TradeRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.equity = self.cfg.initial_capital
        self.peak_equity = self.cfg.initial_capital

    @property
    def variant_id(self) -> str:
        return f"th{self.threshold:.6f}_{self.cfg.exit_type}"

    @property
    def win_rate(self) -> float:
        return self.n_wins / self.n_trades * 100.0 if self.n_trades > 0 else 0.0

    @property
    def total_return_pct(self) -> float:
        return (self.equity - self.cfg.initial_capital) / self.cfg.initial_capital * 100.0


# ---------------------------------------------------------------------------
# 메인 러너
# ---------------------------------------------------------------------------

class PaperStrategyRunner:
    def __init__(self, cfg: PaperConfig) -> None:
        self.cfg = cfg
        self.settings = get_strategy_settings()

        # Rolling candle buffers
        self.buf_1m: Deque[Candle] = deque(maxlen=600)
        self.buf_5m: Deque[Candle] = deque(maxlen=200)
        self.buf_15m: Deque[Candle] = deque(maxlen=80)

        self.variants: List[VariantState] = [
            VariantState(threshold=th, cfg=cfg) for th in cfg.thresholds
        ]

        # 출력 경로
        out_dir = Path(cfg.out_dir) if cfg.out_dir else Path(__file__).parent / "paper_results"
        out_dir.mkdir(parents=True, exist_ok=True)
        self._out_dir = out_dir

        # CSV 파일 핸들 (variant별)
        self._csv_files: Dict[str, Any] = {}
        self._csv_writers: Dict[str, csv.DictWriter] = {}
        self._setup_csv_files()

    # ------------------------------------------------------------------
    # 초기화
    # ------------------------------------------------------------------

    def _setup_csv_files(self) -> None:
        ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        fields = [
            "variant_id",
            "entry_time", "exit_time",
            "entry_price", "exit_price", "exit_reason",
            "pnl_pct", "net_pct", "tp1_hit",
            "equity_before", "position_notional", "pnl_usdt", "equity_after",
            "sig_slope_15m", "sig_slope_5m", "sig_slope_1m",
            "sig_rsi_1m", "sig_rsi_5m", "sig_pullback",
            "sig_adx", "sig_volume_ratio",
        ]
        for v in self.variants:
            fname = self._out_dir / f"paper_{v.variant_id}_{ts_str}.csv"
            f = open(fname, "w", newline="", encoding="utf-8")
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            self._csv_files[v.variant_id] = f
            self._csv_writers[v.variant_id] = w
            logger.info("Trade log: %s", fname)

    def close(self) -> None:
        for f in self._csv_files.values():
            try:
                f.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # DB warm-up
    # ------------------------------------------------------------------

    async def warmup(self) -> None:
        """DB에서 최근 캔들 로드 → rolling buffer 초기화."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        from_dt = now - timedelta(hours=self.cfg.warmup_hours)

        logger.info("Warming up from DB (last %dh)...", self.cfg.warmup_hours)
        try:
            candles_1m = load_1m_from_db(
                symbol=self.cfg.symbol, start_ts=from_dt, end_ts=now
            )
            candles_5m = load_5m_from_db(
                symbol=self.cfg.symbol, start_ts=from_dt, end_ts=now
            )
            candles_15m = load_15m_from_db(
                symbol=self.cfg.symbol, start_ts=from_dt, end_ts=now
            )
        except Exception as e:
            logger.warning("DB warmup failed (%s) — starting cold.", e)
            return

        for c in candles_1m[-500:]:
            self.buf_1m.append(c)
        for c in candles_5m[-150:]:
            self.buf_5m.append(c)
        for c in candles_15m[-60:]:
            self.buf_15m.append(c)

        logger.info(
            "Warmup done. 1m=%d 5m=%d 15m=%d",
            len(self.buf_1m), len(self.buf_5m), len(self.buf_15m),
        )

    # ------------------------------------------------------------------
    # WebSocket 콜백
    # ------------------------------------------------------------------

    def on_candle(self, candle: Candle, is_closed: bool, interval: str) -> None:
        if not is_closed:
            return
        if interval == "1m":
            self.buf_1m.append(candle)
            self._on_1m_closed(candle)
        elif interval == "5m":
            self.buf_5m.append(candle)
        elif interval == "15m":
            self.buf_15m.append(candle)

    # ------------------------------------------------------------------
    # 1m 봉 마감 처리
    # ------------------------------------------------------------------

    def _on_1m_closed(self, candle: Candle) -> None:
        feats = self._compute_features()
        if feats is None:
            return

        for v in self.variants:
            if v.in_position:
                self._check_exit(v, candle, feats)
            else:
                if self._check_entry(v, feats):
                    self._enter(v, candle, feats)

    # ------------------------------------------------------------------
    # Feature 계산
    # ------------------------------------------------------------------

    def _compute_features(self) -> Optional[Dict[str, float]]:
        buf1 = list(self.buf_1m)
        buf5 = list(self.buf_5m)
        buf15 = list(self.buf_15m)

        if len(buf1) < 50 or len(buf5) < 20 or len(buf15) < 20:
            return None

        try:
            feats = extract_feature_values_research_minimal(
                candles_1m=buf1,
                candles_5m=buf5,
                settings=self.settings,
                candles_15m=buf15,
            )
            # partial exit에 필요한 ema20 절대값 추가
            closes_1m = [c.close for c in buf1 if c.close]
            ema20_val, _ = _ema_last_and_prev(closes_1m, 20)
            feats["ema20_1m"] = ema20_val if ema20_val is not None else 0.0
            return feats
        except Exception as e:
            logger.warning("Feature compute error: %s", e)
            return None

    # ------------------------------------------------------------------
    # 진입 조건
    # ------------------------------------------------------------------

    def _check_entry(self, v: VariantState, feats: Dict[str, float]) -> bool:
        # evaluate_strict 조건
        if not (
            feats.get("ema20_slope_5m", 0.0) > _STRICT["ema20_slope_5m_gt"]
            and feats.get("ema20_slope_1m", 0.0) < _STRICT["ema20_slope_1m_lt"]
            and feats.get("rsi_1m", 0.0) < _STRICT["rsi_1m_lt"]
            and feats.get("rsi_5m", 0.0) > _STRICT["rsi_5m_gt"]
            and feats.get("pullback_depth_pct", 0.0) > _STRICT["pullback_depth_gt"]
            and feats.get("adx_14", 0.0) >= _STRICT["adx_14_gte"]
            and feats.get("volume_ratio", 0.0) >= _STRICT["volume_ratio_gte"]
        ):
            return False
        # regime threshold 필터
        if feats.get("ema20_slope_15m", 0.0) <= v.threshold:
            return False
        return True

    # ------------------------------------------------------------------
    # 진입 실행
    # ------------------------------------------------------------------

    def _enter(self, v: VariantState, candle: Candle, feats: Dict[str, float]) -> None:
        # 슬리피지: long 진입은 close보다 slippage_bps만큼 높게 체결
        slip = 1.0 + self.cfg.slippage_bps / 10000.0
        entry_price = candle.close * slip

        notional = v.equity * self.cfg.notional_fraction * self.cfg.leverage

        v.in_position = True
        v.entry_price = entry_price
        v.entry_time = candle.timestamp
        v.bars_held = 0
        v.tp1_hit = False
        v.partial_pnl_pct = 0.0
        v.position_size = 1.0
        v.entry_notional = notional
        v.equity_at_entry = v.equity

        v.sig_slope_15m = feats.get("ema20_slope_15m", 0.0)
        v.sig_slope_5m = feats.get("ema20_slope_5m", 0.0)
        v.sig_slope_1m = feats.get("ema20_slope_1m", 0.0)
        v.sig_rsi_1m = feats.get("rsi_1m", 0.0)
        v.sig_rsi_5m = feats.get("rsi_5m", 0.0)
        v.sig_pullback = feats.get("pullback_depth_pct", 0.0)
        v.sig_adx = feats.get("adx_14", 0.0)
        v.sig_volume_ratio = feats.get("volume_ratio", 0.0)

        logger.info(
            "[%s] ▶ ENTER  %s | price=%.2f  sl15m=%+.6f  sl5m=%+.6f  rsi1m=%.1f  rsi5m=%.1f  pb=%.2f  adx=%.1f  vr=%.2f",
            v.variant_id, candle.timestamp.strftime("%Y-%m-%d %H:%M"),
            entry_price,
            v.sig_slope_15m, v.sig_slope_5m,
            v.sig_rsi_1m, v.sig_rsi_5m,
            v.sig_pullback, v.sig_adx, v.sig_volume_ratio,
        )

    # ------------------------------------------------------------------
    # 청산 체크
    # ------------------------------------------------------------------

    def _check_exit(
        self, v: VariantState, candle: Candle, feats: Dict[str, float]
    ) -> None:
        high = candle.high
        low = candle.low
        close = candle.close
        v.bars_held += 1

        entry = v.entry_price
        sl_price = entry * (1.0 - self.cfg.sl_pct / 100.0)
        # 슬리피지: exit은 불리하게 체결 (long exit = close보다 낮게)
        slip_exit = 1.0 - self.cfg.slippage_bps / 10000.0

        exit_price: Optional[float] = None
        exit_reason = ""

        if self.cfg.exit_type == "old":
            tp_price = entry * (1.0 + self.cfg.tp_pct / 100.0)

            if high >= tp_price:
                exit_price = tp_price           # limit TP = 슬리피지 없음
                exit_reason = "tp"
            elif low <= sl_price:
                exit_price = sl_price * slip_exit
                exit_reason = "sl"
            elif v.bars_held >= self.cfg.timeout_bars:
                exit_price = close * slip_exit
                exit_reason = "timeout"

        else:  # partial
            tp1_price = entry * (1.0 + self.cfg.tp1_pct / 100.0)

            # SL (최우선)
            if low <= sl_price:
                exit_price = sl_price * slip_exit
                exit_reason = "tp1_then_sl" if v.tp1_hit else "sl"

            # TP1 히트 체크
            elif not v.tp1_hit and high >= tp1_price:
                v.tp1_hit = True
                v.position_size = 1.0 - self.cfg.tp1_size
                v.partial_pnl_pct = self.cfg.tp1_size * self.cfg.tp1_pct

            # Runner exits (TP1 이후)
            if exit_price is None and v.tp1_hit:
                ema20_val = feats.get("ema20_1m", 0.0)
                slope5m = feats.get("ema20_slope_5m", 0.0)
                buf_low = list(self.buf_1m)
                runner_low = (
                    min(c.low for c in buf_low[-6:-1]) if len(buf_low) >= 6 else 0.0
                )

                if runner_low > 0 and low <= runner_low:
                    exit_price = runner_low * slip_exit
                    exit_reason = "tp1_then_runner"
                elif ema20_val > 0 and close < ema20_val:
                    exit_price = close * slip_exit
                    exit_reason = "tp1_then_ema20"
                elif slope5m <= 0:
                    exit_price = close * slip_exit
                    exit_reason = "tp1_then_slope5m"

            # Timeout
            if exit_price is None and v.bars_held >= self.cfg.timeout_bars:
                exit_price = close * slip_exit
                exit_reason = "tp1_then_timeout" if v.tp1_hit else "timeout"

        if exit_price is not None:
            self._exit(v, candle.timestamp, exit_price, exit_reason)

    # ------------------------------------------------------------------
    # 청산 실행
    # ------------------------------------------------------------------

    def _exit(
        self,
        v: VariantState,
        ts: datetime,
        exit_price: float,
        exit_reason: str,
    ) -> None:
        entry = v.entry_price
        fee_pct = 2.0 * self.cfg.fee_bps / 10000.0 * 100.0  # round-trip %

        if self.cfg.exit_type == "old":
            gross_pct = (exit_price - entry) / entry * 100.0
            net_pct = gross_pct - fee_pct
        else:
            runner_gross = v.position_size * (exit_price - entry) / entry * 100.0
            gross_pct = v.partial_pnl_pct + runner_gross
            net_pct = gross_pct - fee_pct

        notional = v.entry_notional
        pnl_usdt = notional * (net_pct / 100.0)
        equity_before = v.equity_at_entry
        equity_after = equity_before + pnl_usdt

        v.equity = equity_after
        v.in_position = False
        v.n_trades += 1
        if net_pct > 0:
            v.n_wins += 1

        # MDD 갱신
        if equity_after > v.peak_equity:
            v.peak_equity = equity_after
        dd = (equity_after - v.peak_equity) / v.peak_equity * 100.0
        if dd < v.max_drawdown_pct:
            v.max_drawdown_pct = dd

        rec = TradeRecord(
            variant_id=v.variant_id,
            entry_time=v.entry_time,
            exit_time=ts,
            entry_price=entry,
            exit_price=exit_price,
            exit_reason=exit_reason,
            pnl_pct=round(gross_pct, 4),
            net_pct=round(net_pct, 4),
            tp1_hit=v.tp1_hit,
            equity_before=round(equity_before, 4),
            position_notional=round(notional, 4),
            pnl_usdt=round(pnl_usdt, 4),
            equity_after=round(equity_after, 4),
            sig_slope_15m=round(v.sig_slope_15m, 8),
            sig_slope_5m=round(v.sig_slope_5m, 8),
            sig_slope_1m=round(v.sig_slope_1m, 8),
            sig_rsi_1m=round(v.sig_rsi_1m, 2),
            sig_rsi_5m=round(v.sig_rsi_5m, 2),
            sig_pullback=round(v.sig_pullback, 4),
            sig_adx=round(v.sig_adx, 2),
            sig_volume_ratio=round(v.sig_volume_ratio, 4),
        )
        v.trade_log.append(rec)
        self._write_csv(v.variant_id, rec)

        sign = "✓" if net_pct > 0 else "✗"
        logger.info(
            "[%s] %s EXIT   %s | price=%.2f  reason=%-20s  net=%+.3f%%  equity=%.2f"
            "  [trades=%d  wr=%.1f%%  mdd=%.2f%%]",
            v.variant_id, sign,
            ts.strftime("%Y-%m-%d %H:%M"),
            exit_price, exit_reason, net_pct, equity_after,
            v.n_trades, v.win_rate, v.max_drawdown_pct,
        )

        if v.n_trades % self.cfg.stats_every == 0:
            self._print_stats(v)

    # ------------------------------------------------------------------
    # CSV 로깅
    # ------------------------------------------------------------------

    def _write_csv(self, variant_id: str, rec: TradeRecord) -> None:
        w = self._csv_writers.get(variant_id)
        if w is None:
            return
        w.writerow({
            "variant_id":        rec.variant_id,
            "entry_time":        rec.entry_time,
            "exit_time":         rec.exit_time,
            "entry_price":       rec.entry_price,
            "exit_price":        rec.exit_price,
            "exit_reason":       rec.exit_reason,
            "pnl_pct":           rec.pnl_pct,
            "net_pct":           rec.net_pct,
            "tp1_hit":           rec.tp1_hit,
            "equity_before":     rec.equity_before,
            "position_notional": rec.position_notional,
            "pnl_usdt":          rec.pnl_usdt,
            "equity_after":      rec.equity_after,
            "sig_slope_15m":     rec.sig_slope_15m,
            "sig_slope_5m":      rec.sig_slope_5m,
            "sig_slope_1m":      rec.sig_slope_1m,
            "sig_rsi_1m":        rec.sig_rsi_1m,
            "sig_rsi_5m":        rec.sig_rsi_5m,
            "sig_pullback":      rec.sig_pullback,
            "sig_adx":           rec.sig_adx,
            "sig_volume_ratio":  rec.sig_volume_ratio,
        })
        self._csv_files[variant_id].flush()

    # ------------------------------------------------------------------
    # 콘솔 통계 출력
    # ------------------------------------------------------------------

    def _print_stats(self, v: VariantState) -> None:
        if not v.trade_log:
            return
        gross_profits = sum(r.pnl_usdt for r in v.trade_log if r.pnl_usdt > 0)
        gross_losses = abs(sum(r.pnl_usdt for r in v.trade_log if r.pnl_usdt < 0))
        pf = (gross_profits / gross_losses) if gross_losses > 0 else float("inf")

        print(
            f"\n  ── [{v.variant_id}] Stats (n={v.n_trades}) ──"
            f"\n  Win Rate   : {v.win_rate:.1f}%"
            f"\n  Profit Fac : {pf:.3f}"
            f"\n  Total Ret  : {v.total_return_pct:+.3f}%"
            f"\n  Equity     : {v.equity:.2f} USDT"
            f"\n  Max DD     : {v.max_drawdown_pct:.2f}%"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="MTF Trend Pullback 페이퍼 트레이더")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument(
        "--thresholds", default="0.000285",
        help="comma-sep regime thresholds, e.g. 0.0002,0.000285",
    )
    parser.add_argument("--exit-type", choices=["old", "partial"], default="old")
    parser.add_argument("--tp", type=float, default=1.2, help="old TP%")
    parser.add_argument("--tp1", type=float, default=0.8, help="partial TP1%")
    parser.add_argument("--tp1-size", type=float, default=0.5)
    parser.add_argument("--sl", type=float, default=0.6)
    parser.add_argument("--timeout-bars", type=int, default=30)
    parser.add_argument("--initial-capital", type=float, default=1000.0)
    parser.add_argument("--notional-fraction", type=float, default=0.05)
    parser.add_argument("--leverage", type=float, default=2.0)
    parser.add_argument("--fee-bps", type=float, default=4.0)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    parser.add_argument("--warmup-hours", type=int, default=20)
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--stats-every", type=int, default=5)
    args = parser.parse_args()

    thresholds = [float(x.strip()) for x in args.thresholds.split(",")]

    cfg = PaperConfig(
        symbol=args.symbol,
        thresholds=thresholds,
        exit_type=args.exit_type,
        tp_pct=args.tp,
        tp1_pct=args.tp1,
        tp1_size=args.tp1_size,
        sl_pct=args.sl,
        timeout_bars=args.timeout_bars,
        initial_capital=args.initial_capital,
        notional_fraction=args.notional_fraction,
        leverage=args.leverage,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        warmup_hours=args.warmup_hours,
        out_dir=args.out_dir,
        stats_every=args.stats_every,
    )

    logger.info("=== Paper Trade Start ===")
    logger.info("Symbol          : %s", cfg.symbol)
    logger.info("Thresholds      : %s", cfg.thresholds)
    logger.info("Exit type       : %s", cfg.exit_type)
    if cfg.exit_type == "old":
        logger.info("TP / SL         : %.2f%% / %.2f%%", cfg.tp_pct, cfg.sl_pct)
    else:
        logger.info("TP1 / SL        : %.2f%% / %.2f%%", cfg.tp1_pct, cfg.sl_pct)
    logger.info("Notional frac   : %.2f × leverage %.1fx", cfg.notional_fraction, cfg.leverage)
    logger.info("Fee / Slippage  : %.1f bps / %.1f bps", cfg.fee_bps, cfg.slippage_bps)
    logger.info("Initial capital : %.2f USDT", cfg.initial_capital)

    runner = PaperStrategyRunner(cfg)

    async def run() -> None:
        await runner.warmup()
        logger.info("Connecting to Binance WebSocket...")
        try:
            await run_binance_kline_ws(cfg.symbol, runner.on_candle)
        finally:
            runner.close()

    asyncio.run(run())


if __name__ == "__main__":
    main()
