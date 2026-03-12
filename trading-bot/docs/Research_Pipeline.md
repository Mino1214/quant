# Full Strategy Research Pipeline

단순 백테스트/파라미터 스캔을 넘어 **시스템적 전략 연구 파이프라인**을 위한 단계별 가이드.

---

## 한눈에 보기 (요약)

**뭔가요?**  
전략을 “한 번에 규칙 몇 개만 바꾸기”가 아니라, **단계별로 연구해서 시스템으로 키우는** 흐름이다.

**어떤 데이터 씁요?**  
- **기본:** DB의 **candidate_signals 테이블** (지금까지 수집한 시그널, 예: 1.7만 건).  
  → 340만 봉이 있어도, 연구 단계에서는 “이미 나온 시그널들”만 갖고 통계·메트릭을 본다.
- **선택:** 1m 캔들 전체로 **페이퍼 백테스트** (봉 하나하나 돌리기) — 필요할 때만.

**단계 순서 (Phase 1 → 8):**

| Phase | 한 줄 요약 | 뭐 하는지 |
|-------|------------|-----------|
| **1** | Baseline 고정 | “기준 설정” 하나 정해 둠. 이후 실험은 다 이걸이랑 비교. |
| **2** | 레짐 진단 | 상승/하락/횡보/혼조 구간별로 성과 따로 본다. |
| **3** | Edge 감쇠 | 진입 후 몇 봉 지나면 엣지가 사라지는지 보고, 청산/홀딩 설계. |
| **4** | 진입 품질 | 모멘텀·풀백·위크 등으로 “약한 진입” 걸러 내기. |
| **5** | 시그널 랭킹 | 시그널에 점수 매겨서 상위 N%만 거래해 보기. |
| **6** | 메타 라벨링 | “이 시그널이 수익 낼 확률이 있나?” 예측하는 2단계 모델. |
| **7** | Kelly 사이징 | 시그널 품질에 따라 포지션 크기 다르게 (동적 사이징). |
| **8** | Walk-Forward | 기간 나눠서 train/test 반복해서 과적합 아닌지 검증. |

**정리:**  
- 연구할 때 쓰는 데이터 = **candidate_signals** (수집된 시그널).  
- 1m 봉 전부 돌리는 건 “전체 백테스트” 할 때만 옵션으로.  
- 모든 실험은 **Phase 1 baseline**이랑 비교해서 개선됐는지 본다.

**한 번에 전부 돌리기 (시그널 테이블 개수만큼 리서치):**  
- candidate_signals가 2만 개면 2만 개 전부로 Phase 1~6까지 한 번에 실행. 켜 두고 다른 일 해도 됨.
  ```bash
  python -m analysis.run_research_pipeline
  ```
  - `--limit 30000` 이렇게 주면 최대 3만 개만 사용.
  - `--with-backtest` 넣으면 Phase 7(Kelly), 8(Walk-Forward)까지 포함 (1m 캔들 돌려서 느림).

**피처 엔지니어링 리서치 사이클 (목표: Top 10% PF > 1.3):**  
- 새 피처 추가 후 데이터셋 재구축 → 파라미터 스캔·진입품질·랭킹·메타라벨링 실행 → 이전 런과 비교.  
- 상세: [Research_Cycle_Feature_Engineering.md](Research_Cycle_Feature_Engineering.md)

---

## Phase 1 — Baseline 전략 고정

**목표:** 이후 모든 개선의 기준이 되는 baseline 설정을 고정한다.

- **설정:** `config/baseline_strategy.json` (ema_distance_threshold, volume_multiplier, rsi, use_trend_filter)

**어떤 baseline을 쓰나요? (덮어쓰기 방지)**  
- **Phase 2~8에서 비교할 때 쓰는 건 항상** `baseline_metrics.json` **한 개뿐**이다.  
- 이 파일은 **`--from-candidates-db`** 로 돌렸을 때만 쓴다.  
- `--from-db`(백테스트)로 돌리면 **`baseline_metrics_backtest.json`** 등 **별도 파일**에 저장해서, `baseline_metrics.json` 은 덮어쓰지 않는다.  
→ 정리: **파이프라인 기준 = candidate_signals 기준 한 번 돌린 결과.** 백테스트는 참고용.

- **실행 (권장 — 파이프라인 비교 기준, 이걸 한 번 돌려두면 됨):**
  ```bash
  python -m analysis.run_baseline --from-candidates-db
  ```
  → `baseline_performance.csv`, `baseline_summary.txt`, `baseline_equity_curve.png`, **`baseline_metrics.json`** 생성.
- **실행 (선택 — 1m 캔들 페이퍼 백테스트, 참고용):**
  ```bash
  python3 -m analysis.run_baseline --from-db --limit 18000
  ```
  → `baseline_performance_backtest.csv`, `baseline_summary_backtest.txt`, `baseline_equity_curve_backtest.png`, `baseline_metrics_backtest.json` 생성. **기존 baseline_metrics.json 은 그대로.**

**백테스트에 baseline 프로필 사용:**
```bash
python3 -m backtest.backtest_runner --from-db --bars 18000 --profile baseline
```

**비교:** Phase 2~8에서 `load_baseline_metrics()` / `compare_to_baseline()` 은 **`baseline_metrics.json`** 만 읽는다 (= `--from-candidates-db` 결과).

---

## Phase 2 — 트렌드 정렬 및 레짐 진단

**목표:** TRENDING_UP / TRENDING_DOWN / RANGING / CHAOTIC 별 성과를 공식화·문서화.

- **트렌드 필터:** config `use_trend_filter` 또는 스캔 시 `--compare-trend` 로 trend ON/OFF 비교.
- **레짐별 스캔:** `run_stability_scan` 기본 동작으로 `parameter_scan_results_trending_up.csv` 등 4개 생성.
- **레짐 요약:** (폴더 생략 시 최신 타임스탬프 폴더 사용)
  ```bash
  python3 -m analysis.run_regime_summary
  # 또는: python -m analysis.run_regime_summary analysis/output/202603081556
  ```
- **출력:**
  - `regime_summary_table.csv` — 레짐별 average_profit_factor, best_profit_factor, average_avg_R, best_avg_R, trade_count
  - `regime_performance_chart.png`
  - `regime_diagnostics.txt`

---

## Phase 3 — Edge 감쇠 분석

**목표:** 진입 후 얼마나 오래 보유할 때 엣지가 유지되는지로 청산/홀딩 설계.

- **실행:**
  ```bash
  python3 -m analysis.run_edge_decay --from-db
  # 선택: --output-dir analysis/output
  ```
- **출력:**
  - `edge_decay_summary.csv` (스캔에서 생성 시), `edge_decay_by_horizon.csv`
  - `edge_decay_plot.png` — horizon별 avg_R
  - `optimal_holding_period.txt` — 권장 홀딩 봉 수

---

## Phase 4 — 진입 품질 튜닝

**목표:** momentum_ratio, pullback_depth, upper/lower_wick, breakout 등으로 약한 진입을 걸러 낸다.

- **실행:**
  ```bash
  python3 -m analysis.run_entry_quality_scan --from-db
  # 선택: --output-dir analysis/output
  ```
- **출력:**
  - `entry_quality_scan.csv` — 조합별 trades, winrate, avg_R, profit_factor, max_drawdown
  - `entry_quality_debug.csv` — total_candidates, after_momentum_filter, after_pullback_filter, after_wick_filter, after_breakout_filter, final_trades
  - `entry_quality_heatmaps/` — 2D 히트맵

---

## Phase 5 — 시그널 랭킹

**목표:** 모든 후보를 거래하지 않고, 점수로 정렬한 뒤 상위 N%만 거래해 PF·avg_R 개선.

- **점수 예:**  
  `score = momentum_ratio*0.4 + volume_ratio*0.2 + ema50_slope*0.2 - abs(pullback_depth_pct)*0.1 - upper_wick_ratio*0.1`
- **실행:**
  ```bash
  python3 -m analysis.run_signal_ranking --from-db
  # 선택: --output-dir analysis/output
  ```
- **출력:**
  - `signal_ranking_results.csv` — top 100%, 50%, 30%, 20%, 10% 별 메트릭
  - `ranking_performance_chart.png`
  - `ranking_summary.txt`

---

## Phase 6 — 메타 라벨링 모델

**목표:** 2단계 모델로 “이 후보가 수익 낼 가능성이 있는가?”를 예측 (win_probability, expected_return).

- **실행:**
  ```bash
  python3 -m analysis.run_meta_labeling --from-db
  # 선택: --output-dir analysis/output
  ```
- **출력:**
  - `meta_model_results.csv` — logistic_regression, random_forest, gradient_boosting 정확도 등
  - `feature_importance.csv`
  - `meta_model_summary.txt`

---

## Phase 7 — Kelly 포지션 사이징

**목표:** 시그널 품질에 따라 동적 포지션 사이즈 (저품질 스킵, 고품질 fractional Kelly).

- **실행:** (baseline 설정에 Kelly 이미 포함)
  ```bash
  python3 -m analysis.run_kelly_sizing --from-db
  # 선택: --bars 50000 --output-dir analysis/output
  ```
- **출력:**
  - `kelly_sizing_results.csv` — 거래별 kelly_fraction, allocated_risk_pct
  - `equity_curve_kelly.png`
  - `risk_analysis.txt`

---

## Phase 8 — Walk-Forward 검증

**목표:** 시간 구간을 나누어 train/test 반복으로 일반화 성능 확인.

- **실행:**
  ```bash
  python3 -m analysis.walk_forward
  # 선택: --output-dir analysis/output --save-db
  ```
- **출력:**
  - `walk_forward_results.csv` — fold별 train/test 기간, trades, profit_factor, avg_R, drawdown, stability_score
  - `walk_forward_equity.png`
  - `walk_forward_summary.txt`

---

## 파이프라인 전체 구조

1. **후보 시그널 생성** (기존 전략 로직)
2. **레짐 필터** (Phase 2)
3. **진입 품질 필터** (Phase 4)
4. **시그널 랭킹** (Phase 5)
5. **메타 라벨링 모델** (Phase 6)
6. **동적 포지션 사이징** (Phase 7)
7. **Walk-Forward 검증** (Phase 8)

모든 실험은 **Phase 1 baseline** 메트릭과 `compare_to_baseline()` 로 비교하여 profit factor, avg_R, drawdown, robustness 개선 여부를 판단한다.
