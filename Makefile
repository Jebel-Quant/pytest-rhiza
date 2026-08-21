# Minimal entry points for this repo. `uv run` builds and installs pytest-rhiza
# itself, which is what registers the pytest11 entry point the suite relies on.
# Hooks run through prek, the Rust drop-in for pre-commit; uvx fetches it, so
# there is nothing to install up front.

.DEFAULT_GOAL := help

PREK := uvx prek

.PHONY: help lint install-hooks typecheck docs-coverage deptry security test rhiza-test clean

help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

lint: ## Run all pre-commit hooks over every file
	$(PREK) run --all-files

install-hooks: ## Install the git pre-commit hook
	$(PREK) install

# The four gates below run in CI through the reusable workflow
# `jebel-quant/rhiza/.github/workflows/rhiza_ci.yml`, which means their flags are owned
# upstream rather than by this repo. They had no local entry point at all, so a
# contributor could not reproduce a red CI job before pushing — the same hazard the
# comment on `test` names, one gate over.
#
# Each recipe is the CI job's command line copied verbatim, and that is the point: the
# thresholds are not re-decided here. Read them off a run with
# `gh run view <id> --log | grep -E '^\$'` if they ever need re-checking, and keep the
# two in step. `deptry` is the one deliberate exception, for the reasons above it.
#
# Deliberately *not* mirrored into `[tool.interrogate]` / `[tool.mypy]` in pyproject.toml.
# A committed table would be a second home for a threshold whose first home is upstream's
# workflow, and two homes for one number is how they drift apart.

typecheck: ## Type-check src (mirrors the rhiza_ci "Type checking" job)
	uv run --with ty ty check src

docs-coverage: ## Docstring coverage (mirrors the rhiza_ci "docs-coverage" job)
	uv run --with interrogate interrogate -vv --fail-under 100 --ignore-init-method --ignore-magic src tests

# The fourth gate, and the one recipe that is deliberately *not* the CI command line.
# Upstream runs `uvx rhiza-task@0.3.1 deps` (the `deptry` job in rhiza_ci.yml); this names
# deptry directly, for two reasons.
#
# There is no threshold to mirror. deptry's entire configuration is `[tool.deptry]` in this
# repository's pyproject.toml — the `python-dotenv` → `dotenv` module map, and the DEP002
# ignore for the entry-point-only pytest-timeout. Nothing about this gate is owned
# upstream, so the paragraph above does not apply to it, and there is no number here that
# could drift from one.
#
# And routing it through `rhiza-task` would close a loop. rhiza-task depends on
# pytest-rhiza, so a *local* gate on this package invoked through the front door would
# fetch a released copy of this very package in order to check the copy being edited. The
# three recipes above already avoid that by naming the underlying tool (`ty`, `interrogate`,
# `bandit`) rather than `rhiza-task <gate>`; this one does the same, and it is the gate
# where the reason is load-bearing rather than incidental.
deptry: ## Unused/missing dependency analysis (mirrors the rhiza_ci "deptry" job)
	uvx deptry src

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

# The checks this package ships, run against this repository (#47).
#
# README.md claimed `make rhiza-test` was what kept its module-list table honest, and no
# such target existed: the fence was only ever executed by the upstream reusable workflow,
# so a contributor could not reproduce a red check locally. That is the same hazard the
# comment above `typecheck` names, one gate over — and the README naming a target that is
# not there is worse than the gap it papers over.
#
# `test_cargo_toml` and `test_go_module` are absent from the list deliberately: there is no
# Cargo.toml or go.mod here for them to judge, and a check with no subject would skip,
# which reads as a pass (#34).
#
# RHIZA_DOCTEST_FOLDERS is left unset on purpose — this project's Python *is* under `src`,
# which is the variable's own fallback, so setting it would add a second place to keep the
# folder name correct. A consumer whose layout differs is the case the README documents.
rhiza-test: ## Run this package's checks against this repository
	uv run --group test pytest -ra --pyargs \
		pytest_rhiza.checks.test_readme \
		pytest_rhiza.checks.test_readme_validation \
		pytest_rhiza.checks.test_pyproject \
		pytest_rhiza.checks.test_docstrings \
		pytest_rhiza.checks.test_release_tags

clean: ## Remove build artefacts and caches
	rm -rf dist build .pytest_cache .ruff_cache .coverage htmlcov *.egg-info src/*.egg-info
	find . -path ./.venv -prune -o -name '__pycache__' -type d -exec rm -rf {} +

-include local.mk
