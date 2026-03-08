# 리서치가 하는 일 + analysis/output 결과물 정리

## 1. 리서치가 정확히 하는 일

**리서치** = 과거 시그널 데이터로 **전략/파라미터 품질**을 진단하고, **사람이 config를 고를 때 쓸 근거**를 만드는 단계다.

| 단계 | 하는 일 | 결과로 기대하는 것 |
|------|---------|-------------------|
| **sync** | Binance에서 1m/5m/15m 최신 봉을 DB에 갭 채우기 | 다음 단계용 데이터 확보 |
| **build_dataset** | 과거 1m 봉을 한 봉씩 돌며 “이때 진입 후보였다”는 시점만 **candidate_signals** 에 저장 | 학습/분석용 후보 시그널 테이블 |
| **outcomes** | 각 후보에 대해 “그 시점 이후 실제 수익률”(future_r_5/10/20/30) 계산 → **signal_outcomes** 에 저장 | 각 시그널의 **정답(레이블)** |
| **stability** | 후보+아웃컴으로 **파라미터 그리드 스캔** (ema_distance, volume_ratio, rsi 구간별 성과) | **안정 구간** 보기 위한 히트맵·CSV |
| **walk_forward** | 기간을 나눠 학습/테스트 반복, 폴드별 성과 저장 | 시계열로 성능이 깨지지 않는지 확인 |
| **step_ml** | candidate_signals + signal_outcomes 로 “feature → 승률/예상 R” 모델 학습 → ml/models 저장 | 실시간에서 쓸 **ML 예측** |
| **step_online_ml** | (선택) 더 많은 데이터로 재학습, 성능 좋으면 배포 | 모델 주기 갱신 |
| **report** | 파이프라인 실행 시각만 기록한 **report_YYYYMMDD.txt** | “오늘 리서치 돌렸다”는 확인용 |

정리하면, 리서치는 **데이터 정리 → 레이블 계산 → 파라미터 스캔/시각화 → ML 학습 → 리포트**까지 한 번에 돌리는 흐름이고, **“기대하는 값”**은 아래 두 가지다.

- **숫자/차트**: 어떤 파라미터 구간이 괜찮은지, 승률·R·레짐별 성과 등 **객관적 근거**
- **모델 파일**: 실시간에서 쓰는 **win_probability / expected_R** 예측

---

## 2. analysis/output 에 뭐가 쌓이는지 (파일별 역할)

같은 폴더에 **두 가지 경로**에서 나온 결과가 섞여 있을 수 있다.

### 2.1 리서치 파이프라인(스태빌리티)에서 나오는 것

UI **“리서치 실행”** 또는 `python -m scheduler.research_pipeline` 실행 시 **step_stability** 가 돌면서 생성한다.

| 파일 | 의미 | 우리가 기대하는 값 |
|------|------|---------------------|
| **parameter_scan_results.csv** | ema_distance / volume_ratio / rsi 조합마다 거래 수, 승률, avg_R, profit_factor, max_drawdown | **안정 구간** 찾을 때 쓰는 원본 데이터. 이걸로 recommended_config 제안도 뽑음. |
| **heatmap_ema_vs_volume.png** | ema_distance × volume_ratio (rsi 한 값 고정) 일 때 avg_R 색상 | 구간별로 **어디가 초록(양의 R)** 인지 눈으로 확인 → stable region 선택 |
| **heatmap_ema_vs_rsi.png** | ema_distance × rsi (volume 한 값 고정) 일 때 avg_R | 위와 같음. **best 한 점**이 아니라 **초록이 넓게 퍼진 구간**을 고르는 용도. |
| **heatmap_volume_vs_rsi.png** | volume_ratio × rsi (ema 한 값 고정) 일 때 avg_R | 위와 같음. |
| **report_YYYYMMDD.txt** | “Pipeline run at …” 시각 한 줄 | 오늘 리서치 돌렸는지 확인용. |

→ **파라미터를 “best 값”이 아니라 “안정 구간 + 그 중앙”으로 고르기 위한 시각/표**가 기대하는 값이다.

### 2.2 시그널 분포 분석에서 나오는 것

**파이프라인에는 포함되지 않고**,  
`python -m analysis.run_signal_analysis --candidates-csv ... --output-dir analysis/output`  
또는 백테스트 `--export-candidates` + `--run-analysis` 로 따로 돌릴 때 생성된다.

| 파일 | 의미 | 우리가 기대하는 값 |
|------|------|---------------------|
| **r_distribution.png** | 수익률 R 의 분포(히스토그램 등) | 전략이 **얼마나 크게 이기고/지는지**, 꼬리 위험 감각. |
| **approval_score_vs_r.png** | 승인 점수 구간별 평균 R / 승률 | **approval_threshold** 를 몇으로 할지 정할 때 참고. |
| **feature_impact.png** | feature(ema_distance, volume_ratio, rsi 등) 구간별 성과 | 어떤 지표가 **진짜 수익에 기여**하는지, ML feature 선택/해석용. |
| **regime_performance.png** | 레짐(트렌드/레인지/혼란 등)별 승률·평균 R | **레짐 필터** 켜고 끄기, 레짐별 리스크 조절할 때 참고. |
| **holding_time_vs_profit.png** | 보유 봉 수 vs 수익 | **TP/트레일링/청산 타이밍** 잡을 때, Edge Decay 느낌으로 “몇 봉까지 edge가 있는지” 참고. |
| **time_of_day.png** | 시간대별 성과 | 몇 시대에 진입을 줄이거나 늘릴지 참고. |

→ **전략 품질·승인 점수·feature·레짐·보유시간**을 “숫자만 보지 말고 그림으로 한 번 더 보기” 위한 것이 기대하는 값이다.

### 2.3 그밖에

| 파일 | 의미 | 기대하는 값 |
|------|------|-------------|
| **recommended_config.json** | parameter_suggestion_engine 이 stable region 기준으로 뽑은 제안 (ema/volume/rsi 중앙값 등) | **사람이 검토한 뒤** config.json 에 반영할 후보. 자동 적용 아님. |
| **test_candidates.csv** 등 | 테스트용 후보/내보내기 CSV | 분석·디버깅용. |

---

## 3. 한 줄 요약

- **리서치가 하는 일**:  
  과거 시그널 + 아웃컴(미래 수익률)로 **파라미터 스캔·시각화·ML 학습**을 돌리고,  
  **“어느 구간이 안정적인지”** 와 **“실시간에 쓸 예측 모델”** 을 만들어 두는 것.
- **analysis/output** 에 우리가 기대하는 값:  
  - **스캔 결과**: parameter_scan_results.csv + heatmap_*.png → **안정 구간 보고 config(필터 파라미터) 고르기**  
  - **분포/품질 차트**: r_distribution, approval_score_vs_r, feature_impact, regime_performance, holding_time_vs_profit, time_of_day → **전략·승인·feature·레짐·청산 타이밍** 판단용  
  - **제안**: recommended_config.json → **사람이 골라서 config에 반영**  
  - **확인용**: report_YYYYMMDD.txt → 리서치 실행 여부 확인

즉, **리서치는 “자동으로 best 값을 넣는 것”이 아니라, 이 결과물들을 보고 사람이 config를 골라 넣기 위한 근거를 만드는 것**이다.
