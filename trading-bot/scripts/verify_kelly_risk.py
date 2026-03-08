#!/usr/bin/env python3
"""
9단계 Kelly + Risk Engine 검증 스크립트.
- Kelly: raw_kelly_fraction, kelly_risk_pct, compute_kelly_risk
- Capital allocator: score_to_risk_pct, apply_regime_multiplier, get_position_size, get_total_open_risk_pct
실행: cd trading-bot && PYTHONPATH=. python scripts/verify_kelly_risk.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import CapitalAllocationSettings, Direction, KellySettings, Position


def verify_raw_kelly():
    """raw_kelly_fraction: p - q/b, invalid 입력 시 None."""
    from execution.kelly_allocator import raw_kelly_fraction

    # avg_loss_R >= 0 → None
    assert raw_kelly_fraction(0.6, 1.2, 0.0) is None
    # b = 1.2/1 = 1.2, raw = 0.6 - 0.4/1.2 = 0.6 - 0.333... ≈ 0.267
    r = raw_kelly_fraction(0.6, 1.2, -1.0)
    assert r is not None and 0.2 < r < 0.35
    print("[OK] raw_kelly_fraction returns None for invalid, valid fraction for p=0.6, b=1.2")
    return True


def verify_kelly_risk_pct():
    """kelly_risk_pct: fractional + caps."""
    from execution.kelly_allocator import kelly_risk_pct

    # raw ≈ 0.267, safe = 0.267*0.25 ≈ 0.067, safe_pct ≈ 6.7 → cap to 1.0
    pct = kelly_risk_pct(0.6, 1.2, -1.0, fractional=0.25, min_risk_pct=0.25, max_risk_pct=1.0)
    assert 0.25 <= pct <= 1.0
    # raw None → 0
    assert kelly_risk_pct(0.4, 1.2, -1.0) == 0.0  # raw negative
    print("[OK] kelly_risk_pct applies fractional and caps")
    return True


def verify_compute_kelly_risk():
    """compute_kelly_risk returns dict with kelly_fraction, final_risk_pct, skip."""
    from execution.kelly_allocator import compute_kelly_risk

    settings = KellySettings(enabled=True, fractional_kelly=0.25, min_risk_per_trade_pct=0.25, max_risk_per_trade_pct=1.0)
    out = compute_kelly_risk(0.6, 1.2, -1.0, settings)
    assert "kelly_fraction" in out and "final_risk_pct" in out and "skip" in out
    assert out["skip"] is False
    assert 0.25 <= out["final_risk_pct"] <= 1.0
    skip_out = compute_kelly_risk(0.3, 1.2, -1.0, settings)  # low p → raw negative
    assert skip_out["skip"] is True and skip_out["final_risk_pct"] == 0.0
    print("[OK] compute_kelly_risk returns expected dict; skip when raw <= 0")
    return True


def verify_score_to_risk_pct():
    """score_to_risk_pct: tiers 0.75→3%, 0.65→2%, 0.55→1%, else 0."""
    from execution.capital_allocator import score_to_risk_pct

    settings = CapitalAllocationSettings(tiers=[(0.75, 3.0), (0.65, 2.0), (0.55, 1.0)])
    assert score_to_risk_pct(0.8, settings) == 3.0
    assert score_to_risk_pct(0.7, settings) == 2.0
    assert score_to_risk_pct(0.6, settings) == 1.0
    assert score_to_risk_pct(0.5, settings) == 0.0
    print("[OK] score_to_risk_pct maps quality tiers correctly")
    return True


def verify_apply_regime_multiplier():
    """apply_regime_multiplier and cap."""
    from execution.capital_allocator import apply_regime_multiplier

    settings = CapitalAllocationSettings(regime_multipliers={"TRENDING_UP": 1.2, "CHAOTIC": 0.5})
    assert apply_regime_multiplier(2.0, "TRENDING_UP", settings) == 2.4
    assert apply_regime_multiplier(2.0, "CHAOTIC", settings) == 1.0
    assert apply_regime_multiplier(0.0, "TRENDING_UP", settings) == 0.0
    print("[OK] apply_regime_multiplier applies multiplier")
    return True


def verify_get_position_size():
    """get_position_size: override_risk_pct (Kelly), portfolio cap."""
    from execution.capital_allocator import get_position_size

    settings = CapitalAllocationSettings(max_portfolio_risk_pct=6.0, tiers=[(0.75, 3.0), (0.65, 2.0), (0.55, 1.0)])
    balance, entry, stop = 10000.0, 50000.0, 49000.0
    # Kelly override
    qty, risk = get_position_size(
        balance, entry, stop, Direction.LONG, score=0.5, regime="RANGE",
        settings=settings, current_open_risk_pct=0.0, override_risk_pct=0.5,
    )
    assert risk == 0.5 and qty > 0
    # Portfolio cap: current 5.5% + 1% would exceed 6%
    qty_cap, _ = get_position_size(
        balance, entry, stop, Direction.LONG, score=0.8, regime="RANGE",
        settings=settings, current_open_risk_pct=5.5, override_risk_pct=None,
    )
    assert qty_cap == 0.0
    print("[OK] get_position_size uses override_risk_pct; respects max_portfolio_risk_pct")
    return True


def verify_get_total_open_risk_pct():
    """get_total_open_risk_pct: sum (size * |entry - stop|) / balance * 100."""
    from execution.capital_allocator import get_total_open_risk_pct

    # size=0.1, entry=50000, stop=49000 → risk_amount = 100, balance=10000 → 1%
    pos = Position(symbol="BTCUSDT", side=Direction.LONG, size=0.1, entry_price=50000.0, stop_loss=49000.0)
    pct = get_total_open_risk_pct([pos], 10000.0)
    assert abs(pct - 1.0) < 0.01  # 100/10000 * 100 = 1%
    assert get_total_open_risk_pct([], 10000.0) == 0.0
    print("[OK] get_total_open_risk_pct computes portfolio risk %")
    return True


def main():
    print("=== 9단계 Kelly + Risk Engine 검증 ===\n")
    ok = True
    for name, fn in [
        ("raw_kelly", verify_raw_kelly),
        ("kelly_risk_pct", verify_kelly_risk_pct),
        ("compute_kelly_risk", verify_compute_kelly_risk),
        ("score_to_risk_pct", verify_score_to_risk_pct),
        ("apply_regime_multiplier", verify_apply_regime_multiplier),
        ("get_position_size", verify_get_position_size),
        ("get_total_open_risk_pct", verify_get_total_open_risk_pct),
    ]:
        try:
            fn()
        except Exception as e:
            print("[FAIL] %s: %s" % (name, e))
            ok = False
        print()
    if ok:
        print("9단계 검증 통과.")
    else:
        print("일부 검증 실패.")
        sys.exit(1)


if __name__ == "__main__":
    main()
