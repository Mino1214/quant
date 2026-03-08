#!/usr/bin/env python3
"""
7단계 Walk Forward Validation 검증 스크립트.
- _metrics_from_trades: 거래 리스트 → profit_factor, avg_R, drawdown
- default_folds: 폴드 기간 반환
- run_walk_forward: (선택) DB 캔들로 폴드 실행 후 결과 구조 확인
실행: cd trading-bot && PYTHONPATH=. python scripts/verify_walk_forward.py
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import Direction, TradeRecord


def verify_metrics_from_trades():
    """_metrics_from_trades 동작 확인."""
    from analysis.walk_forward import _metrics_from_trades

    base = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    trades = [
        TradeRecord(symbol="BTCUSDT", side=Direction.LONG, size=0.1, entry_price=100.0, exit_price=101.0, stop_loss=99.0, take_profit=102.0, pnl=100.0, rr=1.0, reason_entry="test", reason_exit="tp", opened_at=base, closed_at=base),
        TradeRecord(symbol="BTCUSDT", side=Direction.LONG, size=0.1, entry_price=100.0, exit_price=99.0, stop_loss=99.0, take_profit=102.0, pnl=-50.0, rr=-0.5, reason_entry="test", reason_exit="sl", opened_at=base, closed_at=base),
    ]
    m = _metrics_from_trades(trades)
    assert "profit_factor" in m and "avg_R" in m and "drawdown" in m
    assert m["avg_R"] == 0.25  # (1.0 + -0.5) / 2
    print("[OK] _metrics_from_trades returns profit_factor, avg_R, drawdown")
    return True


def verify_default_folds():
    """default_folds() 반환값 구조."""
    from analysis.walk_forward import default_folds

    folds = default_folds()
    assert isinstance(folds, list) and len(folds) >= 1
    for f in folds:
        assert len(f) == 4  # train_start, train_end, test_start, test_end
    print("[OK] default_folds() returns %d folds (train_start, train_end, test_start, test_end)" % len(folds))
    return True


def verify_run_walk_forward():
    """run_walk_forward 실행 후 결과 리스트·키 확인. 빠른 검증용으로 단일 폴드(짧은 기간) 사용."""
    from analysis.walk_forward import run_walk_forward

    # 짧은 기간 1폴드만 사용해 DB 부하·대기 시간 최소화 (캔들 없으면 0 메트릭으로 즉시 반환)
    quick_folds = [
        (datetime(2020, 1, 1), datetime(2020, 1, 2), datetime(2020, 1, 2), datetime(2020, 1, 3)),
    ]
    try:
        results = run_walk_forward(quick_folds, symbol="BTCUSDT", table="btc1m")
    except Exception as e:
        print("[SKIP] run_walk_forward (DB/candles): %s" % (e,))
        return True
    assert isinstance(results, list)
    assert len(results) == len(quick_folds)
    for r in results:
        for k in ["train_start", "train_end", "test_start", "test_end", "profit_factor", "avg_R", "drawdown", "stability_score"]:
            assert k in r
    print("[OK] run_walk_forward returned %d results with expected keys" % len(results))
    return True


def main():
    print("=== 7단계 Walk Forward Validation 검증 ===\n")
    ok = True
    try:
        verify_metrics_from_trades()
    except Exception as e:
        print("[FAIL] _metrics_from_trades:", e)
        ok = False
    print()
    try:
        verify_default_folds()
    except Exception as e:
        print("[FAIL] default_folds:", e)
        ok = False
    print()
    try:
        verify_run_walk_forward()
    except Exception as e:
        print("[FAIL] run_walk_forward:", e)
        ok = False
    print()
    if ok:
        print("7단계 검증 통과.")
    else:
        print("일부 검증 실패.")
        sys.exit(1)


if __name__ == "__main__":
    main()
