#!/usr/bin/env python3
"""
리서치 결과 CSV 한곳에 모으기 + 보기 쉬운 차트 생성.

- 지정한 run 폴더(또는 최신 run)의 CSV들을 research_bundle 폴더로 복사
- DB에서 후보 시그널 CSV로 내보내기 (백테스트 다시 안 돌려도 됨)
- 대시보드 차트 자동 생성 (edge decay, 레짐 비교, 파라미터 스캔)

Usage:
  # 최신 run 폴더 기준으로 CSV 모으기 + 차트 생성
  python scripts/export_research_bundle.py --latest

  # 특정 run 폴더 지정
  python scripts/export_research_bundle.py --run analysis/output/202603081221

  # DB에서 후보 시그널 CSV 내보내기 (리서치용, 백테스트 생략)
  python scripts/export_research_bundle.py --export-db --limit 20000

  # 위 둘 다: DB 내보내기 + 최신 run 번들 + 차트
  python scripts/export_research_bundle.py --latest --export-db --limit 20000
"""
import argparse
import csv
import shutil
import sys
from pathlib import Path

# Project root
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def get_latest_run_dir(base: Path) -> Path | None:
    """analysis/output 아래에서 가장 최신 YYYYMMDDHHmm 폴더."""
    if not base.exists():
        return None
    dirs = [d for d in base.iterdir() if d.is_dir() and d.name.isdigit() and len(d.name) >= 10]
    if not dirs:
        return None
    return max(dirs, key=lambda d: d.name)


def copy_run_csvs(run_dir: Path, bundle_dir: Path) -> list[Path]:
    """Run 폴더의 CSV들을 bundle_dir로 복사. 반환: 복사된 경로 목록."""
    bundle_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for f in run_dir.iterdir():
        if f.suffix.lower() == ".csv" or (f.suffix.lower() == ".txt" and "summary" in f.name.lower()):
            dest = bundle_dir / f.name
            shutil.copy2(f, dest)
            copied.append(dest)
    return copied


def export_db_candidates(bundle_dir: Path, symbol: str = "BTCUSDT", limit: int = 20000) -> Path | None:
    """DB에서 candidate_signals + outcomes 를 CSV로 저장. 경로 반환."""
    try:
        from storage.database import SessionLocal, init_db
        from storage.repositories import get_candidate_signals_with_outcomes
    except ImportError:
        return None
    init_db()
    db = SessionLocal()
    try:
        rows = get_candidate_signals_with_outcomes(db, symbol=symbol, limit=limit)
    finally:
        db.close()
    if not rows:
        return None
    bundle_dir.mkdir(parents=True, exist_ok=True)
    out_path = bundle_dir / "candidates_from_db.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        keys = list(rows[0].keys())
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in keys})
    return out_path


def main():
    parser = argparse.ArgumentParser(description="리서치 CSV 모으기 + 대시보드 차트")
    parser.add_argument("--run", type=str, default="", help="Run 폴더 경로 (예: analysis/output/202603081221)")
    parser.add_argument("--latest", action="store_true", help="최신 run 폴더 사용")
    parser.add_argument("--bundle-dir", type=str, default="", help="번들 저장 경로 (기본: analysis/output/research_bundle/<run_id>)")
    parser.add_argument("--export-db", action="store_true", help="DB 후보 시그널을 CSV로 내보내기")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--limit", type=int, default=20000, help="DB export 시 limit")
    parser.add_argument("--no-charts", action="store_true", help="차트 생성 생략")
    args = parser.parse_args()

    base = ROOT / "analysis" / "output"
    run_dir = None
    if args.run:
        run_dir = ROOT / args.run
        if not run_dir.exists():
            run_dir = Path(args.run)
        if not run_dir.exists():
            print("Run dir not found:", args.run, file=sys.stderr)
            sys.exit(1)
    elif args.latest:
        run_dir = get_latest_run_dir(base)
        if not run_dir:
            print("No run folder found under analysis/output", file=sys.stderr)
            sys.exit(1)
        print("Latest run:", run_dir)

    bundle_dir = Path(args.bundle_dir) if args.bundle_dir else (base / "research_bundle" / (run_dir.name if run_dir else "export"))
    if run_dir and not bundle_dir.is_absolute():
        bundle_dir = ROOT / bundle_dir
    bundle_dir.mkdir(parents=True, exist_ok=True)

    # 1) DB export
    if args.export_db:
        p = export_db_candidates(bundle_dir, symbol=args.symbol, limit=args.limit)
        if p:
            print("Exported DB candidates:", p)
        else:
            print("DB export failed or no data.", file=sys.stderr)

    # 2) Copy run CSVs to bundle
    if run_dir:
        copied = copy_run_csvs(run_dir, bundle_dir)
        print("Copied", len(copied), "files to", bundle_dir)
        for c in copied[:15]:
            print(" ", c.name)
        if len(copied) > 15:
            print(" ... and", len(copied) - 15, "more")

    # 3) Generate dashboard charts (from run_dir or bundle_dir if it has the CSVs)
    if not args.no_charts and run_dir:
        from analysis.research_dashboard import generate_all
        saved = generate_all(run_dir, bundle_dir)
        print("Dashboard charts:", len(saved))
        for s in saved:
            print(" ", s.name)
        html = bundle_dir / "research_dashboard.html"
        if html.exists():
            print("Open:", html.absolute())

    if not args.export_db and not run_dir:
        print("Use --latest or --run PATH to bundle run CSVs, or --export-db to export DB.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
