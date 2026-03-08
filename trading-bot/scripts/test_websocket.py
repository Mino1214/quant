"""
Binance Futures WebSocket 테스트: 1m kline 스트림 수신 확인.
몇 개 메시지 수신 후 종료 (Ctrl+C 가능).
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market.binance_ws import run_binance_kline_ws
from core.models import Candle


def main():
    symbol = "BTCUSDT"
    count = [0]
    max_events = 20
    done = asyncio.Event()

    def on_candle(candle: Candle, is_closed: bool, interval: str):
        count[0] += 1
        status = "CLOSED" if is_closed else "open"
        print(f"[{count[0]}] {interval} {status}  ts={candle.timestamp}  O={candle.open} H={candle.high} L={candle.low} C={candle.close} V={candle.volume}")
        if count[0] >= max_events:
            done.set()

    async def run():
        print(f"Connecting to Binance Futures WebSocket: {symbol}@kline_1m/5m/15m")
        print(f"Receiving up to {max_events} events (then exit). Ctrl+C to stop early.\n")
        task = asyncio.create_task(run_binance_kline_ws(symbol, on_candle))
        await done.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nStopped by user.")
    print(f"\nDone. Received {count[0]} events. WebSocket OK.")


if __name__ == "__main__":
    main()
