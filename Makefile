# Messer developer commands. Python via uv, JS via pnpm.
SHELL := /bin/bash
PY := uv run --no-sync
DB_ENV := env -u DATABASE_URL

.PHONY: help install dev api web worker runtime scheduler voice mcp migrate bootstrap seed test test-core test-api \
        lint format typecheck e2e up down build-images

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install Python and JS dependencies
	uv sync --all-packages
	pnpm install

migrate: ## Apply database migrations (Alembic)
	$(DB_ENV) $(PY) alembic -c infra/migrations/alembic.ini upgrade head

bootstrap: migrate ## Seed plans, prices, templates; create superadmin and first organization
	$(DB_ENV) $(PY) python -m messer_api.cli bootstrap

seed: ## Re-seed reference data (idempotent)
	$(DB_ENV) $(PY) python -m messer_api.cli seed

api: ## Run the platform API on :8000
	$(DB_ENV) $(PY) uvicorn messer_api.main:app --reload --port 8000

web: ## Run the web app on :3000
	pnpm --filter @messer/web dev

test: test-core test-api ## Run all Python tests

test-core: ## Engine (messer-core) test suite
	cd packages/messer-core && ../../.venv/bin/python -m pytest -q --no-cov -n 4 -o addopts="" -m "not integration" python/tests

test-api: ## Platform tests (needs local Postgres + Redis)
	$(PY) pytest apps/api/tests packages/messer-common/tests

lint: ## Ruff + ESLint
	$(PY) ruff check $$(ls -d packages/messer-common apps/api services/* packages/connectors packages/messer-sdk-py infra/migrations 2>/dev/null)
	pnpm -r --if-present lint

format: ## Format Python
	$(PY) ruff format $$(ls -d packages/messer-common apps/api services/* packages/connectors packages/messer-sdk-py 2>/dev/null)

typecheck: ## Pyright + tsc
	$(PY) pyright
	pnpm -r --if-present typecheck

e2e: ## Playwright end-to-end tests against a running stack
	pnpm --filter @messer/e2e test

up: ## Start the full stack with Docker Compose
	docker compose up --build

down: ## Stop the stack
	docker compose down
