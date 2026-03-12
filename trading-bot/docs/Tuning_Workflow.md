# Strategy Tuning Workflow

튜닝은 **한 번에 최적점 하나**를 찾는 것이 아니라, **안정 구간**, **충분한 거래 수**, **양의 기대값**, **허용 가능한 낙폭**, **시간/레짐별 일관성**을 만족하는 설정을 찾는 과정이다.

## 워크플로 순서

1. **Coarse 스캔** — ema_distance, volume_ratio, rsi만 넓은 구간·희소 그리드로 스캔.
2. **트렌드 필터 비교** — baseline vs trend-filtered (`--compare-trend`).
3. **레짐별 스캔** — TRENDING_UP, TRENDING_DOWN, RANGING, CHAOTIC 별도 CSV.
4. **엣지 감쇠** — 파라미터 조합별 `edge_decay_summary.csv` + `edge_decay_heatmap.png`.
5. **Entry quality 필터** — momentum / pullback / breakout / wick를 점진 적용 후 스캔.
6. **Fine 스캔** — Coarse에서 좋은 구간 주변만 조밀 그리드 (`--stage fine --fine-from-csv`).
7. **추천 생성** — stable region + 이웃 양수 + 설명 → `recommended_config.json` + `recommended_config_explanation.txt`.

## 실행 예시

```bash
# 1) Coarse + 트렌드 비교 + 레짐 분리 + 엣지 감쇠 + 추천 (한 번에)
python3 -m analysis.run_stability_scan --from-db --compare-trend

# 2) Fine 스캔 (Coarse 결과에서 유망 구간만 조밀 스캔)
python3 -m analysis.run_stability_scan --from-db --stage fine --fine-from-csv analysis/output/202603081500/parameter_scan_results_clean.csv

# 3) 워크플로 스크립트: Coarse 후 Fine 자동 실행
python -m analysis.run_tuning_workflow --from-db --stage full
```

## 출력 파일

- `parameter_scan_results.csv` / `parameter_scan_results_clean.csv` — 전 구간 / 유효만.
- `parameter_scan_debug.csv` — 단계별 필터 생존 수 (after_ema_filter, after_momentum_filter 등).
- `parameter_scan_results_trending_up.csv`, `_trending_down.csv`, `_ranging.csv`, `_chaotic.csv`.
- `edge_decay_summary.csv`, `edge_decay_heatmap.png` — 호라이즌별 기대값·best_horizon.
- `recommended_config.json`, `recommended_config_explanation.txt` — 안정 구간 중앙값 + 이웃·레짐·호라이즌 설명.

## 원칙

- **단일 최대값이 아니라 안정 구간**을 선호한다.
- **거래 수 ≥ 200**, **profit_factor > 1.05**, **avg_R > 0**, **이웃 조합도 양수**인 구간을 추천한다.
- **어디서(레짐)** 잘 작동하는지, **몇 봉에서** 수익이 나는지(엣지 감쇠)를 함께 본다.
