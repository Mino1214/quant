"""
Entry point: paper trading (default) or backtest. API runs separately via uvicorn.
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.loader import load_config, get_approval_settings, get_capital_allocation_settings, get_kelly_settings, get_leverage_settings, get_ml_settings, get_risk_settings, get_strategy_settings, get_regime_settings, get_use_trend_filter
from core.engine import TradingEngine
from core.state import EngineState
from risk.risk_manager import RiskManager
from strategy.filters.market_regime import MarketRegimeFilter
from execution.broker_factory import create_broker
from market.binance_ws import run_binance_kline_ws

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", type=str, default="paper", choices=["paper", "backtest", "live"])
    parser.add_argument("--symbol", type=str, default=None, help="Override config symbol")
    parser.add_argument("--data", type=str, default="", help="For backtest: path to 1m CSV")
    parser.add_argument("--from-db", action="store_true", help="For backtest: load 1m from DB table (btc1m)")
    parser.add_argument("--table", type=str, default="btc1m", help="For backtest with --from-db: table name")
    parser.add_argument("--limit", type=int, default=None, help="For backtest with --from-db: 첫 봉부터 N개 (오래된 순)")
    parser.add_argument("--bars", type=int, default=None, help="For backtest with --from-db: 기준(가장 최근 봉)으로부터 이전 N봉만 사용 (권장)")
    parser.add_argument("--verbose", "-v", action="store_true", help="For backtest: 0건일 때 막힌 이유 요약")
    parser.add_argument("--with-api", action="store_true", help="Run API server with engine (paper/live). UI에서 실시간 상태 표시.")
    args = parser.parse_args()

    config = load_config()
    mode = args.mode or config.get("trading_mode", "paper")
    symbol = args.symbol or config.get("symbol", "BTCUSDT")

    # API + 엔진 한 프로세스: UI에서 실시간 차트/전략/포지션/오늘거래 표시
    if args.with_api:
        import os
        os.environ["RUN_ENGINE"] = "1"
        import uvicorn
        uvicorn.run("api.server:app", host="0.0.0.0", port=8000, reload=False)
        return

    if mode == "backtest":
        from backtest.backtest_runner import main_async
        # Patch argv for backtest_runner argparse
        patch = [sys.argv[0], "--symbol", symbol]
        if args.from_db:
            patch.append("--from-db")
            patch.extend(["--table", args.table])
            if args.bars is not None:
                patch.extend(["--bars", str(args.bars)])
            elif args.limit is not None:
                patch.extend(["--limit", str(args.limit)])
        if args.verbose:
            patch.append("--verbose")
        if args.data:
            patch.extend(["--data", args.data])
        sys.argv = patch
        asyncio.run(main_async())
        return

    # Paper or live: run realtime engine with WebSocket
    strat_settings = get_strategy_settings(config)
    risk_settings = get_risk_settings(config)
    regime_settings = get_regime_settings(config)
    approval_settings = get_approval_settings(config)
    regime_filter = MarketRegimeFilter(regime_settings) if regime_settings.enabled else None
    risk_mgr = RiskManager(risk_settings)
    initial_balance = config.get("backtest", {}).get("initial_balance", 10000.0)
    commission_rate = config.get("backtest", {}).get("commission_rate", 0.0004)
    broker = create_broker(mode, initial_balance=initial_balance, commission_rate=commission_rate)

    state = EngineState()
    engine = TradingEngine(
        state=state,
        broker=broker,
        risk_manager=risk_mgr,
        strategy_settings=strat_settings,
        risk_settings=risk_settings,
        symbol=symbol,
        balance=initial_balance,
        regime_filter=regime_filter,
        approval_settings=approval_settings,
        ml_settings=get_ml_settings(config),
        capital_allocation_settings=get_capital_allocation_settings(config),
        kelly_settings=get_kelly_settings(config),
        leverage_settings=get_leverage_settings(config),
        use_trend_filter=get_use_trend_filter(config),
    )

    def on_candle(candle, is_closed: bool, interval: str):
        if not is_closed:
            return
        state = engine.state
        if interval == "1m":
            engine.on_1m_closed(candle)
        elif interval == "5m":
            if not state.candles_5m or state.candles_5m[-1].timestamp != candle.timestamp:
                state.add_5m(candle)
            try:
                from storage.candle_persistence import save_candle_5m
                save_candle_5m(candle, table="btc5m", symbol=symbol)
            except Exception:
                pass
        elif interval == "15m":
            if not state.candles_15m or state.candles_15m[-1].timestamp != candle.timestamp:
                state.add_15m(candle)
            try:
                from storage.candle_persistence import save_candle_15m
                save_candle_15m(candle, table="btc15m", symbol=symbol)
            except Exception:
                pass

    async def run_ws() -> None:
        await run_binance_kline_ws(symbol, on_candle)

    logger.info("Starting %s mode for %s", mode, symbol)
    asyncio.run(run_ws())


if __name__ == "__main__":
    main()
