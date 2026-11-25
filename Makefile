.PHONY: setup up down api worker web lint test test-integration format check migrate

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

test-integration:
	uv run pytest -m integration

check: lint test
	cd apps/web && npm run build
