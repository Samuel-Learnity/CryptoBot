# -*- coding: utf-8 -*-
"""
WebSocket client gratuit pour Binance Spot (market data uniquement).
- Streams: kline_x (bougies) et ticker
- Sans ccxt.pro (payant). Utilise la lib `websockets` (gratuite).
"""
import asyncio
import json
from dataclasses import dataclass, field
from typing import Dict, Callable, Optional, List

import websockets

BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream"

def to_stream_symbol(ccxt_symbol: str) -> str:
    # "BTC/USDT" -> "btcusdt"
    return ccxt_symbol.replace("/", "").lower()

@dataclass
class StreamConfig:
    symbols: List[str]
    timeframe: str = "1h"  # ex: "1m","1h","4h"
    on_kline_closed: Optional[Callable[[str, dict], None]] = None
    on_ticker: Optional[Callable[[str, dict], None]] = None
    reconnect_delay: float = 3.0

class BinanceWS:
    def __init__(self, cfg: StreamConfig):
        self.cfg = cfg
        self._task: Optional[asyncio.Task] = None
        self._running = False

    def _build_url(self) -> str:
        streams = []
        for s in self.cfg.symbols:
            ss = to_stream_symbol(s)
            streams.append(f"{ss}@kline_{self.cfg.timeframe}")
            streams.append(f"{ss}@miniTicker")
        stream_str = "/".join(streams)
        return f"{BINANCE_WS_BASE}?streams={stream_str}"

    async def _consume(self):
        url = self._build_url()
        while self._running:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    while self._running:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        stream = data.get("stream", "")
                        payload = data.get("data", {})
                        if "kline" in stream and "k" in payload:
                            k = payload["k"]
                            if k.get("x"):  # closed candle
                                sym = payload.get("s", "").upper().replace("USDT", "/USDT") if "/" not in payload.get("s","") else payload["s"]
                                if self.cfg.on_kline_closed:
                                    self.cfg.on_kline_closed(sym, payload)
                        elif "miniTicker" in stream:
                            sym = payload.get("s", "").upper().replace("USDT", "/USDT")
                            if self.cfg.on_ticker:
                                self.cfg.on_ticker(sym, payload)
            except Exception as e:
                # Reconnect loop
                await asyncio.sleep(self.cfg.reconnect_delay)

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None):
        if self._running:
            return
        self._running = True
        loop = loop or asyncio.get_event_loop()
        self._task = loop.create_task(self._consume())

    async def stop(self):
        self._running = False
        if self._task:
            await asyncio.sleep(0)  # yield to allow exit
            self._task = None
