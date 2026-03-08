"""
Load trained models and predict win_probability, expected_R, signal_quality_score for a single signal.
"""
from pathlib import Path
from typing import Dict, Optional

import joblib
import numpy as np


FEATURE_COLS = ["ema_distance", "volume_ratio", "rsi", "trend_direction_enc", "regime_enc", "momentum_ratio"]
TREND_MAP = {"long": 0, "short": 1, "LONG": 0, "SHORT": 1}
REGIME_ORDER = ["UNKNOWN", "RANGING", "TRENDING_UP", "TRENDING_DOWN", "CHAOTIC"]


def _encode_trend(s: str) -> int:
    return TREND_MAP.get((s or "").lower(), 0)


def _encode_regime(s: str) -> int:
    s = (s or "UNKNOWN").upper()
    for i, r in enumerate(REGIME_ORDER):
        if r in s or s in r:
            return i
    return 0


def build_feature_vector(
    ema_distance: float,
    volume_ratio: float,
    rsi: float,
    trend_direction: str,
    regime: str,
    momentum_ratio: float = 0.0,
) -> np.ndarray:
    """Build 1D feature array in same order as training."""
    return np.array([[
        float(ema_distance),
        float(volume_ratio),
        float(rsi),
        _encode_trend(trend_direction),
        _encode_regime(regime),
        float(momentum_ratio),
    ]])


class SignalPredictor:
    """Load RF (or first available) classifier + regressor and expose predict."""

    def __init__(self, model_dir: str = "ml/models"):
        self.model_dir = Path(model_dir)
        self._clf = None
        self._reg = None
        self._feature_cols = None
        self._load()

    def _load(self) -> None:
        for name in ["rf", "xgb", "lgb"]:
            clf_path = self.model_dir / f"{name}_clf.joblib"
            reg_path = self.model_dir / f"{name}_reg.joblib"
            if clf_path.exists() and reg_path.exists():
                self._clf = joblib.load(clf_path)
                self._reg = joblib.load(reg_path)
                break
        if self._clf is None or self._reg is None:
            raise FileNotFoundError(f"No model found in {self.model_dir}")
        fc_path = self.model_dir / "feature_cols.joblib"
        if fc_path.exists():
            self._feature_cols = joblib.load(fc_path)

    def _build_X(self, feature_dict: Dict[str, float]) -> np.ndarray:
        """Build feature vector from dict; use saved feature_cols order (multi-TF + cross-market)."""
        if self._feature_cols and isinstance(self._feature_cols, list) and len(self._feature_cols) > 0 and feature_dict:
            vals = [float(feature_dict.get(k, 0) or 0) for k in self._feature_cols]
            return np.array([vals])
        return build_feature_vector(
            feature_dict.get("ema_distance", 0) or 0,
            feature_dict.get("volume_ratio", 0) or 0,
            feature_dict.get("rsi") or feature_dict.get("rsi_5m") or 50,
            str(feature_dict.get("trend_direction", "long")),
            str(feature_dict.get("regime", "UNKNOWN")),
            feature_dict.get("momentum_ratio", 0) or 0,
        )

    def predict(
        self,
        ema_distance: float = 0,
        volume_ratio: float = 0,
        rsi: float = 50,
        trend_direction: str = "long",
        regime: str = "UNKNOWN",
        momentum_ratio: float = 0,
        feature_dict: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """
        Return win_probability, expected_R, signal_quality_score.
        When feature_dict is provided and model uses multi-TF features, X is built from feature_dict.
        """
        if feature_dict is not None and self._feature_cols:
            X = self._build_X(feature_dict)
        else:
            X = build_feature_vector(
                ema_distance, volume_ratio, rsi, trend_direction, regime, momentum_ratio
            )
        win_prob = float(self._clf.predict_proba(X)[0, 1])
        expected_R = float(self._reg.predict(X)[0])
        signal_quality_score = win_prob * max(0, expected_R) + (1 - win_prob) * min(0, expected_R)
        return {
            "win_probability": win_prob,
            "expected_R": expected_R,
            "signal_quality_score": signal_quality_score,
        }


def predict_signal(
    feature_dict: Dict[str, float],
    model_dir: str = "ml/models",
) -> Optional[Dict[str, float]]:
    """
    Predict from a dict. Supports legacy keys (ema_distance, volume_ratio, rsi_5m, ...)
    and multi-TF keys (ema_distance_1m, volume_ratio_1m, adx_5m, ...). Uses saved feature_cols when present.
    """
    try:
        pred = SignalPredictor(model_dir=model_dir)
        if pred._feature_cols and feature_dict:
            return pred.predict(feature_dict=feature_dict)
        return pred.predict(
            ema_distance=feature_dict.get("ema_distance", 0) or 0,
            volume_ratio=feature_dict.get("volume_ratio", 0) or 0,
            rsi=feature_dict.get("rsi") or feature_dict.get("rsi_5m") or 50,
            trend_direction=str(feature_dict.get("trend_direction", "long")),
            regime=str(feature_dict.get("regime", "UNKNOWN")),
            momentum_ratio=feature_dict.get("momentum_ratio", 0) or 0,
        )
    except Exception:
        return None
