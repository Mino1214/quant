"""
Binance Futures broker: real order execution via REST API.
TODO before live: double-check order types, error handling, rate limits.
"""
import logging
import os
import time
from typing import Optional

import requests

from core.models import Direction, Position
from execution.base_broker import BaseBroker

logger = logging.getLogger(__name__)

BINANCE_FUTURES_BASE = "https://fapi.binance.com"


class BinanceBroker(BaseBroker):
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        self._api_key = api_key or os.environ.get("BINANCE_API_KEY", "")
        self._api_secret = api_secret or os.environ.get("BINANCE_API_SECRET", "")
        self._session = requests.Session()

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        signed: bool = True,
    ) -> dict:
        url = f"{BINANCE_FUTURES_BASE}{endpoint}"
        if params is None:
            params = {}
        if signed and self._api_key and self._api_secret:
            params["timestamp"] = int(time.time() * 1000)
            # TODO: add HMAC signature for params
            from urllib.parse import urlencode
            import hmac
            import hashlib
            qs = urlencode(params)
            sig = hmac.new(
                self._api_secret.encode(),
                qs.encode(),
                hashlib.sha256,
            ).hexdigest()
            params["signature"] = sig
            self._session.headers["X-MBX-APIKEY"] = self._api_key
        r = self._session.request(method, url, params=params)
        r.raise_for_status()
        return r.json() if r.content else {}

    async def place_market_order(
        self,
        symbol: str,
        side: Direction,
        quantity: float,
        reduce_only: bool = False,
    ) -> Optional[str]:
        try:
            data = self._request(
                "POST",
                "/fapi/v1/order",
                params={
                    "symbol": symbol,
                    "side": "BUY" if side == Direction.LONG else "SELL",
                    "type": "MARKET",
                    "quantity": quantity,
                    "reduceOnly": str(reduce_only).lower(),
                },
            )
            return str(data.get("orderId", ""))
        except Exception as e:
            logger.exception("Binance place_market_order failed: %s", e)
            return None

    async def place_stop_loss_order(
        self,
        symbol: str,
        side: Direction,
        quantity: float,
        stop_price: float,
        reduce_only: bool = True,
    ) -> Optional[str]:
        try:
            data = self._request(
                "POST",
                "/fapi/v1/order",
                params={
                    "symbol": symbol,
                    "side": "SELL" if side == Direction.LONG else "BUY",
                    "type": "STOP_MARKET",
                    "quantity": quantity,
                    "stopPrice": stop_price,
                    "reduceOnly": str(reduce_only).lower(),
                    "closePosition": "false",
                },
            )
            return str(data.get("orderId", ""))
        except Exception as e:
            logger.exception("Binance place_stop_loss_order failed: %s", e)
            return None

    async def place_take_profit_order(
        self,
        symbol: str,
        side: Direction,
        quantity: float,
        stop_price: float,
        reduce_only: bool = True,
    ) -> Optional[str]:
        try:
            data = self._request(
                "POST",
                "/fapi/v1/order",
                params={
                    "symbol": symbol,
                    "side": "SELL" if side == Direction.LONG else "BUY",
                    "type": "TAKE_PROFIT_MARKET",
                    "quantity": quantity,
                    "stopPrice": stop_price,
                    "reduceOnly": str(reduce_only).lower(),
                },
            )
            return str(data.get("orderId", ""))
        except Exception as e:
            logger.exception("Binance place_take_profit_order failed: %s", e)
            return None

    async def close_position(self, symbol: str) -> bool:
        pos = await self.get_open_position(symbol)
        if pos is None or pos.size == 0:
            return True
        side = Direction.SHORT if pos.side == Direction.LONG else Direction.LONG
        oid = await self.place_market_order(symbol, side, pos.size, reduce_only=True)
        return oid is not None

    async def get_open_position(self, symbol: str) -> Optional[Position]:
        try:
            data = self._request("GET", "/fapi/v2/positionRisk", params={"symbol": symbol})
            for p in data:
                amt = float(p.get("positionAmt", 0))
                if amt == 0:
                    continue
                return Position(
                    symbol=symbol,
                    side=Direction.LONG if amt > 0 else Direction.SHORT,
                    size=abs(amt),
                    entry_price=float(p.get("entryPrice", 0)),
                    opened_at=__import__("datetime").datetime.utcnow(),
                )
            return None
        except Exception as e:
            logger.exception("Binance get_open_position failed: %s", e)
            return None
