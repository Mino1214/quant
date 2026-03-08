# Binance Futures MTF Scalping Trading System

Multi-timeframe EMA Pullback strategy: 15m bias, 5m trend, 1m entry. Paper and live share the same strategy and broker interface.

## File tree

```
trading-bot/
├── config/
│   ├── config.json
│   ├── symbols.json
│   └── loader.py
├── core/
│   ├── engine.py
│   ├── state.py
│   ├── scheduler.py
│   ├── models.py
│   └── __init__.py
├── market/
│   ├── binance_rest.py   # 1m 갭 채우기 (REST klines)
│   ├── binance_ws.py
│   ├── candle_buffer.py
│   ├── timeframe_aggregator.py
│   └── __init__.py
├── indicators/
│   ├── ema.py
│   ├── atr.py
│   ├── volume.py
│   ├── swing.py
│   ├── slope.py
│   └── __init__.py
├── strategy/
│   ├── mtf_ema_pullback.py
│   └── __init__.py
├── risk/
│   ├── risk_manager.py
│   ├── position_size.py
│   └── __init__.py
├── execution/
│   ├── base_broker.py
│   ├── paper_broker.py
│   ├── binance_broker.py
│   ├── broker_factory.py
│   └── __init__.py
├── storage/
│   ├── candle_loader.py
│   ├── candle_persistence.py   # 1m/5m/15m DB 저장
│   ├── database.py
│   ├── models.py
│   ├── trade_logger.py
│   ├── repositories.py
│   └── __init__.py
├── backtest/
│   ├── backtest_runner.py
│   └── __init__.py
├── api/
│   ├── server.py
│   └── __init__.py
├── main.py
├── requirements.txt
└── README.md
```

## Run

From project root `trading-bot/`:

```bash
# Install
pip install -r requirements.txt

# Binance WebSocket 테스트 (1m kline 수신 확인)
export PYTHONPATH=.
python scripts/test_websocket.py

# Paper trading (default; needs network for Binance WebSocket)
python main.py --mode paper

# Paper + API 한 프로세스: UI에서 실시간 차트 요약·전략 상태·포지션·오늘 거래 요약 표시
python main.py --mode paper --with-api
# 이후 브라우저에서 http://localhost:8000 또는 UI 프록시 http://localhost:3000

# Backtest: CSV 또는 DB 테이블(btc1m)
python main.py --mode backtest --data path/to/1m.csv
python main.py --mode backtest --from-db
# Or: python -m backtest.backtest_runner --from-db --table btc1m --limit 50000 --symbol BTCUSDT

# API (status, config, trades, pnl)
uvicorn api.server:app --host 0.0.0.0 --port 8000
# From project root: PYTHONPATH=. uvicorn api.server:app --port 8000
```

## Config

- `config/config.json`: `trading_mode` (paper | live), symbol, strategy/risk/backtest params.
- `DATABASE_URL` env for MySQL (default in loader). 백테스트 시 `btc1m` 테이블에서 1m 봉 로드 가능 (`--from-db`).
- **Live**: Binance API 키는 반드시 환경 변수로만 설정. 코드/설정 파일에 넣지 말 것.
  - `export BINANCE_API_KEY=...` / `export BINANCE_API_SECRET=...`
  - 또는 `.env` 파일에 넣고 `python-dotenv` 등으로 로드 (`.env`는 .gitignore에 추가).

## 1m/5m/15m 저장 및 갭 채우기

서버가 꺼졌다 켜지면 WebSocket만으로는 그동안의 1m 봉이 비어 있어 5m/15m도 끊깁니다. 아래 두 가지로 맞춥니다.

1. **DB 저장**  
   - 수신한 **1m** 봉을 `btc1m`, 집계한 **5m/15m**을 `btc5m`/`btc15m`에 저장합니다.  
   - `SAVE_CANDLES=1`(기본)이면 저장, `0`이면 저장하지 않습니다.  
   - 테이블 컬럼: `open_time`(ms 권장), `open`, `high`, `low`, `close`, `volume`. `open_time`은 PRIMARY KEY 또는 UNIQUE 권장(중복 시 INSERT IGNORE로 스킵).

2. **갭 채우기**  
   - API+엔진 기동 시: DB 워밍업 후 **마지막 봉 ~ 현재(마감된 분)** 구간을 Binance REST로 조회해 1m 봉을 채우고, 그대로 5m/15m 버퍼에 반영합니다.  
   - DB가 없어도, 버퍼가 비어 있으면 최근 약 750분 치 1m을 REST로 가져와 채웁니다.

정리하면: 저장으로 재시작 후에도 이어받고, 갭 채우기로 꺼져 있던 구간을 메꿉니다.

## UI (운영 대시보드)

설정 → 실시간 모니터링 → 가상/실제매매를 위한 6개 화면 (Dashboard, Strategy, Signals, Positions, Trades, Settings).

```bash
# API 서버 먼저 실행 (터미널 1) — 포트 8000
cd trading-bot && PYTHONPATH=. uvicorn api.server:app --port 8000

# UI 개발 서버 (터미널 2) — 포트 3000
cd trading-bot/ui && npm install && npm run dev
# 브라우저 http://localhost:3000

# 포트 정리: 3000 = 웹(UI), 8000 = API. UI는 /api 요청을 Vite가 8000으로 프록시함.
# API를 8000으로 직접 쓰고 싶으면: ui/.env 에 VITE_API_URL=http://localhost:8000
```

- **Dashboard**: 모드, 심볼, 오늘 손익, 포지션, 전략 상태(15m/5m/1m)
- **Strategy**: 그룹별 파라미터 카드, Paper/Live 전환 (Live 시 2단계 확인 모달)
- **Signals**: 15m/5m/1m 조건 카드, 시그널 로그 테이블
- **Positions**: 현재 포지션, 활성 주문, 브로커 상태
- **Trades**: 거래 내역 테이블, 클릭 시 상세 패널
- **Settings**: DB/Binance 연결 테스트, 로그 export

## API endpoints

- `GET /health` — ok
- `GET /status` — mode, symbol
- `GET /config` — current config (masked)
- `POST /config` — save config (body: full JSON)
- `POST /config/reload` — acknowledge reload
- `GET /trades/recent?limit=50` — recent trades from DB
- `GET /pnl/today` — today’s realized PnL
- `GET /paper/performance?days=7` — Paper 최근 N일 성과 (승률, pnl, avg_r). Live 전환 판단용
- `GET /position` — current position (stub)
- `GET /signals/recent?limit=20` — signal log (stub)
- `POST /config/test-db` — test DB connection
- `POST /config/test-binance` — test Binance connectivity

## 자동화 및 Paper → Live 전환

Paper를 24/7 돌리고, 승률·성과가 괜찮을 때 Live로 전환하려면 **docs/Automation_and_Live_Switch.md** 참고.  
요약: Paper+API 상시 실행(systemd/nohup), cron으로 리서치 파이프라인, `GET /paper/performance?days=7` 로 확인 후 `config.json`의 `trading_mode`를 `live`로 바꾸고 API 키 설정·재시작.

## TODOs before safe live trading

1. Restrict API key to Futures only, minimal permissions.
2. Add explicit “live trading” flag and double-confirm before sending real orders.
3. Validate slippage and commission in backtest and paper.
4. On WebSocket reconnect, sync open position with exchange and resume SL/TP.
5. Test daily limits (max trades, loss/profit R) in paper.
6. Add rate limiting and error retries for Binance REST in `binance_broker.py`.
