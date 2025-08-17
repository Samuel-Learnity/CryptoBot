Voici un **README.md** complet, en **Markdown**, prêt à coller à la racine de ton projet 👇

---

# Crypto Stop-Loss Bot — Démo pédagogique (fix + overlays + Makefile)

Bot pédagogique de suivi de tendance : **breakout HH**, **stop LL/ATR**, **TP partiel**, **trailing**, **kill switch**.
Affichage terminal : **plotext** (bougies couleur + overlays) et **ASCII** (ultra-robuste).

> ⚠️ Usage éducatif. Lance en `dry_run: true` avant toute chose.

---

## ✨ Points clés

- **Préflight symboles** : corrige `USUT → USDT`, erreur claire si symbole indisponible.
- **WebSocket gratuit (Binance)** : scan **à la clôture** des bougies.
- **Affichages** :

     - `terminal_candles_stream.py` (plotext, couleurs, overlays MA/HH)
     - `terminal_candles_stream_ascii.py` (ASCII pur, zéro dépendance graphique)
     - `terminal_candles.py` (snapshot)

- **Makefile** simple : lance **bot**, **viewer**, **les deux**, **logs**, **stop**.
- **Alertes sonores** : entrée / TP / stop / kill switch (macOS : `afplay`).

---

## 🚀 Installation rapide

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config.example.yaml config.yaml   # ajuste tes paramètres
```

---

## ⚙️ Configuration (extrait & schéma)

`config.yaml` (clés reconnues) :

```yaml
exchange: binance # binance | kraken
sandbox: false # true => sandbox exchange si dispo
dry_run: true
symbols: ["BTC/USDT"] # ou "BTC/USDT"
timeframe: "1h"
risk_per_trade_pct: 1.0
breakout_lookback: 20
stop_lookback: 10
use_atr_stop: false
atr_mult: 2.0
max_spread_pct: 0.5
take_profit_R: 1.0
tp_fraction: 0.5
trailing_use_atr: true
kill_switch_daily_dd_pct: -3.0
poll_seconds: 60
journal_csv: "trades.csv"
fiat: "USDT"
use_websocket: true
ws_reconnect_sec: 3.0
sound_alerts: true
```

> Les autres clés (ex: `market_data:`) sont **ignorées** pour éviter les crashs.

---

## 🌐 WebSocket gratuit (Binance)

- Active `use_websocket: true` (par défaut).
- Aucun coût : flux public via `websockets`.
- Le bot rescannera **dès la clôture** (`k.x == true`) → entrées plus réactives.

---

## 📈 Affichages bougies (scripts)

### Snapshot (un coup, puis stop)

```bash
python terminal_candles.py --symbol BTC/USDT --timeframe 1h --limit 120
```

- Utilise `plotext` si dispo (candlestick couleur). Sinon fallback simplifié.

### Streaming **plotext** (bougies couleur + overlays)

```bash
python terminal_candles_stream.py --symbol BTC/USDT --timeframe 1m --limit 120
# Overlays (SMA20 + HH lookback identique au bot)
python terminal_candles_stream.py --symbol BTC/USDT --timeframe 1h --limit 120 --overlay_ma20 --overlay_hh20 --lookback 20
```

### Streaming **ASCII** (sans dépendances graphiques)

```bash
python terminal_candles_stream_ascii.py --symbol BTC/USDT --timeframe 1m --limit 200 --height 24 --cols 100
```

**Overlays (plotext uniquement)**

- `--overlay_ma20` : SMA 20
- `--overlay_hh20 --lookback N` : plus haut des `N` dernières bougies (ligne de breakout)

> Pour coller au bot, mets le même `lookback` que `breakout_lookback` (ex. 20).

---

## 🧰 Makefile (sync avec `config.yaml`)

Le **bot** lit **uniquement** `config.yaml`.
Le **viewer**, par défaut, **lit aussi** `symbol` et `timeframe` dans `config.yaml`.
Tu peux **forcer** un autre symbole/timeframe **uniquement pour le viewer** via `SYMBOL=` / `TIMEFRAME=`.

### Pré-requis Makefile

Crée le petit helper (si absent) :

```bash
mkdir -p scripts
```

```python
# scripts/read_cfg.py
import sys, yaml
with open("config.yaml", "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f) or {}
arg = sys.argv[1] if len(sys.argv) > 1 else "symbol"
if arg == "symbol":
    s = cfg.get("symbols", ["BTC/USDT"])
    print(s[0] if isinstance(s, list) else s)
elif arg == "timeframe":
    print(cfg.get("timeframe", "1h"))
else:
    raise SystemExit(f"unknown arg: {arg}")
```

### Cibles principales

```bash
make venv                # crée .venv et installe les deps
make bot                 # lance le bot (lit config.yaml)
make viewer              # lance le viewer (par défaut: ASCII, sync YAML)
make both                # bot + viewer en arrière-plan, logs dans ./logs
make tail-bot            # suit les logs du bot
make tail-viewer         # suit les logs du viewer
make stop                # stoppe les 2 processus lancés par 'make both'
```

### Choisir le viewer

```bash
make viewer VIEWER=ascii
make viewer VIEWER=plotext
```

### Activer les overlays (plotext)

```bash
make viewer VIEWER=plotext OVERLAY=1 LOOKBACK=20
# équivaut à: --overlay_ma20 --overlay_hh20 --lookback 20
```

### Forcer symbole/TF **uniquement** pour le viewer

```bash
make viewer VIEWER=plotext SYMBOL=ETH/USDT TIMEFRAME=1m OVERLAY=1
```

### Lancer en arrière-plan (logs)

```bash
make both                         # viewer plotext par défaut
make both VIEWER=ascii OVERLAY=1 LOOKBACK=20
make tail-bot
make tail-viewer
make stop
```

### Géométrie du viewer ASCII

```bash
make viewer VIEWER=ascii ASCII_FLAGS="--limit 300 --height 28 --cols 120"
```

> Rappels :
>
> - `--height` / `--cols` → **ASCII seulement**
> - `--overlay_*` / `--lookback` → **plotext seulement**

---

## 🔔 Alertes sonores (bot)

- Active/désactive via `sound_alerts: true|false` dans `config.yaml`.
- **macOS** : joue un son natif via `afplay` (Glass=enter, Ping=TP, Basso=STOP, Sosumi=kill switch).
- Autres OS : cloche terminal (`\a`) en fallback.
- Déclenchées sur : **ENTER**, **TP**, **STOP**, **Kill switch**.

---

## 🎓 Mode “démo” (entrées rapides en dry-run)

Pour observer une entrée rapidement (alt volatile + lookbacks courts) :

```yaml
exchange: binance
dry_run: true
symbols: ["WIF/USDT", "PYTH/USDT", "JUP/USDT"]
timeframe: "5m" # 1m pour encore plus d’action
breakout_lookback: 5
stop_lookback: 3
use_atr_stop: false
max_spread_pct: 0.7
risk_per_trade_pct: 0.5
take_profit_R: 1.0
tp_fraction: 0.5
trailing_use_atr: true
kill_switch_daily_dd_pct: -5.0
use_websocket: true
sound_alerts: true
```

Viewer plotext pour valider visuellement :

```bash
make viewer VIEWER=plotext OVERLAY=1 LOOKBACK=5
```

---

## 🛠️ Troubleshooting

- **`unrecognized arguments: --height --cols`**
  → Tu as passé des flags ASCII au viewer plotext. Utilise `VIEWER=ascii` **ou** enlève ces flags.

- **plotext plante / rien ne s’affiche**
  → Utilise le viewer **ASCII** (ultra robuste) :

     ```bash
     make viewer VIEWER=ascii
     ```

- **Rien ne se passe tout de suite**
  → Le bot n’entre qu’à la **clôture** d’une bougie qui casse **HH** (ex. HH20).
  Affiche le viewer plotext en `1h` avec `OVERLAY=1` pour **voir** la ligne HH et attendre la clôture au-dessus.

---

## ⚖️ Avertissement

Projet éducatif. **Aucune garantie**. Le trading comporte des **risques de perte**.
Toujours tester en **dry run** et garder un **risque par trade ≤ 1%**.
