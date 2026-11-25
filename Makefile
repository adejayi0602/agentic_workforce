.PHONY: setup up down api worker web lint test test-integration format check migrate contracts

setup:
	uv sync --all-packages
	cd apps/web && npm ci

up:
	docker compose up -d

down:
	docker compose down

api:
	uv run --package workforce-api uvicorn workforce_api.main:app --reload --port 8000

worker:
	uv run --package workforce-workers python -m workforce_workers.worker

web:
	cd apps/web && npm run dev

migrate:
	cd services/api && uv run alembic upgrade head

# Regenerate the OpenAPI contract and the web app's TypeScript types from the API.
contracts:
	uv run python services/api/scripts/export_openapi.py
	cd apps/web && npm run gen:api

format:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy packages/contracts/src services/api/src services/workers/src
	cd apps/web && npm run lint && npm run typecheck

test:
	uv run pytest
	cd apps/web && npm test

test-integration:
	uv run pytest -m integration

check: lint test
	uv run python services/api/scripts/export_openapi.py && git diff --exit-code packages/contracts/openapi.json
	cd apps/web && npm run build
