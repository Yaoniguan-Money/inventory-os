SHELL := /bin/bash

.PHONY: dev up down db logs migrate seed test backend-test frontend-build typecheck lint reset

dev:
	docker compose up --build

up:
	docker compose up -d --build

down:
	docker compose down

db:
	docker compose up -d postgres

logs:
	docker compose logs -f

migrate:
	cd backend && uv run alembic upgrade head

seed:
	cd backend && uv run python -m app.scripts.seed

reset:
	docker compose down -v
	docker compose up -d postgres
	cd backend && uv run alembic upgrade head && uv run python -m app.scripts.seed

test:
	cd backend && uv run pytest

backend-test:
	cd backend && uv run pytest

typecheck:
	cd backend && uv run mypy app

lint:
	cd backend && uv run ruff check .

frontend-install:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

frontend-typecheck:
	cd frontend && npm run typecheck
