# 자동화 시 얻는 것 + 결과 보며 수정할 수 있는 부분

## 1. 프로젝트를 자동화하면 얻을 수 있는 것

### 1.1 데이터가 계속 쌓인다

| 자동화 요소 | 얻는 것 |
|-------------|---------|
| **Paper 24/7** | 1m 봉이 WebSocket으로 계속 들어와 **btc1m, btc5m, btc15m**에 저장됨. 나중에 백테스트·리서치할 때 쓸 수 있음. |
| **리서치 파이프라인 (cron)** | **sync** → 최신 봉 보강. **build_dataset** → 과거 봉으로 후보 시그널(**candidate_signals**) 생성. **outcomes** → 각 후보의 실제 수익률(**signal_outcomes**) 계산. 이렇게 **feature + 레이블**이 계속 쌓임. |

→ 자동화만 해두면 **학습/검증에 쓸 데이터**가 저절로 늘어남.

---

### 1.2 모델이 주기적으로 갱신된다

| 자동화 요소 | 얻는 것 |
|-------------|---------|
| **step_ml** (파이프라인) | **candidate_signals + signal_outcomes**로 “승률/예상 R” 예측 모델 재학습 → **ml/models/** 에 저장. |
| **step_online_ml** (선택) | 더 많은 데이터로 재학습하고, 성능이 좋으면 해당 모델로 배포. |

→ 시장이 바뀌어도 **일정 주기로 자동 재학습**되면, 오래된 모델에 묶여 있지 않을 수 있음.

---

### 1.3 성과를 숫자로 계속 볼 수 있다

| 보는 곳 | 얻는 것 |
|---------|---------|
| **GET /paper/performance?days=7** | 최근 N일 **Paper만** 집계: 거래 수, 승/패, 승률, PnL, 평균 R. |
| **GET /today_summary** | 오늘 하루 거래 수, 승률, PnL. |
| **GET /trades/recent** | 최근 체결 목록. |
| **DB (trade_records, candidate_signals)** | 장기적으로 “언제 어떤 조건에서 진입/블록됐는지” 분석 가능. |

→ **가만히 두어도** 주기적으로 API/DB만 보면 Paper 성과를 추적할 수 있음.

---

### 1.4 Live 전환을 안전하게 준비할 수 있다

- Paper를 **일정 기간(예: 1~4주)** 켜두고, 위 성과 API로 **승률·평균 R·PnL**을 본 뒤 기준을 정해 Live 전환 여부를 결정할 수 있음.
- 리서치 파이프라인을 돌려두면 **스태빌리티 스캔·워크포워드·ML** 결과도 쌓이므로, “어느 구간이 안정적인지” 같은 정보를 보고 전략/파라미터를 다듬을 수 있음.

---

### 1.5 손으로 할 일이 줄어든다

- 매번 터미널에서 `sync` → `build_dataset` → `outcomes` → `train` 을 실행할 필요 없음.
- cron으로 **한 번 설정**해 두면, 정해진 시간에 위 단계가 자동 실행됨.

---

## 2. 결과를 보며 수정할 수 있는 부분

“어디를 보고” → “무엇이 문제일 때” → “어떤 설정/코드를 고치면 되는지” 순서로 정리함.  
설정은 모두 **config/config.json** 에 있음.

---

### 2.1 “진입이 너무 없다” / “시그널이 거의 안 나온다”

| 볼 것 | 의심되는 부분 | 수정할 곳 (config.json) |
|-------|----------------|-------------------------|
| 로그: `Regime block` 자주 출력 | 레짐 필터가 대부분 차단 | **regime.enabled** → `false` 로 끄기. 또는 **regime.adx_min**, **regime.natr_min/max**, **regime.score_threshold** 완화. |
| 로그: `Approval block: score=4 threshold=5` | 승인 점수 부족으로 차단 | **approval.approval_threshold** 낮추기 (예: `4`). 또는 **approval.*** 항목들(volume_multiplier_min, breakout_required 등) 완화. |
| 로그: `ML block` | ML 필터가 차단 | **ml.enabled** → `false` 로 끄기. 또는 **ml.threshold_win_prob**, **ml.threshold_expected_r** 낮추기. |
| 로그: `Capital allocation block` / `signal_quality_score <= threshold` | 품질 점수 임계값 | **capital_allocation.min_quality_threshold** 낮추기 (예: `0.45`). |
| 로그: `Kelly block` | Kelly가 거래 스킵 | **kelly.enabled** → `false` 또는 **kelly.avg_win_R** 올리기 / **kelly.avg_loss_R** 완화. |
| Bias/trend/trigger 는 나오는데 진입만 없음 | 위 필터들 중 하나 | 위 항목을 순서대로 확인. |

→ **진입 개수**는 주로 **regime / approval / ml / capital_allocation / kelly** 쪽 임계값으로 조절 가능함.

---

### 2.2 “진입은 많은데 승률이 낮다” / “손실이 많다”

| 볼 것 | 의심되는 부분 | 수정할 곳 |
|-------|----------------|-----------|
| **/paper/performance** 에서 win_rate 낮음, avg_r 마이너스 | 조건이 너무 느슨함 | **approval.approval_threshold** 올리기 (예: `6`). **regime.enabled** `true` 유지하고 **regime.score_threshold** 올리기. |
| | | **ml.enabled** `true` 로 두고 **ml.threshold_win_prob**, **ml.threshold_expected_r** 올리기 (예: 0.62, 0.3). |
| | | **capital_allocation.min_quality_threshold** 올리기 (예: `0.6`). |
| 승률은 괜찮은데 한 번 질 때 크게 짐 | 손절/포지션 크기 | **risk.atr_multiplier** (손절 폭), **risk.partial_tp_***, **risk.trailing_atr_multiplier** 점검. **kelly.max_risk_per_trade_pct** / **capital_allocation.tiers** 로 1회 리스크 축소. |

→ **품질**을 올리려면 **approval / regime / ml / capital_allocation** 의 임계값을 **올리는** 방향으로 조정.

---

### 2.3 “진입도 적고 수익도 별로다”

- 위 2.1로 **진입이 나오게** 완화한 뒤, 2.2처럼 **승률/손실**을 보면서 **approval, regime, ml, min_quality_threshold** 를 조금씩 올려서 “거래 수 vs 승률” 균형을 찾는 식으로 수정하면 됨.
- **strategy.*** (ema_fast, ema_mid, volume_multiplier, rsi_long_min 등) 은 **전략 감도**를 바꿈. 리서치 파이프라인에서 나오는 **스태빌리티 스캔·워크포워드** 결과를 보고, 어떤 구간이 좋은지 참고한 뒤 조정하는 것이 좋음.

---

### 2.4 “낙폭이 크다” / “한 번에 너무 많이 잃는다”

| 볼 것 | 수정할 곳 |
|-------|-----------|
| 1회 거래 리스크 | **risk.risk_per_trade_pct** 낮추기. **kelly.max_risk_per_trade_pct**, **capital_allocation.tiers** 의 risk_pct 값들 낮추기. |
| 동시 포지션/총 리스크 | **capital_allocation.max_portfolio_risk_pct** 낮추기 (예: `4`). |
| 레버리지 | **leverage.max_leverage** 낮추기. **leverage.regime_leverage** 값들 줄이기. |
| 일일 한도 | **risk.daily_loss_limit_r**, **risk.max_trades_per_day** 확인. |

→ **risk / kelly / capital_allocation / leverage** 가 “결과를 보며 수정할 수 있는 부분”임.

---

### 2.5 “학습(ML)이 제대로 반영되고 싶다”

| 하고 싶은 것 | 수정/확인할 것 |
|--------------|----------------|
| Paper에서 ML로 필터링 쓰기 | **ml.enabled** → `true`. **ml.threshold_win_prob**, **ml.threshold_expected_r** 설정. |
| 학습 데이터가 쌓이게 | 리서치 파이프라인을 주기 실행해 **build_dataset → outcomes** 가 돌아가도록 함. 1m 백필로 **candidate_signals** 가 충분히 쌓인 뒤 **step_ml** 이 돌아가야 함. |
| 더 공격적/보수적으로 | **ml.threshold_win_prob**, **ml.threshold_expected_r** 낮추면 진입 많아지고, 올리면 진입 줄고 품질 위주로. |

→ **결과(승률/PnL)** 를 보면서 **ml.enabled** 와 **ml.threshold_*** 만 바꿔도 어느 정도 조정 가능함.

---

### 2.6 요약: 결과 → 수정 부위 매핑

| 보고 싶은 결과 | 주로 보는 곳 | 주로 수정하는 config 섹션 |
|----------------|-------------|---------------------------|
| 진입 개수 늘리기 | 로그 (Regime/Approval/ML/Capital/Kelly block) | regime, approval, ml, capital_allocation, kelly |
| 승률/품질 올리기 | /paper/performance, /today_summary | approval, regime, ml, capital_allocation (임계값 상향) |
| 낙폭/1회 리스크 줄이기 | /trades/recent, PnL | risk, kelly, capital_allocation, leverage |
| 전략 감도/파라미터 | 스태빌리티·워크포워드 결과, analysis/output | strategy, regime (일부) |

설정 변경 후에는 **Paper+API 프로세스를 한 번 재시작**해야 반영됨.  
(문서 버전: 1.0)
