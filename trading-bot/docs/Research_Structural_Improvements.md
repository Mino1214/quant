# 구조적 전략 개선 연구 (Structural Strategy Improvements)

현재 feature set(ema_distance + RSI + volume threshold)만으로는 **양의 기대수익(positive expectancy)** 이 나오지 않음이 확인되었습니다.  
이 단계에서는 **임계값 미세 조정을 멈추고**, **구조적 전략 개선**에 집중합니다.

---

## 1. 트렌드 정렬 필터 (Trend Alignment Filter)

**목적:** 역추세 진입이 음의 기대수익의 주된 원인인지 확인.

**조건:**
- **LONG:** `ema20 > ema50` 그리고 `ema50_slope > 0`
- **SHORT:** `ema20 < ema50` 그리고 `ema50_slope < 0`

**실행:**
```bash
# 트렌드 필터 없음 vs 적용 결과를 동시에 생성
python -m analysis.run_stability_scan --from-db --compare-trend
```
출력: `parameter_scan_results_clean_no_trend.csv`, `parameter_scan_results_clean_trend_filtered.csv`  
→ 두 파일의 avg_R / profit_factor 비교로 역추세 진입 영향도 판단.

---

## 2. 시장 레짐별 스캔 (Split by Market Regime)

**목적:** 전구간 평균은 음이어도, 특정 레짐에서만 양의 엣지가 있는지 확인.

**레짐:** TRENDING_UP, TRENDING_DOWN, RANGING

**실행:**
```bash
python -m analysis.run_stability_scan --from-db
```
기본으로 다음 파일이 생성됩니다.
- `parameter_scan_results_trending_up.csv`
- `parameter_scan_results_trending_down.csv`
- `parameter_scan_results_ranging.csv`

레짐별 heatmap도 `heatmap_*_trending_up.png` 등으로 저장됩니다.

---

## 3. 엣지 감쇠 / 보유 기간 분석 (Edge Decay / Holding Horizon)

**목적:**
- 진입 후 어느 시점에서 엣지가 가장 강한지
- 보유 기간이 길어지면 기대수익이 깨지는지
- TP / 트레일링 / max holding bars 설정 근거 마련

**실행:**
```bash
python -m analysis.run_edge_decay --from-db [--output-dir analysis/output]
```
출력:
- `edge_decay_by_horizon.csv`: horizon 5/10/20/30별 trades, winrate, avg_R, profit_factor
- `edge_decay_by_horizon_trend_filtered.csv`: 트렌드 필터 적용 시
- `edge_decay_by_horizon_{regime}.csv`: 레짐별
- `edge_decay_summary.txt`: 요약

**해석:** avg_R이 horizon N에서 최대이고 N+1에서 하락하면, N봉 근처에서 TP/청산 설계를 고려.

---

## 4. 후보 품질 강화 (Entry Quality Filters)

**목적:** 임계값 필터 전에, 저품질 시그널을 줄이기 위한 **진입 조건 강화**.

추가된 feature ( strategy/feature_extractor.py ):
- **pullback_depth_pct:** 최근 구간 대비 얼마나 pullback 했는지 (0~1)
- **breakout_confirmation:** 종가가 최근 고점 돌파(long) / 저점 이탈(short) 여부
- **lower_wick_ratio, upper_wick_ratio:** 마지막 봉의 하단/상단 꼬리 비율 (body/wick 구조)
- **momentum_ratio:** 기존 body/range (모멘텀 확인)

**스캔 시 적용 예:**
```bash
# 풀백 깊이 0.2~0.8, 브레이크아웃 필수, body 비율 최소 0.4
python -m analysis.run_stability_scan --from-db --min-pullback 0.2 --max-pullback 0.8 --require-breakout --min-momentum-ratio 0.4
# LONG만 상단 꼬리 짧은 것 (반등 거부 필터)
python -m analysis.run_stability_scan --from-db --max-upper-wick-long 0.3
```

데이터셋/백테스트에서 이미 `extract_feature_values`를 쓰므로, 재빌드 없이 DB/CSV에 이 컬럼들이 있으면 스캔에서 바로 사용 가능합니다. (기존 캔들만 있으면 빌드 시 자동 계산됨.)

---

## 5. 임계값 튜닝은 보조로 (Threshold Tuning Secondary)

- **구조적 필터(트렌드 정렬, 레짐 분리, 보유 기간, 진입 품질)를 먼저 적용한 뒤**, 그 결과에 대해 임계값 스캔을 진행합니다.
- 임계값 최적화만으로 기대수익을 확보하려 하지 않습니다.

---

## 기대 결과 정리

다음 순서로 확인할 수 있어야 합니다.

1. **트렌드 정렬:** 역추세 제거 후 avg_R / PF 개선 여부
2. **레짐 분리:** TRENDING_UP/DOWN/RANGING 중 특정 레짐에서만 양의 avg_R 여부
3. **보유 기간:** horizon 5/10/20/30 중 어디서 엣지가 최대인지, 길게 잡으면 깨지는지
4. **진입 품질:** pullback/breakout/body·wick 필터로 후보를 줄였을 때 스캔 지표 개선 여부

이후, 구조적 개선이 확인된 설정만 남기고, 그 위에서만 임계값(ema_distance, volume_ratio, rsi) 스캔을 이어갑니다.
