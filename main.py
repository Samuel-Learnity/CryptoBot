#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Crypto Stop-Loss Bot — Démo pédagogique (corrigé)
Stratégie : Breakout(20) + Stop (LL10 ou ATR) + TP partiel à 1R + Trailing

⚠️ Éducation uniquement. Lance d'abord en dry_run.
"""

import os
import time
import math
import json
import csv
import signal
import shutil
import sys
import datetime as dt
from datetime import timezone
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

import ccxt
import pandas as pd
import numpy as np
from dotenv import load_dotenv
import yaml
from rich.console import Console
from rich.table import Table
from rich import box

# === AJOUTS: logging & asyncio helpers ===
import logging
import asyncio
import inspect
from concurrent.futures import TimeoutError as FuturesTimeout

# WS (optionnel, gratuit via API Binance)
try:
    from ws_binance import BinanceWS, StreamConfig
except Exception:
    BinanceWS = None
    StreamConfig = None

console = Console()


def now_utc() -> dt.datetime:
    return dt.datetime.now(timezone.utc)


def today_utc_date() -> dt.date:
    return now_utc().date()


def _setup_file_logger(name: str = "bot", log_dir: str = "logs") -> logging.Logger:
    """Crée un logger fichier avec timestamps."""
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fname = os.path.join(log_dir, f"bot-events-{now_utc().strftime('%Y%m%d')}.log")
    fh = logging.FileHandler(fname, encoding="utf-8")
    fmt = logging.Formatter(fmt="%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


@dataclass
class Config:
    exchange: str = "binance"
    sandbox: bool = False
    dry_run: bool = True
    symbols: List[str] = field(default_factory=lambda: ["BTC/USDT"])
    timeframe: str = "1h"
    risk_per_trade_pct: float = 1.0
    breakout_lookback: int = 20
    stop_lookback: int = 10
    use_atr_stop: bool = False
    atr_mult: float = 2.0
    max_spread_pct: float = 0.5
    take_profit_R: float = 1.0
    tp_fraction: float = 0.5
    trailing_use_atr: bool = True
    kill_switch_daily_dd_pct: float = -3.0
    poll_seconds: int = 60
    journal_csv: str = "trades.csv"
    fiat: str = "USDT"
    use_websocket: bool = True
    ws_reconnect_sec: float = 3.0
    sound_alerts: bool = True
    dashboard_clear: bool = True   # AJOUT: permet de ne pas effacer le terminal si False

    @staticmethod
    def from_yaml(path: str) -> "Config":
        cfg = Config()
        if not os.path.exists(path):
            console.print(f"[yellow]Config '{path}' non trouvé, usage des valeurs par défaut.[/yellow]")
            return cfg
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        # Fusionne uniquement les clés connues
        for k, v in raw.items():
            if k == "symbols" and isinstance(v, str):
                v = [v]
            if hasattr(cfg, k):
                setattr(cfg, k, v)
            else:
                console.print(f"[yellow]Clé inconnue dans config: '{k}' — ignorée.[/yellow]")
        return cfg


@dataclass
class Position:
    symbol: str
    entry_price: float
    qty: float
    stop_price: float
    r_value: float
    tp1_price: float
    tp_fraction: float
    remaining_qty: float
    side: str = "long"
    opened_at: dt.datetime = field(default_factory=now_utc)
    realized_pnl: float = 0.0
    closed: bool = False
    closed_at: Optional[dt.datetime] = None


class StopLossBot:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._levels = {}  # {symbol: {"hh": float, "ll": float, "asof": pd.Timestamp}}
        self.exchange = self._init_exchange(cfg)
        self.markets = self.exchange.load_markets()
        # Préflight des symbols (et correction USUT -> USDT si besoin)
        for s in list(self.cfg.symbols):
            if s not in self.markets:
                fixed = s.replace("USUT", "USDT")
                if fixed in self.markets:
                    console.print(f"[yellow]Symbole '{s}' introuvable. Correction automatique -> '{fixed}'.[/yellow]")
                    self.cfg.symbols[self.cfg.symbols.index(s)] = fixed
                else:
                    examples = [m for m in self.markets.keys() if m.endswith(f"/{self.cfg.fiat}")][:10]
                    raise ValueError(f"Symbole '{s}' indisponible sur {self.exchange.id}. Exemples valides: {examples}")
        self.position: Optional[Position] = None
        self.equity: float = 10_000.0
        self.daily_start_equity: float = self.equity
        self.daily_date: dt.date = today_utc_date()
        self.journal_path = cfg.journal_csv
        self._init_journal()

        # Logger fichiers
        self.log = _setup_file_logger()

        # WS helpers
        self._ws = None
        self._last_ticker: Dict[str, float] = {}
        self._last_closed_ts: Dict[str, int] = {}

        console.print(f"[cyan]Exchange:[/cyan] {self.exchange.id} | [cyan]Dry run:[/cyan] {self.cfg.dry_run}")
        self.log.info("BOOT exchange=%s dry_run=%s symbols=%s timeframe=%s",
                      self.exchange.id, self.cfg.dry_run, self.cfg.symbols, self.cfg.timeframe)

        # WebSocket: démarrage si activé et exchange=binance
        if self.cfg.use_websocket and self.exchange.id == "binance" and BinanceWS and StreamConfig:
            def on_kline_closed(sym, payload):
                k = payload["k"]
                self._last_closed_ts[sym] = int(k["T"])  # close time ms

            def on_ticker(sym, payload):
                try:
                    self._last_ticker[sym] = float(payload.get("c") or payload.get("C") or 0.0)
                except Exception:
                    pass

            sc = StreamConfig(
                symbols=self.cfg.symbols,
                timeframe=self.cfg.timeframe,
                on_kline_closed=on_kline_closed,
                on_ticker=on_ticker,
                reconnect_delay=self.cfg.ws_reconnect_sec,
            )
            try:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                self._ws = BinanceWS(sc)
                self._ws.start(loop)
                console.print("[green]WebSocket Binance démarré (gratuit, market data).[/green]")
                self.log.info("WS started (binance)")
            except Exception as e:
                console.print(f"[yellow]WebSocket non démarré: {e}. Fallback polling.[/yellow]")
                self.log.warning("WS not started: %s", e)

    def _compute_levels_from_df(self, df: pd.DataFrame) -> dict:
        """Calcule HH/LL sur la base du DF passé (pas d'appel réseau ici)."""
        Lh = self.cfg.breakout_lookback
        Ll = self.cfg.stop_lookback
        if len(df) < max(Lh, Ll) + 2:
            return {}
        hh = float(df["high"].iloc[-(Lh + 1):-1].max())
        ll = float(df["low"].iloc[-(Ll + 1):-1].min())
        return {"hh": hh, "ll": ll, "asof": df["ts"].iloc[-1]}

    def _cache_levels(self, symbol: str, df: pd.DataFrame) -> None:
        lv = self._compute_levels_from_df(df)
        if lv:
            self._levels[symbol] = lv

    # ---------------- Sound Alerts ----------------
    def _ding(self, kind: str = "info"):
        """Play a short sound (macOS 'afplay' if available) or terminal bell."""
        if not getattr(self.cfg, "sound_alerts", True):
            return
        try:
            if sys.platform == "darwin" and shutil.which("afplay"):
                sounds = {
                    "enter": "/System/Library/Sounds/Glass.aiff",
                    "tp": "/System/Library/Sounds/Ping.aiff",
                    "stop": "/System/Library/Sounds/Basso.aiff",
                    "kill": "/System/Library/Sounds/Sosumi.aiff",
                    "info": "/System/Library/Sounds/Pop.aiff",
                }
                path = sounds.get(kind, sounds["info"])
                if os.path.exists(path):
                    import subprocess
                    subprocess.Popen(["afplay", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return
            print("\a", end="", flush=True)  # terminal bell fallback
        except Exception:
            try:
                print("\a", end="", flush=True)
            except Exception:
                pass

    # ---------------- Setup helpers ----------------
    def _init_exchange(self, cfg: Config):
        load_dotenv()
        ex_id = cfg.exchange.lower()
        if ex_id == "binance":
            api_key = os.getenv("BINANCE_API_KEY") or ""
            secret = os.getenv("BINANCE_API_SECRET") or ""
            exchange = ccxt.binance({
                "apiKey": api_key,
                "secret": secret,
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            })
            if cfg.sandbox:
                exchange.set_sandbox_mode(True)
        elif ex_id == "kraken":
            api_key = os.getenv("KRAKEN_API_KEY") or ""
            secret = os.getenv("KRAKEN_API_SECRET") or ""
            exchange = ccxt.kraken({
                "apiKey": api_key,
                "secret": secret,
                "enableRateLimit": True,
            })
        else:
            raise ValueError(f"Exchange non supporté: {ex_id}")
        return exchange

    def _init_journal(self):
        os.makedirs(os.path.dirname(self.journal_path) or ".", exist_ok=True)
        if not os.path.exists(self.journal_path):
            with open(self.journal_path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["ts", "symbol", "action", "price", "qty", "realized_pnl", "equity", "note"])

    def _log_trade(self, action: str, symbol: str, price: float, qty: float, pnl: float, note: str = ""):
        with open(self.journal_path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([now_utc().isoformat(), symbol, action, f"{price:.8f}", f"{qty:.8f}", f"{pnl:.2f}", f"{self.equity:.2f}", note])
        # AJOUT: log lisible avec timestamp
        self.log.info("TRADE action=%s symbol=%s price=%.4f qty=%.8f pnl=%.2f equity=%.2f note=%s",
                      action, symbol, price, qty, pnl, self.equity, note)

    # ---------------- Market helpers ----------------
    def _fetch_ohlcv_df(self, symbol: str, limit: int = 200) -> pd.DataFrame:
        ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe=self.cfg.timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
        return df

    def _atr(self, df: pd.DataFrame, n: int = 14) -> pd.Series:
        prev_close = df["close"].shift(1)
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs()
        ], axis=1).max(axis=1)
        return tr.ewm(alpha=1.0 / n, adjust=False).mean()

    def _orderbook_spread_pct(self, symbol: str) -> float:
        ob = self.exchange.fetch_order_book(symbol, limit=5)
        best_bid = ob["bids"][0][0] if ob["bids"] else None
        best_ask = ob["asks"][0][0] if ob["asks"] else None
        if best_bid is None or best_ask is None:
            return 999.0
        mid = (best_bid + best_ask) / 2.0
        return (best_ask - best_bid) / mid * 100.0

    def _get_market_info(self, symbol: str) -> Dict[str, Any]:
        m = self.markets[symbol]
        return {
            "min_cost": (m.get("limits", {}).get("cost", {}) or {}).get("min"),
            "min_amount": (m.get("limits", {}).get("amount", {}) or {}).get("min"),
            "amount_step": (m.get("precision", {}) or {}).get("amount"),
            "price_step": (m.get("precision", {}) or {}).get("price"),
        }

    def _round_amount(self, symbol: str, amount: float) -> float:
        m = self.markets[symbol]
        precision = m["precision"]["amount"]
        step = 10 ** (-precision) if isinstance(precision, int) else None
        if step:
            return math.floor(amount / step) * step
        return float(f"{amount:.8f}")

    # ---------------- Sizing ----------------
    def _position_size(self, entry: float, stop: float) -> float:
        risk_quote = self.equity * (self.cfg.risk_per_trade_pct / 100.0)
        stop_dist_pct = abs(entry - stop) / entry
        if stop_dist_pct <= 0:
            return 0.0
        notional = risk_quote / stop_dist_pct
        return notional / entry

    # ---------------- Signal ----------------
    def _compute_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        if len(df) < max(self.cfg.breakout_lookback, self.cfg.stop_lookback) + 5:
            return {"entry_ok": False}
        close = df["close"].iloc[-1]
        high_n = df["high"].iloc[-(self.cfg.breakout_lookback + 1):-1].max()
        entry_ok = close > high_n
        if self.cfg.use_atr_stop:
            atr = self._atr(df, 14).iloc[-1]
            stop = close - self.cfg.atr_mult * atr
        else:
            stop = df["low"].iloc[-(self.cfg.stop_lookback + 1):-1].min()
        r_value = close - stop
        tp1 = close + self.cfg.take_profit_R * r_value
        return {"entry_ok": bool(entry_ok), "entry_price": float(close), "stop_price": float(stop), "r_value": float(r_value), "tp1_price": float(tp1)}

    # ---------------- Execution ----------------
    def _enter_position(self, symbol: str, entry: float, stop: float, tp1: float) -> Optional[Position]:
        spread_pct = self._orderbook_spread_pct(symbol)
        if spread_pct > self.cfg.max_spread_pct:
            console.print(f"[yellow]Spread {spread_pct:.2f}% > max {self.cfg.max_spread_pct:.2f}% : pas d'entrée.[/yellow]")
            self.log.info("ENTRY_BLOCKED spread=%.3f%% max=%.3f%% symbol=%s", spread_pct, self.cfg.max_spread_pct, symbol)
            return None
        qty = self._position_size(entry, stop)
        qty = self._round_amount(symbol, qty)
        if qty <= 0:
            console.print("[red]Taille calculée nulle. Vérifie le capital, le risque ou le stop.[/red]")
            self.log.warning("SIZE_ZERO symbol=%s entry=%.4f stop=%.4f", symbol, entry, stop)
            return None
        m = self._get_market_info(symbol)
        min_cost = m["min_cost"]
        if min_cost:
            notional = qty * entry
            if notional < min_cost:
                console.print(f"[yellow]Notional {notional:.2f} < min_cost {min_cost:.2f}. Ajuste le risque ou choisis un autre symbole.[/yellow]")
                self.log.info("ENTRY_BLOCKED min_cost notional=%.2f min_cost=%.2f", notional, min_cost)
                return None
        pos = Position(symbol=symbol, entry_price=entry, qty=qty, stop_price=stop, r_value=entry - stop, tp1_price=tp1, tp_fraction=self.cfg.tp_fraction, remaining_qty=qty)
        if self.cfg.dry_run:
            self.position = pos
            self._log_trade("ENTER_SIM", symbol, entry, qty, 0.0, note="breakout entry")
            console.print(f"[green]DRY RUN:[/green] Entrée {symbol} qty={qty} @ {entry:.2f} | stop={stop:.2f} | tp1={tp1:.2f}")
            self._ding("enter")
            return pos
        try:
            order = self.exchange.create_order(symbol, "market", "buy", qty, None, {})
            fill_price = order["average"] or entry
            pos.entry_price = float(fill_price)
            self.position = pos
            self._log_trade("ENTER_LIVE", symbol, pos.entry_price, qty, 0.0, note="live entry")
            console.print(f"[green]LIVE:[/green] Entrée {symbol} qty={qty} @ {pos.entry_price:.2f} | stop={stop:.2f} | tp1={tp1:.2f}")
            self._ding("enter")
            return pos
        except Exception as e:
            console.print(f"[red]Erreur d'exécution live: {e}[/red]")
            self.log.error("ENTER_ERROR %s", e)
            return None

    def _exit_market(self, reason: str, price: float):
        if not self.position:
            return
        pos = self.position
        qty = pos.remaining_qty
        if qty <= 0:
            return
        if self.cfg.dry_run:
            if reason and "STOP" in reason:
                self._ding("stop")
            else:
                self._ding("info")
            pnl = (price - pos.entry_price) * qty
            self.equity += pnl
            pos.realized_pnl += pnl
            pos.remaining_qty = 0.0
            pos.closed = True
            pos.closed_at = now_utc()
            self._log_trade(f"EXIT_SIM_{reason}", pos.symbol, price, qty, pnl, note=reason)
            console.print(f"[cyan]DRY RUN:[/cyan] Sortie {reason} qty={qty} @ {price:.2f} | PnL={pnl:.2f} | Equity={self.equity:.2f}")
            self.position = None
            return
        try:
            order = self.exchange.create_order(pos.symbol, "market", "sell", qty, None, {})
            fill_price = order["average"] or price
            pnl = (fill_price - pos.entry_price) * qty
            self.equity += pnl
            pos.realized_pnl += pnl
            pos.remaining_qty = 0.0
            pos.closed = True
            pos.closed_at = now_utc()
            self._log_trade(f"EXIT_LIVE_{reason}", pos.symbol, float(fill_price), qty, pnl, note=reason)
            console.print(f"[cyan]LIVE:[/cyan] Sortie {reason} qty={qty} @ {fill_price:.2f} | PnL={pnl:.2f} | Equity={self.equity:.2f}")
            self.position = None
        except Exception as e:
            console.print(f"[red]Erreur de sortie live: {e}[/red]")
            self.log.error("EXIT_ERROR %s", e)

    def _partial_take_profit(self, price: float):
        if not self.position:
            return
        pos = self.position
        qty_tp = pos.remaining_qty * pos.tp_fraction
        qty_tp = max(0.0, min(qty_tp, pos.remaining_qty))
        if qty_tp <= 0:
            return
        if self.cfg.dry_run:
            self._ding("tp")
            pnl = (price - pos.entry_price) * qty_tp
            self.equity += pnl
            pos.realized_pnl += pnl
            pos.remaining_qty -= qty_tp
            pos.stop_price = max(pos.stop_price, pos.entry_price)
            self._log_trade("TP1_SIM", pos.symbol, price, qty_tp, pnl, note="take partial & move stop to BE")
            console.print(f"[magenta]DRY RUN:[/magenta] TP partiel qty={qty_tp} @ {price:.2f} | Stop => {pos.stop_price:.2f}")
            return
        try:
            order = self.exchange.create_order(pos.symbol, "market", "sell", qty_tp, None, {})
            fill_price = order["average"] or price
            pnl = (fill_price - pos.entry_price) * qty_tp
            self.equity += pnl
            pos.realized_pnl += pnl
            pos.remaining_qty -= qty_tp
            pos.stop_price = max(pos.stop_price, pos.entry_price)
            self._log_trade("TP1_LIVE", pos.symbol, float(fill_price), qty_tp, pnl, note="take partial & move stop to BE")
            console.print(f"[magenta]LIVE:[/magenta] TP partiel qty={qty_tp} @ {fill_price:.2f} | Stop => {pos.stop_price:.2f}")
        except Exception as e:
            console.print(f"[red]Erreur TP1 live: {e}[/red]")
            self.log.error("TP1_ERROR %s", e)

    # ---------------- Risk throttles ----------------
    def _reset_daily_if_needed(self):
        d = today_utc_date()
        if d != self.daily_date:
            self.daily_date = d
            self.daily_start_equity = self.equity

    def _daily_pnl_pct(self) -> float:
        return (self.equity - self.daily_start_equity) / self.daily_start_equity * 100.0

    def _kill_switch_tripped(self) -> bool:
        return self._daily_pnl_pct() <= self.cfg.kill_switch_daily_dd_pct

    # ---------------- Main loop ----------------
    def run(self):
        console.rule("[bold green]Stop-Loss Bot — Démarrage")
        last_checked_candle = {s: None for s in self.cfg.symbols}
        try:
            while True:  # loop; SIGTERM/KeyboardInterrupt will break
                self._reset_daily_if_needed()
                if self._kill_switch_tripped():
                    self._ding("kill")
                    console.print(f"[red]Kill switch: PnL journalier {self._daily_pnl_pct():.2f}% <= {self.cfg.kill_switch_daily_dd_pct:.2f}% — pause jusqu'au lendemain.[/red]")
                    self.log.warning("KILL_SWITCH daily_pnl=%.2f%% threshold=%.2f%%", self._daily_pnl_pct(), self.cfg.kill_switch_daily_dd_pct)
                    time.sleep(self.cfg.poll_seconds)
                    continue

                if self.position:
                    symbol = self.position.symbol
                    ticker = self.exchange.fetch_ticker(symbol)
                    last_price = ticker.get("last") or ticker.get("close") or ticker.get("bid") or ticker.get("ask")
                    if last_price is None:
                        time.sleep(self.cfg.poll_seconds)
                        continue
                    if self.position.remaining_qty > 0 and last_price >= self.position.tp1_price and self.position.tp_fraction > 0:
                        self._partial_take_profit(last_price)
                    if self.cfg.trailing_use_atr:
                        df = self._fetch_ohlcv_df(symbol, limit=100)
                        atr = self._atr(df, 14).iloc[-1]
                        trail = df["high"].iloc[-1] - self.cfg.atr_mult * atr
                        if trail > self.position.stop_price:
                            self.position.stop_price = trail
                        self._cache_levels(symbol, df)
                    if last_price <= self.position.stop_price:
                        self._exit_market("STOP", last_price)
                else:
                    for symbol in self.cfg.symbols:
                        df = self._fetch_ohlcv_df(symbol, limit=200)
                        self._cache_levels(symbol, df)
                        last_ts = df["ts"].iloc[-1]
                        if last_checked_candle[symbol] is None or last_ts > last_checked_candle[symbol]:
                            last_checked_candle[symbol] = last_ts
                            sig = self._compute_signal(df)
                            if sig.get("entry_ok"):
                                if self._enter_position(symbol, sig["entry_price"], sig["stop_price"], sig["tp1_price"]):
                                    break

                self._render_status()
                # Log périodique d'état (lisible) :
                try:
                    sym0 = self.cfg.symbols[0]
                    self.log.info("STATUS ex=%s dry=%s eq=%.2f daily=%.2f%% pos=%s",
                                  self.exchange.id, self.cfg.dry_run, self.equity, self._daily_pnl_pct(),
                                  (self.position.symbol if self.position else "None"))
                except Exception:
                    pass

                time.sleep(self.cfg.poll_seconds)
        except KeyboardInterrupt:
            console.print("[yellow]Arrêt demandé par l'utilisateur.[/yellow]")
            self.log.info("USER_INTERRUPT")

    def _current_hh_level(self, symbol: str) -> float:
        L = self.cfg.breakout_lookback
        df = self._fetch_ohlcv_df(symbol, limit=L + 2)
        return float(df["high"].iloc[-(L + 1):-1].max())

    def _current_ll_level(self, symbol: str) -> float:
        L = self.cfg.stop_lookback
        df = self._fetch_ohlcv_df(symbol, limit=L + 2)
        return float(df["low"].iloc[-(L + 1):-1].min())

    # ---------------- Status UI ----------------
    def _render_status(self):
        table = Table(title="État du bot", box=box.MINIMAL_DOUBLE_HEAD)
        table.add_column("Clé", style="cyan", no_wrap=True)
        table.add_column("Valeur", style="white")

        table.add_row("Exchange", self.exchange.id)
        table.add_row("Dry run", str(self.cfg.dry_run))
        table.add_row("Equity", f"{self.equity:.2f}")
        table.add_row("PnL journalier", f"{self._daily_pnl_pct():.2f}%")

        # Afficher prix/spread du 1er symbole
        try:
            sym0 = self.cfg.symbols[0]
            last = self._last_ticker.get(sym0) if hasattr(self, "_last_ticker") else None
            if last is None:
                t = self.exchange.fetch_ticker(sym0)
                last = t.get("last") or t.get("close") or t.get("bid") or t.get("ask")
            spread_pct = self._orderbook_spread_pct(sym0)
            table.add_row(f"Prix ({sym0})", f"{(last or 0):.4f}")
            table.add_row("Spread", f"{spread_pct:.3f}%")
            try:
                lv = getattr(self, "_levels", {}).get(sym0)
                if lv:
                    table.add_row(f"HH{self.cfg.breakout_lookback} ({sym0})",
                                  f"{lv['hh']:.4f}  (close > ceci ⇒ entrée)")
                    table.add_row(f"LL{self.cfg.stop_lookback} ({sym0})",
                                  f"{lv['ll']:.4f}  (stop initial ≈ ceci)")
                else:
                    table.add_row("HH/LL", "n/c — en attente d’un premier calcul")
            except Exception:
                pass
        except Exception:
            pass

        if self.position:
            table.add_row("Position", json.dumps({
                "symbol": self.position.symbol,
                "entry": round(self.position.entry_price, 2),
                "stop": round(self.position.stop_price, 2),
                "tp1": round(self.position.tp1_price, 2),
                "qty": round(self.position.remaining_qty, 8),
            }))
        else:
            table.add_row("Position", "Aucune")

        # Ne pas écraser le terminal si dashboard_clear=False
        if self.cfg.dashboard_clear:
            console.clear()
        console.print(table)

    def close(self):
        """Nettoyage doux: arrêter le WS, flush, etc."""
        try:
            ws = getattr(self, "_ws", None)
            if ws:
                stop = getattr(ws, "stop", None)
                if stop:
                    try:
                        res = stop()
                        if inspect.isawaitable(res):
                            # Si le WS expose sa loop, tente d'arrêter dessus
                            loop = getattr(ws, "loop", None)
                            if loop and loop.is_running():
                                fut = asyncio.run_coroutine_threadsafe(res, loop)
                                try:
                                    fut.result(timeout=2.0)
                                except FuturesTimeout:
                                    pass
                            else:
                                try:
                                    asyncio.run(res)
                                except RuntimeError:
                                    # Si une loop est déjà active dans ce thread
                                    new_loop = asyncio.new_event_loop()
                                    new_loop.run_until_complete(res)
                                    new_loop.close()
                    except Exception:
                        pass
        except Exception:
            pass
        try:
            # CCXT ne nécessite pas de close explicite
            _ = getattr(self, "exchange", None)
        except Exception:
            pass


def main():
    cfg = Config.from_yaml("config.yaml")
    bot = StopLossBot(cfg)

    pid = os.getpid()
    print(f"[BOOT] PID={pid}")

    def _graceful_exit(signum, frame):
        # Laisser remonter SystemExit pour casser les boucles de run()
        raise SystemExit(0)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _graceful_exit)
        except Exception:
            pass

    try:
        bot.run()
    except SystemExit:
        pass
    finally:
        try:
            bot.close()
        finally:
            print(f"[SHUTDOWN] PID={pid}")


if __name__ == "__main__":
    main()
