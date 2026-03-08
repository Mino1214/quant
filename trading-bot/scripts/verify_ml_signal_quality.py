#!/usr/bin/env python3
"""
8단계 ML Signal Quality 검증 스크립트.
- train_models: 최소 행으로 학습 후 모델·feature_cols 파일 생성 확인
- predict_signal: feature_dict로 win_probability, expected_R, signal_quality_score 반환 확인
- online_training: time_based_split, should_deploy 등 유틸 동작 확인 (run_online_training은 DB 필요 시 스킵)
실행: cd trading-bot && PYTHONPATH=. python scripts/verify_ml_signal_quality.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def make_fake_rows(n: int = 60):
    """train_models에 넣을 최소 컬럼 갖춘 더미 행."""
    import random
    rows = []
    for i in range(n):
        rows.append({
            "ema_distance": random.uniform(-0.02, 0.02),
            "volume_ratio": random.uniform(0.5, 2.0),
            "rsi": random.uniform(30, 70),
            "trend_direction": random.choice(["long", "short"]),
            "regime": random.choice(["RANGING", "TRENDING_UP", "TRENDING_DOWN"]),
            "momentum_ratio": random.uniform(0.8, 1.2),
            "R_return": random.uniform(-1.0, 1.0),
        })
    return rows


def verify_train_models():
    """소량 데이터로 학습 후 rf_clf, rf_reg, feature_cols.joblib 생성 확인."""
    from ml.train import train_models

    tmp = tempfile.mkdtemp(prefix="verify_ml_")
    rows = make_fake_rows(60)
    out = train_models(rows, model_dir=tmp, r_key="R_return", test_size=0.2)
    assert isinstance(out, dict)
    assert (Path(tmp) / "rf_clf.joblib").exists()
    assert (Path(tmp) / "rf_reg.joblib").exists()
    assert (Path(tmp) / "feature_cols.joblib").exists()
    assert (Path(tmp) / "meta.json").exists()
    print("[OK] train_models produced rf_clf, rf_reg, feature_cols.joblib, meta.json")
    return tmp


def verify_predict_signal(model_dir: str):
    """feature_dict로 예측 시 win_probability, expected_R, signal_quality_score 반환 확인."""
    from ml.predictor import predict_signal

    fd = {"ema_distance": 0.01, "volume_ratio": 1.0, "rsi": 50, "trend_direction": "long", "regime": "RANGING", "momentum_ratio": 1.0}
    result = predict_signal(fd, model_dir=model_dir)
    assert result is not None
    assert "win_probability" in result and "expected_R" in result and "signal_quality_score" in result
    assert 0 <= result["win_probability"] <= 1
    print("[OK] predict_signal returns win_probability, expected_R, signal_quality_score")
    return True


def verify_online_utils():
    """time_based_split, should_deploy 등 온라인 러닝 유틸만 검증 (DB 불필요)."""
    import pandas as pd
    from ml.online_training import time_based_split, should_deploy

    df = pd.DataFrame({
        "time": pd.date_range("2024-01-01", periods=100, freq="h"),
        "x": range(100),
    })
    train_df, test_df = time_based_split(df, test_ratio=0.2, time_col="time")
    assert len(train_df) == 80 and len(test_df) == 20
    print("[OK] time_based_split splits by time")

    assert should_deploy({"expected_R_corr": 0.3}, None) is True
    assert should_deploy({"expected_R_corr": 0.2}, {"expected_R_corr": 0.3}) is False
    assert should_deploy({"expected_R_corr": 0.4}, {"expected_R_corr": 0.3}) is True
    print("[OK] should_deploy policy works")
    return True


def main():
    print("=== 8단계 ML Signal Quality 검증 ===\n")
    ok = True
    model_dir = None
    try:
        model_dir = verify_train_models()
    except Exception as e:
        print("[FAIL] train_models:", e)
        ok = False
    print()

    if model_dir:
        try:
            verify_predict_signal(model_dir)
        except Exception as e:
            print("[FAIL] predict_signal:", e)
            ok = False
        try:
            import shutil
            shutil.rmtree(model_dir, ignore_errors=True)
        except Exception:
            pass
    print()

    try:
        verify_online_utils()
    except Exception as e:
        print("[FAIL] online_utils:", e)
        ok = False
    print()

    if ok:
        print("8단계 검증 통과.")
    else:
        print("일부 검증 실패.")
        sys.exit(1)


if __name__ == "__main__":
    main()
