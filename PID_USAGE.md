# Multi-instance PID workflow

## Lancer plusieurs bots

    make run-bot ARGS="--any-args"

Chaque lancement affiche:
Started bot PID=<PID>
Log: logs/bot-<PID>.log

## Lister

    make list-bots

## Tails (voir un bot précis)

    make tail-bot PID=<PID>

## Kill un PID spécifique

    make kill-bot PID=<PID>

## Kill tous les bots (basé sur les pidfiles)

    make kill-all-bots

Astuce: Le Makefile crée:

- run/bot-<PID>.pid
- logs/bot-<timestamp>.log + symlink logs/bot-<PID>.log

## Viewer (si `viewer.py` existe)

- Lancer un viewer :
  make run-viewer ARGS="--port 8080"
- Lister les viewers :
  make list-viewers
- Tail d’un viewer :
  make tail-viewer PID=<PID>
- Tuer un viewer précis :
  make kill-viewer PID=<PID>
- Tuer tous les viewers :
  make kill-all-viewers
