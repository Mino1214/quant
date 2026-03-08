#!/usr/bin/env python3
"""
6단계 Edge Stability Map 검증 스크립트.
- run_parameter_scan: 그리드 스캔 동작, 결과에 trades/winrate/avg_R 등 존재
- plot_heatmaps: (선택) 히트맵 생성
실행: cd trading-bot && PYTHONPATH=. python scripts/verify_edge_stability.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _sample_rows():
    """검증용 샘플 rows (ema_distance, volume_ratio, rsi, side, R_return)."""
    return [
        {"ema_distance": 0.0005, "volume_ratio": 1.2, "rsi": 55, "rsi_5m": 55, "side": "long", "R_return": 0.5},
        {"ema_distance": 0.001, "volume_ratio": 1.0, "rsi": 45, "rsi_5m": 45, "side": "short", "R_return": -0.3},
        {"ema_distance": 0.0008, "volume_ratio": 1.5, "rsi": 58, "rsi_5m": 58, "side": "long", "R_return": 1.0},
        {"ema_distance": 0.0012, "volume_ratio": 0.9, "rsi": 42, "rsi_5m": 42, "side": "short", "R_return": 0.2},
    ]


def verify_parameter_scan():
    """run_parameter_scan 실행 후 결과 구조 확인."""
    from analysis.stability_map import run_parameter_scan, metrics_for_rows

    rows = _sample_rows()
    ema_vals = [0.0003, 0.001]
    vol_vals = [0.9, 1.2]
    rsi_vals = [40, 50]
    results = run_parameter_scan(rows, ema_vals, vol_vals, rsi_vals, r_key="R_return")
    assert isinstance(results, list)
    assert len(results) == len(ema_vals) * len(vol_vals) * len(rsi_vals)
    required = ["ema_distance_threshold", "volume_ratio_threshold", "rsi_threshold", "trades", "winrate", "avg_R", "profit_factor", "max_drawdown"]
    for r in results:
        for k in required:
            assert k in r, "Missing key: %s" % k
    print("[OK] run_parameter_scan returns %d rows with expected keys" % len(results))
    return True


def verify_heatmaps():
    """plot_heatmaps 실행 후 파일 생성 여부."""
    from analysis.stability_map import run_parameter_scan, plot_heatmaps

    rows = _sample_rows()
    ema_vals = [0.0005, 0.001]
    vol_vals = [1.0, 1.2]
    rsi_vals = [45, 55]
    results = run_parameter_scan(rows, ema_vals, vol_vals, rsi_vals)
    out_dir = Path(__file__).resolve().parent.parent / "analysis" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = plot_heatmaps(results, str(out_dir))
    print("[OK] plot_heatmaps completed (saved %d files)" % len(paths))
    return True


def main():
    print("=== 6단계 Edge Stability Map 검증 ===\n")
    ok = True
    try:
        verify_parameter_scan()
    except Exception as e:
        print("[FAIL] Parameter scan:", e)
        ok = False
    print()
    try:
        verify_heatmaps()
    except Exception as e:
        print("[FAIL] Heatmaps:", e)
        ok = False
    print()
    if ok:
        print("6단계 검증 통과.")
    else:
        print("일부 검증 실패.")
        sys.exit(1)


if __name__ == "__main__":
    main()
