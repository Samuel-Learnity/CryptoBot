# -*- coding: utf-8 -*-
"""
Streaming Candlestick (Terminal) — Binance WebSocket + plotext (gratuit)
- Précharge l'historique via REST Binance (affichage immédiat)
- Bougies en temps réel via WS
- Utilise des indices numériques en abscisse + étiquettes texte (évite les erreurs de format de dates)
Usage:
    python terminal_candles_stream.py --symbol BTC/USDT --timeframe 1m --limit 120
"""
import argparse
import asyncio
import json
import math
import signal
from datetime import datetime, timezone
from typing import Deque, List, Tuple
from collections import deque

import websockets
import requests

try:
    import plotext as plx
except Exception as e:
    print("plotext est requis pour l'affichage en bougies. Installe-le:  pip install plotext")
    raise

def to_stream_symbol(sym: str) -> str:
    return sym.replace("/", "").lower()

def to_rest_symbol(sym: str) -> str:
    return sym.replace("/", "").upper()

def ts_to_str(ms: int) -> str:
    # label lisible pour l'axe (HH:MM)
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%H:%M")

class CandleBuffer:
    """Tampon de N bougies OHLC avec bougie courante remplaçable tant qu'elle n'est pas close."""
    def __init__(self, limit: int):
        self.limit = limit
        self.opens: Deque[float] = deque(maxlen=limit)
        self.highs: Deque[float] = deque(maxlen=limit)
        self.lows: Deque[float] = deque(maxlen=limit)
        self.closes: Deque[float] = deque(maxlen=limit)
        self.labels: Deque[str] = deque(maxlen=limit)
        self.current_open: float = math.nan
        self.current_high: float = math.nan
        self.current_low: float = math.nan
        self.current_close: float = math.nan
        self.current_label: str = ""

    def preload(self, ohlc_list):
        """Remplit l'historique initial (liste d'items [openTime, o, h, l, c, v, closeTime, ...])"""
        for item in ohlc_list:
            t_close = int(item[6])
            o = float(item[1]); h=float(item[2]); l=float(item[3]); c=float(item[4])
            self.opens.append(o); self.highs.append(h); self.lows.append(l); self.closes.append(c); self.labels.append(ts_to_str(t_close))

    def update_live(self, o,h,l,c, label: str):
        self.current_open, self.current_high, self.current_low, self.current_close = o,h,l,c
        self.current_label = label

    def close_current(self):
        if math.isnan(self.current_open):
            return
        self.opens.append(self.current_open)
        self.highs.append(self.current_high)
        self.lows.append(self.current_low)
        self.closes.append(self.current_close)
        self.labels.append(self.current_label)
        self.current_open = self.current_high = self.current_low = self.current_close = math.nan
        self.current_label = ""

    def get_arrays(self) -> Tuple[List[float], List[float], List[float], List[float], List[str]]:
        o = list(self.opens); h = list(self.highs); l = list(self.lows); c = list(self.closes); lbl = list(self.labels)
        if not math.isnan(self.current_open):
            o.append(self.current_open); h.append(self.current_high); l.append(self.current_low); c.append(self.current_close); lbl.append(self.current_label + "*")
        return o,h,l,c,lbl

def fetch_klines_rest(symbol: str, timeframe: str, limit: int):
    """Binance REST public klines"""
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": to_rest_symbol(symbol), "interval": timeframe, "limit": limit}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()

async def stream(symbol: str, timeframe: str, limit: int, ma_period:int=20, breakout:int=20, overlay_ma20:bool=False, overlay_hh20:bool=False, lookback:int=20):
    url = f"wss://stream.binance.com:9443/ws/{to_stream_symbol(symbol)}@kline_{timeframe}"
    buf = CandleBuffer(limit=limit)

    # Précharge l'historique pour rendu immédiat
    try:
        hist = fetch_klines_rest(symbol, timeframe, limit=limit)
        # garde toutes sauf la bougie en cours
        buf.preload(hist[:-1])
    except Exception as e:
        print("Préchargement REST échoué:", e)

    async def render(overlay_ma20=False, overlay_hh20=False, lookback=20):
        o,h,l,c,lbl = buf.get_arrays()
        if len(o) < 1:
            return
        plx.clear_figure()
        # Utilise des indices pour l'axe X et colle des labels texte
        x = list(range(len(o)))
        plx.candlestick(dates=x, data={"Open": o, "High": h, "Low": l, "Close": c})
        # Overlays: MA and HH breakout
        if len(c) >= ma_period:
            ma_vals = [sum(c[max(0,i-ma_period+1):i+1]) / (i - max(0,i-ma_period+1) + 1) for i in range(len(c))]
            plx.plot(x, ma_vals, label=f"MA{ma_period}")
        if len(h) >= breakout:
            hh_vals = []
            for i in range(len(h)):
                start = max(0, i - breakout + 1)
                hh_vals.append(max(h[start:i+1]))
            plx.plot(x, hh_vals, label=f"HH{breakout}")
        plx.title(f"{symbol} {timeframe}  (Bougies: {len(o)})")
        # Overlays
        try:
            x = list(range(len(o)))
            if overlay_ma20 and len(c) >= 2:
                ma = []
                for i in range(len(c)):
                    s = max(0, i-19); w = c[s:i+1]; ma.append(sum(w)/len(w))
                plx.plot(x, ma, label="MA20")
            if overlay_hh20 and len(h) >= 2:
                hh = []
                for i in range(len(h)):
                    s = max(0, i - lookback)
                    prev = h[s:i] if i > s else []
                    lvl = max(prev) if prev else h[i]
                    hh.append(lvl)
                plx.plot(x, hh, label=f"HH{lookback}")
            plx.legend(True)
        except Exception:
            pass

        try:
            step = max(1, len(lbl)//6)
            xticks = [i for i in range(0, len(lbl), step)]
            xlabels = [lbl[i] for i in xticks]
            plx.xticks(xticks, xlabels)
        except Exception:
            pass
        plx.show()

    # Premier rendu
    await render(overlay_ma20=overlay_ma20, overlay_hh20=overlay_hh20, lookback=lookback)

    while True:
        try:
            async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                async for msg in ws:
                    data = json.loads(msg)
                    k = data.get("k", {})
                    if not k:
                        k = data.get("data", {}).get("k", {})
                    if not k:
                        continue
                    o = float(k["o"]); h = float(k["h"]); l = float(k["l"]); c = float(k["c"])
                    is_closed = bool(k["x"])
                    label = ts_to_str(int(k["T"]))

                    if is_closed:
                        buf.update_live(o,h,l,c,label)
                        buf.close_current()
                    else:
                        buf.update_live(o,h,l,c,label)
                    await render(overlay_ma20=overlay_ma20, overlay_hh20=overlay_hh20, lookback=lookback)
        except (asyncio.CancelledError, KeyboardInterrupt):
            break
        except Exception:
            await asyncio.sleep(2.0)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--timeframe", default="1m")
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--overlay_ma20", action="store_true")
    ap.add_argument("--overlay_hh20", action="store_true")
    ap.add_argument("--lookback", type=int, default=20)
    ap.add_argument("--ma", type=int, default=20)
    ap.add_argument("--breakout", type=int, default=20)
    args = ap.parse_args()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    task = loop.create_task(stream(args.symbol, args.timeframe, args.limit, args.ma, args.breakout, args.overlay_ma20, args.overlay_hh20, args.lookback))

    def handle_sig(*_):
        if not task.done():
            task.cancel()
    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, handle_sig)
        except NotImplementedError:
            pass

    try:
        loop.run_until_complete(task)
    finally:
        loop.stop()
        loop.close()

if __name__ == "__main__":
    main()
