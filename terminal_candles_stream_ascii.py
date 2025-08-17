# -*- coding: utf-8 -*-
"""
ASCII Candlestick Streaming (gratuit, sans plotext)
- WebSocket Binance gratuit (kline_{timeframe})
- Couleurs ANSI (vert/rouge) si terminal compatible
- Mise à jour en continu : ticks et clôtures
Usage:
    python terminal_candles_stream_ascii.py --symbol BTC/USDT --timeframe 1m --limit 120 --height 24 --cols 100
"""

import argparse
import asyncio
import json
import math
import os
import shutil
import signal
import sys
from collections import deque
from datetime import datetime, timezone

import websockets

RESET = "\033[0m"
RED = "\033[31m"
GREEN = "\033[32m"
DIM = "\033[2m"
BOLD = "\033[1m"

def supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("TERM") not in (None, "dumb")

HAS_COLOR = supports_color()

def colorize(s: str, color: str) -> str:
    if not HAS_COLOR:
        return s
    return color + s + RESET

def to_stream_symbol(sym: str) -> str:
    return sym.replace("/", "").lower()

def ts_str(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%H:%M")

class KlineBuf:
    def __init__(self, limit: int):
        self.limit = limit
        self.data = deque(maxlen=limit)  # list of dicts: {o,h,l,c,t_close}

    def upsert_live(self, o, h, l, c, t_close, closed: bool):
        if closed:
            self.data.append({"o": o, "h": h, "l": l, "c": c, "t": t_close})
        else:
            # replace or append current forming candle
            if self.data and self.data[-1].get("_forming", False):
                self.data[-1] = {"o": o, "h": h, "l": l, "c": c, "t": t_close, "_forming": True}
            else:
                self.data.append({"o": o, "h": h, "l": l, "c": c, "t": t_close, "_forming": True})

    def arrays(self):
        o = [d["o"] for d in self.data]
        h = [d["h"] for d in self.data]
        l = [d["l"] for d in self.data]
        c = [d["c"] for d in self.data]
        t = [d["t"] for d in self.data]
        forming = [bool(d.get("_forming")) for d in self.data]
        return o, h, l, c, t, forming

def scale(val, vmin, vmax, rows):
    if vmax - vmin < 1e-12:
        return 0
    # 0 at bottom, rows-1 at top
    y = int((val - vmin) / (vmax - vmin) * (rows - 1))
    return max(0, min(rows - 1, y))

def render(symbol, timeframe, buf: KlineBuf, height: int = 24, cols: int = 100, ma: int = 20, breakout: int = 20):
    o, h, l, c, t, forming = buf.arrays()
    if len(o) < 2:
        return
    # If too many candles for cols, sample the last 'cols'
    n = len(o)
    start = max(0, n - cols)
    o = o[start:]; h = h[start:]; l = l[start:]; c = c[start:]; t = t[start:]; forming = forming[start:]
    # Determine min/max range with small padding
    vmin = min(l); vmax = max(h)
    pad = (vmax - vmin) * 0.02 if vmax > vmin else 1.0
    vmin -= pad; vmax += pad

    rows = height
    # build grid of spaces
    grid = [[" "]*len(o) for _ in range(rows)]

    for x in range(len(o)):
        oy = scale(o[x], vmin, vmax, rows)
        hy = scale(h[x], vmin, vmax, rows)
        ly = scale(l[x], vmin, vmax, rows)
        cy = scale(c[x], vmin, vmax, rows)

        # wick: vertical line from low to high
        for y in range(ly, hy+1):
            grid[rows-1-y][x] = "│"  # invert y for printing (row 0 is top)

        # body: between open and close
        y1, y2 = sorted((oy, cy))
        for y in range(y1, y2+1):
            grid[rows-1-y][x] = "█"

    # Overlays: draw MA and HH lines as dots if those cells are empty
    if len(c) >= ma or len(h) >= breakout:
        for x in range(len(o)):
            # MA
            if len(c) >= ma and x >= ma - 1:
                start = x - ma + 1
                window = c[start:x+1]
                ma_val = sum(window) / len(window)
                y = scale(ma_val, vmin, vmax, rows)
                ry = rows - 1 - y
                if 0 <= ry < rows and grid[ry][x] == " ":
                    grid[ry][x] = "."
            # HH
            if len(h) >= breakout and x >= breakout - 1:
                start = x - breakout + 1
                hh = max(h[start:x+1])
                y = scale(hh, vmin, vmax, rows)
                ry = rows - 1 - y
                if 0 <= ry < rows and grid[ry][x] == " ":
                    grid[ry][x] = "·"


    # Prepare header
    last_close = c[-1]
    change = (last_close - c[0]) / c[0] * 100 if c[0] else 0.0
    header = f"{symbol} {timeframe}  last={last_close:.2f}  Δ={change:+.2f}%  range=[{vmin:.2f} .. {vmax:.2f}]"
    if HAS_COLOR:
        header_col = colorize(header, GREEN if last_close >= o[-1] else RED)
    else:
        header_col = header

    # Clear screen
    cols_term = shutil.get_terminal_size((120, rows+4)).columns
    print("\033[H\033[J", end="")  # ANSI clear
    print(BOLD + header_col + RESET)
    # Print grid with colors for up/down candles
    for y in range(rows):
        line = []
        for x in range(len(o)):
            ch = grid[y][x]
            if ch == "█":
                col = GREEN if c[x] >= o[x] else RED
                line.append(colorize("█", col))
            elif ch == "│":
                col = GREEN if c[x] >= o[x] else RED
                line.append(colorize("│", col))
            else:
                line.append(" ")
        print("".join(line))

    # Footer labels
    left = ts_str(t[0]); right = ts_str(t[-1])
    label_line = f"{DIM}{left}{RESET}".ljust(cols_term - len(right)) + f"{DIM}{right}{RESET}"
    print(label_line)

def ts_str(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")

async def main_async(symbol: str, timeframe: str, limit: int, height: int, cols: int, ma:int, breakout:int):
    url = f"wss://stream.binance.com:9443/ws/{to_stream_symbol(symbol)}@kline_{timeframe}"
    buf = KlineBuf(limit=max(limit, cols))

    async def consume():
        async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
            async for msg in ws:
                data = json.loads(msg)
                k = data.get("k", {})
                if not k:
                    k = data.get("data", {}).get("k", {})
                if not k:
                    continue
                o = float(k["o"]); h = float(k["h"]); l = float(k["l"]); c = float(k["c"])
                closed = bool(k["x"])
                t_close = int(k["T"])
                buf.upsert_live(o, h, l, c, t_close, closed)
                render(symbol, timeframe, buf, height=height, cols=cols, ma=ma, breakout=breakout)

    while True:
        try:
            await consume()
        except (asyncio.CancelledError, KeyboardInterrupt):
            break
        except Exception:
            await asyncio.sleep(2.0)

def cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--timeframe", default="1m")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--overlay_ma20", action="store_true")
    ap.add_argument("--overlay_hh20", action="store_true")
    ap.add_argument("--lookback", type=int, default=20)
    ap.add_argument("--ma", type=int, default=20)
    ap.add_argument("--breakout", type=int, default=20)
    ap.add_argument("--height", type=int, default=24)
    ap.add_argument("--cols", type=int, default=100)
    args = ap.parse_args()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    task = loop.create_task(main_async(args.symbol, args.timeframe, args.limit, args.height, args.cols, args.ma, args.breakout))

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
    cli()
