# -*- coding: utf-8 -*-
"""
Affichage terminal des bougies (snapshot) avec plotext (ASCII).
- Si plotext manque, on affiche un fallback simple et on suggère l'installation.
Usage:
    python terminal_candles.py --symbol BTC/USDT --timeframe 1h --limit 120
"""
import argparse
import importlib
import ccxt
import pandas as pd

def fetch_df(exchange_id: str, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    ex = getattr(ccxt, exchange_id)({"enableRateLimit": True})
    ohlcv = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","volume"])
    return df

def show_candles(df):
    try:
        plx = importlib.import_module("plotext")
        o = df["open"].tolist(); h = df["high"].tolist(); l = df["low"].tolist(); c = df["close"].tolist()
        plx.clear_figure()
        plx.candlestick(data={"Open": o, "High": h, "Low": l, "Close": c})  # plotext colore généralement up/down
        plx.title("Candles (snapshot)")
        plx.show()
    except ModuleNotFoundError:
        closes = df["close"].tolist()
        mn, mx = min(closes), max(closes)
        print("(fallback) plotext non installé. Installe-le:  pip install plotext")
        print(f"Close min={mn:.2f} max={mx:.2f}")
        width = 60
        for v in closes[-60:]:
            pos = int((v - mn) / (mx - mn + 1e-9) * (width - 1))
            print(" " * pos + "*")
    except Exception as e:
        print("Erreur d'affichage:", e)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exchange", default="binance")
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--limit", type=int, default=120)
    args = ap.parse_args()
    df = fetch_df(args.exchange, args.symbol, args.timeframe, args.limit)
    show_candles(df)

if __name__ == "__main__":
    main()
