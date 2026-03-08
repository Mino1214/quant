# Parameter Scan Calculation Audit

이 문서는 파라미터 스캔 결과의 **R_return**, **profit_factor**, **avg_R** 등이 어떻게 계산되는지, 그리고 의심스러운 값(avg_R 수백/수천, profit_factor=100, 소수 거래+극단 기대값)을 방지하기 위한 검증·제한 사항을 정리합니다.

---

## 1. R_return 계산

- **정의**: `R_return = (exit_price - entry) / risk` (롱) 또는 `(entry - exit_price) / risk` (숏).  
  `risk = abs(entry - stop_loss)`.
- **출처**:
  - **DB/리서치**: `signal_outcomes.future_r_30` → 30봉 종가 기준 R.  
    `storage/signal_outcome.py`의 `compute_outcome_for_signal` → `_r_at_price()`.
  - **백테스트**: `backtest_runner`에서 실제 청산가로 계산한 `total_r`을 `R_return`으로 저장.
- **Stop 거리 과소**: `risk`가 너무 작으면 R이 폭발할 수 있음.  
  - **조치**: `storage/signal_outcome.py`에서 `risk < abs(entry)*1e-5`이면 `risk`를 `min_risk`로 올리고,  
    모든 R을 **[-20, 20]** 구간으로 cap (`_r_at_price` 반환값 cap).
- **스캔 단계**: `analysis/stability_map.py`의 `_r_values()`로 행의 R 수집 후,  
  `metrics_for_rows()` 내부에서 평균/합 등 계산 전에 **같이 [-20, 20]으로 cap** (`_cap_r`).

---

## 2. Time-expiry(만기) 신호의 R_return

- TP/SL이 30봉 안에 안 걸리면, **30봉 종가**를 exit으로 사용해 `future_r_30` 계산.
- 즉 “시간 만기”도 하나의 R 값으로 포함되며, 별도 label=-1 같은 값은 사용하지 않음.
- 동일하게 `_r_at_price`와 스캔 단계 cap으로 극단값 방지.

---

## 3. Profit factor 계산 및 gross loss ≈ 0

- **정의**: `profit_factor = gross_profit / gross_loss`  
  (wins 합 / losses 절대값 합).
- **문제**: `gross_loss == 0`이면 분모 0 → 무한대.  
  과거에는 100으로 cap했으나, 소수 거래만으로 100이 나오면 “의심스러운 값”으로 간주.
- **조치**:
  - `analysis/stability_map.py`의 `metrics_for_rows()`에서  
    `profit_factor > 10` 또는 `inf`인 경우 **10.0으로 cap**.
  - Sanity 단계에서 `profit_factor > 10`인 행은 **플래그** 후,  
    클린 테이블(`parameter_scan_results_clean.csv`)에서는 **제외**.

---

## 4. Sanity 플래그 및 클린 테이블

다음 조건을 만족하면 **의심 행**으로 플래그하고, 클린 결과에서는 제외합니다.

| 조건 | 플래그 | 클린 테이블 |
|------|--------|-------------|
| `abs(avg_R) > 5` | `suspicious_abs_avg_r` | 제외 |
| `profit_factor > 10` | `suspicious_pf` | 제외 |
| `trades < 30` | `suspicious_low_trades` | 제외 |

- **전체 결과**: `parameter_scan_results.csv` (플래그 컬럼 포함).
- **클린 결과**: `parameter_scan_results_clean.csv` (위 조건 통과한 행만).
- **히트맵**: 클린 행만 사용해 재생성 (`plot_heatmaps(cleaned)`).

---

## 5. Label = -1 / timeout 샘플 포함 여부

- 이 코드베이스에서는 “label=-1” 또는 “timeout” 전용 컬럼을 두지 않음.
- Time-expiry는 30봉 종가 기준 R로 포함되며,  
  스캔에서는 `R_return`/`future_r_30`이 있는 행만 `_r_values()`로 수집하고,  
  cap 후 평균/합에 사용되므로 **동일한 규칙**으로 처리됨.

---

## 6. 안정 구간 제안(Stable region) 기준

`analysis/parameter_suggestion_engine.py`는 **클린 스캔 결과**를 권장 입력으로 사용하며,  
다음 기준으로 “안정 구간”만 필터한 뒤, 그 구간의 중앙값을 제안합니다.

- `trades >= 50`
- `profit_factor > 1.2`
- `avg_R > 0.05`
- `max_drawdown` 이하 (설정값)

**넓은 안정 구간(broad stable region) 선호**:  
isolated peak보다는 여러 파라미터 조합이 위 조건을 만족하는 구간의 중앙을 사용합니다.  
`_meta.stable_region_size`로 해당 구간 크기를 확인할 수 있습니다.

---

## 7. 요약

| 항목 | 처리 |
|------|------|
| R 계산 | risk 과소 시 min_risk 적용 + R cap [-20, 20] (outcome + 스캔) |
| Time-expiry | 30봉 종가 R로 포함, 동일 cap |
| profit_factor | inf/과대 시 10.0 cap; >10 이면 sanity 플래그 후 클린에서 제외 |
| 소수 거래 | trades < 30 플래그 후 클린에서 제외 |
| avg_R 극단값 | abs(avg_R) > 5 플래그 후 클린에서 제외 |
| 히트맵/제안 | 클린 테이블만 사용; 제안은 trades≥50, pf>1.2, avg_R>0.05 |
