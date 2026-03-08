"""
Minimal FastAPI: health, status, config, reload, trades/recent, pnl/today, UI endpoints.
RUN_ENGINE=1 이면 같은 프로세스에서 엔진+WebSocket 구동, 실시간 상태 노출.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any

from fastapi import Body, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config.loader import load_config, get_approval_settings, get_capital_allocation_settings, get_kelly_settings, get_leverage_settings, get_ml_settings, get_risk_settings, get_strategy_settings, get_regime_settings, get_use_trend_filter
from core.engine import TradingEngine
from core.models import Candle, CandidateSignalRecord, Direction, Timeframe
from core.state import EngineState
from risk.risk_manager import RiskManager
from strategy.filters.market_regime import MarketRegimeFilter
from execution.broker_factory import create_broker
from market.binance_rest import fill_gap_1m
from market.binance_ws import run_binance_kline_ws
from storage.binance_sync import sync_binance_to_db
from storage.candle_loader import load_1m_last_n, load_5m_last_n, load_15m_last_n
from storage.database import SessionLocal, init_db
from storage.repositories import get_paper_performance, get_recent_trades, get_pnl_today, get_today_trade_summary
from storage.signal_dataset_logger import log_candidate_signal
from core.models import TradeRecord


@asynccontextmanager
async def lifespan(app: FastAPI):
    """RUN_ENGINE=1 이면 엔진+WebSocket 백그라운드 실행."""
    if os.environ.get("RUN_ENGINE") == "1":
        config = load_config()
        symbol = config.get("symbol", "BTCUSDT")
        mode = config.get("trading_mode", "paper")
        strat = get_strategy_settings(config)
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
            strategy_settings=strat,
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
        app.state.engine = engine
        app.state.broker = broker
        app.state.state = state
        app.state.symbol = symbol
        app.state.risk_mgr = risk_mgr

        # 0) 서버 시작 시 Binance → DB 동기화 (1m, 5m, 15m 최신화)
        try:
            await asyncio.to_thread(sync_binance_to_db, symbol)
        except Exception as e:
            import logging as _log
            _log.getLogger("api.server").warning("Binance sync at startup: %s", e)

        # 0-1) 1번에서 동기화된 1m 데이터 중 candidate_signals 없는 구간만 후보 생성 + signal_outcomes 저장
        try:
            from scripts.build_signal_dataset import sync_recent_from_db
            logged, skipped = await asyncio.to_thread(sync_recent_from_db, symbol, "btc1m", 5000)
            import logging as _log
            _log.getLogger("api.server").info("Sync candidates+outcomes: logged=%d skipped=%d", logged, skipped)
        except Exception as e:
            import logging as _log
            _log.getLogger("api.server").warning("Sync candidates+outcomes at startup: %s", e)

        # 1) DB에서 있는 만큼 로드 (symbol 필터)
        did_seed = False
        try:
            hist_1m = load_1m_last_n(1000, table="btc1m", symbol=symbol)
            hist_5m = load_5m_last_n(100, table="btc5m", symbol=symbol)
            hist_15m = load_15m_last_n(100, table="btc15m", symbol=symbol)
            if hist_1m and hist_5m and hist_15m and len(hist_15m) >= 55:
                engine.seed_from_db(hist_1m, hist_5m, hist_15m)
                did_seed = True
            elif hist_1m and len(hist_1m) >= 100:
                engine.warm_up(hist_1m)
        except Exception as e:
            import logging
            logging.getLogger("api.server").warning("Warm-up skip (DB?): %s", e)
        # 2) 없는데이터 = 누락 구간 반드시 채우기 (DB 끝 ~ 지금). 그래야 소켓으로 받는 봉이 연속됨.
        import logging as _log
        for attempt in range(2):
            try:
                filled = await fill_gap_1m(engine, symbol)
                break
            except Exception as e:
                _log.getLogger("api.server").warning("Gap-fill attempt %s: %s", attempt + 1, e)
                if attempt == 0:
                    await asyncio.sleep(2)
                    continue
                raise
        # seed로 5m/15m 이미 넣었으면 rebuild 생략 (안 하면 1m만으로 재계산해서 15m이 33개로 줄어 전략 상태 안 나옴)
        if not did_seed:
            engine.rebuild_5m_15m_from_1m()
        engine.update_display_state()

        def on_candle(candle, is_closed: bool, interval: str):
            from datetime import datetime as dt
            import logging as _log
            state = engine.state
            state.last_ws_at = dt.utcnow()
            if interval == "1m":
                state.current_1m = candle
            if is_closed:
                if interval == "1m":
                    _log.getLogger("api.server").info("WS 1m CLOSED ts=%s → engine.on_1m_closed", getattr(candle, "timestamp", None))
                    engine.on_1m_closed(candle)  # 엔진 내부에서 btc1m 저장
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

        async def run_ws():
            await run_binance_kline_ws(symbol, on_candle)

        task = asyncio.create_task(run_ws())
        app.state._ws_task = task
    else:
        app.state.engine = None
        app.state.broker = None
        app.state.state = None
        app.state.symbol = None
        app.state.risk_mgr = None
    yield
    if hasattr(app.state, "_ws_task"):
        app.state._ws_task.cancel()
        try:
            await app.state._ws_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="MTF Scalping Bot API", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict:
    """서버 확인용: 이게 보이면 이 앱이 8000에서 동작 중입니다."""
    return {
        "service": "MTF Scalping Bot API",
        "version": "1.0",
        "endpoints": ["/health", "/status", "/config", "/position", "/trades/recent", "/docs"],
    }


def _mask_config(c: dict) -> dict:
    """Mask secrets for GET /config."""
    out = dict(c)
    if "api_key" in out:
        out["api_key"] = "***"
    if "api_secret" in out:
        out["api_secret"] = "***"
    return out


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/status")
def status(request: Request) -> dict:
    out = {
        "mode": "paper",
        "symbol": "BTCUSDT",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "regime": {},
    }
    try:
        config = load_config()
        out["mode"] = config.get("trading_mode", "paper")
        out["symbol"] = config.get("symbol", "BTCUSDT")
        out["regime"] = config.get("regime", {})
    except Exception:
        pass
    try:
        s = getattr(request.app.state, "state", None)
        if s is not None:
            out["engine_state"] = {
                "bias_15m": s.last_bias.value if s.last_bias else None,
                "trend_5m": s.last_trend.value if s.last_trend else None,
                "trigger_1m": s.last_trigger.value if s.last_trigger else None,
                "regime": s.last_regime,
                "regime_blocked": s.last_regime_blocked,
                "last_order_at": s.last_order_at.isoformat() + "Z" if getattr(s, "last_order_at", None) else None,
            }
            out["last_ws_at"] = s.last_ws_at.isoformat() + "Z" if getattr(s, "last_ws_at", None) else None
            if s.candles_1m:
                last = list(s.candles_1m)[-1]
                out["last_1m"] = {
                    "close": last.close,
                    "open": last.open,
                    "high": last.high,
                    "low": last.low,
                    "volume": last.volume,
                    "timestamp": last.timestamp.isoformat() + "Z",
                    "_note": "방금 마감된 1m 봉 (UTC). 전략은 마감 봉만 사용.",
                }
            if getattr(s, "current_1m", None) is not None:
                c = s.current_1m
                out["current_1m"] = {
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume,
                    "timestamp": c.timestamp.isoformat() + "Z",
                    "_note": "현재 진행 중인 1m 봉 (UTC). WS 매 틱 갱신.",
                }
    except Exception:
        pass
    return out


@app.get("/config")
def get_config() -> dict:
    try:
        return _mask_config(load_config())
    except Exception:
        return {}


@app.post("/config")
def save_config_endpoint(body: dict = Body(...)) -> dict:
    """Save config to config.json. UI sends full config (no secrets)."""
    root = Path(__file__).resolve().parent.parent
    path = root / "config" / "config.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(body, f, indent=2, ensure_ascii=False)
    return {"status": "saved"}


@app.post("/config/reload")
def config_reload() -> dict:
    # Reload from disk on next load_config() call; no cache in v1
    return {"status": "reload acknowledged"}


class TradeOut(BaseModel):
    symbol: str
    side: str
    size: float
    entry_price: float
    exit_price: float
    pnl: float
    rr: float
    reason_entry: str
    reason_exit: str
    opened_at: str
    closed_at: str


def _trade_to_out(t: TradeRecord) -> dict:
    return {
        "symbol": t.symbol,
        "side": t.side.value,
        "size": t.size,
        "entry_price": t.entry_price,
        "exit_price": t.exit_price,
        "pnl": t.pnl,
        "rr": t.rr,
        "reason_entry": t.reason_entry,
        "reason_exit": t.reason_exit,
        "opened_at": t.opened_at.isoformat(),
        "closed_at": t.closed_at.isoformat(),
        "approval_score": getattr(t, "approval_score", 0),
        "blocked_reason": getattr(t, "blocked_reason", None),
        "mode": getattr(t, "mode", "paper"),
    }


@app.get("/trades/recent")
def trades_recent(limit: int = 50) -> dict:
    try:
        init_db()
        db = SessionLocal()
        try:
            trades = get_recent_trades(db, limit=limit)
            return {"trades": [_trade_to_out(t) for t in trades]}
        finally:
            db.close()
    except Exception:
        return {"trades": []}


@app.get("/pnl/today")
def pnl_today() -> dict:
    try:
        init_db()
        db = SessionLocal()
        try:
            pnl = get_pnl_today(db)
            return {"pnl": pnl, "date": date.today().isoformat()}
        finally:
            db.close()
    except Exception:
        return {"pnl": 0.0, "date": date.today().isoformat()}


@app.get("/position")
async def position(request: Request) -> dict | None:
    """Current open position. Live when RUN_ENGINE=1."""
    if not hasattr(request.app.state, "broker") or request.app.state.broker is None:
        return None
    if not hasattr(request.app.state, "symbol"):
        return None
    pos = await request.app.state.broker.get_open_position(request.app.state.symbol)
    if pos is None:
        return None
    return {
        "symbol": pos.symbol,
        "side": pos.side.value,
        "size": pos.size,
        "entry_price": pos.entry_price,
        "stop_loss": pos.stop_loss,
        "take_profit": pos.take_profit,
        "unrealized_pnl": getattr(pos, "unrealized_pnl", None),
        "opened_at": pos.opened_at.isoformat() if pos.opened_at else None,
    }


@app.get("/signals/recent")
def signals_recent(limit: int = 20) -> dict:
    """Recent signal log. Stub until engine exposes state."""
    return {"signals": []}


@app.get("/today_summary")
def today_summary() -> dict:
    """오늘 거래 요약: count, wins, losses, win_rate, pnl."""
    default = {"count": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "pnl": 0.0}
    try:
        init_db()
        db = SessionLocal()
        try:
            out = get_today_trade_summary(db)
            return {**default, **out} if isinstance(out, dict) else default
        finally:
            db.close()
    except Exception:
        return default


@app.get("/paper/performance")
def paper_performance(days: int = 7) -> dict:
    """최근 N일간 Paper 거래 성과. Live 전환 판단용: win_rate, pnl, avg_r 등."""
    try:
        init_db()
        db = SessionLocal()
        try:
            return get_paper_performance(db, days=days, mode_filter="paper")
        finally:
            db.close()
    except Exception as e:
        return {"error": str(e), "days": days, "count": 0, "win_rate": 0.0, "pnl": 0.0, "avg_r": 0.0}


@app.post("/config/test-db")
def test_db() -> dict:
    try:
        init_db()
        db = SessionLocal()
        try:
            get_recent_trades(db, limit=1)
            return {"ok": True}
        finally:
            db.close()
    except Exception as e:
        return {"ok": False, "error": str(e)}


# --- Research: 리서치 실행 + 결과물 목록/파일 서빙 ---
RESEARCH_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "analysis" / "output"


def _run_research_pipeline(skip_sync: bool = True, skip_build: bool = False, skip_outcomes: bool = False,
                           skip_stability: bool = False, skip_walk_forward: bool = True,
                           skip_ml: bool = False, skip_online_ml: bool = True) -> dict:
    """동기 함수: research_pipeline 실행. 스킵 옵션으로 빠른 리서치 가능."""
    from scheduler.research_pipeline import run_pipeline
    try:
        run_pipeline(
            symbol="BTCUSDT",
            output_dir=str(RESEARCH_OUTPUT_DIR),
            skip_sync=skip_sync,
            skip_build=skip_build,
            skip_outcomes=skip_outcomes,
            skip_stability=skip_stability,
            skip_walk_forward=skip_walk_forward,
            skip_ml=skip_ml,
            skip_online_ml=skip_online_ml,
        )
        return {"ok": True, "message": "리서치 파이프라인 완료"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/research/run")
async def research_run(
    skip_sync: bool = True,
    skip_stability: bool = False,
    skip_walk_forward: bool = True,
    skip_ml: bool = False,
    skip_online_ml: bool = True,
) -> dict:
    """
    리서치 파이프라인 실행 (기본: sync 제외, stability 포함, walk_forward/ml/online_ml 제외로 빠르게).
    백그라운드 스레드에서 실행 후 완료 시 결과 반환. 오래 걸릴 수 있음.
    """
    result = await asyncio.to_thread(
        _run_research_pipeline,
        skip_sync=skip_sync,
        skip_build=False,
        skip_outcomes=False,
        skip_stability=skip_stability,
        skip_walk_forward=skip_walk_forward,
        skip_ml=skip_ml,
        skip_online_ml=skip_online_ml,
    )
    return result


def _research_output_files() -> list:
    """List files under analysis/output: run folders (YYYYMMDDHHmm) and research_bundle/<run_id>."""
    if not RESEARCH_OUTPUT_DIR.exists():
        return []
    out = []

    def add_file(file_path: Path, rel_path: str, run_label: str) -> None:
        low = file_path.name.lower()
        if low.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            kind = "image"
        elif low.endswith(".csv"):
            kind = "csv"
        elif low.endswith(".json"):
            kind = "json"
        elif low.endswith((".txt", ".md")):
            kind = "text"
        elif low.endswith(".html"):
            kind = "file"
        else:
            kind = "file"
        out.append({"name": file_path.name, "type": kind, "path": rel_path, "run": run_label})

    for p in sorted(RESEARCH_OUTPUT_DIR.iterdir(), reverse=True):
        if p.is_dir():
            if p.name == "research_bundle":
                for sub in sorted(p.iterdir(), reverse=True):
                    if sub.is_dir():
                        run_label = f"bundle/{sub.name}"
                        for q in sorted(sub.iterdir()):
                            if q.is_file():
                                rel = f"{p.name}/{sub.name}/{q.name}"
                                add_file(q, rel, run_label)
                    elif sub.is_file():
                        add_file(sub, f"{p.name}/{sub.name}", p.name)
            else:
                run_label = p.name
                for q in sorted(p.iterdir()):
                    if q.is_file():
                        rel = f"{p.name}/{q.name}"
                        add_file(q, rel, run_label)
        elif p.is_file():
            name = p.name
            low = name.lower()
            if low.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                kind = "image"
            elif low.endswith(".csv"):
                kind = "csv"
            elif low.endswith(".json"):
                kind = "json"
            elif low.endswith((".txt", ".md")):
                kind = "text"
            else:
                kind = "file"
            out.append({"name": name, "type": kind, "path": name, "run": None})
    return out


@app.get("/research/outputs")
def research_outputs() -> dict:
    """analysis/output 내 파일 목록 (타임스탬프 폴더 포함). type: image | csv | json | text. path로 다운로드."""
    files = _research_output_files()
    return {"files": files}


@app.get("/research/output/{file_path:path}")
def research_output_file(file_path: str):
    """결과물 파일 서빙. analysis/output 하위만 허용 (예: 202603081606/parameter_scan_results.csv)."""
    if not file_path or ".." in file_path:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid path")
    path = (RESEARCH_OUTPUT_DIR / file_path).resolve()
    if not path.is_file() or not str(path).startswith(str(RESEARCH_OUTPUT_DIR.resolve())):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="File not found")
    media = "application/octet-stream"
    if file_path.lower().endswith(".png"):
        media = "image/png"
    elif file_path.lower().endswith((".jpg", ".jpeg")):
        media = "image/jpeg"
    elif file_path.lower().endswith(".json"):
        media = "application/json"
    elif file_path.lower().endswith(".csv"):
        media = "text/csv"
    elif file_path.lower().endswith(".txt"):
        media = "text/plain"
    return FileResponse(path, media_type=media)


@app.post("/config/test-binance")
def test_binance() -> dict:
    try:
        import requests
        r = requests.get("https://fapi.binance.com/fapi/v1/ping", timeout=5)
        return {"ok": r.status_code == 200}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------- Webhook: continuous signal dataset (Phase 1) ----------


class WebhookCandleBody(BaseModel):
    """Candle payload for POST /webhook/candle. Timestamp in ISO or unix ms."""
    timestamp: str | int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class WebhookSignalBody(BaseModel):
    """Pre-computed signal snapshot for POST /webhook/signal."""
    time: str
    close: float
    side: str  # long, short
    regime: str = ""
    trend_direction: str = ""
    approval_score: int = 0
    ema_distance: float = 0.0
    volume_ratio: float = 0.0
    rsi: float = 0.0
    trade_outcome: str  # executed, blocked
    blocked_reason: str | None = None
    symbol: str = "BTCUSDT"


def _parse_ts(ts: str | int) -> datetime:
    if isinstance(ts, (int, float)):
        if ts > 1e12:
            return datetime.utcfromtimestamp(ts / 1000.0)
        return datetime.utcfromtimestamp(float(ts))
    s = str(ts).replace("Z", "+00:00")
    return datetime.fromisoformat(s)


@app.post("/webhook/candle")
async def webhook_candle(request: Request, body: WebhookCandleBody = Body(...)) -> dict:
    """
    Receive a closed 1m candle; push to engine and run strategy.
    If RUN_ENGINE=1 the engine will log the candidate signal internally.
    """
    try:
        ts = _parse_ts(body.timestamp)
        candle = Candle(
            open=body.open,
            high=body.high,
            low=body.low,
            close=body.close,
            volume=body.volume,
            timestamp=ts,
            timeframe=Timeframe.M1,
        )
        engine = getattr(request.app.state, "engine", None)
        if engine is not None:
            engine.on_1m_closed(candle)
        return {"ok": True, "message": "candle processed"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/webhook/signal")
def webhook_signal(body: WebhookSignalBody = Body(...)) -> dict:
    """Insert a pre-computed signal snapshot into candidate_signals (outcome filled later)."""
    try:
        ts = _parse_ts(body.time)
        direction = Direction(body.side) if body.side in ("long", "short") else Direction.LONG
        record = CandidateSignalRecord(
            timestamp=ts,
            entry_price=body.close,
            regime=body.regime,
            trend_direction=direction,
            approval_score=body.approval_score,
            feature_values={
                "ema_distance": body.ema_distance,
                "volume_ratio": body.volume_ratio,
                "rsi_5m": body.rsi,
            },
            trade_outcome=body.trade_outcome,
            blocked_reason=body.blocked_reason,
            symbol=body.symbol,
        )
        cid = log_candidate_signal(record)
        return {"ok": cid is not None, "candidate_signal_id": cid}
    except Exception as e:
        return {"ok": False, "error": str(e)}
