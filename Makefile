.DEFAULT_GOAL := help
.PHONY: help setup lint fmt typecheck test check ingest backfill compact verify samples docker-build tf-fmt tf-validate tf-test clean

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

setup: ## install deps (workspace incl. lake/) and git hooks
	uv sync --all-packages --all-groups
	uv run pre-commit install --hook-type pre-commit --hook-type commit-msg

lint: ## ruff check + format check (no changes)
	uv run ruff check .
	uv run ruff format --check .

fmt: ## ruff autofix + format
	uv run ruff check --fix .
	uv run ruff format .

typecheck: ## mypy strict
	uv run mypy

test: ## pytest with coverage
	uv run pytest --cov --cov-report=term-missing

check: lint typecheck test ## everything CI runs for Python

ingest: ## poll into $$LAKE_ROOT (PRODUCT=key|all; OFFLINE=1 uses samples/)
	uv run ingest --product $(or $(PRODUCT),all) $(if $(OFFLINE),--offline,)

backfill: ## past vintages into $$LAKE_ROOT (PRODUCT=key FROM=YYYY-MM-DD TO=YYYY-MM-DD)
	uv run backfill --product $(or $(PRODUCT),openmeteo-gfs-seamless) --from $(FROM) --to $(TO)

compact: ## merge curated files older than an hour, per partition
	uv run compact

verify: ## check $$LAKE_ROOT against the contract with DuckDB
	uv run python -m scripts.verify_lake

samples: ## refresh samples/openmeteo from the live API (first 6 hours)
	uv run python -m scripts.fetch_sample

docker-build: ## build the Lambda image (arm64, single manifest)
	docker build --platform linux/arm64 --provenance=false --sbom=false -t weather-ingest:local .

tf-fmt: ## terraform fmt check over infra/ (TF_FIX=1 rewrites)
	terraform fmt -recursive $(if $(TF_FIX),,-check -diff) infra

tf-validate: ## validate the example root and every module it uses (no backend, no credentials)
	terraform -chdir=infra/examples init -backend=false -input=false
	terraform -chdir=infra/examples validate

tf-test: tf-validate ## terraform test against a mocked AWS provider
	terraform -chdir=infra/examples test

clean: ## remove caches
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
