# Minimal entry points for this repo. `uv run` builds and installs pytest-rhiza
# itself, which is what registers the pytest11 entry point the suite relies on.
# Hooks run through prek, the Rust drop-in for pre-commit; uvx fetches it, so
# there is nothing to install up front.

.DEFAULT_GOAL := help

PREK := uvx prek

.PHONY: help lint install-hooks test clean

help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

lint: ## Run all pre-commit hooks over every file
	$(PREK) run --all-files

install-hooks: ## Install the git pre-commit hook
	$(PREK) install

# Same flags CI runs, deliberately: a coverage threshold that only exists in one of the
# two is a threshold nobody notices crossing. `--cov=src` matches what `rhiza-task test`
# passes, and the 90 is its default `coverage_fail_under`. Subprocess measurement is
# configured in pyproject.toml — without it this number is meaningless, because the
# checks only ever execute in child processes.
test: ## Run the test suite with coverage
	uv run --group test pytest -ra --cov=src --cov-report=term-missing --cov-fail-under=90

clean: ## Remove build artefacts and caches
	rm -rf dist build .pytest_cache .ruff_cache .coverage htmlcov *.egg-info src/*.egg-info
	find . -path ./.venv -prune -o -name '__pycache__' -type d -exec rm -rf {} +

-include local.mk
