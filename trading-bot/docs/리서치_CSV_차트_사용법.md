# 리서치 CSV 내보내기 & 차트 보기

테스트가 오래 걸릴 때, **이미 나온 결과**만 한곳에 모아서 CSV 받고 차트로 보는 방법.

---

## 1. CSV 한곳에 모으기 + 보기 쉬운 차트

```bash
# 최신 run 폴더 기준으로 CSV 복사 + 차트 생성
python scripts/export_research_bundle.py --latest

# 특정 run 폴더 지정
python scripts/export_research_bundle.py --run analysis/output/202603081221
```

**결과 위치:** `analysis/output/research_bundle/<run_id>/`

- Run 폴더에 있던 **CSV 전부** 복사
- **PNG 차트** 생성: Edge decay(보유 봉수별), 레짐 비교, 파라미터 스캔 상위/히트맵
- **research_dashboard.html** → 브라우저로 열면 위 차트들을 한 페이지에서 볼 수 있음

---

## 2. DB에서 후보 시그널만 CSV로 (백테스트 생략)

백테스트 다시 안 돌리고, DB에 쌓인 후보만 CSV로 받을 때:

```bash
python scripts/export_research_bundle.py --export-db --limit 20000
```

**저장:** `analysis/output/research_bundle/export/candidates_from_db.csv`

이 CSV로 나중에 다음을 돌릴 수 있음:
- `run_stability_scan --candidates-csv analysis/output/research_bundle/export/candidates_from_db.csv`
- `run_edge_decay --candidates-csv ...`

---

## 3. 차트만 다시 만들기

CSV는 이미 있는데 차트만 다시 만들고 싶을 때:

```bash
python -m analysis.research_dashboard analysis/output/202603081221

# 결과를 다른 폴더에 저장
python -m analysis.research_dashboard analysis/output/202603081221 --out-dir analysis/output/research_bundle/202603081221
```

---

## 4. 대시보드에 나오는 차트 종류

| 차트 | 설명 |
|------|------|
| Edge decay (Overall) | 보유 봉 5/10/20/30별 avg R, Winrate |
| Edge decay (Trending up/down/ranging) | 레짐별 보유 봉수별 avg R |
| Regime comparison | TRENDING_UP / DOWN / RANGING 레짐별 avg R, 거래 수 |
| Parameter scan top | avg R 기준 상위 파라미터 조합 막대 차트 |
| Parameter heatmap | EMA vs Volume 히트맵 (RSI 고정) |
