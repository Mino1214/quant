# 시그널 데이터(과거+미래)로 뭘 배우고, 뭐가 현재 차트에 적용되는지

질문: **"signal_dataset(과거+미래)로 최적 파라미터 찾아서, 그걸 현재 차트에 적용하는 거 아냐?"**

→ **반은 맞고, 반은 아님.** 그리고 **파라미터를 자동 적용하지 않는 것은 의도된 설계**다.

---

## 0. 왜 파라미터를 자동 적용하지 않게 해두었는가 (설계 의도)

퀀트에서 가장 위험한 패턴은 다음과 같다.

**백테스트 → 최고 파라미터 발견 → 자동 적용**

이렇게 하면 거의 항상 **과최적화(Overfitting)** 가 발생한다.

- 예: `ema_distance=0.00073`, `volume_ratio=1.37`, `rsi=54.2` 가 과거 데이터에서 최고 성능일 수 있다.
- 하지만 실제 시장에서는 **다음 달에 깨지는** 경우가 많다.

그래서 기관들도 보통 이렇게 한다.

1. Scan 결과 확인  
2. **사람이** stability region(안정 구간) 확인  
3. **“best 값”이 아니라 “안정적인 범위”** 선택  
4. 그 범위의 **중앙값** 등으로 config 수정  

즉, **“best 값” 자동 적용이 아니라 “안정 구간 → 사람이 선택 → config 수정”** 이 정석 워크플로우다.

---

## 1. 데이터가 어떻게 쓰이는지 (과거 vs 미래)

| 데이터 | 역할 |
|--------|------|
| **과거 (시점 T까지)** | 시그널이 나온 **그 순간의** feature만 사용 → **입력(input)** |
| **미래 (T 이후)** | 그 시그널의 실제 수익률(future_r_5, future_r_30 등) → **정답 레이블(label)** 로만 사용. 입력에는 넣지 않음. |

---

## 2. 두 가지: ML vs 파라미터

### 2.1 ML (feature → win probability / expected R)

| | |
|---|--|
| **학습** | (과거 feature at T, 미래 outcome after T) 로 “이런 feature일 때 승률/예상 R” 학습 → `ml/models/` 저장. |
| **현재 차트에 적용** | ✅ **자동.** 실시간 feature만 넣어서 예측 → ML 필터·캐피탈/Kelly에 사용. |

→ **이건 자동 적용이 맞다.**

### 2.2 파라미터 (filter threshold 등)

| | |
|---|--|
| **스캔** | 과거+미래 데이터로 그리드 서치 → 조합별 승률/avg_R/profit_factor 계산. |
| **저장** | heatmap, CSV, `parameter_scan_results`. |
| **현재 차트에 적용** | ❌ **자동 아님.** **사람이** stability region 보고 config 수정. |

→ **이건 의도적으로 사람이 선택하게 해둔 것이다.**

---

## 3. Stable region을 쓰는 이유 (예시)

Stability Map이 예를 들어 이렇게 나왔다고 하자.

| ema_distance | avg_R |
|--------------|-------|
| 0.0003 | -0.1 |
| 0.0005 | 0.15 |
| **0.0007** | **0.17** ← 최고 |
| 0.0009 | 0.16 |
| 0.0011 | 0.14 |

- **최고값만 쓰면**: 0.0007 → 시장이 조금만 바뀌어도 깨지기 쉽다.
- **기관이 하는 방식**: **0.0005 ~ 0.001** 처럼 **avg_R이 괜찮은 구간(안정 구간)** 을 잡고, 그 **중앙값** (0.00075 or 0.0008) 을 선택. 그래야 시장 변화에도 덜 깨진다.

그래서 현재 구조(**scan → heatmap/CSV → 사람이 config 수정**)는 **정석 퀀트 워크플로우**에 맞게 설계된 것이다.

---

## 4. Semi-auto: Parameter Suggestion Engine

“best 값” 자동 적용은 하지 않되, **안전한 자동화**는 다음처럼 할 수 있다.

- **Stable region 자동 탐색**  
  예: `avg_R > 0.1`, `profit_factor > 1.2`, `drawdown < threshold` 인 구간만 필터.
- 그 구간의 **중앙값**(또는 중앙에 가까운 값)을 계산.
- 그걸 **recommended_config.json** (또는 `recommended_params.json`) 으로 출력.
- **사람이 검토 후** `config.json` 에 반영.

즉, **scan → stable region 탐색 → suggested parameters 생성 → 사람이 승인 → config 적용** 이 **semi-auto** 로서 현실적인 자동화다.

이를 위해 **parameter_suggestion_engine** 이 추가되어 있다 (scan 결과 분석 → stable region 탐색 → `recommended_config.json` 출력). 민오는 그 파일을 보고 `config.json` 을 업데이트하면 된다.

---

## 5. Edge Decay (future_r_5 / 10 / 30 활용)

데이터셋에 **future_r_5, future_r_10, future_r_30** 처럼 여러 horizon이 있으면, **Edge Decay** 분석을 할 수 있다.

- **진입 후 몇 봉까지가 진짜 edge(우위)인지** 를 보는 분석.
- 이걸 찾으면 **TP, Trailing, Exit 로직** 전부 개선에 쓰일 수 있고, **수익 안정화**에 직접 영향을 준다.

원하면 **Edge Decay 분석용 프롬트/명세**를 따로 만들어 줄 수 있다. (진입 후 몇 봉까지 edge가 유지되는지 분석 → TP/Trailing/Exit 개선.)

---

## 6. Parameter Suggestion Engine 사용법

Scan 실행 후, stable region 기준으로 제안만 생성한다 (자동으로 config 덮어쓰지 않음).

```bash
# CSV에서 로드 (run_stability_scan --from-db 후 생성된 CSV)
python -m analysis.parameter_suggestion_engine --from-csv analysis/output/parameter_scan_results.csv --output analysis/output/recommended_config.json

# DB에서 최근 스캔 결과 로드
python -m analysis.parameter_suggestion_engine --from-db --output analysis/output/recommended_config.json
```

생성된 `recommended_config.json` 의 `strategy` / `approval` 블록을 검토한 뒤, 필요한 값만 `config/config.json` 에 반영하면 된다.

---

*문서 버전: 1.1. 설계 의도(과최적화 방지, stable region) 및 semi-auto, Edge Decay 반영.*
