"""
Load 1m (and optionally 5m/15m) candles from DB tables: btc1m, btc5m, btc15m.
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import text

from core.models import Candle, Timeframe
from storage.database import engine


def _parse_ts(row: dict) -> datetime:
    """Parse timestamp: unix ms, unix s, or datetime. openTime(수집기), open_time, timestamp, time."""
    for key in ("openTime", "open_time", "timestamp", "time", "t"):
        val = row.get(key)
        if val is not None:
            break
    else:
        raise ValueError("No time column found (openTime, open_time, timestamp, time)")
    if isinstance(val, datetime):
        return val
    if isinstance(val, (int, float)):
        if val > 1e12:
            return datetime.utcfromtimestamp(val / 1000.0)
        return datetime.utcfromtimestamp(float(val))
    s = str(val).replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def _ohlcv(row: dict) -> tuple:
    """수집기 스키마(o,h,l,c,v) 또는 일반(open,high,low,close,volume) 지원."""
    o = row.get("o") or row.get("open") or row.get("Open")
    h = row.get("h") or row.get("high") or row.get("High")
    l_ = row.get("l") or row.get("low") or row.get("Low")
    c = row.get("c") or row.get("close") or row.get("Close")
    v = row.get("v") or row.get("volume") or row.get("Volume") or 0
    return float(o), float(h), float(l_), float(c), float(v)


def load_1m_from_db(
    table: str = "btc1m",
    start_ts: Optional[datetime] = None,
    end_ts: Optional[datetime] = None,
    limit: Optional[int] = None,
    time_col: str = "openTime",
    symbol: Optional[str] = None,
) -> List[Candle]:
    """
    Load 1m OHLCV from table. 수집기 스키마: symbol, openTime, o, h, l, c, v.
    symbol 있으면 WHERE symbol = :symbol 반드시 사용 (섞이면 15m 집계/지표가 0 됨).
    """
    conditions = []
    params = {}
    if symbol is not None:
        conditions.append("`symbol` = :symbol")
        params["symbol"] = symbol
    if start_ts is not None:
        conditions.append("`" + time_col + "` >= :start_ts")
        params["start_ts"] = start_ts
    if end_ts is not None:
        conditions.append("`" + time_col + "` <= :end_ts")
        params["end_ts"] = end_ts
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    limit_clause = f" LIMIT {int(limit)}" if limit else ""
    sql = f"SELECT * FROM `{table}` {where} ORDER BY `{time_col}` ASC {limit_clause}"
    candles = []
    # openTime(BIGINT ms) 컬럼이면 시각을 ms로 넘김
    if time_col in ("openTime", "open_time"):
        if "start_ts" in params:
            params["start_ts"] = int(params["start_ts"].timestamp() * 1000)
        if "end_ts" in params:
            params["end_ts"] = int(params["end_ts"].timestamp() * 1000)
    with engine.connect() as conn:
        result = conn.execute(text(sql), params)
        for row in result.mappings():
            try:
                r = dict(row)
                ts = _parse_ts(r)
                o, h, l_, c, v = _ohlcv(r)
                # Optional extended fields (Binance-style schema 우선 지원)
                qv = (
                    r.get("quote_volume")
                    or r.get("quoteVolume")
                    or r.get("quoteVolumeUSDT")
                    or 0
                )
                tc = r.get("trade_count") or r.get("n") or 0
                tbv = (
                    r.get("taker_buy_volume")
                    or r.get("takerBuyBaseVolume")
                    or r.get("taker_buy_base_volume")
                    or 0
                )
                tbqv = (
                    r.get("taker_buy_quote_volume")
                    or r.get("takerBuyQuoteVolume")
                    or r.get("taker_buy_quote_volume")
                    or 0
                )
                candles.append(
                    Candle(
                        open=o,
                        high=h,
                        low=l_,
                        close=c,
                        volume=v,
                        timestamp=ts,
                        timeframe=Timeframe.M1,
                        quote_volume=float(qv) if qv is not None else 0.0,
                        trade_count=int(tc) if tc is not None else 0,
                        taker_buy_volume=float(tbv) if tbv is not None else 0.0,
                        taker_buy_quote_volume=float(tbqv) if tbqv is not None else 0.0,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
    return candles


def load_5m_from_db(
    table: str = "btc5m",
    start_ts: Optional[datetime] = None,
    end_ts: Optional[datetime] = None,
    limit: Optional[int] = None,
    time_col: str = "openTime",
    symbol: Optional[str] = None,
) -> List[Candle]:
    """Load 5m OHLCV from table."""
    return _load_generic_from_db(table, start_ts, end_ts, limit, time_col, symbol, Timeframe.M5)


def load_15m_from_db(
    table: str = "btc15m",
    start_ts: Optional[datetime] = None,
    end_ts: Optional[datetime] = None,
    limit: Optional[int] = None,
    time_col: str = "openTime",
    symbol: Optional[str] = None,
) -> List[Candle]:
    """Load 15m OHLCV from table."""
    return _load_generic_from_db(table, start_ts, end_ts, limit, time_col, symbol, Timeframe.M15)


def _load_generic_from_db(
    table: str,
    start_ts: Optional[datetime],
    end_ts: Optional[datetime],
    limit: Optional[int],
    time_col: str,
    symbol: Optional[str],
    timeframe: Timeframe,
) -> List[Candle]:
    """Generic DB loader for OHLCV with given timeframe."""
    conditions = []
    params = {}
    if symbol is not None:
        conditions.append("`symbol` = :symbol")
        params["symbol"] = symbol
    if start_ts is not None:
        conditions.append("`" + time_col + "` >= :start_ts")
        params["start_ts"] = start_ts
    if end_ts is not None:
        conditions.append("`" + time_col + "` <= :end_ts")
        params["end_ts"] = end_ts
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    limit_clause = f" LIMIT {int(limit)}" if limit else ""
    sql = f"SELECT * FROM `{table}` {where} ORDER BY `{time_col}` ASC {limit_clause}"
    candles: List[Candle] = []
    if time_col in ("openTime", "open_time"):
        if "start_ts" in params:
            params["start_ts"] = int(params["start_ts"].timestamp() * 1000)
        if "end_ts" in params:
            params["end_ts"] = int(params["end_ts"].timestamp() * 1000)
    with engine.connect() as conn:
        result = conn.execute(text(sql), params)
        for row in result.mappings():
            try:
                r = dict(row)
                ts = _parse_ts(r)
                o, h, l_, c, v = _ohlcv(r)
                qv = (
                    r.get("quote_volume")
                    or r.get("quoteVolume")
                    or r.get("quoteVolumeUSDT")
                    or 0
                )
                tc = r.get("trade_count") or r.get("n") or 0
                tbv = (
                    r.get("taker_buy_volume")
                    or r.get("takerBuyBaseVolume")
                    or r.get("taker_buy_base_volume")
                    or 0
                )
                tbqv = (
                    r.get("taker_buy_quote_volume")
                    or r.get("takerBuyQuoteVolume")
                    or r.get("taker_buy_quote_volume")
                    or 0
                )
                candles.append(
                    Candle(
                        open=o,
                        high=h,
                        low=l_,
                        close=c,
                        volume=v,
                        timestamp=ts,
                        timeframe=timeframe,
                        quote_volume=float(qv) if qv is not None else 0.0,
                        trade_count=int(tc) if tc is not None else 0,
                        taker_buy_volume=float(tbv) if tbv is not None else 0.0,
                        taker_buy_quote_volume=float(tbqv) if tbqv is not None else 0.0,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
    return candles


def _load_last_n(
    n: int,
    table: str,
    time_col: str,
    timeframe: Timeframe,
    symbol: Optional[str] = None,
) -> List[Candle]:
    """DB에서 가장 최근 n개 봉을 시간 오름차순으로 로드. 수집기 스키마(openTime, o,h,l,c,v) 공통."""
    where = " WHERE `symbol` = :symbol" if symbol else ""
    sql = f"SELECT * FROM `{table}`{where} ORDER BY `{time_col}` DESC LIMIT :lim"
    params: dict = {"lim": n}
    if symbol:
        params["symbol"] = symbol
    candles = []
    with engine.connect() as conn:
        result = conn.execute(text(sql), params)
        rows = list(result.mappings())
    for row in reversed(rows):
        try:
            r = dict(row)
            ts = _parse_ts(r)
            o, h, l_, c, v = _ohlcv(r)
            qv = (
                r.get("quote_volume")
                or r.get("quoteVolume")
                or r.get("quoteVolumeUSDT")
                or 0
            )
            tc = r.get("trade_count") or r.get("n") or 0
            tbv = (
                r.get("taker_buy_volume")
                or r.get("takerBuyBaseVolume")
                or r.get("taker_buy_base_volume")
                or 0
            )
            tbqv = (
                r.get("taker_buy_quote_volume")
                or r.get("takerBuyQuoteVolume")
                or r.get("taker_buy_quote_volume")
                or 0
            )
            candles.append(
                Candle(
                    open=o,
                    high=h,
                    low=l_,
                    close=c,
                    volume=v,
                    timestamp=ts,
                    timeframe=timeframe,
                    quote_volume=float(qv) if qv is not None else 0.0,
                    trade_count=int(tc) if tc is not None else 0,
                    taker_buy_volume=float(tbv) if tbv is not None else 0.0,
                    taker_buy_quote_volume=float(tbqv) if tbqv is not None else 0.0,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return candles


def load_1m_last_n(
    n: int = 800,
    table: str = "btc1m",
    time_col: str = "openTime",
    symbol: Optional[str] = None,
) -> List[Candle]:
    """DB에서 가장 최근 n개 1m 봉 (시간 오름차순). symbol 있으면 해당 심볼만."""
    return _load_last_n(n, table, time_col, Timeframe.M1, symbol=symbol)


def load_5m_last_n(
    n: int = 100,
    table: str = "btc5m",
    time_col: str = "openTime",
    symbol: Optional[str] = None,
) -> List[Candle]:
    """DB에서 가장 최근 n개 5m 봉 (시간 오름차순). symbol 있으면 해당 심볼만."""
    return _load_last_n(n, table, time_col, Timeframe.M5, symbol=symbol)


def load_15m_last_n(
    n: int = 100,
    table: str = "btc15m",
    time_col: str = "openTime",
    symbol: Optional[str] = None,
) -> List[Candle]:
    """DB에서 가장 최근 n개 15m 봉 (시간 오름차순). symbol 있으면 해당 심볼만."""
    return _load_last_n(n, table, time_col, Timeframe.M15, symbol=symbol)


def load_1m_before_t_last_n(
    end_ts: datetime,
    n: int = 100,
    table: str = "btc1m",
    time_col: str = "openTime",
    symbol: Optional[str] = None,
) -> List[Candle]:
    """
    Load last n 1m candles with timestamp <= end_ts (ascending order).
    For cross-market features: use only data at or before signal time T.
    """
    conditions = ["`{}` <= :end_ts".format(time_col)]
    params: dict = {"end_ts": end_ts}
    if symbol is not None:
        conditions.append("`symbol` = :symbol")
        params["symbol"] = symbol
    where = " WHERE " + " AND ".join(conditions)
    if time_col in ("openTime", "open_time"):
        params["end_ts"] = int(end_ts.timestamp() * 1000)
    limit_clause = f" LIMIT {int(n)}"
    sql = f"SELECT * FROM `{table}` {where} ORDER BY `{time_col}` DESC {limit_clause}"
    candles = []
    with engine.connect() as conn:
        result = conn.execute(text(sql), params)
        rows = list(result.mappings())
    for row in reversed(rows):
        try:
            r = dict(row)
            ts = _parse_ts(r)
            o, h, l_, c, v = _ohlcv(r)
            candles.append(
                Candle(open=o, high=h, low=l_, close=c, volume=v, timestamp=ts, timeframe=Timeframe.M1)
            )
        except (KeyError, TypeError, ValueError):
            continue
    return candles
