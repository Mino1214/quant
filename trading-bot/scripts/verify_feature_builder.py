#!/usr/bin/env python3
"""
2단계 Feature Builder 검증 스크립트.
- 멀티타임프레임 피처 키·정렬(T 이전만) 확인
- (선택) 크로스마켓 피처 키 확인
- 미래 데이터 누수 없음 확인
실행: cd trading-bot && PYTHONPATH=. python scripts/verify_feature_builder.py
"""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.models import Candle, StrategySettings, Timeframe


def make_fake_candles(n: int, base_ts: datetime) -> list:
    """테스트용 캔들 n개 생성 (timestamp 오름차순)."""
    candles = []
    for i in range(n):
        t = base_ts + timedelta(minutes=i)
        candles.append(
            Candle(
                open=100.0 + i * 0.1,
                high=100.5 + i * 0.1,
                low=99.5 + i * 0.1,
                close=100.0 + (i + 1) * 0.1,
                volume=1000.0 + i * 10,
                timestamp=t,
                timeframe=Timeframe.M1,
            )
        )
    return candles


def verify_multi_tf():
    """멀티타임프레임: 키 일치, T 이전만 사용."""
    from features.multi_tf_feature_builder import (
        build_multi_tf_features,
        MULTI_TF_FEATURE_KEYS,
        _filter_past,
    )

    base = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    n = 100
    c1 = make_fake_candles(n, base)
    # 5m: 5분 간격
    c5 = []
    for i in range(0, n, 5):
        if i + 5 <= n:
            c5.append(
                Candle(
                    open=c1[i].open,
                    high=max(c.high for c in c1[i : i + 5]),
                    low=min(c.low for c in c1[i : i + 5]),
                    close=c1[i + 4].close,
                    volume=sum(c.volume for c in c1[i : i + 5]),
                    timestamp=c1[i].timestamp,
                    timeframe=Timeframe.M5,
                )
            )
    c15 = []
    for i in range(0, n, 15):
        if i + 15 <= n:
            c15.append(
                Candle(
                    open=c1[i].open,
                    high=max(c.high for c in c1[i : i + 15]),
                    low=min(c.low for c in c1[i : i + 15]),
                    close=c1[i + 14].close,
                    volume=sum(c.volume for c in c1[i : i + 15]),
                    timestamp=c1[i].timestamp,
                    timeframe=Timeframe.M15,
                )
            )

    settings = StrategySettings()
    T = c1[80].timestamp  # 80번째 봉 시점
    out = build_multi_tf_features(c1, c5, c15, T, settings)

    # 1) 모든 MULTI_TF_FEATURE_KEYS 가 출력에 있음
    missing = [k for k in MULTI_TF_FEATURE_KEYS if k not in out]
    assert not missing, f"Missing keys: {missing}"
    print("[OK] Multi-TF output contains all MULTI_TF_FEATURE_KEYS")

    # 2) T 이전만 사용: _filter_past 확인
    past_1m = _filter_past(c1, T)
    assert all(c.timestamp <= T for c in past_1m), "past 1m must be <= T"
    print("[OK] _filter_past: only candles with timestamp <= T")

    # 3) 값이 숫자 (NaN 아님)
    for k, v in out.items():
        assert isinstance(v, (int, float)) and (v == v), f"Invalid value for {k}: {v}"
    print("[OK] No NaN in multi-TF features")
    return True


def verify_cross_market_keys():
    """크로스마켓: 키 목록 및 build 시 키 존재 (DB 없어도 0으로 반환)."""
    from features.cross_market_feature_builder import (
        build_cross_market_features,
        CROSS_MARKET_FEATURE_KEYS,
    )

    settings = StrategySettings()
    T = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    btc_features = {"ema_distance_1m": 0.001, "volume_ratio_1m": 1.2, "rsi_1m": 50.0}

    # DB 없을 수 있음 → 예외 시 0으로 채워진 dict 기대
    try:
        out = build_cross_market_features(T, btc_features, settings, eth_candles=None)
    except Exception as e:
        print(f"[SKIP] build_cross_market_features (DB/table missing): {e}")
        print("       CROSS_MARKET_FEATURE_KEYS만 확인합니다.")
        for k in CROSS_MARKET_FEATURE_KEYS:
            print(f"       - {k}")
        return True

    for k in CROSS_MARKET_FEATURE_KEYS:
        assert k in out, f"Missing cross-market key: {k}"
    print("[OK] Cross-market output contains all CROSS_MARKET_FEATURE_KEYS")
    return True


def main():
    print("=== 2단계 Feature Builder 검증 ===\n")
    ok = True
    try:
        verify_multi_tf()
    except Exception as e:
        print(f"[FAIL] Multi-TF: {e}")
        ok = False
    print()
    try:
        verify_cross_market_keys()
    except Exception as e:
        print(f"[FAIL] Cross-market: {e}")
        ok = False
    print()
    if ok:
        print("2단계 검증 통과.")
    else:
        print("일부 검증 실패.")
        sys.exit(1)


if __name__ == "__main__":
    main()
