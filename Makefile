MODEL ?= mlx-community/Qwen3.6-27B-4bit
PORT  ?= 8765
PIDFILE := .server.pid
LOG     := server.log

.PHONY: help start start-interactive stop restart status logs agent test download

help: ## show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-18s %s\n", $$1, $$2}'

start: ## start the inference server (MODEL=... PORT=...)
	@if [ -f $(PIDFILE) ] && kill -0 $$(cat $(PIDFILE)) 2>/dev/null; then \
		echo "already running (pid $$(cat $(PIDFILE))) — make stop first"; exit 1; fi
	@echo "checking weights for $(MODEL) (downloads with progress if missing)..."
	@HF_XET_HIGH_PERFORMANCE=1 uv run hf download $(MODEL)
	@KAS_MODEL=$(MODEL) nohup uv run uvicorn server.app:app --port $(PORT) > $(LOG) 2>&1 & \
		echo $$! > $(PIDFILE)
	@echo "starting $(MODEL) on :$(PORT) (pid $$(cat $(PIDFILE))) — loading into memory..."
	@i=0; until curl -s -m 1 http://127.0.0.1:$(PORT)/v1/models >/dev/null 2>&1; do \
		i=$$((i+1)); \
		if [ $$i -gt 150 ]; then echo "server did not come up — make logs"; exit 1; fi; \
		if ! kill -0 $$(cat $(PIDFILE)) 2>/dev/null; then echo "server died — make logs"; exit 1; fi; \
		sleep 2; done
	@echo "ready: http://127.0.0.1:$(PORT)/v1/messages"

start-interactive: ## pick a locally downloaded model, then start
	@$(MAKE) start MODEL=$$(uv run python scripts/select_model.py)

stop: ## stop the inference server
	@if [ -f $(PIDFILE) ]; then \
		kill $$(cat $(PIDFILE)) 2>/dev/null && echo "stopped (pid $$(cat $(PIDFILE)))" || echo "not running"; \
		rm -f $(PIDFILE); \
	else pkill -f "uvicorn server.app" 2>/dev/null && echo "stopped" || echo "not running"; fi

restart: stop start ## restart the server

status: ## server status + loaded model
	@if [ -f $(PIDFILE) ] && kill -0 $$(cat $(PIDFILE)) 2>/dev/null; then \
		echo "running (pid $$(cat $(PIDFILE)))"; \
		curl -s -m 2 http://127.0.0.1:$(PORT)/v1/models | uv run python -c "import json,sys; print('model  :', json.load(sys.stdin)['data'][0]['id'])" 2>/dev/null || echo "model  : (still loading)"; \
	else echo "not running"; fi

logs: ## tail the server log
	@tail -f $(LOG)

perf: ## summarize request performance from the server log
	@uv run python scripts/perf_report.py $(LOG)

agent: ## run the agent REPL (ARGS="--yolo --workdir ~/proj")
	@uv run python -m agent $(ARGS)

test: ## run parser + protocol + characterization tests (no model needed)
	@uv run python tests/test_parser.py
	@uv run python tests/test_api.py
	@uv run python tests/test_continuation.py
	@uv run python tests/test_cache.py
	@uv run python tests/test_tools.py

download: ## download model weights (MODEL=...)
	@HF_XET_HIGH_PERFORMANCE=1 uv run hf download $(MODEL)

install: ## install `kas` as a global CLI (uv tool)
	@./install.sh
