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
