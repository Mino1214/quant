"""
Feature-engineering research cycle: run parameter scan, entry quality, signal ranking, meta labeling;
compare to previous run; check goal (top 10% profit factor > 1.3).

Assumes new features (atr_ratio, distance_from_high_20, candle_strength, close_position_in_candle,
volume_spike) are in feature_extractor and dataset is rebuilt via build_signal_dataset.

Usage:
  python -m analysis.run_research_cycle
  python -m analysis.run_research_cycle --previous-dir analysis/output/202603081730
  python -m analysis.run_research_cycle --limit 50000

Output: {output_dir}/{timestamp}/ with pipeline outputs + research_cycle_summary.txt (comparison + goal).
"""
import argparse
import csv
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOAL_TOP10_PF = 1.3


def run(cmd: list, name: str) -> bool:
    print(f"\n[{name}] {' '.join(cmd)}")
    rc = subprocess.run(cmd, cwd=ROOT)
    if rc.returncode != 0:
        print(f"[{name}] 실패 (exit {rc.returncode})", file=sys.stderr)
        return False
    return True


def get_top10_pf(csv_path: Path) -> float | None:
    with open(csv_path, "r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            if row.get("percentile") == "top_10%":
                try:
                    return float(row.get("profit_factor", 0))
                except (TypeError, ValueError):
                    return None
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Feature-engineering research cycle + compare + goal")
    parser.add_argument("--output-dir", type=str, default="analysis/output")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--previous-dir", type=str, default=None, help="이전 런 폴더 (비교용, e.g. analysis/output/202603081730)")
    parser.add_argument("--rebuild-dataset", action="store_true", help="먼저 build_signal_dataset 실행 (새 피처 반영된 데이터셋으로 재구축)")
    parser.add_argument("--dataset-limit", type=int, default=None, help="--rebuild-dataset 시 로드할 1m 봉 수 (미지정 시 전체)")
    parser.add_argument("--signals-table", type=str, default="candidate_signals", help="candidate_signals 대신 사용할 signals table/view (e.g. candidate_signals_sorted)")
    args = parser.parse_args()

    start = time.perf_counter()
    limit = args.limit if args.limit is not None else 500_000
    base_out = Path(args.output_dir)
    run_ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    out_dir = base_out / run_ts
    out_dir.mkdir(parents=True, exist_ok=True)
    out = str(out_dir)
    py = sys.executable
    print(f"출력 폴더: {out}")

    if args.rebuild_dataset:
        ds_limit = args.dataset_limit or 500_000
        build_cmd = [py, "-m", "scripts.build_signal_dataset", "--symbol", args.symbol, "--limit", str(ds_limit), "--skip-existing"]
        if not run(build_cmd, "Rebuild dataset (build_signal_dataset)"):
            sys.exit(1)

    # 1) Baseline (so we have a baseline in this run)
    if not run([py, "-m", "analysis.run_baseline", "--from-candidates-db", "--output-dir", out, "--limit", str(limit), "--signals-table", args.signals_table], "Baseline (candidate_signals)"):
        sys.exit(1)
    # 2) Parameter scan (stability scan)
    if not run(
        [py, "-m", "analysis.run_stability_scan", "--from-db", "--output-dir", out, "--no-timestamp-dir", "--limit", str(limit), "--symbol", args.symbol, "--signals-table", args.signals_table],
        "Parameter scan (stability)",
    ):
        sys.exit(1)
    if not run([py, "-m", "analysis.run_regime_summary", out], "Regime summary"):
        sys.exit(1)
    # 3) Entry quality scan
    if not run([py, "-m", "analysis.run_entry_quality_scan", "--from-db", "--output-dir", out, "--limit", str(limit), "--signals-table", args.signals_table], "Entry quality scan"):
        sys.exit(1)
    # 4) Signal ranking
    if not run([py, "-m", "analysis.run_signal_ranking", "--from-db", "--output-dir", out, "--limit", str(limit), "--signals-table", args.signals_table], "Signal ranking"):
        sys.exit(1)
    # 5) Meta labeling
    if not run([py, "-m", "analysis.run_meta_labeling", "--from-db", "--output-dir", out, "--limit", str(limit), "--signals-table", args.signals_table], "Meta labeling"):
        sys.exit(1)

    # Compare & goal
    ranking_csv = out_dir / "signal_ranking_results.csv"
    current_pf = get_top10_pf(ranking_csv) if ranking_csv.exists() else None
    previous_pf = None
    if args.previous_dir:
        prev_path = Path(args.previous_dir) / "signal_ranking_results.csv"
        if prev_path.exists():
            previous_pf = get_top10_pf(prev_path)

    goal_met = current_pf is not None and current_pf >= GOAL_TOP10_PF
    lines = [
        "=" * 60,
        "Research cycle summary (feature engineering)",
        "=" * 60,
        f"Run: {run_ts}",
        "",
        "New features in dataset:",
        "  atr_ratio = atr_5 / atr_50 (5m)",
        "  distance_from_high_20",
        "  candle_strength = body / range",
        "  close_position_in_candle = (close-low)/(high-low)",
        "  volume_spike = volume / volume_ma20",
        "",
        "Pipeline: parameter scan → entry quality → signal ranking → meta labeling",
        "",
        "--- Goal: top 10% profit factor > 1.3 ---",
        f"  Current run top_10%% PF: {current_pf}" + (" (goal met)" if goal_met else f" (goal: >= {GOAL_TOP10_PF})"),
    ]
    if previous_pf is not None:
        delta = (current_pf or 0) - previous_pf
        lines.append(f"  Previous run top_10%% PF: {previous_pf}")
        lines.append(f"  Delta: {delta:+.4f}")
    lines.append("")
    lines.append("Outputs in this run: baseline_*.csv, parameter_scan_results*.csv, entry_quality_*.csv,")
    lines.append("signal_ranking_results.csv, ranking_summary.txt, meta_model_*.csv, etc.")
    summary_path = out_dir / "research_cycle_summary.txt"
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  요약: {summary_path}")
    print(f"  Top 10%% PF: {current_pf}  (goal >= {GOAL_TOP10_PF})" + (" [목표 달성]" if goal_met else ""))

    # 리서치 파이프라인처럼 한눈에 보는 최종본도 생성 (baseline, regime, entry quality, ranking, meta 등)
    elapsed = time.perf_counter() - start

    def _format_elapsed(sec: float) -> str:
        s = int(round(sec))
        if s < 60:
            return f"{s}초"
        m, s = divmod(s, 60)
        if m < 60:
            return f"{m}분 {s}초"
        h, m = divmod(m, 60)
        return f"{h}시간 {m}분 {s}초"

    _lines = [
        "=" * 60,
        "리서치 파이프라인 요약 최종본",
        "=" * 60,
        f"Run: {run_ts}  |  소요 시간: {_format_elapsed(elapsed)}",
        "",
    ]
    for title, fname in [
        ("Phase 1 — Baseline", "baseline_summary.txt"),
        ("Phase 2 — Regime 진단", "regime_diagnostics.txt"),
        ("Phase 3 — Edge 감쇠 / 홀딩", "optimal_holding_period.txt"),
        ("Phase 4 — Entry quality", "entry_quality_scan.csv"),
        ("Phase 5 — Signal ranking", "ranking_summary.txt"),
        ("Phase 6 — Meta labeling", "meta_model_summary.txt"),
    ]:
        path = out_dir / fname
        if not path.exists():
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
            if fname.endswith(".csv"):
                raw = "\n".join(raw.strip().split("\n")[:8])
            _lines.append("-" * 60)
            _lines.append(title)
            _lines.append("-" * 60)
            _lines.append(raw.strip())
            _lines.append("")
        except OSError:
            _lines.append(f"[{title}] {fname} 읽기 실패")
            _lines.append("")
    final_summary_path = out_dir / "research_summary.txt"
    final_summary_path.write_text("\n".join(_lines), encoding="utf-8")
    print(f"  요약 최종본: {final_summary_path}")


if __name__ == "__main__":
    main()
