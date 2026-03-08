"""
Research dashboard: easy-to-read charts from scan + edge decay CSVs.

Reads CSVs from a run folder (e.g. analysis/output/202603081221) and generates:
- Edge decay: line/bar (horizon vs avg_R, winrate, PF) — overall + by regime
- Regime comparison: bar chart (TRENDING_UP / DOWN / RANGING)
- Parameter scan: top combos by avg_R, heatmap-style summary

Usage:
  python -m analysis.research_dashboard analysis/output/202603081221
  python -m analysis.research_dashboard analysis/output/202603081221 --out-dir analysis/output/research_bundle
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

# Project root
if __name__ == "__main__":
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))


def _ensure_matplotlib():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["figure.figsize"] = (8, 5)
        plt.rcParams["font.size"] = 10
        return plt
    except ImportError:
        return None


def _load_csv(path: Path) -> list[dict]:
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            row = {}
            for k, v in r.items():
                try:
                    if "." in str(v) or "e" in str(v).lower():
                        row[k] = float(v)
                    else:
                        row[k] = int(v) if v and v.strip().lstrip("-").isdigit() else v
                except (ValueError, TypeError):
                    row[k] = v
            out.append(row)
    return out


def plot_edge_decay(run_dir: Path, out_dir: Path, plt) -> list[Path]:
    """Edge decay: horizon 5/10/20/30 vs avg_R, winrate, PF. Overall + by regime."""
    saved = []
    run_dir = Path(run_dir)
    out_dir = Path(out_dir)

    # Overall
    p = run_dir / "edge_decay_by_horizon.csv"
    if not p.exists():
        return saved
    rows = _load_csv(p)
    if not rows:
        return saved

    horizons = [r["horizon"] for r in rows]
    avg_r = [r["avg_R"] for r in rows]
    winrate = [r["winrate"] for r in rows]
    pf = [min(r["profit_factor"], 3.0) for r in rows]  # cap for scale

    fig, ax1 = plt.subplots(figsize=(9, 5))
    ax1.bar([h - 0.8 for h in horizons], avg_r, width=0.7, color="steelblue", label="avg_R", edgecolor="navy")
    ax1.axhline(0, color="gray", linestyle="--", linewidth=0.8)
    ax1.set_xlabel("Horizon (bars)")
    ax1.set_ylabel("avg R", color="steelblue")
    ax1.set_xticks(horizons)
    ax1.tick_params(axis="y", labelcolor="steelblue")
    ax2 = ax1.twinx()
    ax2.plot(horizons, winrate, "o-", color="darkgreen", linewidth=2, markersize=8, label="Winrate %")
    ax2.set_ylabel("Winrate %", color="darkgreen")
    ax2.tick_params(axis="y", labelcolor="darkgreen")
    ax2.set_ylim(0, 60)
    ax1.set_title("Edge decay: avg R & Winrate by Horizon (Overall)")
    ax1.legend(loc="upper left")
    ax2.legend(loc="upper right")
    fig.tight_layout()
    path = out_dir / "dashboard_edge_decay_overall.png"
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    saved.append(path)

    # By regime
    for reg in ("trending_up", "trending_down", "ranging"):
        p = run_dir / f"edge_decay_by_horizon_{reg}.csv"
        if not p.exists():
            continue
        rows = _load_csv(p)
        if not rows:
            continue
        horizons = [r["horizon"] for r in rows]
        avg_r = [r["avg_R"] for r in rows]
        fig, ax = plt.subplots(figsize=(8, 4))
        bars = ax.bar(horizons, avg_r, width=1.5, color="coral" if "down" in reg else "seagreen" if "up" in reg else "gray", edgecolor="black")
        ax.axhline(0, color="gray", linestyle="--", linewidth=0.8)
        ax.set_xlabel("Horizon (bars)")
        ax.set_ylabel("avg R")
        ax.set_title(f"Edge decay: {reg.replace('_', ' ').title()}")
        for b, v in zip(bars, avg_r):
            ax.text(b.get_x() + b.get_width() / 2, b.get_height() + (0.02 if v >= 0 else -0.03), f"{v:.3f}", ha="center", fontsize=9)
        fig.tight_layout()
        path = out_dir / f"dashboard_edge_decay_{reg}.png"
        fig.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        saved.append(path)

    return saved


def plot_regime_comparison(run_dir: Path, out_dir: Path, plt) -> list[Path]:
    """Regime별 avg_R, trades 비교 막대 차트."""
    saved = []
    run_dir = Path(run_dir)
    out_dir = Path(out_dir)

    # Use edge_decay by regime: take horizon=30 (or first) for avg_R and trades
    regimes = []
    avg_rs = []
    trades_list = []
    for reg in ("trending_up", "trending_down", "ranging"):
        p = run_dir / f"edge_decay_by_horizon_{reg}.csv"
        if not p.exists():
            continue
        rows = _load_csv(p)
        if not rows:
            continue
        # use last horizon (30) as representative
        r = rows[-1]
        regimes.append(reg.replace("_", " ").title())
        avg_rs.append(r["avg_R"])
        trades_list.append(r["trades"])

    if not regimes:
        return saved

    fig, ax1 = plt.subplots(figsize=(8, 5))
    x = range(len(regimes))
    w = 0.35
    ax1.bar([i - w / 2 for i in x], avg_rs, width=w, label="avg R (horizon=30)", color="steelblue", edgecolor="navy")
    ax1.axhline(0, color="gray", linestyle="--", linewidth=0.8)
    ax1.set_ylabel("avg R", color="steelblue")
    ax1.set_xticks(x)
    ax1.set_xticklabels(regimes)
    ax1.tick_params(axis="y", labelcolor="steelblue")
    ax2 = ax1.twinx()
    ax2.bar([i + w / 2 for i in x], trades_list, width=w, label="trades", color="lightcoral", alpha=0.8, edgecolor="darkred")
    ax2.set_ylabel("Trades", color="darkred")
    ax2.tick_params(axis="y", labelcolor="darkred")
    ax1.set_title("Regime Comparison (Horizon 30)")
    ax1.legend(loc="upper left")
    ax2.legend(loc="upper right")
    fig.tight_layout()
    path = out_dir / "dashboard_regime_comparison.png"
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    saved.append(path)
    return saved


def plot_parameter_scan_top(run_dir: Path, out_dir: Path, plt, top_n: int = 15) -> list[Path]:
    """Parameter scan: top N 조합 by avg_R (막대 차트)."""
    saved = []
    p = run_dir / "parameter_scan_results_clean.csv"
    if not p.exists():
        p = run_dir / "parameter_scan_results_clean_no_trend.csv"
    if not p.exists():
        return saved
    rows = _load_csv(p)
    if not rows:
        return saved
    rows = sorted(rows, key=lambda r: r.get("avg_R", 0), reverse=True)[:top_n]
    labels = [f"ema={r['ema_distance_threshold']:.4f}\nvol={r['volume_ratio_threshold']}\nrsi={r['rsi_threshold']}" for r in rows]
    avg_rs = [r["avg_R"] for r in rows]
    trades = [r["trades"] for r in rows]

    fig, ax1 = plt.subplots(figsize=(12, 6))
    x = range(len(labels))
    ax1.bar(x, avg_rs, color="steelblue", edgecolor="navy")
    ax1.axhline(0, color="gray", linestyle="--", linewidth=0.8)
    ax1.set_ylabel("avg R")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
    ax1.set_title("Parameter Scan: Top combos by avg R")
    fig.tight_layout()
    path = out_dir / "dashboard_parameter_scan_top.png"
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    saved.append(path)
    return saved


def plot_parameter_scan_heatmap_simple(run_dir: Path, out_dir: Path, plt) -> list[Path]:
    """Parameter scan: ema vs volume (rsi 고정) heatmap."""
    p = run_dir / "parameter_scan_results_clean.csv"
    if not p.exists():
        p = run_dir / "parameter_scan_results_clean_no_trend.csv"
    if not p.exists():
        return []
    rows = _load_csv(p)
    if not rows:
        return []
    try:
        import numpy as np
    except ImportError:
        return []

    # Fix rsi at middle value
    rsi_vals = sorted({r["rsi_threshold"] for r in rows})
    rsi_fix = rsi_vals[len(rsi_vals) // 2] if rsi_vals else 50
    sub = [r for r in rows if r.get("rsi_threshold") == rsi_fix]
    if not sub:
        return []

    ema_vals = sorted({r["ema_distance_threshold"] for r in sub})
    vol_vals = sorted({r["volume_ratio_threshold"] for r in sub})
    ema_idx = {v: i for i, v in enumerate(ema_vals)}
    vol_idx = {v: i for i, v in enumerate(vol_vals)}
    grid = np.full((len(vol_vals), len(ema_vals)), np.nan)
    for r in sub:
        i = vol_idx.get(r["volume_ratio_threshold"])
        j = ema_idx.get(r["ema_distance_threshold"])
        if i is not None and j is not None:
            grid[i, j] = r["avg_R"]

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(grid, aspect="auto", origin="lower", cmap="RdYlGn", vmin=-0.15, vmax=0.1)
    ax.set_xticks(range(len(ema_vals)))
    ax.set_yticks(range(len(vol_vals)))
    ax.set_xticklabels([f"{x:.4f}" for x in ema_vals], rotation=45)
    ax.set_yticklabels([f"{y:.2f}" for y in vol_vals])
    ax.set_xlabel("EMA distance threshold")
    ax.set_ylabel("Volume ratio threshold")
    ax.set_title(f"Parameter Scan Heatmap (avg R, RSI={rsi_fix} fixed)")
    plt.colorbar(im, ax=ax, label="avg R")
    fig.tight_layout()
    path = out_dir / "dashboard_parameter_heatmap.png"
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return [path]


def write_html_index(out_dir: Path, chart_paths: list[Path], run_id: str = "") -> Path:
    """HTML 대시보드: 차트 이미지 + 섹션별 제목. 브라우저에서 열면 한눈에 보기 좋음."""
    out_dir = Path(out_dir)
    # 그룹: edge_decay → Edge decay, regime → 레짐 비교, parameter → 파라미터 스캔
    groups = {
        "edge": ("Edge decay (보유 봉수별 성과)", []),
        "regime": ("레짐별 비교", []),
        "parameter": ("파라미터 스캔", []),
    }
    for cp in chart_paths:
        name = cp.name
        if "edge_decay" in name:
            groups["edge"][1].append(cp)
        elif "regime" in name:
            groups["regime"][1].append(cp)
        elif "parameter" in name or "heatmap" in name:
            groups["parameter"][1].append(cp)

    lines = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'><title>Research Dashboard</title>",
        "<style>",
        "body{font-family:'Segoe UI',sans-serif;margin:24px;background:#f0f2f5;}",
        "h1{color:#1a1a2e;border-bottom:2px solid #16213e;padding-bottom:8px;}",
        ".section{background:#fff;padding:20px;margin:16px 0;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,.08);}",
        ".section h2{margin:0 0 12px 0;color:#16213e;font-size:1.1em;}",
        "img{max-width:100%;height:auto;border-radius:8px;margin:12px 0;display:block;}",
        ".meta{color:#666;font-size:0.9em;margin-bottom:20px;}",
        "</style></head><body>",
        "<h1>리서치 대시보드</h1>",
        f"<p class='meta'>Run: <strong>{run_id or 'latest'}</strong> · 차트 {len(chart_paths)}개</p>",
    ]
    for key, (title, paths) in groups.items():
        if not paths:
            continue
        lines.append("<div class='section'>")
        lines.append(f"<h2>{title}</h2>")
        for cp in sorted(paths, key=lambda p: p.name):
            lines.append(f"<p><img src='{cp.name}' alt='{cp.name}' style='max-width:920px;'/></p>")
        lines.append("</div>")
    lines.append("</body></html>")
    index_path = out_dir / "research_dashboard.html"
    index_path.write_text("\n".join(lines), encoding="utf-8")
    return index_path


def generate_all(run_dir: Path, out_dir: Path | None = None) -> list[Path]:
    """Generate all dashboard charts + HTML. run_dir = e.g. analysis/output/202603081221 (CSV 있는 폴더)."""
    run_dir = Path(run_dir)
    out_dir = Path(out_dir or run_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plt = _ensure_matplotlib()
    if plt is None:
        return []

    all_saved = []
    all_saved.extend(plot_edge_decay(run_dir, out_dir, plt))
    all_saved.extend(plot_regime_comparison(run_dir, out_dir, plt))
    all_saved.extend(plot_parameter_scan_top(run_dir, out_dir, plt))
    all_saved.extend(plot_parameter_scan_heatmap_simple(run_dir, out_dir, plt))
    if all_saved:
        write_html_index(out_dir, all_saved, run_dir.name)
    return all_saved


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Research dashboard: charts from scan + edge decay CSVs")
    parser.add_argument("run_dir", type=str, help="Run folder (e.g. analysis/output/202603081221)")
    parser.add_argument("--out-dir", type=str, default="", help="Output folder (default: same as run_dir)")
    args = parser.parse_args()
    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print("Run dir not found:", run_dir, file=sys.stderr)
        sys.exit(1)
    out_dir = Path(args.out_dir) if args.out_dir else run_dir
    saved = generate_all(run_dir, out_dir)
    print("Charts saved:", len(saved))
    for p in saved:
        print(" ", p)
    if saved:
        print("HTML:", out_dir / "research_dashboard.html")


if __name__ == "__main__":
    main()
