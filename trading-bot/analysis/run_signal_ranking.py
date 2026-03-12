"""
Phase 5 — Signal ranking layer: score candidates by features, trade top N% and compare metrics.

Score = momentum_ratio*0.25 + body_to_range_ratio*0.15 + (1-close_near_high)*0.15 + volume_zscore*0.10
      + ema50_slope*0.10 + atr_ratio_1m_5m*0.10 + breakout_pressure*0.10 - upper_wick_ratio*0.05

Where:
  atr_ratio_1m_5m = atr_1m / atr_5m (volatility compression)
  breakout_pressure = 1 - dist_from_recent_high_pct/10 (normalized 0..1)

Then sort by score and evaluate: all, top 50%, top 30%, top 20%, top 10%.

Usage:
  python -m analysis.run_signal_ranking --from-db [--output-dir analysis/output]
  python -m analysis.run_signal_ranking --from-db --previous-dir analysis/output/202603090215

Outputs:
  signal_ranking_results.csv
  ranking_performance_chart.png
  ranking_summary.txt
"""
import argparse
import csv
import sys
from pathlib import Path

# Project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.stability_map import _get_float, metrics_for_rows
from analysis.store_loader import load_rows_from_store


def _score_signal(r: dict) -> float:
    """
    score = momentum_ratio*0.25 + body_to_range_ratio*0.15 + (1-close_near_high)*0.15 + volume_zscore*0.10
          + ema50_slope*0.10 + atr_ratio_1m_5m*0.10 + breakout_pressure*0.10 - upper_wick_ratio*0.05

    atr_ratio_1m_5m = atr_1m / atr_5m (clamped for div-by-zero)
    breakout_pressure = max(0, 1 - dist_from_recent_high_pct/10) (normalized 0..1)
    """
    mom = _get_float(r, "momentum_ratio", 1.0)
    body_range = _get_float(r, "body_to_range_ratio", _get_float(r, "candle_strength", 1.0))
    close_near_high = _get_float(r, "close_near_high", 0.0)
    vol_z = _get_float(r, "volume_zscore", 0.0)
    slope = _get_float(r, "ema50_slope", 0.0)
    upper_wick = _get_float(r, "upper_wick_ratio", 0.0)
    atr_1m = _get_float(r, "atr_1m", 0.0)
    atr_5m = _get_float(r, "atr_5m", 1.0)
    dist_high = _get_float(r, "dist_from_recent_high_pct", 0.0)

    atr_ratio_1m_5m = (atr_1m / atr_5m) if atr_5m and atr_5m > 0 else 1.0
    atr_ratio_norm = min(atr_ratio_1m_5m, 2.0) / 2.0  # 0..1
    breakout_pressure = max(0.0, 1.0 - dist_high / 10.0)  # 0..1
    close_reward = 1.0 - close_near_high  # high when close near high
    slope_scaled = max(0, min(1, (slope * 100 + 1) / 2))  # -0.01..0.01 -> 0..1
    vol_z_scaled = max(0, min(1, (vol_z + 2) / 4))  # -2..2 -> 0..1

    return (
        min(mom, 1.5) / 1.5 * 0.25
        + min(body_range, 1.0) * 0.15
        + min(close_reward, 1.0) * 0.15
        + vol_z_scaled * 0.10
        + slope_scaled * 0.10
        + atr_ratio_norm * 0.10
        + breakout_pressure * 0.10
        - min(upper_wick, 1.0) * 0.05
    )


def load_candidates_csv(path: Path) -> list:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows


def load_candidates_db(symbol: str = "BTCUSDT", limit: int = 10000, signals_table: str = "candidate_signals") -> list:
    """
    기존: candidate_signals + signal_outcomes.
    신규: feature_store_1m + outcome_store_1m (signals_table 인자는 레거시 호환용).
    """
    # 우선순위: feature/outcome store에서 직접 로딩
    try:
        rows = load_rows_from_store(symbol=symbol, limit=limit, feature_version=1)
        if rows:
            return rows
    except Exception:
        pass
    # fallback: 기존 candidate_signals 경로
    from storage.database import SessionLocal, init_db
    from storage.repositories import get_candidate_signals_with_outcomes

    init_db()
    db = SessionLocal()
    try:
        return get_candidate_signals_with_outcomes(db, symbol=symbol, limit=limit, signals_table=signals_table)
    finally:
        db.close()


def _get_pf_by_percentile(csv_path: Path, pct: int) -> float | None:
    with open(csv_path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("percentile") == f"top_{pct}%":
                try:
                    return float(row.get("profit_factor", 0))
                except (TypeError, ValueError):
                    return None
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Signal ranking: score and trade top N%")
    parser.add_argument("--candidates-csv", type=str, default="")
    parser.add_argument("--from-db", action="store_true")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--output-dir", type=str, default="analysis/output")
    parser.add_argument("--previous-dir", type=str, default="", help="이전 런 폴더 (top 10%%/20%% PF 비교용)")
    parser.add_argument("--signals-table", type=str, default="candidate_signals", help="DB signals table/view name (default: candidate_signals)")
    args = parser.parse_args()

    if args.candidates_csv:
        path = Path(args.candidates_csv)
        if not path.exists():
            print("CSV not found:", path, file=sys.stderr)
            sys.exit(1)
        rows = load_candidates_csv(path)
        r_key = "R_return"
    elif args.from_db:
        rows = load_candidates_db(symbol=args.symbol, limit=args.limit, signals_table=args.signals_table)
        r_key = "future_r_30"
    else:
        print("Provide --candidates-csv or --from-db", file=sys.stderr)
        sys.exit(1)

    if not rows:
        print("No rows loaded", file=sys.stderr)
        sys.exit(0)

    # Add score to each row (handle both dict with feature_values and flat dict)
    for r in rows:
        if "feature_values" in r and isinstance(r.get("feature_values"), dict):
            flat = {**r, **r["feature_values"]}
        else:
            flat = r
        r["_ranking_score"] = _score_signal(flat)
    rows_sorted = sorted(rows, key=lambda x: x["_ranking_score"], reverse=True)
    n = len(rows_sorted)

    percentiles = [100, 50, 30, 20, 10]
    results = []
    for pct in percentiles:
        if pct == 100:
            subset = rows_sorted
        else:
            k = max(1, int(n * pct / 100))
            subset = rows_sorted[:k]
        m = metrics_for_rows(subset, r_key=r_key, r_cap=20.0)
        results.append({
            "percentile": f"top_{pct}%",
            "pct": pct,
            "n_signals": len(subset),
            "trades": m["trades"],
            "winrate": m["winrate"],
            "avg_R": m["avg_R"],
            "profit_factor": m["profit_factor"],
            "max_drawdown": m["max_drawdown"],
        })

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "signal_ranking_results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["percentile", "pct", "n_signals", "trades", "winrate", "avg_R", "profit_factor", "max_drawdown"])
        w.writeheader()
        w.writerows(results)
    print(f"Wrote {csv_path}")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots()
        labels = [r["percentile"] for r in results]
        x = range(len(labels))
        ax.bar([i - 0.2 for i in x], [r["avg_R"] for r in results], width=0.4, label="Avg R", color="steelblue")
        ax.bar([i + 0.2 for i in x], [r["profit_factor"] for r in results], width=0.4, label="Profit factor", color="darkorange")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=15)
        ax.set_ylabel("Value")
        ax.set_title("Signal ranking: performance by top N%")
        ax.legend()
        ax.axhline(0, color="gray", linestyle="--")
        fig.tight_layout()
        fig.savefig(out_dir / "ranking_performance_chart.png", dpi=100)
        plt.close(fig)
        print(f"Wrote {out_dir / 'ranking_performance_chart.png'}")
    except ImportError:
        pass

    lines = [
        "Signal ranking summary",
        "=" * 50,
        "Score = momentum_ratio*0.25 + body_to_range_ratio*0.15 + (1-close_near_high)*0.15 + volume_zscore*0.10",
        "      + ema50_slope*0.10 + atr_ratio_1m_5m*0.10 + breakout_pressure*0.10 - upper_wick_ratio*0.05",
        "  atr_ratio_1m_5m = atr_1m/atr_5m,  breakout_pressure = 1 - dist_from_recent_high_pct/10",
        "",
    ]
    for r in results:
        lines.append(f"{r['percentile']}: n={r['n_signals']} trades={r['trades']} winrate={r['winrate']:.1f}% avg_R={r['avg_R']:.4f} PF={r['profit_factor']:.2f}")

    # Compare to previous run
    if args.previous_dir:
        prev_path = Path(args.previous_dir) / "signal_ranking_results.csv"
        if prev_path.exists():
            pf10_prev = _get_pf_by_percentile(prev_path, 10)
            pf20_prev = _get_pf_by_percentile(prev_path, 20)
            pf10_cur = _get_pf_by_percentile(csv_path, 10)
            pf20_cur = _get_pf_by_percentile(csv_path, 20)
            lines.append("")
            lines.append("--- PF comparison vs previous run ---")
            if pf10_prev is not None and pf10_cur is not None:
                delta10 = pf10_cur - pf10_prev
                lines.append(f"  top_10%%: {pf10_prev:.4f} -> {pf10_cur:.4f}  (delta: {delta10:+.4f})")
            if pf20_prev is not None and pf20_cur is not None:
                delta20 = pf20_cur - pf20_prev
                lines.append(f"  top_20%%: {pf20_prev:.4f} -> {pf20_cur:.4f}  (delta: {delta20:+.4f})")
            if pf10_cur is not None or pf20_cur is not None:
                print("\n  PF comparison vs previous:")
                if pf10_cur is not None:
                    print(f"    top_10%%: {pf10_cur:.4f}" + (f" (was {pf10_prev:.4f}, {pf10_cur - pf10_prev:+.4f})" if pf10_prev is not None else ""))
                if pf20_cur is not None:
                    print(f"    top_20%%: {pf20_cur:.4f}" + (f" (was {pf20_prev:.4f}, {pf20_cur - pf20_prev:+.4f})" if pf20_prev is not None else ""))

    (out_dir / "ranking_summary.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_dir / 'ranking_summary.txt'}")


if __name__ == "__main__":
    main()
