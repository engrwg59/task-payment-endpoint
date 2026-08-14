.PHONY: help install env up watch prod down logs db migrate seed run test lint

VENV := .venv
PYTHON := $(VENV)/bin/python
FLASK := $(VENV)/bin/flask

help:  ## Show the available targets
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-9s %s\n", $$1, $$2}'

env:  ## Create .env from the example if it does not exist yet
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example")

install: env  ## Create the virtualenv and install the project with its dev extras
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install --editable ".[dev]"

up: env  ## Start the whole stack in the background (dev configuration)
	docker compose up --build --detach

watch: env  ## Start the stack in the foreground, syncing code changes as you save
	docker compose watch

prod: env  ## Start the production-shaped stack, without the dev override
	docker compose -f compose.yml up --build --detach

down:  ## Stop everything and delete the database volume
	docker compose down --volumes

logs:  ## Follow the API logs
	docker compose logs --follow api

db: env  ## Start PostgreSQL only, for running the app or the tests on the host
	docker compose up --detach db

migrate:  ## Apply migrations to the development database, from the host
	$(FLASK) db upgrade

seed:  ## Insert the demo rows, from the host
	$(FLASK) seed-demo

run:  ## Run the development server on the host
	$(FLASK) run

test: ## Run the test suite in the running stack (nothing to install)
	docker compose exec api pytest

test-host: ## Run the test suite from the host virtualenv (needs: make db)
	$(VENV)/bin/pytest

lint:  ## Check formatting and lint rules
	$(VENV)/bin/ruff format --check .
	$(VENV)/bin/ruff check .
