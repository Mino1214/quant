# Full System Specification + Implementation Checklist

Quantitative trading research and execution system. This document summarizes the architecture, maps modules to the codebase, and provides implementation and test checklists so each stage can be verified independently.

---

## 1. System Overview

End-to-end flow:

```
Market Data
    ↓
Feature Builder (1m / 5m / 15m + Cross-Market)
    ↓
Signal Generator
    ↓
Signal Dataset (DB + outcomes)
    ↓
Research Analysis (distribution, stability, walk-forward)
    ↓
Edge Stability Map
    ↓
Walk Forward Validation
    ↓
ML Signal Quality (offline + online)
    ↓
Signal Quality Ranking
    ↓
Kelly Risk Scaling
    ↓
Regime Adaptive Leverage
    ↓
Capital Allocation Engine
    ↓
Execution Engine
```

The system supports:
- Continuous data updates (Binance sync, cross-market)
- Research automation (pipeline, reports)
- Paper and live execution with dynamic position sizing

---

## 2. Module Map (Concept → Actual Paths)

| Conceptual module | Actual path(s) |
|------------------|----------------|
| **data / market_data_sync** | `storage/binance_sync.py`, `storage/cross_market_sync.py` |
| **data / candle_loader** | `storage/candle_loader.py`, `storage/cross_market_loader.py` |
| **features / feature_builder** | `strategy/feature_extractor.py`, `features/multi_tf_feature_builder.py`, `features/cross_market_feature_builder.py` |
| **features / regime_detector** | `features/regime_detector.py`, `strategy/filters/market_regime.py` |
| **signals / signal_generator** | `strategy/mtf_ema_pullback.py`, `strategy/approval_engine.py` |
| **signals / signal_dataset_builder** | `scripts/build_signal_dataset.py`, `storage/signal_dataset_logger.py`, `storage/signal_outcome.py` |
| **backtest** | `backtest/backtest_runner.py`, `risk/position_size.py` (sizing) |
| **research / signal_distribution** | `analysis/run_signal_analysis.py`, `analysis/distributions.py`, `storage/signal_distribution_export.py` |
| **research / edge_stability_map** | `analysis/run_stability_scan.py`, `analysis/stability_map.py` |
| **research / walk_forward** | `analysis/walk_forward.py` |
| **ml / signal_quality_model** | `ml/train.py`, `ml/predictor.py`, `ml/online_training.py` |
| **risk / kelly_allocator** | `execution/kelly_allocator.py` |
| **risk / position_sizing** | `risk/position_size.py`, `execution/capital_allocator.py`, `execution/leverage_manager.py` |
| **execution / order_executor** | `execution/paper_broker.py`, `execution/binance_broker.py`, `execution/base_broker.py`, `core/engine.py` |
| **scheduler / research_pipeline** | `scheduler/research_pipeline.py` |
| **storage** | `storage/database.py`, `storage/models.py`, `storage/repositories.py`, `storage/trade_logger.py` |

Supporting packages: `config/`, `core/` (engine, state, models), `indicators/`, `market/`.

---

## 3. Data Layer

**Responsibilities**
- Download Binance candles (1m, 5m, 15m) and persist to MySQL.
- Optional: ETH 1m, BTC funding rate, BTC open interest (`cross_market_sync`).
- Load candles by table/symbol/end_ts for features and backtest.

**Tables**
- `btc1m`, `btc5m`, `btc15m`
- Optional: `eth1m`, `btc_funding`, `btc_open_interest`

**Implementation checklist**
- [ ] `storage/binance_sync.sync_binance_to_db()` runs and fills btc1m/5m/15m.
- [ ] Missing candle ranges are backfilled (no large gaps).
- [ ] Continuous update: last openTime/ts used correctly for incremental sync.
- [ ] (Optional) `storage/cross_market_sync.sync_all_cross_market()` fills eth1m, btc_funding, btc_open_interest.
- [ ] `storage/candle_loader.load_1m_from_db` / `load_5m_last_n` / `load_15m_last_n` / `load_1m_before_t_last_n` return correct candles.

**Test checklist**
- [ ] Sync one symbol/interval and verify row count and timestamp range.
- [ ] Load candles with `end_ts` and assert only `timestamp <= end_ts`.
- [ ] Run sync twice; assert no duplicate key errors and data consistent.

---

## 4. Feature Builder

**Responsibilities**
- Compute indicators: EMA, RSI, ATR, ADX, volume ratio, EMA slope, NATR (see `indicators/`).
- Multi-timeframe: 1m entry, 5m trend, 15m regime (`features/multi_tf_feature_builder.py`).
- Cross-market: ETH and derivatives features (`features/cross_market_feature_builder.py`).
- All features use only data at or before signal timestamp T (no future leakage).

**Implementation checklist**
- [ ] Feature calculation is correct (unit test or spot check vs known values).
- [ ] Multi-TF merge: 1m/5m/15m features aligned to T and merged into one dict.
- [ ] Cross-market merge: ETH + funding + OI merged when data exists; missing → 0/default.
- [ ] No NaN propagation: fillna(0) or safe defaults in train/predict and feature builders.
- [ ] `features/regime_detector` (and regime filter) produce consistent regime labels.

**Test checklist**
- [ ] Given fixed candles, `build_multi_tf_features` output keys match `MULTI_TF_FEATURE_KEYS`.
- [ ] Given T, no feature uses a candle with timestamp > T.
- [ ] `build_cross_market_features` returns expected keys; absent DB tables → zeros.

---

## 5. Signal Generator

**Responsibilities**
- Produce candidate signals (e.g. MTF EMA pullback): timestamp, entry_price, direction, regime, trend, approval score, features.
- Include both executed and rejected (blocked) candidates for dataset.

**Implementation checklist**
- [ ] Signal detection: `evaluate_candidate` returns a candidate when conditions are met.
- [ ] Approval/scoring: `approval_engine.score` and filters (regime, signal_quality) behave as configured.
- [ ] Dataset logging: every candidate (executed or blocked) is written to DB with features (and optionally `feature_values_ext`).

**Test checklist**
- [ ] On a short candle series, at least one candidate is generated when conditions are met.
- [ ] Blocked candidates are logged with `trade_outcome="blocked"` and reason.
- [ ] Logged rows contain expected fields (timestamp, entry_price, direction, approval_score, feature_values_ext when used).

**3단계 검증 스크립트**: `scripts/verify_signal_generator.py`  
실행: `cd trading-bot && PYTHONPATH=. python scripts/verify_signal_generator.py`  
DB 로깅 실패 시: `candidate_signals` 테이블에 `time`, `feature_values_ext` 등 현재 모델 스키마와 일치하는지 확인. `init_db()`는 기존 테이블을 변경하지 않으므로, 컬럼이 없으면 ALTER TABLE 또는 테이블 재생성 필요.

---

## 6. Signal Dataset

**Responsibilities**
- Store all candidate signals and, where available, outcomes (e.g. future_r_5/10/20/30, tp/sl first, bars_to_outcome).
- Support CSV/Parquet export if needed; primary storage is DB (`candidate_signals`, `signal_outcomes`).

**Fields (conceptual)**
- timestamp, entry_price, direction, regime, trend_direction, approval_score, ema_distance, volume_ratio, rsi, trade_outcome, R_return (e.g. future_r_30), holding_time, and extended features in `feature_values_ext`.

**Implementation checklist**
- [ ] Dataset build: `build_signal_dataset` or equivalent fills `candidate_signals` from candles + strategy.
- [ ] Features and extended features are stored (e.g. in `feature_values_ext` JSON).
- [ ] Outcomes: `compute_outcome_for_signal` and `save_signal_outcome` fill `signal_outcomes` so that `get_candidate_signals_with_outcomes` returns complete rows.
- [ ] R_return (and holding_time if used) are correct for the chosen horizon.

**Test checklist**
- [ ] Build dataset on a small window; verify row count and presence of feature columns.
- [ ] After outcome computation, `get_candidate_signals_with_outcomes` returns non-null R_return (or future_r_*) where expected.
- [ ] When `feature_values_ext` is present, it is merged into the row dict for ML.

**4단계 검증 스크립트**: `scripts/verify_signal_dataset.py`  
실행: `cd trading-bot && PYTHONPATH=. python3 scripts/verify_signal_dataset.py`  
- `compute_outcome_for_signal` → SignalOutcome (future_r_5/10/20/30) 확인.  
- `get_candidate_signals_with_outcomes` row 구조 확인 (DB 스키마 불일치 시 SKIP).

---

## 7. Signal Distribution Analysis

**Responsibilities**
- R distribution, approval score vs avg_R, feature bins vs avg_R, regime performance, holding time vs profit, time-of-day performance.

**Implementation checklist**
- [ ] Histograms/charts generated (e.g. R distribution, approval vs outcome).
- [ ] Feature bins and regime breakdowns computed.
- [ ] Regime analysis: performance by regime (e.g. TRENDING_UP/DOWN, RANGE, CHAOTIC) available.

**Test checklist**
- [ ] Run analysis on a small dataset; no crash; outputs (files or DB) exist.
- [ ] At least one histogram and one regime table/chart are produced.

**5단계 검증 스크립트**: `scripts/verify_research_analysis.py`  
실행: `cd trading-bot && PYTHONPATH=. python3 scripts/verify_research_analysis.py`  
- distributions 함수들 (r_distribution, score_vs_outcome, regime_performance 등) 샘플 데이터로 동작 확인.  
- run_analysis(rows, output_dir) 실행 후 크래시 없음; 차트는 `analysis/output` 에 저장.

---

## 8. Edge Stability Map

**Responsibilities**
- Parameter grid scan (e.g. ema_distance, volume_multiplier, momentum_ratio).
- Detect stable regions of profitability; optionally visualize.

**Implementation checklist**
- [ ] Grid search runs (e.g. `run_stability_scan` / stability_map).
- [ ] Stability regions or best parameter sets are identified and stored (e.g. `parameter_scan_results`).
- [ ] Visualization or report is produced (e.g. in `analysis/output`).

**Test checklist**
- [ ] Run with a small grid; completion without error.
- [ ] Results table/report contains expected metrics (e.g. winrate, avg_R, profit_factor).

**6단계 검증 스크립트**: `scripts/verify_edge_stability.py`  
실행: `cd trading-bot && PYTHONPATH=. python3 scripts/verify_edge_stability.py`  
- run_parameter_scan 샘플 그리드로 실행, 결과에 trades/winrate/avg_R/profit_factor 등 확인.  
- plot_heatmaps로 히트맵 파일 생성 확인.

---

## 9. Walk Forward Validation

**Responsibilities**
- Train on past window, test on next window; slide forward.
- Log performance and stability across windows.

**Implementation checklist**
- [ ] Train/test split is time-based (no shuffle).
- [ ] Performance (e.g. profit factor, avg_R, drawdown) is logged per fold.
- [ ] Stability across windows is measured (e.g. variance of metrics).

**Test checklist**
- [ ] Run walk-forward with 2–3 folds; no crash.
- [ ] Each fold has train period and test period; results stored (e.g. `walk_forward_results`).

**7단계 검증 스크립트**: `scripts/verify_walk_forward.py`  
실행: `cd trading-bot && PYTHONPATH=. python3 scripts/verify_walk_forward.py`  
- `_metrics_from_trades`로 profit_factor, avg_R, drawdown 계산 확인.  
- `default_folds()` 폴드 개수·구조 확인.  
- `run_walk_forward` 단일 폴드(짧은 기간) 실행 후 결과 키 확인.

---

## 10. ML Signal Quality

**Responsibilities**
- Predict probability of positive R and expected R from signal features (1m/5m/15m + cross-market when available).
- Offline training: `ml/train.py`. Online: `ml/online_training.py`. Inference: `ml/predictor.py`.

**Implementation checklist**
- [ ] Model trains: `train_models(rows, model_dir, r_key)` completes and writes `*_clf.joblib`, `*_reg.joblib`, `feature_cols.joblib`.
- [ ] Predictions are used in trading: engine calls `predict_signal(feature_dict, model_dir)` and uses win_probability and expected_R.
- [ ] Online learning: `run_online_training` loads dataset, time-splits, trains, evaluates, saves version to `ml_models`, and optionally deploys (e.g. symlink `current`).

**Test checklist**
- [ ] Train on a small subset (e.g. 100 rows); model files and feature_cols exist.
- [ ] Predictor loads and returns win_probability and expected_R for a sample feature dict.
- [ ] Online pipeline runs when min_signals is met; if not met, it skips without error.

**8단계 검증 스크립트**: `scripts/verify_ml_signal_quality.py`  
실행: `cd trading-bot && PYTHONPATH=. python3 scripts/verify_ml_signal_quality.py`  
- `train_models`로 60행 더미 데이터 학습 후 rf_clf, rf_reg, feature_cols.joblib 생성 확인.  
- `predict_signal(feature_dict, model_dir)`로 win_probability, expected_R, signal_quality_score 반환 확인.  
- `time_based_split`, `should_deploy` 등 온라인 러닝 유틸 동작 확인.

---

## 11. Kelly Capital Allocation

**Responsibilities**
- Compute raw Kelly from win_probability, avg_win_R, avg_loss_R; apply fractional Kelly and risk caps.
- Output final risk % for position sizing; do not override max_risk_per_trade or max_portfolio_risk.

**Implementation checklist**
- [ ] Kelly fraction computed: `raw_kelly_fraction`, `kelly_risk_pct` or `compute_kelly_risk` match spec (b = avg_win_R/|avg_loss_R|, raw_kelly = p - q/b).
- [ ] raw_kelly <= 0 → skip trade (engine does not place order).
- [ ] Position size is scaled by final_risk_pct (and leverage when enabled).
- [ ] Leverage and portfolio limits: max_risk_per_trade, max_portfolio_risk always enforced (e.g. in capital_allocator).

**Test checklist**
- [ ] Unit test: given p, avg_win_R, avg_loss_R, assert raw_kelly and capped risk_pct.
- [ ] Integration: engine with Kelly enabled uses final_risk_pct and respects cap (e.g. 1%).

**9단계 검증 스크립트**: `scripts/verify_kelly_risk.py`  
실행: `cd trading-bot && PYTHONPATH=. python3 scripts/verify_kelly_risk.py`  
- Kelly: `raw_kelly_fraction`, `kelly_risk_pct`, `compute_kelly_risk` (skip when raw ≤ 0).  
- Capital allocator: `score_to_risk_pct`, `apply_regime_multiplier`, `get_position_size`(override_risk_pct·포트폴리오 상한), `get_total_open_risk_pct`.

---

## 12. Execution Engine

**Responsibilities**
- Place orders (market, stop loss, take profit), manage positions, apply SL/TP/trailing and risk limits.

**Implementation checklist**
- [ ] Order placement: broker interface places market/SL/TP orders (paper or live).
- [ ] Position tracking: open position and PnL are consistent with fills.
- [ ] Risk limits: max_portfolio_risk, max_risk_per_trade, cooldown, daily limits enforced in engine/allocator.

**Test checklist**
- [ ] Paper run: one full cycle (entry → exit by SL or TP or trailing); position and PnL correct.
- [ ] With capital allocation + Kelly: position size respects allocator output and caps.

**10단계 검증 스크립트**: `scripts/verify_execution_engine.py`  
실행: `cd trading-bot && PYTHONPATH=. python3 scripts/verify_execution_engine.py`  
- `risk.position_size`: balance·risk_pct·leverage/stop_distance.  
- `ExecutionEngine.position_size`, `execute_entry` (PaperBroker 연동).  
- PaperBroker: `place_market_order`, `get_open_position`, `close_position`, 진입 후 entry/SL 설정 확인.

---

## 13. Research Automation

**Responsibilities**
- Daily (or periodic) pipeline: sync data, build dataset, run research, update ML, generate reports.

**Implementation checklist**
- [ ] Pipeline runs: `python -m scheduler.research_pipeline` (and optional flags) executes steps in order.
- [ ] Steps: sync, build_dataset, outcomes, stability, walk_forward, step_ml, step_online_ml (optional), report.
- [ ] Reports: at least a simple report file (e.g. `analysis/output/report_*.txt`) is written.
- [ ] Models: step_ml and step_online_ml run when data is sufficient; no crash when data is insufficient.

**Test checklist**
- [ ] Run pipeline with `--skip-*` flags to run only selected steps; each step completes.
- [ ] Full run (or with skips for long steps): report file exists and contains timestamp or summary.

**11단계 검증 스크립트**: `scripts/verify_research_pipeline.py`  
실행: `cd trading-bot && PYTHONPATH=. python scripts/verify_research_pipeline.py`  
- `research_pipeline` 모듈에 step_sync, step_build_dataset, step_outcomes, step_stability, step_walk_forward, step_ml, step_online_ml, run_pipeline 존재 확인.  
- `run_pipeline(..., skip_*=True)` 호출 시 리포트 파일(`report_YYYYMMDD.txt`) 생성 확인.

---

## 14. Testing Strategy (Verification Order)

Verify in this order so each stage has its dependencies validated:

| Order | Stage | What to verify |
|-------|--------|----------------|
| 1 | Data sync | Binance sync and optional cross-market sync; candle loaders |
| 2 | Feature builder | Multi-TF and cross-market features; no future leakage |
| 3 | Signal generator | Candidates and approval; logging to DB |
| 4 | Dataset builder | candidate_signals + signal_outcomes; feature_values_ext merged for ML |
| 5 | Research analysis | Distribution and regime analyses run and produce outputs |
| 6 | Edge stability | Grid scan runs; stability regions or best params stored |
| 7 | Walk forward | Time-based folds; results stored |
| 8 | ML model | Train, predict, optional online train/deploy |
| 9 | Risk engine | Kelly + capital allocator + leverage; caps enforced |
| 10 | Execution | Paper/live order flow; position and risk limits |

Each step should be runnable and verifiable before moving to the next. Use small datasets or short windows where possible to keep feedback fast.

---

## 15. Development Principles

- **Evolve gradually**: data → dataset → research → ML → execution. Avoid large rewrites before the pipeline is stable.
- **Stable pipeline**: research_pipeline and engine run end-to-end without unhandled exceptions.
- **Clean dataset**: Consistent schema, outcomes aligned with signals, no future leakage in features.
- **Robust research**: Analyses and walk-forward complete; results are interpretable and repeatable.
- **Do not optimize prematurely**: Correctness and clarity first; then performance and scaling.

---

## 16. Quick Reference — Key Entry Points

| Task | Entry point |
|------|-------------|
| Sync BTC candles | `storage.binance_sync.sync_binance_to_db()` |
| Sync cross-market | `storage.cross_market_sync.sync_all_cross_market()` |
| Build signal dataset | `scripts.build_signal_dataset.build_dataset()` or pipeline `step_build_dataset` |
| Compute outcomes | Pipeline `step_outcomes` |
| Stability scan | `analysis.run_stability_scan.main()` or pipeline `step_stability` |
| Stable region → 제안 | `analysis.parameter_suggestion_engine` (scan 결과 → recommended_config.json, 사람이 검토 후 config 반영) |
| Walk forward | `analysis.walk_forward.run_walk_forward()`; pipeline `step_walk_forward` |
| Train ML | `ml.train.train_models(rows, model_dir, r_key)`; pipeline `step_ml` |
| Online training | `ml.online_training.run_online_training(...)`; pipeline `step_online_ml` |
| Paper/live run | `main.py` or API server; engine uses `TradingEngine` with broker and settings |

---

## 17. Independent Verification Commands

Run from project root: `cd /path/to/trading-bot`. Use `python -m` or `PYTHONPATH=. python script.py` as needed.

| Step | Verify | Example command / check |
|------|--------|--------------------------|
| 1. Data sync | Tables populated, no errors | `python -c "from storage.binance_sync import sync_binance_to_db; sync_binance_to_db()"` (or run API/server once to trigger sync) |
| 2. Feature builder | Features computed, keys present | `python -c "from features.multi_tf_feature_builder import build_multi_tf_features, MULTI_TF_FEATURE_KEYS; print(MULTI_TF_FEATURE_KEYS)"` |
| 3. Signal generator | Candidates and logging | Run engine once (paper) or backtest; check DB `candidate_signals` has new rows |
| 4. Dataset builder | Outcomes + features | `python -c "from storage.database import init_db, SessionLocal; from storage.repositories import get_candidate_signals_with_outcomes; init_db(); db=SessionLocal(); r=get_candidate_signals_with_outcomes(db, limit=10); print(len(r), list(r[0].keys()) if r else 0)"` |
| 5. Research analysis | Outputs exist | `python -m analysis.run_signal_analysis` (or run pipeline with stability only) and check `analysis/output` |
| 6. Edge stability | Grid completes | `python -m analysis.run_stability_scan --from-db --output-dir analysis/output` |
| 7. Walk forward | Folds and results | `python -c "from analysis.walk_forward import default_folds, run_walk_forward; run_walk_forward(default_folds())"` |
| 8. ML model | Train and predict | `python -c "from ml.train import train_models; from storage.repositories import get_candidate_signals_with_outcomes; from storage.database import init_db, SessionLocal; init_db(); db=SessionLocal(); r=get_candidate_signals_with_outcomes(db, limit=500); train_models(r, model_dir='ml/models') if len(r)>=50 else print('need more rows')"` then `python -c "from ml.predictor import predict_signal; print(predict_signal({'ema_distance_1m':0.001,'rsi_1m':50}))"` |
| 9. Risk engine | Kelly + allocator | `python -c "from execution.kelly_allocator import compute_kelly_risk; print(compute_kelly_risk(0.62, 1.2, -1.0, None))"` and run backtest with capital_allocation + kelly enabled |
| 10. Execution | Paper flow | `python main.py` (paper) or run backtest; one full entry/exit and check logs/DB |

---

## 18. 실행 및 모니터링 가이드 (Run & Monitor)

프로젝트를 실행하고 지켜보려면 아래 순서를 권장한다.

### 1) 사전 준비

- **DB**: `DATABASE_URL` 환경 변수(또는 `config`에서)로 MySQL 연결. `storage.database.init_db()`로 테이블 생성.
- **설정**: `config/config.json`에서 `trading_mode`(paper 권장), `symbol`, 전략/리스크/캐피탈 할당 등 확인.
- **Live 시**: Binance API 키는 환경 변수(`BINANCE_API_KEY`, `BINANCE_API_SECRET`)로만 설정.

### 2) 실행 방향 (둘 중 하나)

| 목적 | 실행 방법 |
|------|-----------|
| **Paper 거래 + 실시간 모니터링** | `cd trading-bot && python main.py --mode paper --with-api` → 엔진과 API가 한 프로세스로 동작. 브라우저에서 `http://localhost:8000` (또는 UI 프록시 3000) 접속. |
| **Paper만 (로그만 보기)** | `cd trading-bot && python main.py --mode paper` → 터미널 로그로 1m 봉 수신·전략·진입/청산만 확인. |

처음에는 **Paper + API**로 띄워 두고, API 엔드포인트로 상태를 보는 흐름을 추천한다.

### 3) 모니터링 포인트

- **로그**: 1m 봉 수신, 후보 신호, 승인/블록, 진입/청산, Kelly·캐피탈 할당 관련 메시지.
- **API** (`--with-api` 사용 시):
  - `GET /status` — 엔진 상태, 심볼, 모드, 레짐 등.
  - `GET /position` — 현재 포지션(있으면).
  - `GET /trades/recent` — 최근 체결/거래.
  - `GET /pnl/today`, `GET /today_summary` — 오늘 손익·요약.
  - `GET /signals/recent` — 최근 후보 신호.
- **DB**: `candidate_signals`, `signal_outcomes`, 체결 로그 테이블에서 신호·결과·거래 이력 확인.

### 4) 리서치 파이프라인 (주기 실행)

매일 또는 주기적으로 데이터 동기화·데이터셋·아웃컴·스태빌리티·워크포워드·ML 학습을 돌리려면:

```bash
# 전체 (동기화·빌드·아웃컴·스태빌리티·워크포워드·ML·온라인ML 후 리포트)
python -m scheduler.research_pipeline

# 일부만 (예: 동기화 스킵, ML만)
python -m scheduler.research_pipeline --skip-sync --skip-build --skip-outcomes --skip-stability --skip-walk-forward
```

리포트는 `analysis/output/report_YYYYMMDD.txt`에 생성된다. 데이터가 부족하면 `step_ml` / `step_online_ml`은 스킵되도록 되어 있어 크래시 없이 동작한다.

### 4-1) 과거 1m 데이터 백필

`candidate_signals` / `step_build_dataset`을 쓰려면 1m 봉이 최소 약 931개 이상 필요하다. DB에 데이터가 없거나 적을 때 Binance에서 과거 구간을 채우려면:

```bash
# 최근 7일치 백필 (빠른 테스트용)
cd trading-bot && PYTHONPATH=. python scripts/backfill_1m.py --days 7

# 최근 30일치 (데이터셋·ML용 권장)
python scripts/backfill_1m.py --days 30

# 특정 기간 (YYYY-MM-DD)
python scripts/backfill_1m.py --from 2024-01-01 --to 2024-01-31
```

백필 후 `python -m scheduler.research_pipeline`을 실행하면 `step_build_dataset`에서 후보 신호가 쌓인다.

### 5) 백테스트로 동작 검증

실행 전/후에 전략·리스크·캐피탈 할당이 기대대로 동작하는지 확인하려면:

```bash
python main.py --mode backtest --from-db --table btc1m --bars 10000
```

DB에 1m 봉이 있어야 하며, 체결·R·승인 점수 등이 로그/DB에 쌓인다.

### 요약

1. **실행**: `python main.py --mode paper --with-api` 로 띄우고 브라우저/API로 상태 확인.  
2. **모니터링**: 로그 + `/status`, `/position`, `/trades/recent`, `/pnl/today`, `/today_summary`, DB 테이블.  
3. **리서치**: `python -m scheduler.research_pipeline` (필요 시 `--skip-*`) 로 주기 실행.  
4. **검증**: 백테스트(`--mode backtest --from-db`)와 각 단계 검증 스크립트(`scripts/verify_*.py`)로 단계별 점검.

**완전 자동화 및 Paper → Live 전환**: 별도 문서 [Automation_and_Live_Switch.md](Automation_and_Live_Switch.md) 참고.  
**Paper 진입이 안 될 때 / 리서치(학습) 흐름**: [Paper_Entry_and_Learning.md](Paper_Entry_and_Learning.md) 참고.  
**자동화로 얻는 것 + 결과 보며 수정할 부분**: [Automation_Benefits_and_Tuning.md](Automation_Benefits_and_Tuning.md) 참고.  
**시그널 데이터(과거+미래)로 뭘 배우고, 뭐가 현재 차트에 적용되는지**: [Data_Flow_and_What_Gets_Applied.md](Data_Flow_and_What_Gets_Applied.md) 참고.  
**리서치가 하는 일 + analysis/output 결과물**: [Research_and_Output_Guide.md](Research_and_Output_Guide.md) 참고.  
Paper 24/7 실행, cron 리서치 파이프라인, `GET /paper/performance?days=7` 로 승률·PnL 확인 후 Live 전환 절차 정리.

---

*Document version: 1.0. Matches the trading-bot codebase structure as of the last update.*
