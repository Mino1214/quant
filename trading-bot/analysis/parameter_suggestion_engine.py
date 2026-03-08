"""
Parameter Suggestion Engine: scan 결과에서 stable region을 찾고, 그 구간의 중앙값을 제안.
"best 값" 자동 적용이 아니라 "안정 구간의 중앙"을 recommended_config.json으로 출력 → 사람이 검토 후 config.json 반영.

Usage:
  python -m analysis.parameter_suggestion_engine --from-csv analysis/output/parameter_scan_results.csv
  python -m analysis.parameter_suggestion_engine --from-db [--output path]
"""
import argparse
import csv
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Stable region 기준: edge 복구 단계 — 넓은 안정 구간, 주변에서도 무너지지 않을 것
DEFAULT_MIN_AVG_R = 0.0
DEFAULT_MIN_PROFIT_FACTOR = 1.02
DEFAULT_MAX_DRAWDOWN = 2.0  # 이 값 이하만 허용 (클수록 낙폭 큼)
DEFAULT_MIN_TRADES = 200


def load_results_csv(path: Path, allow_flag_columns: bool = True) -> list:
    """parameter_scan_results.csv or parameter_scan_results_clean.csv 형식 로드. Clean CSV has no flag columns."""
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            for key in ("ema_distance_threshold", "volume_ratio_threshold", "rsi_threshold", "trades", "winrate", "avg_R", "profit_factor", "max_drawdown"):
                if key in r and r[key] != "":
                    try:
                        if key in ("trades",):
                            r[key] = int(float(r[key]))
                        else:
                            r[key] = float(r[key])
                    except (ValueError, TypeError):
                        r[key] = None
            if allow_flag_columns and "valid" in r:
                try:
                    r["valid"] = str(r.get("valid", "")).strip().lower() in ("true", "1", "yes")
                except Exception:
                    pass
            rows.append(r)
    return rows


def load_results_db(limit: int = 5000) -> list:
    """parameter_scan_results 테이블에서 최근 결과 로드."""
    from storage.database import SessionLocal, init_db
    from storage.models import ParameterScanResultModel

    init_db()
    db = SessionLocal()
    try:
        rows = (
            db.query(ParameterScanResultModel)
            .order_by(ParameterScanResultModel.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "ema_distance_threshold": r.ema_distance_threshold,
                "volume_ratio_threshold": r.volume_ratio_threshold,
                "rsi_threshold": r.rsi_threshold,
                "trades": r.trades or 0,
                "winrate": r.winrate,
                "avg_R": r.avg_R,
                "profit_factor": r.profit_factor,
                "max_drawdown": r.max_drawdown,
            }
            for r in rows
        ]
    finally:
        db.close()


def filter_stable_region(
    results: list,
    min_avg_r: float = DEFAULT_MIN_AVG_R,
    min_profit_factor: float = DEFAULT_MIN_PROFIT_FACTOR,
    max_drawdown: float = DEFAULT_MAX_DRAWDOWN,
    min_trades: int = DEFAULT_MIN_TRADES,
    only_valid_rows: bool = True,
) -> list:
    """
    조건 만족하는 구간만 남김. max_drawdown은 값이 클수록 낙폭이 큰 것이므로 threshold 이하만 허용.
    only_valid_rows: True이면 valid=False인 행만 제외 (sanity-flagged). Clean CSV에는 valid 컬럼 없음 → 전부 사용.
    """
    stable = []
    for r in results:
        if only_valid_rows and "valid" in r and r.get("valid") is False:
            continue
        trades = r.get("trades") or 0
        avg_r = r.get("avg_R")
        pf = r.get("profit_factor")
        dd = r.get("max_drawdown")
        if trades < min_trades:
            continue
        if avg_r is None or avg_r < min_avg_r:
            continue
        if pf is None or pf < min_profit_factor:
            continue
        if dd is not None and dd > max_drawdown:
            continue
        stable.append(r)
    return stable


def center_of_stable(stable: list) -> dict:
    """Stable region 내 조합들에 대해 ema/vol/rsi 의 중앙값(median) 계산 → config에 넣을 제안값."""
    if not stable:
        return {}
    ema_vals = sorted([r["ema_distance_threshold"] for r in stable if r.get("ema_distance_threshold") is not None])
    vol_vals = sorted([r["volume_ratio_threshold"] for r in stable if r.get("volume_ratio_threshold") is not None])
    rsi_vals = sorted([r["rsi_threshold"] for r in stable if r.get("rsi_threshold") is not None])
    if not ema_vals or not vol_vals or not rsi_vals:
        return {}

    def median(arr):
        n = len(arr)
        if n % 2 == 1:
            return arr[n // 2]
        return (arr[n // 2 - 1] + arr[n // 2]) / 2.0

    ema_rec = median(ema_vals)
    vol_rec = median(vol_vals)
    rsi_rec = median(rsi_vals)

    return {
        "strategy": {
            "ema_distance_threshold": round(ema_rec, 6),
            "volume_multiplier": round(vol_rec, 2),
            "rsi_long_min": int(round(rsi_rec)),
            "rsi_short_max": int(round(100 - rsi_rec)),
        },
        "approval": {
            "ema_distance_threshold": round(ema_rec, 6),
            "volume_multiplier_min": round(vol_rec, 2),
        },
        "_meta": {
            "stable_region_size": len(stable),
            "ema_range": [min(ema_vals), max(ema_vals)],
            "volume_range": [min(vol_vals), max(vol_vals)],
            "rsi_range": [min(rsi_vals), max(rsi_vals)],
        },
    }


def run(
    results: list,
    min_avg_r: float = DEFAULT_MIN_AVG_R,
    min_profit_factor: float = DEFAULT_MIN_PROFIT_FACTOR,
    max_drawdown: float = DEFAULT_MAX_DRAWDOWN,
    min_trades: int = DEFAULT_MIN_TRADES,
    only_valid_rows: bool = True,
) -> dict:
    """Stable region 필터 → 중앙값 제안. 넓은 안정 구간(broad stable region) 선호. 반환: recommended config fragment + _stable_sample for explanation."""
    stable = filter_stable_region(
        results,
        min_avg_r=min_avg_r,
        min_profit_factor=min_profit_factor,
        max_drawdown=max_drawdown,
        min_trades=min_trades,
        only_valid_rows=only_valid_rows,
    )
    if not stable:
        logger.warning("No rows in stable region (min_avg_r=%s, min_pf=%s, max_dd=%s, min_trades=%s)",
                       min_avg_r, min_profit_factor, max_drawdown, min_trades)
        return {}
    rec = center_of_stable(stable)
    # Sample one row for explanation (median-like)
    mid = stable[len(stable) // 2]
    rec["_stable_sample"] = {
        "trades": mid.get("trades"),
        "avg_R": mid.get("avg_R"),
        "profit_factor": mid.get("profit_factor"),
        "winrate": mid.get("winrate"),
    }
    return rec


def write_explanation(recommended: dict, out_path: Path, min_trades: int, min_pf: float, min_avg_r: float) -> None:
    """recommended_config_explanation.txt: 왜 그 값이 선택됐는지, trades, avg_R, PF, stable region 범위."""
    meta = recommended.get("_meta", {})
    sample = recommended.get("_stable_sample", {})
    lines = [
        "Recommended config — stable region 중심값",
        "=" * 50,
        "",
        "선택 기준 (모두 만족하는 구간의 중앙값):",
        f"  - trades >= {min_trades}",
        f"  - profit_factor > {min_pf}",
        f"  - avg_R > {min_avg_r}",
        "",
        "Stable region 크기 (조합 수): " + str(meta.get("stable_region_size", 0)),
        "Stable region 범위:",
        f"  - ema_distance_threshold: {meta.get('ema_range', [])}",
        f"  - volume_ratio_threshold: {meta.get('volume_range', [])}",
        f"  - rsi_threshold: {meta.get('rsi_range', [])}",
        "",
        "대표 샘플 (구간 중앙 부근):",
        f"  - trades: {sample.get('trades')}",
        f"  - avg_R: {sample.get('avg_R')}",
        f"  - profit_factor: {sample.get('profit_factor')}",
        f"  - winrate %: {sample.get('winrate')}",
        "",
        "이 값은 자동 적용이 아니라 검토 후 config.json에 반영하세요.",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Scan 결과에서 stable region → recommended_config.json")
    parser.add_argument("--from-csv", type=str, default="", help="Path to parameter_scan_results_clean.csv (preferred) or parameter_scan_results.csv")
    parser.add_argument("--from-db", action="store_true", help="DB parameter_scan_results에서 로드")
    parser.add_argument("--output", type=str, default="analysis/output/recommended_config.json")
    parser.add_argument("--min-avg-r", type=float, default=DEFAULT_MIN_AVG_R)
    parser.add_argument("--min-profit-factor", type=float, default=DEFAULT_MIN_PROFIT_FACTOR)
    parser.add_argument("--max-drawdown", type=float, default=DEFAULT_MAX_DRAWDOWN)
    parser.add_argument("--min-trades", type=int, default=DEFAULT_MIN_TRADES)
    args = parser.parse_args()

    if args.from_csv:
        path = Path(args.from_csv)
        if not path.exists():
            logger.error("CSV not found: %s", path)
            sys.exit(1)
        results = load_results_csv(path)
    elif args.from_db:
        results = load_results_db()
    else:
        logger.error("Provide --from-csv or --from-db")
        sys.exit(1)

    if not results:
        logger.warning("No scan results loaded")
        sys.exit(0)

    recommended = run(
        results,
        min_avg_r=args.min_avg_r,
        min_profit_factor=args.min_profit_factor,
        max_drawdown=args.max_drawdown,
        min_trades=args.min_trades,
    )
    if not recommended:
        sys.exit(0)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # _stable_sample은 설명용; JSON에는 _meta만 남기고 내부용 키 제거해 저장 가능
    to_dump = {k: v for k, v in recommended.items() if not k.startswith("_")}
    to_dump["_meta"] = recommended.get("_meta", {})
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(to_dump, f, indent=2, ensure_ascii=False)
    logger.info("Wrote %s (stable region size=%s). Review and merge into config.json.", out_path, recommended.get("_meta", {}).get("stable_region_size"))

    expl_path = out_path.parent / "recommended_config_explanation.txt"
    write_explanation(recommended, expl_path, args.min_trades, args.min_profit_factor, args.min_avg_r)
    logger.info("Wrote %s", expl_path)


if __name__ == "__main__":
    main()
