"""
Online learning pipeline: load dataset from DB, time-based split, train, evaluate, version, deploy.
"""
import logging
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_MIN_SIGNALS = 50_000
DEFAULT_MAX_ROWS = 500_000
DEFAULT_TEST_RATIO = 0.2


def load_training_dataset(
    symbol: Optional[str] = None,
    min_signals: int = DEFAULT_MIN_SIGNALS,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> Optional[pd.DataFrame]:
    """
    Load candidate_signals + signal_outcomes (with feature_values_ext) from DB.
    Returns DataFrame or None if fewer than min_signals rows.
    """
    from storage.database import SessionLocal, init_db
    from storage.repositories import get_candidate_signals_with_outcomes

    init_db()
    db = SessionLocal()
    try:
        rows = get_candidate_signals_with_outcomes(db, symbol=symbol, limit=max_rows)
        if len(rows) < min_signals:
            logger.info("Online training skip: %d rows < min_signals=%d", len(rows), min_signals)
            return None
        return pd.DataFrame(rows)
    finally:
        db.close()


def time_based_split(
    df: pd.DataFrame,
    test_ratio: float = DEFAULT_TEST_RATIO,
    time_col: str = "time",
) -> tuple:
    """
    Split by time: sort by time_col, last test_ratio is test, rest is train.
    Returns (train_df, test_df).
    """
    if df.empty or time_col not in df.columns:
        return df, pd.DataFrame()
    sorted_df = df.sort_values(time_col).reset_index(drop=True)
    n = len(sorted_df)
    split_idx = int(n * (1 - test_ratio))
    if split_idx >= n or split_idx <= 0:
        return sorted_df, pd.DataFrame()
    return sorted_df.iloc[:split_idx], sorted_df.iloc[split_idx:]


def train_and_evaluate(
    df: pd.DataFrame,
    model_dir: str,
    r_key: str = "R_return",
    test_ratio: float = DEFAULT_TEST_RATIO,
) -> Dict:
    """
    Time-based split, train on train set (test_size=0), evaluate on test set.
    Returns metrics: accuracy, auc, expected_R_corr, train_start_time, train_end_time.
    """
    from ml.train import _prepare_df, train_models, TARGET_BINARY, TARGET_R
    from ml.predictor import SignalPredictor
    import numpy as np

    time_col = "time"
    if time_col not in df.columns:
        logger.warning("No 'time' column for time_based_split")
        return {}

    train_df, test_df = time_based_split(df, test_ratio=test_ratio, time_col=time_col)
    if train_df.empty or test_df.empty:
        logger.warning("Empty train or test set after time split")
        return {}

    train_rows = train_df.to_dict("records")
    train_metrics = train_models(
        train_rows,
        model_dir=model_dir,
        r_key=r_key,
        test_size=0.0,
    )
    if not train_metrics:
        return {}

    # Prepare test set same way as training pipeline
    prepared = _prepare_df(test_df.to_dict("records"), r_key=r_key)
    if prepared.empty or TARGET_R not in prepared.columns:
        return {**train_metrics, "train_start_time": train_df[time_col].min(), "train_end_time": train_df[time_col].max()}

    # Get feature columns used by the just-trained model
    try:
        import joblib
        fc_path = Path(model_dir) / "feature_cols.joblib"
        feature_cols = joblib.load(fc_path) if fc_path.exists() else []
    except Exception:
        feature_cols = []

    if not feature_cols:
        return {**train_metrics, "train_start_time": train_df[time_col].min(), "train_end_time": train_df[time_col].max()}

    X_test = prepared[feature_cols].copy() if all(c in prepared.columns for c in feature_cols) else None
    if X_test is None or len(X_test) == 0:
        for c in feature_cols:
            if c not in prepared.columns:
                prepared[c] = 0.0
        X_test = prepared[feature_cols].fillna(0)

    y_bin = prepared[TARGET_BINARY]
    y_r = prepared[TARGET_R]

    pred = SignalPredictor(model_dir=model_dir)
    proba = pred._clf.predict_proba(X_test)[:, 1]
    pred_r = pred._reg.predict(X_test)

    from sklearn.metrics import accuracy_score, roc_auc_score
    acc = accuracy_score(y_bin, (proba >= 0.5).astype(int))
    try:
        auc = roc_auc_score(y_bin, proba)
    except Exception:
        auc = 0.0
    try:
        expected_R_corr = float(np.corrcoef(pred_r, y_r)[0, 1]) if len(y_r) > 1 else 0.0
    except Exception:
        expected_R_corr = 0.0

    return {
        "accuracy": acc,
        "auc": auc,
        "expected_R_corr": expected_R_corr,
        "train_start_time": train_df[time_col].min(),
        "train_end_time": train_df[time_col].max(),
        "n_train": len(train_df),
        "n_test": len(test_df),
    }


def should_deploy(
    new_metrics: Dict,
    current_metrics: Optional[Dict],
    policy: str = "expected_R_corr",
) -> bool:
    """
    Decide whether to deploy the new model. policy: 'expected_R_corr' (prefer higher corr)
    or 'accuracy' or 'composite' (e.g. weighted).
    """
    if not current_metrics:
        return True
    if policy == "expected_R_corr":
        return (new_metrics.get("expected_R_corr") or 0) > (current_metrics.get("expected_R_corr") or 0)
    if policy == "accuracy":
        return (new_metrics.get("accuracy") or 0) > (current_metrics.get("accuracy") or 0)
    if policy == "composite":
        nc = (new_metrics.get("expected_R_corr") or 0) * 0.6 + (new_metrics.get("accuracy") or 0) * 0.4
        oc = (current_metrics.get("expected_R_corr") or 0) * 0.6 + (current_metrics.get("accuracy") or 0) * 0.4
        return nc > oc
    return False


def save_model_version(
    metrics: Dict,
    model_dir: str,
    version_id: str,
    db_session=None,
) -> None:
    """
    Copy current model_dir to model_dir/versions/<version_id>/ and insert row into ml_models.
    """
    from storage.models import MLModelVersionModel

    out_dir = Path(model_dir)
    version_dir = out_dir / "versions" / version_id
    version_dir.mkdir(parents=True, exist_ok=True)

    for f in ["rf_clf.joblib", "rf_reg.joblib", "feature_cols.joblib", "meta.json"]:
        src = out_dir / f
        if src.exists():
            shutil.copy2(src, version_dir / f)
    for f in ["xgb_clf.joblib", "xgb_reg.joblib", "lgb_clf.joblib", "lgb_reg.joblib"]:
        src = out_dir / f
        if src.exists():
            shutil.copy2(src, version_dir / f)

    if db_session is not None:
        row = MLModelVersionModel(
            version_id=version_id,
            train_start_time=metrics.get("train_start_time"),
            train_end_time=metrics.get("train_end_time"),
            accuracy=metrics.get("accuracy"),
            auc=metrics.get("auc"),
            expected_R_corr=metrics.get("expected_R_corr"),
            model_path=str(version_dir),
            created_at=datetime.utcnow(),
        )
        db_session.add(row)
        db_session.commit()


def get_current_deployed_metrics(model_dir: str, db_session) -> Optional[Dict]:
    """Load metrics of the previously deployed model (second-most-recent row to compare with newly trained)."""
    from storage.models import MLModelVersionModel

    row = (
        db_session.query(MLModelVersionModel)
        .order_by(MLModelVersionModel.created_at.desc())
        .offset(1)
        .first()
    )
    if row is None:
        row = db_session.query(MLModelVersionModel).order_by(MLModelVersionModel.created_at.desc()).first()
    if row is None:
        return None
    return {
        "accuracy": row.accuracy,
        "auc": row.auc,
        "expected_R_corr": row.expected_R_corr,
        "train_start_time": row.train_start_time,
        "train_end_time": row.train_end_time,
    }


def run_online_training(
    symbol: Optional[str] = None,
    model_dir: str = "ml/models",
    min_signals: int = DEFAULT_MIN_SIGNALS,
    max_rows: int = DEFAULT_MAX_ROWS,
    deploy_if_better: bool = True,
    deploy_policy: str = "expected_R_corr",
    test_ratio: float = DEFAULT_TEST_RATIO,
    r_key: str = "R_return",
) -> Dict:
    """
    Load dataset -> train_and_evaluate -> save_model_version -> optionally deploy.
    Deploy: if should_deploy(new, current), copy trained artifacts to model_dir (already there)
    or set model_dir/current -> versions/<version_id>. Logging: 학습 여부, 메트릭, 배포 여부.
    """
    from storage.database import SessionLocal, init_db

    init_db()
    df = load_training_dataset(symbol=symbol, min_signals=min_signals, max_rows=max_rows)
    if df is None:
        return {"trained": False, "reason": "insufficient_data"}

    metrics = train_and_evaluate(df, model_dir=model_dir, r_key=r_key, test_ratio=test_ratio)
    if not metrics:
        return {"trained": False, "reason": "train_and_evaluate_failed"}

    version_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    db = SessionLocal()
    try:
        save_model_version(metrics, model_dir, version_id, db_session=db)
        current = get_current_deployed_metrics(model_dir, db)
        deploy = deploy_if_better and should_deploy(metrics, current, policy=deploy_policy)
        if deploy:
            # Model was already trained into model_dir; we only versioned it. "Deploy" = current is this version.
            # So we just log. Optionally: symlink model_dir/current -> versions/version_id.
            current_dir = Path(model_dir) / "current"
            version_dir = Path(model_dir) / "versions" / version_id
            if version_dir.exists():
                try:
                    if current_dir.exists():
                        current_dir.unlink()
                    current_dir.symlink_to(version_dir)
                except OSError:
                    pass
            logger.info("Online ML: deployed version %s (accuracy=%.3f auc=%.3f expected_R_corr=%.3f)",
                        version_id, metrics.get("accuracy", 0), metrics.get("auc", 0), metrics.get("expected_R_corr", 0))
        else:
            logger.info("Online ML: trained version %s (not deployed). accuracy=%.3f expected_R_corr=%.3f",
                        version_id, metrics.get("accuracy", 0), metrics.get("expected_R_corr", 0))
        return {
            "trained": True,
            "version_id": version_id,
            "metrics": metrics,
            "deployed": deploy,
        }
    finally:
        db.close()
