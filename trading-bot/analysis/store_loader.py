"""
Shared loader helpers for research: load rows from feature_store_1m + outcome_store_1m.

이 모듈은 기존 candidate_signals 기반 로더(load_candidates_db)를 대체/보완해서
전략 독립형 feature/outcome 스토어에서 바로 연구용 row를 가져오도록 한다.
"""
from __future__ import annotations

from typing import Iterable, List, Optional

from sqlalchemy import and_, select

from storage.database import SessionLocal, init_db
from storage.models import FeatureStore1mModel, OutcomeStore1mModel


def load_rows_from_store(
    symbol: str,
    limit: int = 10000,
    feature_version: int = 1,
    extra_filters: Optional[Iterable] = None,
) -> List[dict]:
    """
    feature_store_1m JOIN outcome_store_1m에서 연구용 row 로드.

    반환 dict에는 feature + outcome 컬럼이 모두 포함된다.
    """
    init_db()
    db = SessionLocal()
    try:
        conds = [
            FeatureStore1mModel.symbol == symbol,
            OutcomeStore1mModel.symbol == symbol,
            FeatureStore1mModel.timestamp == OutcomeStore1mModel.timestamp,
            FeatureStore1mModel.feature_version == feature_version,
        ]
        if extra_filters:
            conds.extend(list(extra_filters))
        stmt = (
            select(FeatureStore1mModel, OutcomeStore1mModel)
            .where(and_(*conds))
            .order_by(FeatureStore1mModel.timestamp.asc())
            .limit(limit)
        )
        rows: List[dict] = []
        for f_row, o_row in db.execute(stmt).all():
            r: dict = {}
            # Flatten FeatureStore columns
            for col in f_row.__table__.columns:
                name = col.name
                r[name] = getattr(f_row, name)
            # Flatten OutcomeStore columns (override on conflict with explicit suffix if needed)
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

