"""
리서치 파이프라인 한 번에 실행 — candidate_signals 테이블 개수만큼 전 단계 돌리기.

candidate_signals가 2만 개면 2만 개 전부로 baseline / 스캔 / edge decay / entry quality /
signal ranking / meta labeling 까지 한 번에 실행. 백테스트(캔들 돌리기)는 선택.

Usage:
  python -m analysis.run_research_pipeline
  python -m analysis.run_research_pipeline --limit 30000
  python -m analysis.run_research_pipeline --with-backtest   # Kelly, Walk-Forward 포함 (느림)

실행해 두고 다른 일 하면 됨.
"""
import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str], phase_name: str) -> bool:
    print(f"\n[{phase_name}] {' '.join(cmd)}")
    rc = subprocess.run(cmd, cwd=ROOT)
    if rc.returncode != 0:
        print(f"[{phase_name}] 실패 (exit {rc.returncode})", file=sys.stderr)
        return False
    return True


def _format_elapsed(seconds: float) -> str:
    s = int(round(seconds))
    if s < 60:
        return f"{s}초"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}분 {s}초"
    h, m = divmod(m, 60)
    return f"{h}시간 {m}분 {s}초"


def _write_final_summary(out_dir: Path, elapsed_sec: float, run_ts: str) -> None:
    """타임스탬프 폴더 내 결과를 모아 한눈에 보는 요약 최종본 생성."""
    lines = [
        "=" * 60,
        "리서치 파이프라인 요약 최종본",
        "=" * 60,
        f"Run: {run_ts}  |  소요 시간: {_format_elapsed(elapsed_sec)}",
        "",
    ]
    files_sections = [
        ("Phase 1 — Baseline", "baseline_summary.txt"),
        ("Phase 2 — Regime 진단", "regime_diagnostics.txt"),
        ("Phase 3 — Edge 감쇠 / 홀딩", "optimal_holding_period.txt"),
        ("Phase 4 — Entry quality", "entry_quality_scan.csv"),
        ("Phase 5 — Signal ranking", "ranking_summary.txt"),
        ("Phase 6 — Meta labeling", "meta_model_summary.txt"),
        ("Phase 7 — Kelly / Risk", "risk_analysis.txt"),
        ("Phase 8 — Walk-Forward", "walk_forward_summary.txt"),
    ]
    for title, fname in files_sections:
        path = out_dir / fname
        if not path.exists():
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
            if fname.endswith(".csv"):
                raw = "\n".join(raw.strip().split("\n")[:8])  # 상위 8줄만
            lines.append("-" * 60)
            lines.append(title)
            lines.append("-" * 60)
            lines.append(raw.strip())
            lines.append("")
        except OSError:
            lines.append(f"[{title}] {fname} 읽기 실패")
            lines.append("")
    summary_path = out_dir / "research_summary.txt"
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  요약 최종본: {summary_path}")


def main() -> None:
    start = time.perf_counter()
    parser = argparse.ArgumentParser(description="리서치 파이프라인 한 번에 실행 (시그널 테이블 기준)")
    parser.add_argument("--output-dir", type=str, default="analysis/output")
    parser.add_argument("--limit", type=int, default=None, help="시그널 개수 상한 (미지정 시 전부, 내부적으로 50만)")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--with-backtest", action="store_true", help="Kelly, Walk-Forward 포함 (1m 캔들 백테스트로 느림)")
    parser.add_argument("--no-png", action="store_true", help="종료 후 출력 폴더 내 모든 PNG 삭제")
    args = parser.parse_args()

    limit = args.limit if args.limit is not None else 500_000
    base_out = Path(args.output_dir)
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    out_dir = base_out / run_ts
    out_dir.mkdir(parents=True, exist_ok=True)
    out = str(out_dir)
    py = sys.executable
    print(f"출력 폴더: {out}")

    steps = [
        ("Phase 1 — Baseline (candidate_signals)", [py, "-m", "analysis.run_baseline", "--from-candidates-db", "--output-dir", out, "--limit", str(limit)]),
        ("Phase 2 — Stability scan + Regime 요약", None),
        ("Phase 3 — Edge decay", [py, "-m", "analysis.run_edge_decay", "--from-db", "--output-dir", out, "--limit", str(limit)]),
        ("Phase 4 — Entry quality scan", [py, "-m", "analysis.run_entry_quality_scan", "--from-db", "--output-dir", out, "--limit", str(limit)]),
        ("Phase 5 — Signal ranking", [py, "-m", "analysis.run_signal_ranking", "--from-db", "--output-dir", out, "--limit", str(limit)]),
        ("Phase 6 — Meta labeling", [py, "-m", "analysis.run_meta_labeling", "--from-db", "--output-dir", out, "--limit", str(limit)]),
    ]

    if not run(steps[0][1], steps[0][0]):
        sys.exit(1)

    if not run(
        [py, "-m", "analysis.run_stability_scan", "--from-db", "--output-dir", out, "--no-timestamp-dir", "--limit", str(limit), "--symbol", args.symbol],
        steps[1][0],
    ):
        sys.exit(1)
    if not run([py, "-m", "analysis.run_regime_summary", out], "Phase 2 — Regime summary"):
        sys.exit(1)

    for name, cmd in steps[2:]:
        if cmd and not run(cmd, name):
            sys.exit(1)

    if args.with_backtest:
        if not run([py, "-m", "analysis.run_kelly_sizing", "--from-db", "--output-dir", out], "Phase 7 — Kelly sizing"):
            sys.exit(1)
        if not run([py, "-m", "analysis.walk_forward", "--output-dir", out], "Phase 8 — Walk-Forward"):
            sys.exit(1)

    if args.no_png:
        for p in out_dir.rglob("*.png"):
            try:
                p.unlink()
                print(f"  삭제: {p.relative_to(out_dir)}")
            except OSError:
                pass
    elapsed = time.perf_counter() - start
    _write_final_summary(out_dir, elapsed, run_ts)
    print("\n리서치 파이프라인 완료.")
    print(f"  출력: {out}")
    print(f"  총 소요 시간: {_format_elapsed(elapsed)}")


if __name__ == "__main__":
    main()
