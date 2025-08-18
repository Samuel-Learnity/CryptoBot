# Makefile — Crypto Stop-Loss Bot (robuste, logs + pidfiles)
PY        := python3
VENV      := .venv
PIP       := $(VENV)/bin/pip
PYBIN     := $(VENV)/bin/python
LOGDIR    := logs
RUNDIR    := .run

# Utilitaires
MKDIR_P   := mkdir -p

# === Options utilisateur ===
SYMBOL     ?=
TIMEFRAME  ?=
VIEWER       ?= plotext
ASCII_FLAGS   ?= --limit 200 --height 24 --cols 100
PLOTEXT_FLAGS ?= --limit 300
OVERLAY     ?= 1
LOOKBACK    ?= 20
OVERLAY_FLAGS := $(if $(filter 1 true yes on,$(OVERLAY)),--overlay_ma20 --overlay_hh20 --lookback $(LOOKBACK),)
VIEWER_SERVE ?= 0
BASE_PORT    ?= 8765
PORT         ?=
SERVE_FLAGS  := $(if $(filter 1 true yes on,$(VIEWER_SERVE)),--serve $(if $(PORT),--port $(PORT),--port auto) --base_port $(BASE_PORT),)

# Fichier de config + overrides CLI pour le bot
CONFIG   ?= config.yaml
BOT_CLI  := $(if $(SYMBOL),--symbol "$(SYMBOL)",) $(if $(TIMEFRAME),--timeframe "$(TIMEFRAME)",)

.PHONY: venv bot bot-bg viewer viewer-ascii viewer-plotext both both-ascii both-plotext stop tail-bot tail-viewer list-bots list-viewers kill-all-bots kill-all-viewers

venv:
	@$(MKDIR_P) $(LOGDIR) $(RUNDIR)
	@test -x $(PYBIN) || ($(PY) -m venv $(VENV))
	@$(PYBIN) -m pip install -r requirements.txt

bot: venv
	@$(PYBIN) main.py

bot-bg: venv
	@$(MKDIR_P) $(LOGDIR) $(RUNDIR)
	@TS=$$(date +%Y%m%d-%H%M%S); LOG="$(LOGDIR)/bot-$$TS.log"; \
	nohup $(PYBIN) main.py > "$$LOG" 2>&1 & PID=$$!; \
	echo $$PID > "$(RUNDIR)/bot-$$PID.pid"; \
	echo "BOT PID=$$PID LOG=$$LOG"

viewer: viewer-$(VIEWER)

viewer-ascii: venv
	@$(MKDIR_P) $(LOGDIR) $(RUNDIR)
	@SYM="$$( [ -n "$(SYMBOL)" ] && echo "$(SYMBOL)" || $(PYBIN) scripts/read_cfg.py symbol )"; \
	TF="$$( [ -n "$(TIMEFRAME)" ] && echo "$(TIMEFRAME)" || $(PYBIN) scripts/read_cfg.py timeframe )"; \
	TS=$$(date +%Y%m%d-%H%M%S); LOG="$(LOGDIR)/viewer-$$TS.log"; \
	nohup $(PYBIN) terminal_candles_stream_ascii.py --symbol "$$SYM" --timeframe "$$TF" $(ASCII_FLAGS) > "$$LOG" 2>&1 & PID=$$!; \
	echo $$PID > "$(RUNDIR)/viewer-$$PID.pid"; \
	echo "VIEWER PID=$$PID LOG=$$LOG"

viewer-plotext: venv
	@$(MKDIR_P) $(LOGDIR) $(RUNDIR)
	@SYM="$$( [ -n "$(SYMBOL)" ] && echo "$(SYMBOL)" || $(PYBIN) scripts/read_cfg.py symbol )"; \
	TF="$$( [ -n "$(TIMEFRAME)" ] && echo "$(TIMEFRAME)" || $(PYBIN) scripts/read_cfg.py timeframe )"; \
	TS=$$(date +%Y%m%d-%H%M%S); LOG="$(LOGDIR)/viewer-$$TS.log"; \
	nohup $(PYBIN) terminal_candles_stream.py --symbol "$$SYM" --timeframe "$$TF" $(PLOTEXT_FLAGS) $(OVERLAY_FLAGS) $(SERVE_FLAGS) > "$$LOG" 2>&1 & PID=$$!; \
	echo $$PID > "$(RUNDIR)/viewer-$$PID.pid"; \
	echo "VIEWER PID=$$PID LOG=$$LOG"

both: both-$(VIEWER)

both-ascii: venv
	@$(MKDIR_P) $(LOGDIR) $(RUNDIR)
	@TS=$$(date +%Y%m%d-%H%M%S); BLOG="$(LOGDIR)/bot-$$TS.log"; \
	nohup $(PYBIN) main.py --config "$(CONFIG)" $(BOT_CLI) > "$$BLOG" 2>&1 & BPID=$$!; \
	echo $$BPID > "$(RUNDIR)/bot-$$BPID.pid"; \
	echo "$$BLOG" > "$(RUNDIR)/bot-$$BPID.logpath"; \
	SYM="$$( [ -n "$(SYMBOL)" ] && echo "$(SYMBOL)" || $(PYBIN) scripts/read_cfg.py symbol )"; \
	TF="$$( [ -n "$(TIMEFRAME)" ] && echo "$(TIMEFRAME)" || $(PYBIN) scripts/read_cfg.py timeframe )"; \
	TS2=$$(date +%Y%m%d-%H%M%S); VLOG="$(LOGDIR)/viewer-$$TS2.log"; \
	nohup $(PYBIN) terminal_candles_stream_ascii.py --symbol "$$SYM" --timeframe "$$TF" $(ASCII_FLAGS) > "$$VLOG" 2>&1 & VPID=$$!; \
	echo $$VPID > "$(RUNDIR)/viewer-$$VPID.pid"; \
	echo "$$VLOG" > "$(RUNDIR)/viewer-$$VPID.logpath"; \
	echo "RUNNING BOT PID=$$BPID LOG=$$BLOG | VIEWER PID=$$VPID LOG=$$VLOG"

both-plotext: venv
	@$(MKDIR_P) $(LOGDIR) $(RUNDIR)
	@TS=$$(date +%Y%m%d-%H%M%S); BLOG="$(LOGDIR)/bot-$$TS.log"; \
	nohup $(PYBIN) main.py --config "$(CONFIG)" $(BOT_CLI) > "$$BLOG" 2>&1 & BPID=$$!; \
	echo $$BPID > "$(RUNDIR)/bot-$$BPID.pid"; \
	echo "$$BLOG" > "$(RUNDIR)/bot-$$BPID.logpath"; \
	SYM="$$( [ -n "$(SYMBOL)" ] && echo "$(SYMBOL)" || $(PYBIN) scripts/read_cfg.py symbol )"; \
	TF="$$( [ -n "$(TIMEFRAME)" ] && echo "$(TIMEFRAME)" || $(PYBIN) scripts/read_cfg.py timeframe )"; \
	TS2=$$(date +%Y%m%d-%H%M%S); VLOG="$(LOGDIR)/viewer-$$TS2.log"; \
	nohup $(PYBIN) terminal_candles_stream.py --symbol "$$SYM" --timeframe "$$TF" $(PLOTEXT_FLAGS) $(OVERLAY_FLAGS) $(SERVE_FLAGS) > "$$VLOG" 2>&1 & VPID=$$!; \
	echo $$VPID > "$(RUNDIR)/viewer-$$VPID.pid"; \
	echo "$$VLOG" > "$(RUNDIR)/viewer-$$VPID.logpath"; \
	echo "RUNNING BOT PID=$$BPID LOG=$$BLOG | VIEWER PID=$$VPID LOG=$$VLOG"

stop:
	@echo "Stopping all processes with pidfiles in $(RUNDIR) ..."
	@for f in $(RUNDIR)/*.pid; do \
		[ -f "$$f" ] || continue; \
		pid=$$(basename "$$f" | sed 's/[^0-9]//g'); \
		if [ -n "$$pid" ]; then kill $$pid 2>/dev/null || true; fi; \
		rm -f "$$f"; \
	done || true

tail-bot:
	@ls -1t $(LOGDIR)/bot-*.log 2>/dev/null | head -n 1 | xargs -I{} sh -c 'echo "Tailing: {}"; tail -f "{}"'

tail-viewer:
	@ls -1t $(LOGDIR)/viewer-*.log 2>/dev/null | head -n 1 | xargs -I{} sh -c 'echo "Tailing: {}"; tail -f "{}"'

list-viewers:
	@ls $(RUNDIR)/viewer-*.pid 2>/dev/null || { echo "No viewer pidfiles."; exit 0; }
	@for f in $(RUNDIR)/viewer-*.pid; do \
	    pid=$$(basename "$$f" | sed 's/[^0-9]//g'); \
	    if ps -p $$pid >/dev/null 2>&1; then \
	        echo "VIEWER PID=$$pid"; \
	    else \
	        echo "STALE pidfile: $$f"; \
	    fi; \
	done

list-bots:
	@ls $(RUNDIR)/bot-*.pid 2>/dev/null || { echo "No bot pidfiles."; exit 0; }
	@for f in $(RUNDIR)/bot-*.pid; do \
	    pid=$$(basename "$$f" | sed 's/[^0-9]//g'); \
	    if ps -p $$pid >/dev/null 2>&1; then \
	        echo "BOT PID=$$pid"; \
	    else \
	        echo "STALE pidfile: $$f"; \
	    fi; \
	done

kill-all-viewers:
	@for f in $(RUNDIR)/viewer-*.pid; do \
	    [ -f "$$f" ] || continue; \
	    pid=$$(basename "$$f" | sed 's/[^0-9]//g'); \
	    if ps -p $$pid >/dev/null 2>&1; then \
	        kill $$pid && echo "Killed $$pid"; \
	    else \
	        echo "STALE pidfile: $$f"; \
	    fi; \
	    rm -f "$$f"; \
	done || true

kill-all-bots:
	@for f in $(RUNDIR)/bot-*.pid; do \
	    [ -f "$$f" ] || continue; \
	    pid=$$(basename "$$f" | sed 's/[^0-9]//g'); \
	    if ps -p $$pid >/dev/null 2>&1; then \
	        kill $$pid && echo "Killed $$pid"; \
	    else \
	        echo "STALE pidfile: $$f"; \
	    fi; \
	    rm -f "$$f"; \
	done || true
