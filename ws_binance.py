# -*- coding: utf-8 -*-
"""
ws_binance.py — WebSocket helper (Binance public streams)
Interface (compatible avec main.py) :
- class StreamConfig(symbols, timeframe, on_kline_closed, on_ticker, reconnect_delay)
- class BinanceWS(config): 
    - start(loop)   # démarre en tâche(s) asynchrones (dans la loop fournie, ou sa propre loop)
    - async stop()  # annule proprement les tâches et ferme les WS
Notes:
- Pas de clé API requise (streams publics).
- Annule proprement les tâches pour éviter: 
  "Task was destroyed but it is pending!" et "coroutine was never awaited".
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import websockets

@dataclass
class StreamConfig:
    symbols: List[str]
    timeframe: str
    on_kline_closed: Optional[Callable[[str, dict], None]] = None
    on_ticker: Optional[Callable[[str, dict], None]] = None
    reconnect_delay: float = 3.0

def _to_stream_symbol(sym: str) -> str:
    return sym.replace("/", "").lower()

class BinanceWS:
    def __init__(self, cfg: StreamConfig):
        self.cfg = cfg
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._own_loop = False
        self._thread: Optional[threading.Thread] = None
        self._tasks: List[asyncio.Task] = []
        self._stop_evt = asyncio.Event()
        self._ws_conn = None  # combined stream connection
        self._running = False

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Démarre le consommateur dans la boucle fournie ou crée sa propre boucle threadée."""
        if loop and loop.is_running():
            self.loop = loop
            self._own_loop = False
            self._running = True
            task = loop.create_task(self._runner())
            self._tasks = [task]
        else:
            # Crée sa propre loop dans un thread
            self._own_loop = True
            self._running = True
            self.loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._thread_main, daemon=True)
            self._thread.start()

    def _thread_main(self):
        assert self.loop is not None
        asyncio.set_event_loop(self.loop)
        main_task = self.loop.create_task(self._runner())
        self._tasks = [main_task]
        try:
            self.loop.run_until_complete(main_task)
        except asyncio.CancelledError:
            pass
        finally:
            # Drain cancelled tasks
            pending = [t for t in asyncio.all_tasks(self.loop) if not t.done()]
            for t in pending:
                t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.stop()
            self.loop.close()

    async def stop(self):
        """Annule proprement toutes les tâches et ferme la connexion WS."""
        if not self._running:
            return
        self._running = False
        # Signale aux coroutines de sortir
        try:
            self._stop_evt.set()
        except Exception:
            pass
        # Ferme WS si ouvert
        try:
            if self._ws_conn is not None:
                await self._ws_conn.close()
        except Exception:
            pass
        # Annule tâches
        try:
            tasks = list(self._tasks)
            self._tasks.clear()
            for t in tasks:
                t.cancel()
            if tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            pass
        # Si on a sa propre loop threadée, attendre la fin du thread
        if self._own_loop and self._thread is not None:
            try:
                # post un no-op pour réveiller la loop si besoin
                if self.loop and self.loop.is_running():
                    def _noop(): pass
                    self.loop.call_soon_threadsafe(_noop)
            except Exception:
                pass
            self._thread.join(timeout=2.0)

    async def _runner(self):
        """Boucle de (re)connexion: ouvre une combined stream et dispatch messages."""
        streams = []
        # ticker streams
        for s in self.cfg.symbols:
            streams.append(f"{_to_stream_symbol(s)}@bookTicker")
        # kline streams
        for s in self.cfg.symbols:
            streams.append(f"{_to_stream_symbol(s)}@kline_{self.cfg.timeframe}")
        url = "wss://stream.binance.com:9443/stream?streams=" + "/".join(streams)

        while not self._stop_evt.is_set():
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    self._ws_conn = ws
                    # Consommer jusqu'à stop
                    await self._consume(ws)
            except asyncio.CancelledError:
                break
            except Exception:
                # Reconnect soft
                if self._stop_evt.is_set():
                    break
                await asyncio.sleep(self.cfg.reconnect_delay)
            finally:
                self._ws_conn = None

    async def _consume(self, ws):
        """Lit les messages et envoie aux callbacks. Sort sur stop_evt."""
        while not self._stop_evt.is_set():
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            except asyncio.TimeoutError:
                # keepalive timeout: boucle; ping automatique par websockets
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                # ferme et laisse le runner reconnecter
                break

            try:
                data = json.loads(msg)
            except Exception:
                continue

            payload = data.get("data") or data
            stream = data.get("stream", "")

            # bookTicker => on_ticker
            if "bookTicker" in stream:
                s = stream.split("@")[0].upper()
                if self.cfg.on_ticker:
                    with contextlib.suppress(Exception):
                        self.cfg.on_ticker(s, payload)
                continue

            # kline => on_kline_closed quand x == true
            if "kline_" in stream:
                sym = payload.get("s") or stream.split("@")[0].upper()
                k = payload.get("k", {})
                if k.get("x"):  # closed
                    if self.cfg.on_kline_closed:
                        with contextlib.suppress(Exception):
                            self.cfg.on_kline_closed(sym, payload)
                continue
