#!/usr/bin/env python3
"""
10단계 Execution Engine 검증 스크립트.
- risk.position_size: 레버리지 포함 포지션 사이즈 계산
- ExecutionEngine: position_size, execute_entry (PaperBroker 연동)
- PaperBroker: place_market_order, get_open_position, set_fill_price
실행: cd trading-bot && PYTHONPATH=. python scripts/verify_execution_engine.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import Direction


def verify_position_size():
    """risk.position_size: balance * risk_pct/100 * leverage / stop_distance."""
    from risk.position_size import position_size

    # balance=10000, 1%, entry=50000, stop_dist=1000 → risk=100, qty=0.1
    qty = position_size(10000.0, 1.0, 50000.0, 1000.0, Direction.LONG, leverage=1.0)
    assert abs(qty - 0.1) < 1e-6
    qty_lev = position_size(10000.0, 1.0, 50000.0, 1000.0, Direction.SHORT, leverage=2.0)
    assert abs(qty_lev - 0.2) < 1e-6
    print("[OK] position_size (risk/stop_distance, leverage)")
    return True


def verify_execution_engine_position_size():
    """ExecutionEngine.position_size with simple risk_pct."""
    from execution.paper_broker import PaperBroker
    from execution.execution_engine import ExecutionEngine

    broker = PaperBroker(initial_balance=10000.0)
    eng = ExecutionEngine(broker, equity=10000.0, risk_pct=0.01)
    qty = eng.position_size(entry=50000.0, stop_loss=49000.0, direction=Direction.LONG)
    assert qty > 0 and abs(qty - 0.1) < 1e-5  # 100/1000
    print("[OK] ExecutionEngine.position_size")
    return True


async def _verify_execute_entry():
    """execute_entry: market + SL + TP 주문 후 포지션 존재, set_fill_price 반영."""
    from execution.paper_broker import PaperBroker
    from execution.execution_engine import ExecutionEngine

    broker = PaperBroker(initial_balance=10000.0)
    eng = ExecutionEngine(broker, equity=10000.0, risk_pct=0.01)
    oid = await eng.execute_entry(
        symbol="BTCUSDT",
        side=Direction.LONG,
        entry=50000.0,
        stop_loss=49000.0,
        take_profit=52000.0,
    )
    assert oid is not None
    pos = await broker.get_open_position("BTCUSDT")
    assert pos is not None and pos.size > 0 and pos.symbol == "BTCUSDT"
    # set_fill_price is called inside execute_entry for PaperBroker, so entry/stop should be set
    assert pos.entry_price == 50000.0 and pos.stop_loss == 49000.0
    print("[OK] execute_entry → position with entry/SL set")
    return True


def verify_execute_entry():
    """Async execute_entry wrapper."""
    return asyncio.run(_verify_execute_entry())


def verify_paper_broker_interface():
    """PaperBroker: place_market_order, get_open_position, close_position."""
    async def _run():
        from execution.paper_broker import PaperBroker

        broker = PaperBroker(10000.0)
        oid = await broker.place_market_order("BTCUSDT", Direction.LONG, 0.1, reduce_only=False)
        assert oid is not None
        pos = await broker.get_open_position("BTCUSDT")
        assert pos is not None and pos.size == 0.1
        ok = await broker.close_position("BTCUSDT")
        assert ok
        pos2 = await broker.get_open_position("BTCUSDT")
        assert pos2 is None
        return True

    asyncio.run(_run())
    print("[OK] PaperBroker place_market_order, get_open_position, close_position")
    return True


def main():
    print("=== 10단계 Execution Engine 검증 ===\n")
    ok = True
    for name, fn in [
        ("position_size", verify_position_size),
        ("ExecutionEngine.position_size", verify_execution_engine_position_size),
        ("PaperBroker interface", verify_paper_broker_interface),
        ("execute_entry", verify_execute_entry),
    ]:
        try:
            fn()
        except Exception as e:
            print("[FAIL] %s: %s" % (name, e))
            ok = False
        print()
    if ok:
        print("10단계 검증 통과.")
    else:
        print("일부 검증 실패.")
        sys.exit(1)


if __name__ == "__main__":
    main()
