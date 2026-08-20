# Minimal entry points for this repo. `uv run` builds and installs pytest-rhiza
# itself, which is what registers the pytest11 entry point the suite relies on.
# Hooks run through prek, the Rust drop-in for pre-commit; uvx fetches it, so
# there is nothing to install up front.

.DEFAULT_GOAL := help

PREK := uvx prek

.PHONY: help lint install-hooks typecheck docs-coverage security test clean

help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

lint: ## Run all pre-commit hooks over every file
	$(PREK) run --all-files

install-hooks: ## Install the git pre-commit hook
	$(PREK) install

# The three gates below run in CI through the reusable workflow
# `jebel-quant/rhiza/.github/workflows/rhiza_ci.yml`, which means their flags are owned
# upstream rather than by this repo. They had no local entry point at all, so a
# contributor could not reproduce a red CI job before pushing — the same hazard the
# comment on `test` names, one gate over.
#
# Each recipe is the CI job's command line copied verbatim, and that is the point: the
# thresholds are not re-decided here. Read them off a run with
# `gh run view <id> --log | grep -E '^\$'` if they ever need re-checking, and keep the
# two in step.
#
# Deliberately *not* mirrored into `[tool.interrogate]` / `[tool.mypy]` in pyproject.toml.
# A committed table would be a second home for a threshold whose first home is upstream's
# workflow, and two homes for one number is how they drift apart.

typecheck: ## Type-check src (mirrors the rhiza_ci "Type checking" job)
	uv run --with ty ty check src

docs-coverage: ## Docstring coverage (mirrors the rhiza_ci "docs-coverage" job)
	uv run --with interrogate interrogate -vv --fail-under 100 --ignore-init-method --ignore-magic src tests

# bandit only, matching the CI job. The dependency half of `security` is pip-audit, which
# this repo runs in its own ci.yml `audit` job rather than here.
security: ## Bandit scan of src (mirrors the rhiza_ci "Security scanning" job)
	uvx bandit -r src -ll -q

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
