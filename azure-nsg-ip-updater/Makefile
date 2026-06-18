# Canonical entrypoint for nsg-ip-updater.
# Humans and cron both invoke `make <target>` so commands stay stable
# even when the underlying tooling (uv, pip, pytest) shifts.

# Point at the shared venv in the parent scripts/ directory so this project
# does not need its own interpreter.
PYTHON ?= ../.venv/bin/python
PIP    ?= uv pip
ENVFILE ?= .env

.DEFAULT_GOAL := help
.PHONY: help install test test-watch lint fmt run run-dotenv clean

help: ## Show this help.
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install runtime + dev dependencies AND the package itself (editable).
	VIRTUAL_ENV=$$(cd .. && pwd)/.venv $(PIP) install -r requirements.txt
	VIRTUAL_ENV=$$(cd .. && pwd)/.venv $(PIP) install -e .

test: ## Run the full test suite once.
	$(PYTHON) -m pytest

test-watch: ## Re-run pytest on every file change (requires pytest-watch).
	$(PYTHON) -m pytest_watch -- -q

lint: ## Byte-compile every source file as a cheap syntax/import check.
	$(PYTHON) -m compileall -q src tests

fmt: ## No-op (no formatter wired up yet — left as a placeholder).
	@echo "fmt: no formatter configured; add ruff/black here when desired."

run: ## Run one reconciliation pass using the current shell env.
	$(PYTHON) -m nsg_ip_updater

run-dotenv: ## Run one pass after sourcing $(ENVFILE) — what cron should call.
	@test -f $(ENVFILE) || (echo "missing $(ENVFILE) — copy .env.example" && exit 1)
	@set -a; . ./$(ENVFILE); set +a; $(PYTHON) -m nsg_ip_updater

clean: ## Remove caches and build artifacts.
	rm -rf .pytest_cache __pycache__ src/*.egg-info src/**/__pycache__ tests/__pycache__
