#!/usr/bin/env python3
"""
5단계 Research / Signal Distribution Analysis 검증 스크립트.
- distributions: r_distribution, score_vs_outcome, regime_performance 등 동작
- run_analysis 실행 (샘플 데이터) 후 크래시 없음
- (선택) analysis/output 에 차트/출력 생성
실행: cd trading-bot && PYTHONPATH=. python scripts/verify_research_analysis.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _sample_rows():
    """검증용 샘플 rows (executed + R_return 있음)."""
    return [
        {"trade_outcome": "executed", "R_return": 0.5, "approval_score": 5, "regime": "TRENDING_UP", "ema_distance": 0.001, "volume_ratio": 1.2, "holding_time_bars": 10, "timestamp": "2024-03-01T10:00:00Z"},
        {"trade_outcome": "executed", "R_return": -0.3, "approval_score": 4, "regime": "RANGE", "ema_distance": 0.002, "volume_ratio": 1.0, "holding_time_bars": 5, "timestamp": "2024-03-01T14:30:00Z"},
        {"trade_outcome": "executed", "R_return": 1.0, "approval_score": 6, "regime": "TRENDING_UP", "ema_distance": 0.0008, "volume_ratio": 1.5, "holding_time_bars": 20, "timestamp": "2024-03-01T08:00:00Z"},
        {"trade_outcome": "blocked", "R_return": "", "approval_score": 3, "regime": "CHAOTIC"},
    ]


def verify_distributions():
    """distributions 모듈 함수들이 샘플 데이터로 동작."""
    from analysis.distributions import (
        _executed_rows,
        r_distribution,
        score_vs_outcome,
        regime_performance,
        feature_impact_ema_distance,
        holding_time_impact,
        time_of_day_impact,
    )

    rows = _sample_rows()
    executed = _executed_rows(rows)
    assert len(executed) == 3
    print("[OK] _executed_rows filters executed + R_return")

    bins, counts = r_distribution(rows)
    assert isinstance(bins, list) and isinstance(counts, list)
    print("[OK] r_distribution returns (bins, counts)")

    score_data = score_vs_outcome(rows)
    assert isinstance(score_data, list)
    print("[OK] score_vs_outcome returns list")

    regime_data = regime_performance(rows)
    assert isinstance(regime_data, list)
    print("[OK] regime_performance returns list")

    feature_impact_ema_distance(rows)
    holding_time_impact(rows)
    time_of_day_impact(rows)
    print("[OK] feature_impact, holding_time, time_of_day run without error")
    return True


def verify_run_analysis():
    """run_analysis(rows, output_dir) 실행 후 크래시 없음."""
    from analysis.run_signal_analysis import run_analysis

    out_dir = Path(__file__).resolve().parent.parent / "analysis" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = _sample_rows()
    run_analysis(rows, out_dir)
    print("[OK] run_analysis(rows, output_dir) completed")
    return True


def main():
    print("=== 5단계 Research / Signal Distribution Analysis 검증 ===\n")
    ok = True
    try:
        verify_distributions()
    except Exception as e:
        print("[FAIL] Distributions:", e)
        ok = False
    print()
    try:
        verify_run_analysis()
    except Exception as e:
        print("[FAIL] run_analysis:", e)
        ok = False
    print()
    if ok:
        print("5단계 검증 통과.")
    else:
        print("일부 검증 실패.")
        sys.exit(1)


if __name__ == "__main__":
    main()
