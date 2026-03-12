"""
Strategy candidate views on top of feature_store_1m + outcome_store_1m.

이 모듈은 특정 전략 아이디어(브레이크아웃, 풀백, mean reversion 등)를
SQL/필터 조합 형태로만 정의하고, 공통 store_loader를 사용해 후보 집합을 만든다.
"""
from __future__ import annotations

from typing import List

from sqlalchemy import and_, select

from analysis.store_loader import load_rows_from_store
from storage.database import SessionLocal, init_db
from storage.models import FeatureStore1mModel, OutcomeStore1mModel


def get_breakout_candidates(symbol: str, limit: int = 10000, feature_version: int = 1) -> List[dict]:
    """
    예시 브레이크아웃 전략 candidates:
      volume_zscore > 2
      close_near_high > 0.8
      ema50_slope_15m > 0
    """
    init_db()
    db = SessionLocal()
    try:
        conds = [
            FeatureStore1mModel.symbol == symbol,
            OutcomeStore1mModel.symbol == symbol,
            FeatureStore1mModel.timestamp == OutcomeStore1mModel.timestamp,
            FeatureStore1mModel.feature_version == feature_version,
            FeatureStore1mModel.volume_zscore > 2.0,
            FeatureStore1mModel.close_near_high > 0.8,
            FeatureStore1mModel.ema50_slope_15m > 0.0,
        ]
        stmt = (
            select(FeatureStore1mModel, OutcomeStore1mModel)
            .where(and_(*conds))
            .order_by(FeatureStore1mModel.timestamp.asc())
            .limit(limit)
        )
        rows: List[dict] = []
        for f_row, o_row in db.execute(stmt).all():
            r: dict = {}
            for col in f_row.__table__.columns:
                r[col.name] = getattr(f_row, col.name)
            for col in o_row.__table__.columns:
                name = col.name
                if name in r and name not in ("symbol", "timestamp"):
                    r[f"outcome_{name}"] = getattr(o_row, name)
                else:
                    r[name] = getattr(o_row, name)
            rows.append(r)
        return rows
    finally:
        db.close()


def get_pullback_candidates(symbol: str, limit: int = 10000, feature_version: int = 1) -> List[dict]:
    """
    예시 풀백 전략 candidates:
      ema20_gt_ema50 = 1
      pullback_depth_pct between -0.3 and 0
      volume_ratio > 1.2
    """
    extra_filters = [
        FeatureStore1mModel.ema20_gt_ema50 >= 0.5,
        FeatureStore1mModel.pullback_depth_pct <= 0.0,
        FeatureStore1mModel.pullback_depth_pct >= -0.3,
        FeatureStore1mModel.volume_ratio > 1.2,
    ]
    return load_rows_from_store(symbol=symbol, limit=limit, feature_version=feature_version, extra_filters=extra_filters)


def get_mean_reversion_candidates(symbol: str, limit: int = 10000, feature_version: int = 1) -> List[dict]:
    """
    예시 mean reversion candidates:
      rsi_5m < 25
      dist_from_ema50_pct < -2%
    """
    extra_filters = [
        FeatureStore1mModel.rsi_5m < 25.0,
        FeatureStore1mModel.dist_from_ema50_pct < -2.0,
    ]
    return load_rows_from_store(symbol=symbol, limit=limit, feature_version=feature_version, extra_filters=extra_filters)

