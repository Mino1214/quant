"""
Cross-market features: ETH (1m), BTC funding rate, open interest.
All features aligned to signal_timestamp T (only data at or before T).
"""
from datetime import datetime
from typing import Dict, List, Optional

from core.models import Candle, StrategySettings
from indicators.ema import ema
from indicators.volume import vma_from_candles

from storage.candle_loader import load_1m_before_t_last_n
from storage.cross_market_loader import load_funding_before, load_open_interest_before

# Ordered keys for ML when cross-market features are present
CROSS_MARKET_FEATURE_KEYS = [
    "eth_return_5m",
    "eth_momentum",
    "eth_volume_ratio",
    "funding_rate",
    "open_interest_change",
]

ETH_SYMBOL = "ETHUSDT"
ETH_1M_TABLE = "eth1m"
DEFAULT_ETH_LOOKBACK = 100


def load_eth_features(signal_timestamp: datetime, settings: StrategySettings, eth_candles: Optional[List[Candle]] = None) -> Dict[str, float]:
    """
    ETH features at T: 5-bar return, momentum (close vs EMA), volume ratio.
    Uses only candles with timestamp <= signal_timestamp.
    If eth_candles is provided (e.g. from backtest), use them; else load from eth1m.
    """
    out = {
        "eth_return_5m": 0.0,
        "eth_momentum": 0.0,
        "eth_volume_ratio": 0.0,
    }
    if eth_candles is not None:
        candles = [c for c in eth_candles if c.timestamp <= signal_timestamp]
        candles = sorted(candles, key=lambda c: c.timestamp)[-DEFAULT_ETH_LOOKBACK:]
    else:
        try:
            candles = load_1m_before_t_last_n(
                end_ts=signal_timestamp,
                n=DEFAULT_ETH_LOOKBACK,
                table=ETH_1M_TABLE,
                symbol=ETH_SYMBOL,
            )
        except Exception:
            return out
    if not candles or len(candles) < 5:
        return out
    closes = [c.close for c in candles]
    # 5-bar return
    if closes[-5] and closes[-5] != 0:
        out["eth_return_5m"] = (closes[-1] / closes[-5] - 1.0) * 100.0
    # momentum: close vs EMA
    period = min(settings.ema_mid, len(closes) - 1)
    if period >= 2 and candles[-1].close and candles[-1].close > 0:
        e = ema(closes, period)
        if e is not None:
            out["eth_momentum"] = (candles[-1].close - e) / candles[-1].close * 100.0
    # volume ratio
    if len(candles) >= settings.volume_ma_period:
        vma_val = vma_from_candles(candles, settings.volume_ma_period)
        if vma_val and vma_val > 0:
            out["eth_volume_ratio"] = candles[-1].volume / vma_val
    return out


def load_derivatives_features(signal_timestamp: datetime) -> Dict[str, float]:
    """
    Derivatives at T: latest funding_rate (at or before T), open_interest_change from latest 2 OI rows.
    """
    out = {
        "funding_rate": 0.0,
        "open_interest_change": 0.0,
    }
    try:
        funding_rows = load_funding_before(signal_timestamp, limit=1)
        if funding_rows:
            out["funding_rate"] = float(funding_rows[0].get("funding_rate", 0) or 0)
    except Exception:
        pass
    try:
        oi_rows = load_open_interest_before(signal_timestamp, limit=2)
        if len(oi_rows) >= 2:
            v0 = float(oi_rows[1].get("sum_open_interest") or 0)
            v1 = float(oi_rows[0].get("sum_open_interest") or 0)
            if v0 and v0 > 0:
                out["open_interest_change"] = (v1 - v0) / v0 * 100.0
    except Exception:
        pass
    return out


def build_cross_market_features(
    signal_timestamp: datetime,
    btc_features_already: Dict[str, float],
    settings: StrategySettings,
    eth_candles: Optional[List[Candle]] = None,
) -> Dict[str, float]:
    """
    Build cross-market feature dict at signal_timestamp.
    Merges btc_features_already + eth features + derivatives (funding, OI change).
    Missing data: use 0 so training/inference can proceed without leakage.
    """
    eth_feat = load_eth_features(signal_timestamp, settings, eth_candles=eth_candles)
    deriv_feat = load_derivatives_features(signal_timestamp)
    result = dict(btc_features_already)
    result.update(eth_feat)
    result.update(deriv_feat)
    return result
