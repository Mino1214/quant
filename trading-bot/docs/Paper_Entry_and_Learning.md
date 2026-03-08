# Paper 진입이 안 될 때 + 리서치(학습) 흐름

## 0. 1m/5m/15m 저장이 안 되는 것 같을 때

- **재시작 시 로그 (sync)**: `[DONE] 1m updated rows: 14` 같은 숫자는 **갭 채우기**만 의미한다. DB에 이미 있는 **마지막 봉 이후 ~ 현재** 구간만 Binance에서 받아와 채운다. 그래서 서버를 14분 정도 꺼뒀다 켜면 14개 1m만 올 수 있다. **저장을 안 하는 게 아니라**, 그동안 비어 있던 구간만 채우는 것이다.
- **실시간 저장**: 서버가 **켜져 있는 동안**에는 WebSocket으로 들어오는 1m(및 5m/15m) 마감 봉마다 `candle_persistence`로 DB에 저장된다. 1m은 엔진 `_on_1m_closed`에서, 5m/15m은 엔진 집계 또는 WS 수신 시 API 콜백에서 저장된다.
- **저장 끄기**: `SAVE_CANDLES=0` 이면 1m/5m/15m DB 저장이 비활성화된다. 저장이 되게 하려면 설정하지 않거나 `SAVE_CANDLES=1` 로 두면 된다.
- **저장 실패**: 로그에 `Save 1m to DB failed` / `Save candle btc1m ...` 같은 경고가 보이면 DB 스키마·연결 문제일 수 있다. `storage.candle_persistence`와 `storage.binance_sync`의 테이블 스키마(openTime, o, h, l, c, v 등)가 DB와 맞는지 확인하면 된다.

---

## 1. Paper에서 진입이 안 되는 이유

진입은 **1m 봉이 마감될 때마다** 한 번씩 평가되며, 아래 조건을 **모두** 만족해야 주문이 나갑니다.

### 1.1 버퍼 조건 (가장 흔한 원인)

엔진은 **15m 50개, 5m 50개, 1m 50개**가 쌓여 있어야 전략을 돌립니다.

```
len(candles_15m) >= 50 and len(candles_5m) >= 50 and len(candles_1m) >= 50
```

- **15m**은 1m 봉이 **15분마다** 한 번씩 묶여서 만들어짐.
- 따라서 15m 50개를 만들려면 **1m 봉이 최소 750개**(50×15) 필요 → **약 12.5시간 분량**.

**처음 켰을 때 DB가 비어 있으면:**

- WebSocket으로 1m만 들어오고, 5m/15m은 이 1m을 묶어서 만듦.
- 15m 50개가 차기까지 **실제로 12.5시간** 정도 걸림.
- 그동안에는 위 조건이 안 맞아서 **진입 평가 자체가 스킵**됩니다.

**해결:** DB에 1m 과거 데이터를 미리 채워 두고 기동.

1. **백필 실행**  
   ```bash
   cd trading-bot && PYTHONPATH=. python scripts/backfill_1m.py --days 7
   ```
2. **그 다음** Paper+API 기동  
   ```bash
   python main.py --mode paper --with-api
   ```
3. 기동 시 DB에서 최근 1m 1000개를 읽어와 **warm_up**으로 5m/15m을 만들기 때문에, 15m 50개가 바로 채워지고 **곧바로 진입 평가**가 가능해짐.

DB에 **btc5m, btc15m**까지 있으면(예: `sync_binance_to_db`로 채운 경우) **seed_from_db**로 15m 55개를 바로 넣어서, 더 빠르게 진입 가능.

---

### 1.2 그 다음 단계에서 걸리는 경우

버퍼가 충분해도 아래에서 막힐 수 있습니다.

| 단계 | 조건 | 로그 예시 |
|------|------|-----------|
| **레짐** | `regime_result.allow_trading` | `Regime block: ... (ADX=... NATR=...)` |
| **방향** | LONG이면 `can_long`, SHORT이면 `can_short` | `Regime block: long not allowed` |
| **전략** | `evaluate_candidate`가 후보 생성 | 후보 없으면 로그 없이 스킵 |
| **승인** | `approval_score >= approval_threshold` (기본 5) | `Approval block: score=4 threshold=5` |
| **ML** | config에서 `ml.enabled: true`이면 win_prob, expected_R 기준 | `ML block: win_prob=0.52 expected_R=0.10` |
| **캐피탈** | signal_quality_score > min_quality_threshold, Kelly skip 아님 | `Capital allocation block` / `Kelly block` |
| **리스크** | cooldown, 일일 한도 등 | `Risk block: ...` |

로그에 위와 비슷한 메시지가 나오면, 그 단계에서 막힌 것입니다.

---

### 1.3 요약: 진입이 되게 하려면

1. **1m 백필 후 기동**  
   `backfill_1m.py --days 7` → `main.py --mode paper --with-api`  
   → 버퍼가 바로 차서 12.5시간 기다리지 않아도 됨.
2. **로그 확인**  
   `Regime block`, `Approval block`, `ML block` 등으로 어디서 막히는지 확인.
3. **테스트용으로 필터 완화**  
   - `config.json`에서 `approval.approval_threshold` 낮추기 (예: 4).  
   - `regime.enabled: false` 로 두면 레짐 필터 비활성화.  
   - `ml.enabled: false` 로 두면 ML 필터 비활성화.

---

## 2. 리서치(학습)가 어떻게 이뤄지는지

`python -m scheduler.research_pipeline` 은 아래 순서로 돌아갑니다.  
“학습”은 **step_build_dataset → step_outcomes → step_ml** (그리고 선택적으로 step_online_ml) 입니다.

```
step_sync
    → Binance에서 1m/5m/15m 최신 봉 가져와 btc1m, btc5m, btc15m 에 저장.

step_build_dataset
    → btc1m 과거 봉을 한 봉씩 돌면서, 그 시점의 5m/15m/1m으로 전략·승인·레짐 평가.
    → “이때 진입했으면” 하는 후보를 candidate_signals 테이블에 저장 (실제 주문 아님).

step_outcomes
    → 아직 결과가 없는 candidate_signals 에 대해, 그 시점 이후 실제 가격으로
      “30봉 뒤 수익률(future_r_30)” 등 계산 → signal_outcomes 테이블에 저장.
    → 즉, “그 신호가 났다면 얼마나 이득/손해였을지” 레이블을 붙이는 단계.

step_stability / step_walk_forward
    → 파라미터 그리드/폴드로 전략 안정성·워크포워드 검증 (선택).

step_ml
    → candidate_signals + signal_outcomes (feature + future_r_30 등) 를 합쳐서
      “특징(feature) → 승률/예상 R” 을 학습.
    → RandomForest/XGB/LightGBM 등으로 win_probability, expected_R 예측 모델 생성.
    → ml/models/ 에 저장 (실시간에서는 이걸로 win_prob, expected_R 사용).

step_online_ml (선택)
    → 더 많은 데이터로 같은 방식으로 재학습, 성능 좋으면 배포.
```

정리하면:

- **학습 데이터**: 과거 1m 봉으로 만든 **후보 신호(candidate_signals)** + 그에 대한 **실제 수익률(signal_outcomes)**.
- **학습 내용**: “이런 feature일 때 승률/예상 R이 이렇다”를 맞추는 모델.
- **실시간 사용**: Paper/Live 시 새 신호의 feature를 모델에 넣어 `win_probability`, `expected_R`을 구하고, ML 필터·캐피탈/Kelly 등에 사용.

그래서 **리서치**는 “과거 데이터로 시그널·결과를 만들고 → 그걸로 모델을 학습시키고 → 그 모델을 실시간에서 쓰는” 흐름입니다.

---

## 3. candidate_signals 데이터 늘리는 방법

`candidate_signals`가 적으면 파라미터 스캔·ML 학습·리서치 결과가 불안정해집니다. **과거 1m 봉**으로 후보를 만들어 DB에 채우는 방법입니다.

### 3.1 순서

1. **1m 캔들 먼저 DB에 채우기**  
   `candidate_signals`는 **btc1m** 테이블의 1m 봉을 한 봉씩 돌면서 “그 시점에 전략이 내던 후보”를 만들어 저장합니다.  
   그래서 **btc1m에 과거 1m 데이터가 있어야** 후보를 만들 수 있습니다.

   ```bash
   cd trading-bot
   # 최근 30일치 1m 백필 (필요하면 더 늘리기)
   PYTHONPATH=. python scripts/backfill_1m.py --days 30
   # 또는 구간 지정
   PYTHONPATH=. python scripts/backfill_1m.py --from 2024-01-01 --to 2024-01-31
   ```

   - 최소 **약 1,000봉 이상** 권장 (전략이 15m 50봉 등 버퍼를 쓰므로 931+ 봉 필요).  
   - 30일 1m ≈ 43,200봉이면 후보가 많이 나옵니다.

2. **build_signal_dataset으로 후보 대량 생성**  
   리서치 파이프라인의 `step_build_dataset`은 **5,000봉**만 불러와서 처리합니다.  
   데이터를 많이 만들려면 **build_signal_dataset CLI**를 직접 돌려서 **limit을 크게** 주거나 **구간을 지정**하세요.

   ```bash
   cd trading-bot
   # 최근 5만 봉 기준으로 후보 생성 (이미 있는 (symbol, time) 건너뛰기)
   PYTHONPATH=. python -m scripts.build_signal_dataset --limit 50000 --skip-existing
   # 또는 기간 지정
   PYTHONPATH=. python -m scripts.build_signal_dataset --start 2024-01-01 --end 2024-01-31 --skip-existing
   ```

   - `--skip-existing`: 이미 `candidate_signals`에 있는 (symbol, time)은 건너뜁니다.  
   - 여러 번 돌리거나 기간을 나눠 돌릴 때 유용합니다.

   **340만 봉처럼 많을 때**: 한 번에 `--limit 3400000` 해도 동작하지만, 메모리(수 GB)·실행 시간(수 시간~하루) 부담이 커질 수 있습니다. **배치 스크립트**로 월 단위 자동 실행을 권장합니다.

   ```bash
   # 월 단위로 나눠서 실행 (중간에 끊겨도 --skip-existing 로 이어서 실행 가능)
   PYTHONPATH=. python scripts/build_signal_dataset_batch.py --from 2020-01-01 --to 2024-12-31
   # 또는 최근 N일
   PYTHONPATH=. python scripts/build_signal_dataset_batch.py --days 365
   # 실행할 구간만 확인
   PYTHONPATH=. python scripts/build_signal_dataset_batch.py --from 2024-01-01 --to 2024-12-31 --dry-run
   ```

3. **아웃컴 채우기**  
   후보만 넣으면 `signal_outcomes`가 비어 있어서 스캔/ML에서 쓰이지 않습니다.  
   리서치 파이프라인에서 **step_outcomes**를 실행하면, 아직 outcome이 없는 후보에 대해 **future_r_30** 등을 계산해 넣습니다.

   ```bash
   # 파이프라인에서 outcomes만 실행 (sync/build 건너뛰기)
   python -m scheduler.research_pipeline --skip-sync --skip-build --skip-stability --skip-walk-forward --skip-ml --skip-online-ml
   ```

   또는 `step_outcomes`만 호출하는 스크립트가 있다면 그걸로 실행해도 됩니다.

### 3.2 요약

| 목적 | 명령 |
|------|------|
| 1m 데이터 채우기 | `scripts/backfill_1m.py --days 30` (또는 `--from` / `--to`) |
| 후보 대량 생성 | `scripts.build_signal_dataset --limit 50000 --skip-existing` (또는 `--start` / `--end`) |
| 아웃컴 계산 | `scheduler.research_pipeline` (build 제외, outcomes 포함) 또는 outcomes 단계만 실행 |

데이터가 적을 때는 **1m 백필 → build_signal_dataset (limit/구간 크게) → outcomes** 순서로 한 번 돌려 두면, 그 다음 스캔·ML·리서치가 훨씬 안정적으로 동작합니다.

### 3.3 테이블 비우기 (다시 채우기 전에)

`candidate_signals` / `signal_outcomes`를 비울 때는 **FK 제약** 때문에 **자식(signal_outcomes) → 부모(candidate_signals)** 순서로 지워야 합니다.

```bash
# 스크립트로 순서대로 DELETE (권장)
PYTHONPATH=. python scripts/clear_signal_tables.py
```

MySQL에서 직접 실행할 때:

```sql
DELETE FROM signal_outcomes;
DELETE FROM candidate_signals;
```

`TRUNCATE`를 쓰려면 FK 검사 잠시 끄기:  
`SET FOREIGN_KEY_CHECKS=0;` → `TRUNCATE signal_outcomes;` → `TRUNCATE candidate_signals;` → `SET FOREIGN_KEY_CHECKS=1;`

---

## 4. 한 번에 정리

| 하고 싶은 것 | 할 일 |
|-------------|--------|
| Paper에서 진입이 되게 | 1m 백필(`backfill_1m.py --days 7`) 후 Paper+API 기동. 필요 시 approval/regime/ml 완화. |
| 학습이 어떻게 되는지 이해 | pipeline: sync → build_dataset(후보 저장) → outcomes(수익률 레이블) → ml(모델 학습). 실시간은 그 모델로 win_prob/expected_R 예측. |
| 학습 데이터 쌓기 | pipeline 정기 실행(또는 수동 실행). 1m이 충분히 있어야 build_dataset이 후보를 만들고, 그 다음 outcomes·ml이 의미 있음. |
| **candidate_signals 늘리기** | 1m 백필(`backfill_1m.py --days 30`) → `build_signal_dataset --limit 50000 --skip-existing` → pipeline에서 outcomes 실행. |

*문서 버전: 1.1*
