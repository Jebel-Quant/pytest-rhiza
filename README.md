# pytest-rhiza

The [rhiza](https://github.com/jebel-quant/rhiza) repository checks, installed as a pytest
plugin instead of synced into every consumer repository as `.rhiza/tests/`.

## Why

The seven modules the template syncs into `.rhiza/tests/` are parameterised by exactly two
things: the repository root, and `SOURCE_FOLDER` from `.rhiza/.env`. Nothing else about
them varies per project. Distributing them by file copy costs every consumer repo:

- seven template-owned files in the tree, plus a `conftest.py` nobody may edit
- `pythonpath = .rhiza/tests` in `pytest.ini`, so the synced suite can import itself
- `.rhiza/tests` appended to `make docs-coverage`'s interrogate paths, holding *template*
  code to the project's 100% docstring bar
- `--with pytest-timeout --with python-dotenv --with packaging` spelled out in the
  `rhiza-test` recipe, because a copied file carries no dependency metadata
- the template's own `TestSkipFlag` meta-tests re-running in every project, testing rhiza
  against itself

All five go away when the checks are a dependency. The dependency list is deliberately
three small packages — folding them into `rhiza` would pull `jinja2`, `typer`, `rich` and
`loguru` into every test environment, and into `rhiza-tools` would add `pandas` and
`plotly`. It was four until #53 traded python-dotenv for ten lines of stdlib parsing: it
bought one lookup on a rung that only repos still on rhiza v1.3 reach, and this package is
installed in every rhiza-managed repo's test environment.

## Install

```bash
uv add --dev pytest-rhiza
```

Or, the way a consumer's `rhiza-test` gate does it, without touching the project's
dependencies:

```bash
uv run --with pytest-rhiza pytest --pyargs pytest_rhiza.checks.test_readme
```

## How it is put together

Two halves, because pytest treats them differently.

**The fixtures** arrive through the `pytest11` entry point and are available to any test
in the session without a `conftest.py`:

| fixture | what it gives you |
| --- | --- |
| `root` | the repository under test, as a `Path` |
| `logger` | a session-scoped logger |
| `latest_tag` | the newest `vX.Y.Z` tag, skipping when the repo has none |

**The checks** are tests, which an entry point cannot contribute, so they are named
explicitly with `--pyargs`. One module per file the template used to sync, names unchanged:

| module | named by | replaces |
| --- | --- | --- |
| `test_readme` | `core` | `.rhiza/tests/test_readme.py` |
| `test_release_tags` | `core` | `.rhiza/tests/test_release_tags.py` |
| `test_pyproject` | `python-core` | `.rhiza/tests/test_pyproject.py` |
| `test_docstrings` | `python-core` | `.rhiza/tests/test_docstrings.py` |
| `test_readme_validation` | `tests` | `.rhiza/tests/test_readme_validation.py` |
| `test_cargo_toml` | `rust-core` | `.rhiza/tests/test_cargo_toml.py` |
| `test_go_module` | `go-core` | `.rhiza/tests/test_go_module.py` |

That table is not prose. The fence below enumerates what the installed package actually
ships, and the `rhiza-test` job in `.github/workflows/ci.yml` executes it against this
README — so adding or removing a check without updating the list above turns that job
red:

```python
import pkgutil

import pytest_rhiza.checks as checks

for module in sorted(m.name for m in pkgutil.iter_modules(checks.__path__)):
    print(module)
```

```result
test_cargo_toml
test_docstrings
test_go_module
test_pyproject
test_readme
test_readme_validation
test_release_tags
```

### Which repository is "root"

The one deliberate behaviour change from the synced suite. `.rhiza/tests/conftest.py`
resolved the root by counting directories up from `__file__` — sound while the code lived
*in* the repository, wrong once it is installed. Resolution is now:

1. `--rhiza-root`, when given
2. the directory holding the config file (`pytest.ini`, `pyproject.toml`, …)
3. the directory pytest was invoked from

Step 3 rather than `config.rootpath` on purpose: with no config file, pytest derives its
rootdir from the arguments, and under `--pyargs` those are paths inside site-packages.

## How a consumer selects and pins the checks

Selection is still resolved by **which layers a project has**, not by sniffing its
manifest at runtime — so a misconfigured repo goes red instead of quietly skipping a
check. What changed at rhiza v1.4 is where that resolution lives.

Until v1.3 each bundle shipped a make fragment and appended to a `RHIZA_CHECKS`
accumulator (`core`'s `quality.mk` seeded the two language-neutral checks; `python-core`,
`rust-core`, `go-core` and `tests` each added `+=` a line). That synced make layer is
gone — no `.rhiza/rhiza.mk`, no `.rhiza/make.d/`, no fragments. A repo generates its front
door once:

```bash
uvx rhiza-task shim > Makefile
```

`make rhiza-test` still works and is still what a stranger types, but the Makefile no
longer *contains* the recipe: a `%:` catch-all forwards unmatched targets to the pinned
CLI, and the check list is derived from the declared layer set.

Both settings live in `[tool.rhiza-task]` in the consumer's `pyproject.toml`:

```toml
[tool.rhiza-task]
# Which layers this project has. Declared rather than detected, for the same reason the
# accumulator was resolved at sync time: inference would let a misconfigured checkout
# quietly get a different check set instead of failing.
layers = ["python"]

# The pin. One number, so the checks and the template move together rather than drifting
# on two version axes.
pytest-rhiza = "pytest-rhiza @ git+https://github.com/Jebel-Quant/pytest-rhiza@<version>"
```

`<version>` is a placeholder, not a value to copy — and this README deliberately writes no
literal there. Nothing in this repository bumps a number written in `README.md` (there is
no `[[tool.bumpversion.files]]` entry for it) and until recently nothing read it either, so
the pin sat at `0.1.0` for three releases (#17). `tests/test_readme_pin.py` is what notices
now.

### Doctest scope is the one setting the CLI does not pass

`checks/test_docstrings.py` takes its folders from the `RHIZA_DOCTEST_FOLDERS`
environment variable, falling back to `src`. That variable is **not** set by
`rhiza-task` — a consumer whose Python lives outside its source root exports it around
the gate, which is what rhiza itself does:

```bash +RHIZA_SKIP
RHIZA_DOCTEST_FOLDERS="$(uvx rhiza-task print source_folder)" uvx rhiza-task rhiza-test
```

Without it the check resolves `src` alone, and a project keeping its Python elsewhere has
its examples silently unchecked — rhiza's own repo being the extreme case, with no `src/`
at all.

### How long a release may stay in flight

The version checks assert the declared version is not *behind* the newest tag, and permit
it to be *ahead* — that is what a release in flight looks like, since `/rhiza:release`
bumps by pull request (phase A) and tags the merged commit afterwards (phase B). Nothing
bounded how long it may lead for, so a release whose phase B never ran stayed green
indefinitely while declaring a version that was never tagged and never published (#85).
This package sat in exactly that state.

`RHIZA_RELEASE_GRACE_DAYS` is that bound, defaulting to **3 days**. It is measured from
the commit that wrote the version into the manifest, and only once that commit is on the
default branch — while the release PR is open, nothing fires. A project whose cadence is
genuinely slower raises it:

```bash +RHIZA_SKIP
RHIZA_RELEASE_GRACE_DAYS=30 uvx rhiza-task rhiza-test
```

Everything git cannot answer is a skip rather than a failure: a shallow clone, a checkout
with no `origin/HEAD`, a manifest the version was never written into. None of those mean
the release stalled, they mean the check has no subject.

## Two things that were decided

Both of these were open questions while the split was being designed. They are settled
now, and the second went the opposite way to what was expected — which is the more useful
half to record.

**Version pinning: one number, and no literal in this file.** The worry was that a
separate distribution adds a second version axis to reason about. It does not, because the
pin travels in the template: it is one setting a consumer's sync writes, so a repo on a
given template release runs that release's assertions, exactly as file-copy delivery gave
for free. The alternative considered — aligning this package's `major.minor` with template
releases and pinning `~=` — was not taken.

What *did* need deciding was where the number is written, and the answer is nowhere in
this README. Nothing here bumps it and, until #17, nothing read it either, so the
documented pin sat at `0.1.0` for three releases. The example uses a placeholder, and
`tests/test_readme_pin.py` is what keeps a literal from creeping back.

**Removing the old folder: not required, because a leftover is inert.** The concern was
that a consumer keeps `.rhiza/tests/` on disk (a sync ceasing to deliver a file does not
delete it) and that the copy would then run twice, so a migration would need an explicit
removal step.

That was wrong, and for a reason worth knowing: the gate names **modules**, not paths. It
resolves `pytest_rhiza.checks.*` out of site-packages, so it never looks at the folder —
and `pythonpath = .rhiza/tests`, the one thing that used to make the folder importable, is
itself one of the five costs above that the move removed. A leftover copy is unreachable
rather than duplicated. `rhiza-test` warns while the folder is still present, and deleting
it is tidying rather than a migration step.

## Development

```bash
uv sync
uv run pytest
```

### The gates, and where they are defined

**There is no Makefile, and no `.rhiza/` layer. `.github/workflows/ci.yml` defines every
gate** (#52), and each job is a single command with a comment saying why its threshold is
what it is.

| gate | what it runs |
| --- | --- |
| `lint` | `uvx prek run --all-files` — every hook in `.pre-commit-config.yaml` |
| `test` | the suite on 3 OSes × 4 Python versions, over `src` and `scripts`, at a 90% floor |
| `typecheck` | `ty check src scripts`, then `mypy --strict src scripts` |
| `docs-coverage` | interrogate over `src`, `tests` and `scripts`, at a 100% floor |
| `deptry` | declared-vs-imported deps, against `[tool.deptry]` in `pyproject.toml` |
| `security` | bandit over `src` and `scripts`, medium-and-above |
| `audit` | `pip-audit` over the locked environment |
| `lowest-deps` | the suite against `--resolution lowest-direct`, testing the version floors |
| `license` | refuses strong copyleft in the runtime closure |
| `rhiza-test` | the checks this package ships, against this repository, with tags |
| `ci-gate` | one required check that fails unless every job above succeeded |

#### Running one by hand

```bash
# lint
uvx prek run --all-files --show-diff-on-failure
# typecheck
uv run --with ty ty check src scripts
uv run --with mypy mypy --strict src scripts
# docs-coverage
uv run --with interrogate interrogate -vv --fail-under 100 --ignore-init-method --ignore-magic src tests scripts
# deptry
uvx deptry src
# security
uvx bandit -r src scripts -ll -q
# audit
uvx pip-audit
# license
uv run --with pip-licenses pip-licenses --allow-only "MIT;MIT License;BSD-2-Clause;BSD-3-Clause;Apache-2.0;Apache-2.0 OR BSD-2-Clause;DFSG approved"
# test
uv run --group test pytest -ra --cov=src --cov=scripts --cov-report=term-missing --cov-fail-under=90
# lowest-deps
uv sync --all-extras --all-groups --resolution lowest-direct
uv run --all-extras --all-groups --resolution lowest-direct pytest -ra
# rhiza-test
uv run --group test pytest -ra -rs --pyargs pytest_rhiza.checks.test_readme pytest_rhiza.checks.test_readme_validation pytest_rhiza.checks.test_pyproject pytest_rhiza.checks.test_docstrings pytest_rhiza.checks.test_release_tags
```

**This is a copy, and `ci.yml` is still the definition.** Until #58 the block above did not
exist, on the #52 reasoning that a second home for a command line is a second thing to keep
correct — the same argument that removed the Makefile. What that left was a repository where
reproducing a red job meant opening a workflow file and reading YAML, which is a real cost
paid by every contributor, including the ones who never write CI.

So the copy is allowed and **pinned**: `tests/test_readme_gates.py` asserts that every
command above is the one its job actually runs, and that no CI gate is missing from the
block. A threshold edited in `ci.yml` and not here fails the suite, which is what makes one
of the two homes authoritative rather than merely first.

Two deliberate gaps. `lowest-deps` rewrites `uv.lock`'s resolution in your working tree —
run `uv sync` afterwards to get back. And `rhiza-test`'s line stops at the pytest
invocation: CI wraps it in a `grep` guard that fails the job if any check *skips* (#34),
which is a property of the pipeline rather than of the gate.

#### Running all of them

```bash
python scripts/gates.py              # every gate except the destructive ones
python scripts/gates.py lint test    # just these
python scripts/gates.py --list       # what is defined, without running anything
```

`scripts/gates.py` **runs the block above rather than restating it** (#66), which is what
keeps it from being the second home #52 removed: it parses that fence and executes what it
finds, so `ci.yml` is still the only place a gate command line is written. The runner and
`tests/test_readme_gates.py` share the parser deliberately — if the runner read this file
its own way, that test would pin a parse of the README that nothing actually executes.

It also closes the two gaps above, which is most of why it is worth having. `lowest-deps` is
excluded from a bare run and needs naming (or `--all`), because rewriting your lockfile
should be something you asked for — and when the gate finishes the runner re-syncs the lock
for you, in a `finally`, so a failing or interrupted run recovers too and even `--all` leaves
`git status` clean (#71). And `rhiza-test` carries the `grep` guard, so a local pass means
what CI's does instead of going green on `32 passed, 2 skipped`.

Every selected gate runs even after one fails, and the summary at the end is the whole
picture — the same reason `ci-gate` aggregates rather than the jobs depending on each other.

`weekly.yml` carries the two that are too slow or noisy for every push: a fresh
dependency resolution, and a link check over this file.

Day to day, `uv sync` then `uv run pytest` is the loop; `uvx prek install` wires the hooks
so the formatting gate cannot surprise you.

### Why no Makefile, and why nothing calls jebel-quant/rhiza

This repository used to run rhiza's reusable CI (`rhiza_ci.yml`) like any consumer, and
mirrored a subset of its gates into a Makefile so a contributor could reproduce a red job.
Both layers are gone, because the dependency direction made the first one a cycle:
**`jebel-quant/rhiza` pins pytest-rhiza as a dependency** — its `pyproject.toml` carries
`pytest-rhiza @ git+…`— so this repository calling rhiza's CI meant rhiza's workflow
running the gates that judge the package rhiza depends on. Every other consumer gets a
one-way edge; this one got a loop.

One rhiza workflow stays: `rhiza_release.yml`, synced verbatim, because PyPI Trusted
Publishing validates the exact workflow path. The `rhiza_codeql.yml` and
`rhiza_scorecard.yml` stubs are gone — they called rhiza's reusable CodeQL and OSSF
Scorecard workflows, a pinned edge to keep current for scanning this repository does not
depend on.

The *scanning* came back in #86, as `codeql.yml` and `scorecard.yml`. Only the edge was
ever the objection: both now call `github/codeql-action` and `ossf/scorecard-action`
directly, SHA-pinned like every other third-party action here, so there is no `uses:` line
pointing at rhiza and no cycle. They earn their place beside `security` because bandit
pattern-matches one file at a time and never follows a value across a boundary, and
because nothing else here scores this repository's own supply-chain posture.

The cost of dropping the Makefile was real and was stated plainly here for three releases:
**no gate had a local entry point at all** (#49, #32). That was the call made in #52 — a
Makefile in a repo whose ecosystem retired make as an interface is a second thing to keep
correct — and it meant the only way to run a gate by hand was to read its command line out
of `ci.yml`, which #58 improved to a copy-paste out of this file.

`scripts/gates.py` closes it (#66) without giving any threshold a second home, because it
holds no recipes: it executes the fence above, which `tests/test_readme_gates.py` already
pins to `ci.yml`. That is the distinction #52 was actually protecting — not "no runner", but
no *second copy* of what to run. There is still no `Makefile`, and nothing here invokes
`rhiza-task`.

### The checks, self-applied

The checks run against this repository too — it is a Python project with a README, a
`pyproject.toml` and a release config, so it is a valid subject for its own assertions.
That is what the `rhiza-test` job is:

```bash
uv run --group test pytest -ra --pyargs pytest_rhiza.checks.test_readme
```

The job names the five modules this project is a subject for, and deliberately not
`test_cargo_toml` or `test_go_module`: there is no `Cargo.toml` or `go.mod` here for them
to judge, and a check with no subject skips, which reads as a pass (#34).

The five come to 34 assertions, and all 34 *run* — which is the part worth checking,
because rhiza's own `Rhiza repository checks` job used to report `32 passed, 2
skipped`: its checkout fetched no tags, so the two assertions comparing
`[project].version` against the newest `vX.Y.Z` had nothing to compare and skipped. That is
the one place where local was *stronger* than that job rather than weaker, and it is why
the `rhiza-test` job checks out with `fetch-depth: 0` and then fails if anything skipped at
all (#34) — fetching tags fixes today's symptom, and the no-skip guard is what stops the
failure mode returning through some other change.

## License

MIT — see [LICENSE](LICENSE).
