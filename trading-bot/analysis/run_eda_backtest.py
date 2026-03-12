"""
EDA 정렬 백테스트: feature_store_1m + outcome_store_1m 조인 데이터에
EDA와 동일한 규칙·지표를 적용해 mean_net, pf_net, win_rate 등을 산출.

- 데이터: EDA와 동일 (f JOIN o on symbol, timestamp)
- 진입 규칙: EDA의 TREND_TEST_CANDIDATES (CANDIDATE_1, CANDIDATE_2 등)
- 결과: 각 봉 = 1회 “진입”, 수익 = 해당 row의 future_r_N - fee (SL/TP 시뮬 없음)
- 지표: mean_raw, mean_net, pf_raw, pf_net, win_rate (horizon별)

사용 예:
  python3 -m analysis.run_eda_backtest --symbol BTCUSDT --limit 500000 --fee-bps 4
  python3 -m analysis.run_eda_backtest --symbol BTCUSDT --from 2024-01-01 --to 2024-12-31 --candidates CANDIDATE_1,CANDIDATE_2 --out report.txt
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 프로젝트 루트
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from analysis.eda.eda_feature_outcome_1m import (
    DEFAULT_TARGET_COLS,
    TREND_TEST_CANDIDATES,
    _evaluate_series,
    _parse_date,
    get_engine_from_env,
    load_sample,
)


def run_eda_backtest(
    df: pd.DataFrame,
    fee_bps: float = 4.0,
    candidate_names: list[str] | None = None,
    target_cols: list[str] | None = None,
) -> pd.DataFrame:
    """
    EDA와 동일한 방식으로 후보별·horizon별 메트릭 계산.
    Returns DataFrame: name, target, n, mean_raw, mean_net, win_rate_raw, pf_raw, pf_net.
    """
    target_cols = target_cols or [c for c in DEFAULT_TARGET_COLS if c in df.columns]
    if not target_cols:
        return pd.DataFrame()

    if candidate_names:
        candidates = [c for c in TREND_TEST_CANDIDATES if c["name"] in candidate_names]
    else:
        candidates = [c for c in TREND_TEST_CANDIDATES if c["name"] in {"CANDIDATE_1_정석형", "CANDIDATE_2_강한필터", "CANDIDATE_3_볼륨과열제거"}]

    rows = []
    for item in candidates:
        name = item["name"]
        short = item["short"]
        try:
            mask = item["expr"](df)
        except Exception:
            for target_col in target_cols:
                rows.append({"name": name, "target": target_col, "n": 0, "mean_raw": float("nan"), "mean_net": float("nan"), "win_rate_raw": float("nan"), "pf_raw": float("nan"), "pf_net": float("nan")})
            continue
        sub = df.loc[mask]
        for target_col in target_cols:
            if target_col not in sub.columns:
                continue
            raw = sub[target_col].dropna()
            if short:
                raw = -raw
            metrics = _evaluate_series(raw, fee_bps)
            rows.append({"name": name, "target": target_col, **metrics})

    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="EDA와 동일 데이터·규칙으로 백테스트 메트릭 산출")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--limit", type=int, default=300000)
    parser.add_argument("--from", dest="from_date", type=str, default=None, help="기간 시작 (UTC) YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", type=str, default=None, help="기간 끝 (UTC) YYYY-MM-DD")
    parser.add_argument("--fee-bps", type=float, default=4.0)
    parser.add_argument("--candidates", type=str, default=None, help="쉼표 구분 후보명, 예: CANDIDATE_1_정석형,CANDIDATE_2_강한필터")
    parser.add_argument("--out", type=str, default=None, help="결과 저장 경로 (txt). 없으면 stdout만")
    args = parser.parse_args()

    start_ts = _parse_date(args.from_date) if args.from_date else None
    end_ts = _parse_date(args.to_date) if args.to_date else None
    if args.to_date and len(args.to_date.strip()) <= 10:
        end_ts = end_ts.replace(hour=23, minute=59, second=59, microsecond=999999)

    candidate_list = [s.strip() for s in args.candidates.split(",")] if args.candidates else None

    engine = get_engine_from_env()
    df = load_sample(engine, symbol=args.symbol, limit=args.limit, start_ts=start_ts, end_ts=end_ts)
    if df.empty:
        print("No data from feature_store_1m + outcome_store_1m.", file=sys.stderr)
        sys.exit(1)

    target_cols = [c for c in DEFAULT_TARGET_COLS if c in df.columns]
    result = run_eda_backtest(df, fee_bps=args.fee_bps, candidate_names=candidate_list, target_cols=target_cols)
    result = result.sort_values(["name", "target"])

    report_lines = [
        "=== EDA-aligned backtest ===",
        f"symbol={args.symbol} limit={args.limit} fee_bps={args.fee_bps}",
        f"rows_loaded={len(df)}",
        "",
        result.to_string(index=False),
    ]
    report = "\n".join(report_lines)
    print(report)

    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"\n[OK] Wrote {args.out}")


if __name__ == "__main__":
    main()
