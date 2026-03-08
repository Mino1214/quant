# Signal Distribution Analysis Research Plan (for Cursor)

> 퀀트에서 중요하나 개인 트레이더가 잘 하지 않는 분석.  
> **목적**: "신호가 언제 진짜 좋은지"를 통계적으로 찾는 것.

---

## Goal

Analyze the **statistical distribution** of trading signals to understand:

- **Which signals** produce strong returns
- **Which signals** produce weak returns
- **Which features** correlate with profitable trades

The goal is **not just to measure strategy performance**, but to **understand signal quality structure**.

---

## 1. Candidate Signal Dataset

Construct a dataset containing **all candidate signals**, not only executed trades.

Each candidate signal should include:

| Field | Description |
|-------|-------------|
| `timestamp` | Signal time |
| `entry_price` | Entry price |
| `regime` | Market regime (TREND_UP / TREND_DOWN / RANGE / CHAOTIC) |
| `trend_direction` | 5m trend direction |
| `approval_score` | Approval engine score |
| `feature_values` | ema_distance, volume_ratio, rsi, etc. |
| `trade_outcome` | executed / blocked (reason) |
| `R_return` | Realized R (if executed) |
| `holding_time` | Bars in trade (if executed) |

**Example structure:**

| time | regime | approval_score | ema_distance | volume_ratio | R_return |
|------|--------|----------------|--------------|--------------|----------|
| t1 | TREND_UP | 6 | 0.0011 | 1.8 | 1.2 |
| t2 | RANGE | 4 | 0.0002 | 0.9 | -0.7 |

---

## 2. R Distribution Analysis

Instead of just average results, analyze the **distribution** of trade returns.

- **Plot histogram of**: `R_return`

**Example interpretation:**

- **-1R cluster** → stop losses  
- **0.5R cluster** → small winners  
- **5R+ cluster** → trend capture trades  

**Goal:** Understand whether strategy relies on:

- **high winrate**, or  
- **large tail profits**

---

## 3. Signal Quality vs Score

Analyze how **approval score** correlates with trade outcome.

**Example analysis:**

| approval_score | trades | winrate | avg_R |
|----------------|--------|---------|-------|
| 3 | 200 | 45% | 0.05 |
| 4 | 180 | 52% | 0.12 |
| 5 | 150 | 59% | 0.31 |
| 6 | 90 | 67% | 0.55 |

**Goal:** Determine **optimal approval threshold**.

**Example rule:** `approval_score >= 5`

---

## 4. Feature Impact Analysis

Measure how **each feature** affects profitability.

**Example: EMA Distance**

| ema_distance_range | trades | avg_R |
|--------------------|--------|-------|
| <0.0003 | 150 | -0.12 |
| 0.0003–0.001 | 300 | 0.10 |
| >0.001 | 120 | 0.42 |

**Conclusion example:** EMA distance too small → avoid trade.

**Example: Volume Ratio**

| volume_ratio | trades | avg_R |
|--------------|--------|-------|
| <1.0 | 220 | -0.18 |
| 1.0–1.5 | 280 | 0.15 |
| >1.5 | 130 | 0.48 |

**Conclusion:** Volume expansion strongly improves signal quality.

---

## 5. Regime Performance Analysis

Analyze performance **across regimes**.

| regime | trades | winrate | avg_R |
|--------|--------|---------|-------|
| TREND_UP | … | … | … |
| TREND_DOWN | … | … | … |
| RANGE | … | … | … |

**Goal:** Identify if strategy should **disable trading** during certain regimes.

**Example conclusion:** RANGE regime → negative expectancy.

---

## 6. Holding Time Analysis

Analyze **how long** profitable trades last.

| holding_bars | avg_R |
|--------------|-------|
| 1–5 | 0.02 |
| 5–10 | 0.18 |
| 10–30 | 0.63 |

**Goal:** Improve **exit logic**.

**Example conclusion:** Most profits occur after 10 bars.

---

## 7. Time-of-Day Analysis

Crypto markets behave differently depending on time.  
Analyze signals by **UTC hour**.

| hour | trades | avg_R |
|------|--------|-------|
| 00–04 | … | … |
| 04–08 | … | … |
| 08–12 | … | … |

**Possible findings:**

- US session more volatile  
- Asian session quieter  

---

## 8. Signal Clustering

**Cluster signals** based on feature similarity.

**Goal:** Identify groups such as:

- strong breakout signals  
- weak pullback signals  
- low-volume signals  

This can reveal **hidden patterns** in signal quality.

---

## 9. Signal Filtering Improvement

Use insights from distribution analysis to **refine entry filters**.

**Example improvements:**

- minimum EMA distance  
- minimum volume ratio  
- regime-specific entry rules  

---

## 10. Visualization Requirements

The research module should generate charts for:

1. **R distribution histogram**  
2. **Approval score vs avg_R**  
3. **Feature bins vs avg_R**  
4. **Regime performance**  
5. **Holding time vs profit**  

Visualization helps identify patterns not obvious from raw numbers.

---

## 11. Long-Term Goal

Use signal distribution analysis to evolve from:

**static rule-based strategy**

toward:

**rule-based signals**  
**+**  
**probabilistic signal scoring**

This enables future integration with **machine learning** models.

---

## Core Principle

The goal is **not to find perfect rules**, but to understand:

**where the edge actually comes from**

Signal distribution analysis reveals the **structure of the strategy edge**.

---

## Next Phase: Edge Stability Map (예정)

> 1m entry + 5m trend + 15m regime 구조에서, **대량 데이터(예: 341만 개)**로 수행하면 파라미터 튜닝 필요가 크게 줄어드는 기관 퀀트 수준 분석.  
> 방법론은 별도 문서로 추가 예정.

---

## Implementation Checklist (for Cursor)

1. **Data layer**
   - [ ] 백테스트/엔진에서 **진입한 거래뿐 아니라 모든 candidate signal** 로깅 (blocked 포함).
   - [ ] 각 레코드: timestamp, entry_price, regime, trend_direction, approval_score, feature_values (ema_distance, volume_ratio, rsi 등), trade_outcome, R_return, holding_time.
   - [ ] CSV/Parquet 또는 DB 테이블로 저장 (분석 스크립트 입력용).

2. **분석 스크립트**
   - [ ] R distribution histogram (R_return).
   - [ ] Approval score vs trades / winrate / avg_R 테이블·차트.
   - [ ] Feature bins (ema_distance, volume_ratio 등) vs avg_R.
   - [ ] Regime별 trades / winrate / avg_R.
   - [ ] Holding time bins vs avg_R.
   - [ ] Time-of-day (UTC hour) vs trades / avg_R.
   - [ ] (선택) Signal clustering (feature 기반).

3. **시각화**
   - [ ] R histogram, score vs avg_R, feature bins vs avg_R, regime 성과, holding time vs profit 차트 생성 (matplotlib/plotly 등).

4. **필터 개선**
   - [ ] 분석 결과를 반영한 최소 ema_distance, volume_ratio, regime별 규칙 등 config/필터 제안 또는 자동 반영 옵션.

---

*Document for Cursor: implement analysis pipeline and visualizations per this plan.*
