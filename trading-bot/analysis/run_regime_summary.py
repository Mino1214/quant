"""
Regime summary: PF avg, best PF, avg_R avg 등 레짐별 parameter_scan_results_*.csv 요약.

Usage:
  python -m analysis.run_regime_summary analysis/output/202603081556
  python -m analysis.run_regime_summary   # default: analysis/output 중 최신 타임스탬프 폴더
"""
import csv
import sys
from pathlib import Path

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            row = {}
            for k, v in r.items():
                if v == "" or v is None:
                    row[k] = None
                    continue
                try:
                    if k == "trades":
                        row[k] = int(float(v))
                    else:
                        row[k] = float(v)
                except (ValueError, TypeError):
                    row[k] = v
            rows.append(row)
    return rows


def summarize_results(csv_path: Path) -> dict:
    """
    한 레짐 CSV 요약: pf_avg, best_pf, best_pf_params(ema, vol, rsi), avg_r_avg, best_avg_r 등.
    """
    rows = _load_csv(csv_path)
    if not rows:
        return {
            "pf_avg": None,
            "best_pf": None,
            "best_pf_params": None,
            "avg_r_avg": None,
            "best_avg_r": None,
            "n_combos": 0,
            "trade_count": 0,
            "min_trades": None,
        }
    pfs = [r["profit_factor"] for r in rows if r.get("profit_factor") is not None]
    avg_rs = [r["avg_R"] for r in rows if r.get("avg_R") is not None]
    trades = [r["trades"] for r in rows if r.get("trades") is not None]
    best_pf = max(pfs) if pfs else None
    best_row = max(rows, key=lambda r: r.get("profit_factor") or 0) if rows and best_pf is not None else None
    best_pf_params = None
    if best_row is not None:
        best_pf_params = {
            "ema_distance_threshold": best_row.get("ema_distance_threshold"),
            "volume_ratio_threshold": best_row.get("volume_ratio_threshold"),
            "rsi_threshold": best_row.get("rsi_threshold"),
        }
    total_trades = sum(trades) if trades else 0
    return {
        "pf_avg": round(sum(pfs) / len(pfs), 2) if pfs else None,
        "best_pf": round(best_pf, 2) if best_pf is not None else None,
        "best_pf_params": best_pf_params,
        "avg_r_avg": round(sum(avg_rs) / len(avg_rs), 4) if avg_rs else None,
        "best_avg_r": round(max(avg_rs), 4) if avg_rs else None,
        "n_combos": len(rows),
        "trade_count": total_trades,
        "min_trades": min(trades) if trades else None,
        "max_trades": max(trades) if trades else None,
    }


def build_regime_summary(run_dir: Path) -> dict:
    """레짐별 요약 딕셔너리 반환 (프로그래밍용)."""
    run_dir = Path(run_dir)
    regime_files = {
        "trending_up": run_dir / "parameter_scan_results_trending_up.csv",
        "trending_down": run_dir / "parameter_scan_results_trending_down.csv",
        "ranging": run_dir / "parameter_scan_results_ranging.csv",
        "chaotic": run_dir / "parameter_scan_results_chaotic.csv",
    }
    return {name: summarize_results(path) for name, path in regime_files.items()}


def write_regime_summary_table(run_dir: Path, regime_summary: dict) -> Path:
    """Write regime_summary_table.csv. Returns path."""
    path = Path(run_dir) / "regime_summary_table.csv"
    rows = []
    for name, s in regime_summary.items():
        rows.append({
            "regime": name,
            "average_profit_factor": s.get("pf_avg"),
            "best_profit_factor": s.get("best_pf"),
            "average_avg_R": s.get("avg_r_avg"),
            "best_avg_R": s.get("best_avg_r"),
            "trade_count": s.get("trade_count", 0),
        })
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["regime", "average_profit_factor", "best_profit_factor", "average_avg_R", "best_avg_R", "trade_count"])
        w.writeheader()
        w.writerows(rows)
    return path


def write_regime_performance_chart(run_dir: Path, regime_summary: dict) -> Path | None:
    """Write regime_performance_chart.png (bar chart: best PF and avg PF per regime). Returns path or None."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    regimes = []
    avg_pf = []
    best_pf = []
    for name, s in regime_summary.items():
        if s.get("n_combos", 0) == 0:
            continue
        regimes.append(name.replace("_", " ").title())
        avg_pf.append(s.get("pf_avg") or 0)
        best_pf.append(s.get("best_pf") or 0)
    if not regimes:
        return None
    path = Path(run_dir) / "regime_performance_chart.png"
    fig, ax = plt.subplots()
    x = range(len(regimes))
    w = 0.35
    ax.bar([i - w / 2 for i in x], avg_pf, width=w, label="Avg PF", color="steelblue")
    ax.bar([i + w / 2 for i in x], best_pf, width=w, label="Best PF", color="darkorange")
    ax.set_xticks(x)
    ax.set_xticklabels(regimes)
    ax.set_ylabel("Profit factor")
    ax.set_title("Regime performance")
    ax.legend()
    ax.axhline(1.0, color="gray", linestyle="--")
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)
    return path


def write_regime_diagnostics(run_dir: Path, regime_summary: dict) -> Path:
    """Write regime_diagnostics.txt. Returns path."""
    path = Path(run_dir) / "regime_diagnostics.txt"
    lines = ["Regime diagnostics", "=" * 50]
    for name, s in regime_summary.items():
        lines.append(f"\n{name.upper()}")
        if s.get("n_combos", 0) == 0:
            lines.append("  (no data)")
            continue
        lines.append(f"  average_profit_factor: {s.get('pf_avg')}")
        lines.append(f"  best_profit_factor:    {s.get('best_pf')}")
        lines.append(f"  average_avg_R:         {s.get('avg_r_avg')}")
        lines.append(f"  best_avg_R:            {s.get('best_avg_r')}")
        lines.append(f"  trade_count:           {s.get('trade_count')}")
        if s.get("best_pf_params"):
            p = s["best_pf_params"]
            lines.append(f"  best params: ema={p.get('ema_distance_threshold')}, vol={p.get('volume_ratio_threshold')}, rsi={p.get('rsi_threshold')}")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def print_regime_summary(run_dir: Path) -> None:
    run_dir = Path(run_dir)
    regime_summary = build_regime_summary(run_dir)

    print("REGIME SUMMARY")
    print("=" * 50)
    for name, s in regime_summary.items():
        if s["n_combos"] == 0:
            print(f"\n{name}\n  (no data)")
            continue
        print(f"\n{name}")
        if s["pf_avg"] is not None:
            print(f"  PF avg: {s['pf_avg']}")
        if s["best_pf"] is not None:
            print(f"  best PF: {s['best_pf']}")
        if s.get("best_pf_params"):
            p = s["best_pf_params"]
            print(f"    → ema_distance: {p.get('ema_distance_threshold')}, volume_ratio: {p.get('volume_ratio_threshold')}, rsi: {p.get('rsi_threshold')}")
        if s["avg_r_avg"] is not None:
            print(f"  avg_R avg: {s['avg_r_avg']}")
        if s["best_avg_r"] is not None:
            print(f"  best avg_R: {s['best_avg_r']}")
        print(f"  combos: {s['n_combos']}, trade_count: {s.get('trade_count', 0)}")
    print()


def main() -> None:
    default_output = Path(__file__).resolve().parent / "output"
    if len(sys.argv) >= 2:
        run_dir = Path(sys.argv[1])
    else:
        if not default_output.exists():
            print("Usage: python -m analysis.run_regime_summary <run_dir>", file=sys.stderr)
            print("  e.g. analysis/output/202603081556", file=sys.stderr)
            sys.exit(1)
        # 최신 타임스탬프 폴더 사용
        subdirs = sorted([d for d in default_output.iterdir() if d.is_dir() and d.name.isdigit()], key=lambda p: p.name, reverse=True)
        run_dir = subdirs[0] if subdirs else default_output
    if not run_dir.exists():
        print("Run dir not found:", run_dir, file=sys.stderr)
        sys.exit(1)
    regime_summary = build_regime_summary(run_dir)
    print_regime_summary(run_dir)
    # Phase 2 outputs
    p1 = write_regime_summary_table(run_dir, regime_summary)
    print(f"Wrote {p1}")
    p2 = write_regime_performance_chart(run_dir, regime_summary)
    if p2:
        print(f"Wrote {p2}")
    p3 = write_regime_diagnostics(run_dir, regime_summary)
    print(f"Wrote {p3}")


if __name__ == "__main__":
    main()
