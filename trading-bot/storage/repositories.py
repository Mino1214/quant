"""
Trade record repository: insert and query.
"""
import json
from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.models import BlockedCandidateLog, CandidateSignalRecord, SignalOutcome, TradeRecord
from storage.models import (
    BlockedCandidateModel,
    CandidateSignalModel,
    ParameterScanResultModel,
    SignalOutcomeModel,
    TradeRecordModel,
)


def to_domain(m: TradeRecordModel) -> TradeRecord:
    from core.models import Direction

    return TradeRecord(
        symbol=m.symbol,
        side=Direction(m.side),
        size=m.size,
        entry_price=m.entry_price,
        exit_price=m.exit_price,
        stop_loss=m.stop_loss,
        take_profit=m.take_profit,
        pnl=m.pnl,
        rr=m.rr,
        reason_entry=m.reason_entry or "",
        reason_exit=m.reason_exit or "",
        opened_at=m.opened_at,
        closed_at=m.closed_at,
        approval_score=getattr(m, "approval_score", None) or 0,
        blocked_reason=getattr(m, "blocked_reason", None),
        mode=getattr(m, "mode", None) or "paper",
    )


def create_trade(db: Session, trade: TradeRecord) -> TradeRecordModel:
    row = TradeRecordModel(
        symbol=trade.symbol,
        side=trade.side.value,
        size=trade.size,
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        stop_loss=trade.stop_loss,
        take_profit=trade.take_profit,
        pnl=trade.pnl,
        rr=trade.rr,
        reason_entry=trade.reason_entry,
        reason_exit=trade.reason_exit,
        opened_at=trade.opened_at,
        closed_at=trade.closed_at,
        approval_score=getattr(trade, "approval_score", 0),
        blocked_reason=getattr(trade, "blocked_reason", None),
        mode=getattr(trade, "mode", "paper"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_recent_trades(db: Session, limit: int = 50) -> List[TradeRecord]:
    rows = (
        db.query(TradeRecordModel)
        .order_by(TradeRecordModel.closed_at.desc())
        .limit(limit)
        .all()
    )
    return [to_domain(r) for r in rows]


def get_pnl_today(db: Session, today: date | None = None) -> float:
    if today is None:
        today = date.today()
    start = datetime.combine(today, datetime.min.time())
    end = datetime.combine(today, datetime.max.time())
    from sqlalchemy import func

    result = (
        db.query(func.sum(TradeRecordModel.pnl))
        .filter(
            TradeRecordModel.closed_at >= start,
            TradeRecordModel.closed_at <= end,
        )
        .scalar()
    )
    return float(result or 0.0)


def create_blocked_candidate(db: Session, log: BlockedCandidateLog) -> BlockedCandidateModel:
    row = BlockedCandidateModel(
        symbol=log.symbol,
        side=log.direction.value,
        timestamp=log.timestamp,
        total_score=log.total_score,
        blocked_reason=log.blocked_reason,
        category_scores=json.dumps(log.category_scores) if log.category_scores else None,
        reason_entry=log.reason_entry or None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def create_candidate_signal(db: Session, record: CandidateSignalRecord) -> CandidateSignalModel:
    side = record.trend_direction.value if hasattr(record.trend_direction, "value") else str(record.trend_direction)
    feature_ext_json = None
    if getattr(record, "feature_values", None):
        try:
            feature_ext_json = json.dumps(record.feature_values)
        except (TypeError, ValueError):
            pass
    # time + timestamp(legacy) 동일 값. MySQL DATETIME은 timezone-naive 권장
    ts = record.timestamp
    if ts is not None and hasattr(ts, "replace"):
        ts = ts.replace(tzinfo=None) if getattr(ts, "tzinfo", None) else ts
    row = CandidateSignalModel(
        symbol=record.symbol or "",
        time=ts,
        timestamp=ts,
        close=record.entry_price,
        side=side,
        regime=record.regime,
        trend_direction=side,
        approval_score=record.approval_score,
        ema_distance=record.feature_values.get("ema_distance"),
        volume_ratio=record.feature_values.get("volume_ratio"),
        rsi=record.feature_values.get("rsi_5m"),
        trade_outcome=record.trade_outcome,
        blocked_reason=record.blocked_reason,
        created_at=datetime.utcnow(),
        feature_values_ext=feature_ext_json,
    )
    db.add(row)
    db.flush()
    # MySQL 예약어 `timestamp` 컬럼: INSERT 후 동일 행에 time → timestamp 복사 (비어 있으면 확실히 채움)
    if ts is not None:
        try:
            db.execute(text("UPDATE candidate_signals SET `timestamp` = :ts WHERE id = :id"), {"ts": ts, "id": row.id})
        except Exception:
            pass
    db.commit()
    db.refresh(row)
    return row


def create_signal_outcome(db: Session, outcome: SignalOutcome) -> SignalOutcomeModel:
    row = SignalOutcomeModel(
        signal_id=outcome.candidate_signal_id,  # legacy: signal_id NOT NULL FK 있는 기존 DB 호환
        candidate_signal_id=outcome.candidate_signal_id,
        future_r_5=outcome.future_r_5,
        future_r_10=outcome.future_r_10,
        future_r_20=outcome.future_r_20,
        future_r_30=outcome.future_r_30,
        tp_hit_first=outcome.tp_hit_first,
        sl_hit_first=outcome.sl_hit_first,
        bars_to_outcome=outcome.bars_to_outcome,
        computed_at=outcome.computed_at or datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def create_parameter_scan_result(db: Session, row: dict) -> ParameterScanResultModel:
    from datetime import datetime
    m = ParameterScanResultModel(
        ema_distance_threshold=row["ema_distance_threshold"],
        volume_ratio_threshold=row["volume_ratio_threshold"],
        rsi_threshold=row["rsi_threshold"],
        trades=row["trades"],
        winrate=row.get("winrate"),
        avg_R=row.get("avg_R"),
        profit_factor=row.get("profit_factor"),
        max_drawdown=row.get("max_drawdown"),
        scan_id=row.get("scan_id"),
        created_at=row.get("created_at") or datetime.utcnow(),
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def get_candidate_signals_without_outcome(db: Session, symbol: Optional[str] = None, limit: int = 500) -> List[CandidateSignalModel]:
    """Return candidate_signals that do not yet have a signal_outcomes row. Time-ordered (worker 병렬 삽입 대비)."""
    subq = db.query(SignalOutcomeModel.candidate_signal_id).distinct()
    q = db.query(CandidateSignalModel).filter(~CandidateSignalModel.id.in_(subq))
    if symbol:
        q = q.filter(CandidateSignalModel.symbol == symbol)
    return q.order_by(CandidateSignalModel.time.asc(), CandidateSignalModel.id.asc()).limit(limit).all()


_ALLOWED_SIGNAL_TABLES = {"candidate_signals", "candidate_signals_sorted"}


def get_candidate_signals_with_outcomes(
    db: Session,
    symbol: Optional[str] = None,
    limit: int = 10000,
    signals_table: str = "candidate_signals",
) -> List[dict]:
    """Return joined candidate_signals + signal_outcomes as list of dicts for stability map / ML.
    항상 시간순 정렬(time ASC, id ASC). Worker 병렬 삽입으로 id가 시간순이 아니어도 안전.
    리서치/스캔/volume report/ML 등 DB에서 시그널 불러올 때 이 함수만 사용하면 됨.
    Merges feature_values_ext (JSON) into each row when present."""
    if signals_table not in _ALLOWED_SIGNAL_TABLES:
        raise ValueError(f"Unsupported signals_table: {signals_table}")

    # Default: ORM model on candidate_signals
    if signals_table == "candidate_signals":
        q = (
            db.query(CandidateSignalModel, SignalOutcomeModel)
            .join(SignalOutcomeModel, CandidateSignalModel.id == SignalOutcomeModel.candidate_signal_id)
        )
        if symbol:
            q = q.filter(CandidateSignalModel.symbol == symbol)
        # Worker 병렬 삽입 시 id 순서가 시간 순이 아닐 수 있음 → 항상 시간 기준 정렬
        rows = q.order_by(CandidateSignalModel.time.asc(), CandidateSignalModel.id.asc()).limit(limit).all()
        out: list[dict] = []
        for c, o in rows:
            row = {
                "time": c.time,
                "close": c.close,
                "side": c.side,
                "regime": c.regime,
                "trend_direction": c.side,
                "approval_score": c.approval_score,
                "ema_distance": c.ema_distance or 0,
                "volume_ratio": c.volume_ratio or 0,
                "rsi": c.rsi or 0,
                "rsi_5m": c.rsi or 0,
                "trade_outcome": c.trade_outcome,
                "R_return": o.future_r_30,
                "future_r_5": o.future_r_5,
                "future_r_10": o.future_r_10,
                "future_r_20": o.future_r_20,
                "future_r_30": o.future_r_30,
            }
            if getattr(c, "feature_values_ext", None) and c.feature_values_ext:
                try:
                    ext = json.loads(c.feature_values_ext)
                    if isinstance(ext, dict):
                        row.update(ext)
                except (json.JSONDecodeError, TypeError):
                    pass
            out.append(row)
        return out

    # Non-default: query a table/view with the same schema (e.g. candidate_signals_sorted)
    sql = f"""
    SELECT
        cs.time AS time,
        cs.close AS close,
        cs.side AS side,
        cs.regime AS regime,
        cs.approval_score AS approval_score,
        cs.ema_distance AS ema_distance,
        cs.volume_ratio AS volume_ratio,
        cs.rsi AS rsi,
        cs.trade_outcome AS trade_outcome,
        cs.feature_values_ext AS feature_values_ext,
        so.future_r_5 AS future_r_5,
        so.future_r_10 AS future_r_10,
        so.future_r_20 AS future_r_20,
        so.future_r_30 AS future_r_30
    FROM `{signals_table}` cs
    JOIN signal_outcomes so ON cs.id = so.candidate_signal_id
    WHERE (:symbol IS NULL OR cs.symbol = :symbol)
    ORDER BY cs.time ASC, cs.id ASC
    LIMIT :limit
    """
    rows = db.execute(text(sql), {"symbol": symbol, "limit": int(limit)}).mappings().all()
    out: list[dict] = []
    for r in rows:
        row = {
            "time": r.get("time"),
            "close": float(r.get("close") or 0),
            "side": r.get("side"),
            "regime": r.get("regime"),
            "trend_direction": r.get("side"),
            "approval_score": r.get("approval_score"),
            "ema_distance": float(r.get("ema_distance") or 0),
            "volume_ratio": float(r.get("volume_ratio") or 0),
            "rsi": float(r.get("rsi") or 0),
            "rsi_5m": float(r.get("rsi") or 0),
            "trade_outcome": r.get("trade_outcome"),
            "R_return": r.get("future_r_30"),
            "future_r_5": r.get("future_r_5"),
            "future_r_10": r.get("future_r_10"),
            "future_r_20": r.get("future_r_20"),
            "future_r_30": r.get("future_r_30"),
        }
        ext_raw = r.get("feature_values_ext")
        if ext_raw:
            try:
                ext = json.loads(ext_raw)
                if isinstance(ext, dict):
                    row.update(ext)
            except (json.JSONDecodeError, TypeError):
                pass
        out.append(row)
    return out


def get_today_trade_summary(db: Session, today: date | None = None) -> dict:
    """Returns count, wins, losses, win_rate, pnl for today."""
    if today is None:
        today = date.today()
    start = datetime.combine(today, datetime.min.time())
    end = datetime.combine(today, datetime.max.time())
    rows = (
        db.query(TradeRecordModel)
        .filter(
            TradeRecordModel.closed_at >= start,
            TradeRecordModel.closed_at <= end,
        )
        .all()
    )
    trades = [to_domain(r) for r in rows]
    wins = sum(1 for t in trades if t.pnl > 0)
    losses = sum(1 for t in trades if t.pnl < 0)
    count = len(trades)
    win_rate = (wins / count * 100) if count else 0
    pnl = sum(t.pnl for t in trades)
    return {
        "count": count,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 1),
        "pnl": pnl,
    }


def get_paper_performance(db: Session, days: int = 7, mode_filter: str = "paper") -> dict:
    """최근 N일간 Paper 거래만 집계: count, wins, losses, win_rate, pnl, avg_r. Live 전환 판단용."""
    from datetime import timedelta
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.query(TradeRecordModel)
        .filter(
            TradeRecordModel.closed_at >= since,
            TradeRecordModel.mode == mode_filter,
        )
        .all()
    )
    trades = [to_domain(r) for r in rows]
    wins = sum(1 for t in trades if t.pnl > 0)
    losses = sum(1 for t in trades if t.pnl < 0)
    count = len(trades)
    win_rate = (wins / count * 100) if count else 0.0
    pnl = sum(t.pnl for t in trades)
    avg_r = (sum(t.rr for t in trades) / count) if count else 0.0
    return {
        "days": days,
        "mode": mode_filter,
        "count": count,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 1),
        "pnl": round(pnl, 2),
        "avg_r": round(avg_r, 3),
    }
