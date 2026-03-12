"""
Quick EDA scaffold for feature_store_1m (X) + outcome_store_1m (Y).

사용법 (로컬에서):

    poetry run python -m analysis.eda.eda_feature_outcome_1m \
        --limit 500000 \
        --symbol BTCUSDT

기간 지정 (UTC 기준):

    python -m analysis.eda.eda_feature_outcome_1m --symbol BTCUSDT --from 2024-01-01 --to 2024-12-31
    python -m analysis.eda.eda_feature_outcome_1m --symbol BTCUSDT --from 2024-06-01  # 6월 1일 ~ 최신

기능:
- MySQL에서 feature_store_1m + outcome_store_1m join 샘플 로드
- 기본 통계 / 누수 제외 corr / 분위수 버킷 분석 / 조건부 future_r 요약
- 후보 전략을 future_r_10 / 30 / 60 기준으로 비교
- 후보 전략 월별 안정성 체크
- CSV로 raw 샘플 덤프해서 노트북/다른 툴에서 재사용 가능
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text


LEAKAGE_PREFIXES = ("future_r_", "win_", "mfe_", "mae_")
LEAKAGE_EXACT = {"timestamp"}

# 상위 추세(15m/5m) + 하위 눌림(1m) 기반 후보 (버킷 경계값 반영)
TREND_TEST_CANDIDATES = [
    {
        "name": "CANDIDATE_1_정석형",
        "expr": lambda df: (
            (df["ema20_slope_15m"] > 0.000163)
            & (df["ema20_slope_5m"] > 0.000046)
            & (df["ema20_slope_1m"] < 0)
            & (df["rsi_1m"] < 40)
            & (df["rsi_5m"] > 50)
        ),
        "short": False,
    },
    {
        "name": "CANDIDATE_2_강한필터",
        "expr": lambda df: (
            (df["ema20_slope_15m"] > 0.000285)
            & (df["ema20_slope_5m"] > 0.000094)
            & (df["ema20_slope_1m"] < -0.000018)
            & (df["rsi_1m"] < 38)
            & (df["rsi_5m"] > 54)
            & (df["pullback_depth_pct"] > 0.6)
        ),
        "short": False,
    },
    {
        "name": "CANDIDATE_3_볼륨과열제거",
        "expr": lambda df: (
            (df["ema20_slope_15m"] > 0.000163)
            & (df["ema20_slope_5m"] > 0.000046)
            & (df["ema20_slope_1m"] < 0)
            & (df["rsi_1m"] < 42)
            & (df["rsi_5m"] > 50)
            & (df["volume_ratio"] < 1.4)
            & (df["pullback_depth_pct"] > 0.5)
        ),
        "short": False,
    },
    # 기존 후보
    {
        "name": "TREND_UP_PULLBACK_A",
        "expr": lambda df: (
            (df["regime_tradable"] == 1)
            & (df["regime_label"] == "TRENDING_UP")
            & (df["ema_stack_score"] >= 1)
            & (df["rsi_1m"] < 50)
        ),
        "short": False,
    },
    {
        "name": "TREND_UP_PULLBACK_B",
        "expr": lambda df: (
            (df["regime_tradable"] == 1)
            & (df["regime_label"] == "TRENDING_UP")
            & (df["ema_stack_score"] >= 2)
            & (df["rsi_1m"].between(35, 48))
            & (df["ema20_slope_5m"] > 0)
        ),
        "short": False,
    },
    {
        "name": "TREND_UP_PULLBACK_C",
        "expr": lambda df: (
            (df["regime_tradable"] == 1)
            & (df["regime_label"] == "TRENDING_UP")
            & (df["ema_stack_score"] >= 2)
            & (df["rsi_1m"].between(38, 52))
            & (df["volume_ratio"].between(0.8, 1.8))
            & (df["pullback_depth_pct"].between(0.1, 0.9))
        ),
        "short": False,
    },
    {
        "name": "TREND_DOWN_PULLBACK_A",
        "expr": lambda df: (
            (df["regime_tradable"] == 1)
            & (df["regime_label"] == "TRENDING_DOWN")
            & (df["ema_stack_score"] <= -1)
            & (df["rsi_1m"] > 50)
        ),
        "short": True,
    },
    {
        "name": "TREND_DOWN_PULLBACK_B",
        "expr": lambda df: (
            (df["regime_tradable"] == 1)
            & (df["regime_label"] == "TRENDING_DOWN")
            & (df["ema_stack_score"] <= -2)
            & (df["rsi_1m"].between(52, 65))
            & (df["ema20_slope_5m"] < 0)
            & (df["volume_ratio"].between(0.8, 1.8))
        ),
        "short": True,
    },
]

DEFAULT_TARGET_COLS = ["future_r_10", "future_r_30", "future_r_60"]


def get_engine_from_env() -> "Engine":
    user = "mynolab_user"
    password = "mynolab2026"
    host = "180.230.8.65"
    port = 3306
    db = "tradebot"
    url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{db}"
    return create_engine(url)


def _parse_date(s: str) -> datetime:
    s = s.strip()
    if len(s) <= 10:
        s = s + " 00:00:00"
    dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_sample(
    engine,
    symbol: str,
    limit: int,
    start_ts: Optional[datetime] = None,
    end_ts: Optional[datetime] = None,
) -> pd.DataFrame:
    conditions = ["f.symbol = :symbol"]
    params: dict = {"symbol": symbol, "limit": int(limit)}
    if start_ts is not None:
        conditions.append("f.timestamp >= :start_ts")
        params["start_ts"] = start_ts
    if end_ts is not None:
        conditions.append("f.timestamp <= :end_ts")
        params["end_ts"] = end_ts
    where_clause = " AND ".join(conditions)

    sql = text(
        f"""
        SELECT
            f.symbol,
            f.timestamp,
            f.regime_label,
            f.regime_tradable,
            f.ema_stack_score,
            f.rsi_1m,
            f.rsi_5m,
            f.rsi_15m,
            f.volume_ratio,
            f.volume_ratio_5m,
            f.volume_ratio_15m,
            f.atr_1m,
            f.atr_5m,
            f.atr_15m,
            f.natr_1m,
            f.natr_5m,
            f.natr_15m,
            f.range_pct,
            f.body_pct,
            f.body_to_range_ratio,
            f.close_near_high,
            f.close_near_low,
            f.close_in_range_pct,
            f.recent_high_20,
            f.recent_low_20,
            f.close_in_recent_range,
            f.pullback_depth_pct,
            f.breakout_confirmation,
            f.breakout_strength,
            f.ema20_1m,
            f.ema50_1m,
            f.ema200_1m,
            f.ema20_5m,
            f.ema50_5m,
            f.ema200_5m,
            f.ema20_15m,
            f.ema50_15m,
            f.ema200_15m,
            f.ema20_slope_1m,
            f.ema50_slope_1m,
            f.ema200_slope_1m,
            f.ema20_slope_5m,
            f.ema50_slope_5m,
            f.ema200_slope_5m,
            f.ema20_slope_15m,
            f.ema50_slope_15m,
            f.ema200_slope_15m,
            f.volume_ma20,
            f.quote_volume,
            f.trade_count,
            f.taker_buy_volume,
            f.taker_buy_quote_volume,
            o.future_r_5,
            o.future_r_10,
            o.future_r_20,
            o.future_r_30,
            o.future_r_60,
            o.future_r_120,
            o.mfe_10,
            o.mae_10,
            o.win_5,
            o.win_10,
            o.win_20
        FROM outcome_store_1m o
        JOIN feature_store_1m f
          ON f.symbol = o.symbol
         AND f.timestamp = o.timestamp
        WHERE {where_clause}
        ORDER BY f.timestamp DESC
        LIMIT :limit
        """
    )

    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params=params)

    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def _profit_factor(ret: pd.Series) -> float:
    ret = ret.dropna()
    if ret.empty:
        return np.nan
    gross_profit = ret[ret > 0].sum()
    gross_loss = -ret[ret < 0].sum()
    if gross_loss <= 0:
        return np.inf if gross_profit > 0 else np.nan
    return gross_profit / gross_loss


def _non_leakage_feature_cols(df: pd.DataFrame) -> list[str]:
    cols = []
    for c in df.columns:
        if c in LEAKAGE_EXACT:
            continue
        if c == "symbol" or c == "regime_label":
            continue
        if any(c.startswith(prefix) for prefix in LEAKAGE_PREFIXES):
            continue
        cols.append(c)
    return cols


def _evaluate_series(raw: pd.Series, fee_bps: float) -> dict:
    raw = raw.dropna()
    if raw.empty:
        return {
            "n": 0,
            "mean_raw": np.nan,
            "mean_net": np.nan,
            "win_rate_raw": np.nan,
            "pf_raw": np.nan,
            "pf_net": np.nan,
        }

    fee = fee_bps / 10000.0
    net = raw - fee

    return {
        "n": int(len(raw)),
        "mean_raw": float(raw.mean()),
        "mean_net": float(net.mean()),
        "win_rate_raw": float((raw > 0).mean()),
        "pf_raw": float(_profit_factor(raw)),
        "pf_net": float(_profit_factor(net)),
    }


def basic_eda(df: pd.DataFrame) -> None:
    print("\n=== Shape ===")
    print(df.shape)

    print("\n=== Null ratio (top 30) ===")
    null_ratio = df.isna().mean().sort_values(ascending=False)
    print(null_ratio.head(30))

    print("\n=== Descriptive stats for key features ===")
    cols = [
        "future_r_10",
        "future_r_30",
        "rsi_1m",
        "rsi_5m",
        "ema_stack_score",
        "volume_ratio",
        "volume_ratio_5m",
        "atr_1m",
        "atr_5m",
        "range_pct",
        "body_pct",
        "pullback_depth_pct",
        "breakout_strength",
    ]
    cols = [c for c in cols if c in df.columns]
    print(df[cols].describe(percentiles=[0.01, 0.05, 0.5, 0.95, 0.99]).T)

    print("\n=== Regime distribution ===")
    if "regime_label" in df.columns:
        print(df["regime_label"].value_counts(dropna=False) / len(df))

    print("\n=== Corr with future_r_10 (NO LEAKAGE) ===")
    if "future_r_10" in df.columns:
        feature_cols = _non_leakage_feature_cols(df)
        corr_cols = [c for c in feature_cols if pd.api.types.is_numeric_dtype(df[c])]
        corr_df = df[corr_cols + ["future_r_10"]].copy()
        corr = corr_df.corr(numeric_only=True)["future_r_10"].sort_values(ascending=False)

        print(corr.head(20))
        print("\n--- negative side ---")
        print(corr.tail(20))


def bucket_analysis(
    df: pd.DataFrame,
    col: str,
    target_col: str = "future_r_10",
    q: int = 10,
    min_count: int = 50,
) -> None:
    if col not in df.columns or target_col not in df.columns:
        return

    temp = df[[col, target_col]].dropna().copy()
    if temp.empty:
        print(f"\n=== Bucket analysis: {col} ===")
        print("EMPTY")
        return

    nunique = temp[col].nunique(dropna=True)
    if nunique < 2:
        print(f"\n=== Bucket analysis: {col} ===")
        print(f"SKIP: unique={nunique}")
        return

    bins = min(q, nunique)
    try:
        temp[f"{col}_bucket"] = pd.qcut(temp[col], q=bins, duplicates="drop")
    except Exception as e:
        print(f"\n=== Bucket analysis: {col} ===")
        print(f"SKIP: {e}")
        return

    grp = temp.groupby(f"{col}_bucket", observed=False)[target_col].agg(
        ["count", "mean", "std", "median"]
    )
    grp["win_rate"] = temp.groupby(f"{col}_bucket", observed=False)[target_col].apply(lambda s: (s > 0).mean())
    grp = grp[grp["count"] >= min_count]

    print(f"\n=== Bucket analysis: {col} ===")
    print(grp)


def conditional_future_r(df: pd.DataFrame, fee_bps: float = 0.0) -> None:
    if "future_r_10" not in df.columns:
        return

    fee = fee_bps / 10000.0

    def summarize(name: str, sub: pd.DataFrame, short: bool = False) -> None:
        if sub.empty:
            print(f"{name}: EMPTY")
            return

        raw = sub["future_r_10"].dropna()
        if short:
            raw = -raw

        net = raw - fee

        print(f"\n[{name}] n={len(raw)}")
        print(raw.describe(percentiles=[0.01, 0.05, 0.5, 0.95, 0.99]))
        print(f"win_rate_10_raw = {(raw > 0).mean():.3f}")
        print(f"mean_10_raw = {raw.mean():.6f}")
        print(f"mean_10_net({fee_bps}bps) = {net.mean():.6f}")
        print(f"pf_10_raw = {_profit_factor(raw)}")
        print(f"pf_10_net({fee_bps}bps) = {_profit_factor(net)}")

    summarize("ALL", df)

    cond_trend_pullback = (
        (df.get("regime_tradable", 1) == 1)
        & (df.get("regime_label") == "TRENDING_UP")
        & (df.get("ema_stack_score", 0) >= 1)
        & (df.get("rsi_1m") < 50)
    )
    summarize("TREND_UP_PULLBACK", df[cond_trend_pullback], short=False)

    cond_range_long = (
        (df.get("regime_label") == "RANGING")
        & (df.get("rsi_1m") < 35)
        & (df.get("volume_ratio", 1.0) < 1.5)
    )
    summarize("RANGE_MEAN_REVERT_LONG", df[cond_range_long], short=False)

    cond_range_short = (
        (df.get("regime_label") == "RANGING")
        & (df.get("rsi_1m") > 65)
        & (df.get("volume_ratio", 1.0) < 1.5)
    )
    summarize("RANGE_MEAN_REVERT_SHORT", df[cond_range_short], short=True)


def test_trend_candidates(
    df: pd.DataFrame,
    fee_bps: float = 0.0,
    target_cols: list[str] | None = None,
) -> None:
    if target_cols is None:
        target_cols = DEFAULT_TARGET_COLS

    target_cols = [c for c in target_cols if c in df.columns]
    if not target_cols:
        print("\n=== Trend candidate multi-horizon test ===")
        print("No valid target columns.")
        return

    rows = []

    for item in TREND_TEST_CANDIDATES:
        name = item["name"]
        short = item["short"]

        try:
            mask = item["expr"](df)
        except Exception as e:
            for target_col in target_cols:
                rows.append(
                    {
                        "name": name,
                        "target": target_col,
                        "n": 0,
                        "mean_raw": np.nan,
                        "mean_net": np.nan,
                        "win_rate_raw": np.nan,
                        "pf_raw": np.nan,
                        "pf_net": np.nan,
                        "error": str(e),
                    }
                )
            continue

        for target_col in target_cols:
            sub = df.loc[mask, target_col].dropna()

            if short:
                sub = -sub

            metrics = _evaluate_series(sub, fee_bps)
            rows.append(
                {
                    "name": name,
                    "target": target_col,
                    **metrics,
                    "error": None,
                }
            )

    out = pd.DataFrame(rows)
    out = out.sort_values(["target", "mean_net", "pf_net", "n"], ascending=[True, False, False, False])

    print("\n=== Trend candidate multi-horizon test ===")
    print(out.to_string(index=False))


def monthly_stability_report(
    df: pd.DataFrame,
    candidate_name: str,
    candidate_expr,
    short: bool,
    fee_bps: float = 0.0,
    target_cols: list[str] | None = None,
) -> None:
    if target_cols is None:
        target_cols = DEFAULT_TARGET_COLS

    target_cols = [c for c in target_cols if c in df.columns]
    if not target_cols:
        return

    if "timestamp" not in df.columns:
        return

    try:
        mask = candidate_expr(df)
    except Exception as e:
        print(f"\n=== Monthly stability: {candidate_name} ===")
        print(f"ERROR: {e}")
        return

    sub = df.loc[mask].copy()
    if sub.empty:
        print(f"\n=== Monthly stability: {candidate_name} ===")
        print("EMPTY")
        return

    sub["month"] = pd.to_datetime(sub["timestamp"]).dt.to_period("M").astype(str)

    print(f"\n=== Monthly stability: {candidate_name} ===")
    for target_col in target_cols:
        rows = []
        for month, g in sub.groupby("month"):
            series = g[target_col].dropna()
            if short:
                series = -series

            metrics = _evaluate_series(series, fee_bps)
            rows.append(
                {
                    "month": month,
                    "target": target_col,
                    **metrics,
                }
            )

        out = pd.DataFrame(rows).sort_values("month")
        print(f"\n--- {target_col} ---")
        print(out.to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--limit", type=int, default=300000)
    parser.add_argument(
        "--from",
        dest="from_date",
        type=str,
        default=None,
        help="기간 시작 (UTC), YYYY-MM-DD 또는 YYYY-MM-DD HH:MM:SS",
    )
    parser.add_argument(
        "--to",
        dest="to_date",
        type=str,
        default=None,
        help="기간 끝 (UTC), YYYY-MM-DD 또는 YYYY-MM-DD HH:MM:SS",
    )
    parser.add_argument("--out-csv", type=str, default="eda_feature_outcome_sample.csv")
    parser.add_argument("--fee-bps", type=float, default=4.0)
    parser.add_argument(
        "--monthly-top-k",
        type=int,
        default=3,
        help="multi-horizon 결과 상위 몇 개 후보까지 월별 안정성 출력할지",
    )
    args = parser.parse_args()

    start_ts = _parse_date(args.from_date) if args.from_date else None
    end_ts = _parse_date(args.to_date) if args.to_date else None
    if args.to_date and len(args.to_date.strip()) <= 10:
        end_ts = end_ts.replace(hour=23, minute=59, second=59, microsecond=999999)

    engine = get_engine_from_env()
    df = load_sample(
        engine,
        symbol=args.symbol,
        limit=args.limit,
        start_ts=start_ts,
        end_ts=end_ts,
    )

    basic_eda(df)

    bucket_cols = [
        "rsi_1m",
        "rsi_5m",
        "ema_stack_score",
        "volume_ratio",
        "volume_ratio_5m",
        "pullback_depth_pct",
        "breakout_strength",
        "ema20_slope_1m",
        "ema20_slope_5m",
        "ema20_slope_15m",
    ]
    for col in bucket_cols:
        if col in df.columns:
            bucket_analysis(df, col, target_col="future_r_10", q=10, min_count=100)

    conditional_future_r(df, fee_bps=args.fee_bps)
    test_trend_candidates(df, fee_bps=args.fee_bps, target_cols=DEFAULT_TARGET_COLS)

    # 월별 안정성은 우선 핵심 후보 3개만 출력
    top_candidates_for_monthly = [
        item for item in TREND_TEST_CANDIDATES
        if item["name"] in {"CANDIDATE_1_정석형", "CANDIDATE_2_강한필터", "CANDIDATE_3_볼륨과열제거"}
    ][:args.monthly_top_k]

    for item in top_candidates_for_monthly:
        monthly_stability_report(
            df=df,
            candidate_name=item["name"],
            candidate_expr=item["expr"],
            short=item["short"],
            fee_bps=args.fee_bps,
            target_cols=DEFAULT_TARGET_COLS,
        )

    out_path = Path(args.out_csv)
    df.to_csv(out_path, index=False)
    print(f"\n[OK] Saved sample to {out_path.resolve()}")


if __name__ == "__main__":
    main()