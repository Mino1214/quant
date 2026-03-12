# Research Cycle: Feature Engineering

피처 추가 → 데이터셋 재구축 → 파라미터 스캔·진입품질·랭킹·메타라벨링 실행 → 이전 사이클과 비교. **목표: Top 10% Profit Factor > 1.3.**

---

## 1. 추가된 피처 (candidate_signal dataset)

| 피처 | 정의 | 용도 |
|------|------|------|
| **atr_ratio** | atr_5 / atr_50 (5m) | ATR 압축 구간 식별 (단기 변동성 대비 장기) |
| **distance_from_high_20** | (recent_high_20 - close) / close * 100 | 최근 20봉 고점 대비 거리 |
| **candle_strength** | body_size / candle_range | 봉 강도 (몸통/레인지) |
| **close_position_in_candle** | (close - low) / (high - low) | 봉 내 종가 위치 (0=저가, 1=고가) |
| **volume_spike** | volume / volume_ma20 | 거래량 스파이크 (1m) |

구현 위치: `strategy/feature_extractor.py` — `extract_feature_values()` 반환 dict에 포함.  
백테스트·`scripts/build_signal_dataset` 실행 시 새 시그널에는 자동 반영됨.

---

## 2. 데이터셋 재구축 (Rebuild)

**새 피처가 반영되려면** 시그널을 **다시 생성**해야 한다. (기존 DB 행의 `feature_values_ext`에는 과거 스키마만 있음.)

### 방법 A: 기존 DB에 이어서 채우기 (권장)

- 새 1m 데이터만 시그널로 만들 때:
  ```bash
  python -m scripts.build_signal_dataset --symbol BTCUSDT --limit 500000 --skip-existing
  ```
- 이미 있는 (time, symbol)은 건너뛰고, **새 봉만** 후보 평가해서 DB에 넣음. 새 행에는 5개 피처 포함.

### 방법 B: 전량 재구축

- `candidate_signals` / `signal_outcomes` 테이블을 비운 뒤:
  ```bash
  python -m scripts.build_signal_dataset --symbol BTCUSDT --limit 500000
  ```
- `--skip-existing` 없이 돌리면, 같은 기간을 다시 돌면서 **중복**이 생길 수 있으므로, 전량 재구축 시에는 테이블 비우기 후 한 번만 실행.

---

## 3. 리서치 사이클 한 번에 실행

파라미터 스캔 → 진입 품질 스캔 → 시그널 랭킹 → 메타 라벨링까지 한 번에 돌리고, **이전 런과 비교**·**목표(Top 10% PF > 1.3)** 확인:

```bash
# 데이터셋 먼저 재구축한 뒤 파이프라인만 실행
python -m analysis.run_research_cycle --previous-dir analysis/output/202603081730

# 데이터셋 재구축까지 포함 (새 피처 반영)
python -m analysis.run_research_cycle --rebuild-dataset --previous-dir analysis/output/202603081730

# 시그널 개수 제한 (빠른 테스트)
python -m analysis.run_research_cycle --limit 30000 --previous-dir analysis/output/202603081730
```

**옵션 요약**

| 옵션 | 설명 |
|------|------|
| `--output-dir` | 결과 디렉터리 (기본: analysis/output) |
| `--limit` | 사용할 시그널 개수 상한 (기본: 50만) |
| `--previous-dir` | 이전 런 폴더 경로 (비교 시 필수) |
| `--rebuild-dataset` | 먼저 `build_signal_dataset` 실행 |
| `--dataset-limit` | `--rebuild-dataset` 시 로드할 1m 봉 수 |

**실행 순서 (스크립트 내부)**  
1. (선택) `scripts.build_signal_dataset`  
2. Baseline (candidate_signals 기준)  
3. Parameter scan (stability) + Regime summary  
4. Entry quality scan  
5. Signal ranking  
6. Meta labeling  
7. `research_cycle_summary.txt` 생성: Top 10% PF, 이전 대비 변화, 목표 달성 여부

---

## 4. 목표 및 비교

- **목표:** Signal ranking **Top 10%** 구간의 **Profit Factor ≥ 1.3**.
- **비교:** `--previous-dir`에 이전 런 폴더를 주면, 해당 폴더의 `signal_ranking_results.csv`에서 Top 10% PF를 읽어와 현재 런과 델타를 요약에 쓴다.
- 결과는 `{output_dir}/{timestamp}/research_cycle_summary.txt`에서 확인.

---

## 5. 출력 파일 (타임스탬프 폴더 기준)

- `baseline_*.csv`, `baseline_summary.txt`, `baseline_metrics.json`
- `parameter_scan_results_*.csv`, regime 요약
- `entry_quality_scan.csv`, `entry_quality_debug.csv`
- `signal_ranking_results.csv`, `ranking_summary.txt`
- `meta_model_*.csv`, `meta_model_summary.txt`
- **`research_cycle_summary.txt`** — 새 피처 목록, 파이프라인 요약, Top 10% PF, 이전 대비, 목표 달성 여부
