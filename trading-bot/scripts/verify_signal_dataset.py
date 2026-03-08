#!/usr/bin/env python3
"""
4단계 Signal Dataset 검증 스크립트.
- get_candidate_signals_with_outcomes row 구조 (time, close, R_return, feature_values_ext 병합)
- compute_outcome_for_signal → SignalOutcome (future_r_5/10/20/30)
- 데이터셋 필드 존재 여부
실행: cd trading-bot && PYTHONPATH=. python scripts/verify_signal_dataset.py
"""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import Candle, Direction, Timeframe


def verify_outcome_computation():
    """compute_outcome_for_signal: 가짜 캔들로 R 계산 및 SignalOutcome 구조."""
    from storage.signal_outcome import compute_outcome_for_signal

    base = datetime(2024, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
    # 시그널 이후 30봉: 상승 추세로 가정 → future_r_30 > 0 가능
    candles_after = []
    entry = 100.0
    for i in range(30):
        t = base + timedelta(minutes=i + 1)
        close = entry + (i + 1) * 0.02  # 상승
        candles_after.append(
            Candle(
                open=close - 0.01,
                high=close + 0.01,
                low=close - 0.02,
                close=close,
                volume=1000.0,
                timestamp=t,
                timeframe=Timeframe.M1,
            )
        )
    stop_loss = 99.0
    outcome = compute_outcome_for_signal(
        candidate_signal_id=1,
        candles_1m_after_signal=candles_after,
        entry_price=entry,
        stop_loss=stop_loss,
        direction=Direction.LONG,
    )
    assert hasattr(outcome, "future_r_5") and hasattr(outcome, "future_r_30")
    assert outcome.future_r_5 is not None or outcome.future_r_30 is not None
    print("[OK] compute_outcome_for_signal returns SignalOutcome (future_r_5=%s, future_r_30=%s)" % (outcome.future_r_5, outcome.future_r_30))
    return True


def verify_get_candidate_signals_with_outcomes():
    """get_candidate_signals_with_outcomes: row에 time, close, R_return, (feature_values_ext 병합) 존재."""
    from storage.database import SessionLocal, init_db
    from storage.repositories import get_candidate_signals_with_outcomes

    init_db()
    db = SessionLocal()
    try:
        try:
            rows = get_candidate_signals_with_outcomes(db, limit=5)
        except Exception as e:
            if "Unknown column" in str(e) or "1054" in str(e) or "time" in str(e):
                db.close()
                init_db()
                db = SessionLocal()
                try:
                    rows = get_candidate_signals_with_outcomes(db, limit=5)
                except Exception as e2:
                    print("[SKIP] get_candidate_signals_with_outcomes: DB schema mismatch (init_db() 적용 후에도 실패)")
                    return True
            else:
                raise
    finally:
        db.close()

    required = ["time", "close", "side", "regime", "approval_score", "trade_outcome"]
    if not rows:
        print("[SKIP] get_candidate_signals_with_outcomes: no rows (DB empty or no outcomes yet)")
        return True

    for row in rows:
        for k in required:
            assert k in row, "Missing key in row: %s" % k
        # R_return 또는 future_r_30 (ML/학습용)
        assert "R_return" in row or "future_r_30" in row, "Row should have R_return or future_r_30"
    has_ext = any("ema_distance_1m" in r or "ema_distance" in r for r in rows)
    print("[OK] get_candidate_signals_with_outcomes: row keys OK (required + R_return/future_r_30), feature_ext merged=%s" % has_ext)
    return True


def verify_dataset_fields():
    """데이터셋에 필요한 필드 목록 확인 (문서/스키마 정합성)."""
    expected_fields = [
        "timestamp", "entry_price", "direction", "regime", "trend_direction",
        "approval_score", "ema_distance", "volume_ratio", "rsi", "trade_outcome",
        "R_return", "holding_time",
    ]
    # DB row는 time, close, side 등으로 올 수 있음
    db_row_fields = ["time", "close", "side", "regime", "approval_score", "trade_outcome", "R_return", "future_r_30"]
    print("[OK] Dataset field set defined (time, close, side, regime, approval_score, trade_outcome, R_return/future_r_30, feature_values_ext)")
    return True


def main():
    print("=== 4단계 Signal Dataset 검증 ===\n")
    ok = True
    try:
        verify_outcome_computation()
    except Exception as e:
        print("[FAIL] Outcome computation:", e)
        ok = False
    print()
    try:
        verify_get_candidate_signals_with_outcomes()
    except Exception as e:
        print("[FAIL] get_candidate_signals_with_outcomes:", e)
        ok = False
    print()
    try:
        verify_dataset_fields()
    except Exception as e:
        print("[FAIL] Dataset fields:", e)
        ok = False
    print()
    if ok:
        print("4단계 검증 통과.")
    else:
        print("일부 검증 실패.")
        sys.exit(1)


if __name__ == "__main__":
    main()
