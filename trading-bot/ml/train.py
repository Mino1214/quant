"""
Train ML models on signal dataset: RandomForest, XGBoost, LightGBM.
Features: ema_distance, volume_ratio, rsi, trend_direction, regime, momentum_ratio.
Targets: label_binary (win=1), R_return (continuous).
"""
import json
import logging
from pathlib import Path
from typing import List

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FEATURE_COLS = ["ema_distance", "volume_ratio", "rsi", "trend_direction_enc", "regime_enc", "momentum_ratio"]
TARGET_BINARY = "label_binary"
TARGET_R = "R_return"


def _get_feature_cols(df: pd.DataFrame) -> List[str]:
    """Use multi-TF + cross-market feature columns when present; otherwise legacy FEATURE_COLS."""
    result: List[str] = []
    try:
        from features.multi_tf_feature_builder import MULTI_TF_FEATURE_KEYS
        if all(c in df.columns for c in MULTI_TF_FEATURE_KEYS):
            result = list(MULTI_TF_FEATURE_KEYS)
    except Exception:
        pass
    try:
        from features.cross_market_feature_builder import CROSS_MARKET_FEATURE_KEYS
        if all(c in df.columns for c in CROSS_MARKET_FEATURE_KEYS):
            result = result + list(CROSS_MARKET_FEATURE_KEYS)
    except Exception:
        pass
    return result if result else FEATURE_COLS


def _prepare_df(rows: List[dict], r_key: str = "R_return") -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for c in ["ema_distance", "volume_ratio", "rsi", "momentum_ratio"]:
        if c not in df.columns:
            df[c] = 0.0
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    if "rsi_5m" in df.columns and "rsi" in df.columns and df["rsi"].eq(0).all():
        df["rsi"] = pd.to_numeric(df["rsi_5m"], errors="coerce").fillna(50)
    # Ensure multi-TF and cross-market columns exist when building from feature_values
    try:
        from features.multi_tf_feature_builder import MULTI_TF_FEATURE_KEYS
        for c in MULTI_TF_FEATURE_KEYS:
            if c not in df.columns:
                df[c] = 0.0
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    except Exception:
        pass
    try:
        from features.cross_market_feature_builder import CROSS_MARKET_FEATURE_KEYS
        for c in CROSS_MARKET_FEATURE_KEYS:
            if c not in df.columns:
                df[c] = 0.0
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    except Exception:
        pass
    if r_key not in df.columns and "future_r_30" in df.columns:
        df[r_key] = df["future_r_30"]
    df[TARGET_R] = pd.to_numeric(df.get(r_key, 0), errors="coerce").fillna(0)
    df[TARGET_BINARY] = (df[TARGET_R] > 0).astype(int)
    for col, enc_name in [("trend_direction", "trend_direction_enc"), ("regime", "regime_enc")]:
        raw = df.get(col, pd.Series(["unknown"] * len(df)))
        raw = raw.astype(str).str.lower() if hasattr(raw, "str") else raw.astype(str)
        le = LabelEncoder()
        df[enc_name] = le.fit_transform(raw.astype(str))
    if "momentum_ratio" not in df.columns:
        df["momentum_ratio"] = 0.0
    return df


def train_models(
    rows: List[dict],
    model_dir: str = "ml/models",
    r_key: str = "R_return",
    test_size: float = 0.2,
    random_state: int = 42,
) -> dict:
    df = _prepare_df(rows, r_key=r_key)
    if len(df) < 50:
        logger.warning("Too few rows for training: %d", len(df))
        return {}

    feature_cols = _get_feature_cols(df)
    X = df[feature_cols].copy()
    for c in feature_cols:
        if c not in X.columns:
            X[c] = 0
    X = X[feature_cols]
    y_bin = df[TARGET_BINARY]
    y_r = df[TARGET_R]

    if test_size > 0:
        X_train, X_test, yb_train, yb_test, yr_train, yr_test = train_test_split(
            X, y_bin, y_r, test_size=test_size, random_state=random_state
        )
    else:
        X_train, yb_train, yr_train = X, y_bin, y_r
        X_test, yb_test, yr_test = None, None, None

    out_dir = Path(model_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    clf = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=random_state)
    clf.fit(X_train, yb_train)
    reg = RandomForestRegressor(n_estimators=100, max_depth=10, random_state=random_state)
    reg.fit(X_train, yr_train)
    joblib.dump(clf, out_dir / "rf_clf.joblib")
    joblib.dump(reg, out_dir / "rf_reg.joblib")
    logger.info("Saved RandomForest to %s", out_dir)

    try:
        import xgboost as xgb
        clf_x = xgb.XGBClassifier(n_estimators=100, max_depth=6, random_state=random_state)
        clf_x.fit(X_train, yb_train)
        reg_x = xgb.XGBRegressor(n_estimators=100, max_depth=6, random_state=random_state)
        reg_x.fit(X_train, yr_train)
        joblib.dump(clf_x, out_dir / "xgb_clf.joblib")
        joblib.dump(reg_x, out_dir / "xgb_reg.joblib")
        logger.info("Saved XGBoost to %s", out_dir)
    except ImportError:
        pass

    try:
        import lightgbm as lgb
        clf_l = lgb.LGBMClassifier(n_estimators=100, max_depth=6, random_state=random_state, verbose=-1)
        clf_l.fit(X_train, yb_train)
        reg_l = lgb.LGBMRegressor(n_estimators=100, max_depth=6, random_state=random_state, verbose=-1)
        reg_l.fit(X_train, yr_train)
        joblib.dump(clf_l, out_dir / "lgb_clf.joblib")
        joblib.dump(reg_l, out_dir / "lgb_reg.joblib")
        logger.info("Saved LightGBM to %s", out_dir)
    except ImportError:
        pass

    joblib.dump(feature_cols, out_dir / "feature_cols.joblib")
    with open(out_dir / "meta.json", "w") as f:
        json.dump({"n_samples": len(df), "r_key": r_key}, f)

    if X_test is not None and len(X_test) > 0:
        from sklearn.metrics import accuracy_score, mean_squared_error
        proba = clf.predict_proba(X_test)[:, 1]
        pred_r = reg.predict(X_test)
        acc = accuracy_score(yb_test, (proba >= 0.5).astype(int))
        mse = mean_squared_error(yr_test, pred_r)
        return {"accuracy": acc, "mse_r": mse, "n_train": len(X_train), "n_test": len(X_test)}
    return {"n_train": len(X_train), "n_test": 0}
