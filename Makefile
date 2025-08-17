# Makefile — Crypto Stop-Loss Bot (sync YAML, clean)
PY        := python
VENV      := .venv
PIP       := $(VENV)/bin/pip
PYBIN     := $(VENV)/bin/python
LOGDIR    := logs
RUNDIR    := .run
PIDS      := $(RUNDIR)/pids
BOT_LOG   := $(LOGDIR)/bot.log
VIEW_LOG  := $(LOGDIR)/viewer.log

# === Options utilisateur ===
# Par défaut, on lit SYMBOL/TIMEFRAME via config.yaml.
# Tu peux OVERRIDER en passant SYMBOL=... TIMEFRAME=...
SYMBOL     ?=
TIMEFRAME  ?=

# Choix du viewer: ascii | plotext
VIEWER       ?= plotext

# Flags spécifiques
ASCII_FLAGS   ?= --limit 200 --height 24 --cols 100
PLOTEXT_FLAGS ?= --limit 300

# Overlays (plotext uniquement)
OVERLAY     ?= 1
LOOKBACK    ?= 20
OVERLAY_FLAGS := $(if $(filter 1 true yes on,$(OVERLAY)),--overlay_ma20 --overlay_hh20 --lookback $(LOOKBACK),)

.PHONY: venv bot viewer viewer-ascii viewer-plotext both both-ascii both-plotext stop tail-bot tail-viewer

venv:
	@test -d $(VENV) || (python -m venv $(VENV))
	@$(PIP) install -r requirements.txt

bot: venv
	@$(PYBIN) main.py

viewer: viewer-$(VIEWER)

viewer-ascii: venv
	@mkdir -p $(LOGDIR) $(RUNDIR)
	@SYM="$$( [ -n "$(SYMBOL)" ] && echo "$(SYMBOL)" || $(PYBIN) scripts/read_cfg.py symbol )"; \
	TF="$$( [ -n "$(TIMEFRAME)" ] && echo "$(TIMEFRAME)" || $(PYBIN) scripts/read_cfg.py timeframe )"; \
	$(PYBIN) terminal_candles_stream_ascii.py --symbol "$$SYM" --timeframe "$$TF" $(ASCII_FLAGS)

viewer-plotext: venv
	@mkdir -p $(LOGDIR) $(RUNDIR)
	@SYM="$$( [ -n "$(SYMBOL)" ] && echo "$(SYMBOL)" || $(PYBIN) scripts/read_cfg.py symbol )"; \
	TF="$$( [ -n "$(TIMEFRAME)" ] && echo "$(TIMEFRAME)" || $(PYBIN) scripts/read_cfg.py timeframe )"; \
	$(PYBIN) terminal_candles_stream.py --symbol "$$SYM" --timeframe "$$TF" $(PLOTEXT_FLAGS) $(OVERLAY_FLAGS)

both: both-$(VIEWER)

both-ascii: venv
	@mkdir -p $(LOGDIR) $(RUNDIR)
	@echo "Starting BOT  -> $(BOT_LOG)"
	@nohup $(PYBIN) main.py > $(BOT_LOG) 2>&1 & echo $$! > $(PIDS)
	@echo "Starting VIEW -> $(VIEW_LOG)"
	@SYM="$$( [ -n "$(SYMBOL)" ] && echo "$(SYMBOL)" || $(PYBIN) scripts/read_cfg.py symbol )"; \
	TF="$$( [ -n "$(TIMEFRAME)" ] && echo "$(TIMEFRAME)" || $(PYBIN) scripts/read_cfg.py timeframe )"; \
	nohup $(PYBIN) terminal_candles_stream_ascii.py --symbol "$$SYM" --timeframe "$$TF" $(ASCII_FLAGS) > $(VIEW_LOG) 2>&1 & echo $$! >> $(PIDS)
	@echo "Running. PIDs in $(PIDS). Use 'make tail-bot' or 'make tail-viewer'."

both-plotext: venv
	@mkdir -p $(LOGDIR) $(RUNDIR)
	@echo "Starting BOT  -> $(BOT_LOG)"
	@nohup $(PYBIN) main.py > $(BOT_LOG) 2>&1 & echo $$! > $(PIDS)
	@echo "Starting VIEW -> $(VIEW_LOG)"
	@SYM="$$( [ -n "$(SYMBOL)" ] && echo "$(SYMBOL)" || $(PYBIN) scripts/read_cfg.py symbol )"; \
	TF="$$( [ -n "$(TIMEFRAME)" ] && echo "$(TIMEFRAME)" || $(PYBIN) scripts/read_cfg.py timeframe )"; \
	nohup $(PYBIN) terminal_candles_stream.py --symbol "$$SYM" --timeframe "$$TF" $(PLOTEXT_FLAGS) $(OVERLAY_FLAGS) > $(VIEW_LOG) 2>&1 & echo $$! >> $(PIDS)
	@echo "Running. PIDs in $(PIDS). Use 'make tail-bot' or 'make tail-viewer'."

stop:
	@if [ -f $(PIDS) ]; then \
		echo "Stopping processes..."; \
		while read p; do kill $$p 2>/dev/null || true; done < $(PIDS); \
		rm -f $(PIDS); \
	else \
		echo "No $(PIDS) file. You can also pkill -f main.py or viewers."; \
	fi

tail-bot:
	@tail -f $(BOT_LOG)

tail-viewer:
	@tail -f $(VIEW_LOG)
