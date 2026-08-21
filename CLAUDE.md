# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this package is

`pytest-rhiza` ships the [rhiza](https://github.com/jebel-quant/rhiza) repository checks as
an installed pytest plugin, replacing the seven files the template used to sync into every
consumer repo as `.rhiza/tests/`. The checks are parameterised by only two things — the
repository root and the source folder — so distributing them as a dependency removes the
synced files, the `pythonpath` entry, the interrogate path, the spelled-out `--with` flags
and the template's self-tests from every consumer.

It is a runtime dependency of every rhiza-managed repo's test environment. That is the
reason for two constraints that otherwise look like over-caution: the dependency list is
held to three small packages (`pytest`, `pytest-timeout`, `packaging`), and the `audit` and
`license` gates matter more here than usual, because anything entering this closure
propagates into every consumer.

## Commands

There is **no Makefile** — removed deliberately in #52 — and nothing here invokes
`rhiza-task`. `.github/workflows/ci.yml` is the definition of every gate; `README.md` under
"Running one by hand" carries a copy, and `tests/test_readme_gates.py` pins the two together
in both directions. **Edit a gate's command line in `ci.yml` and the suite fails until the
README matches.**

Day-to-day loop:

```bash
uv sync
uv run pytest                                   # whole suite
uv run pytest tests/test_fences.py              # one file
uv run pytest tests/test_fences.py::test_name   # one test
uvx prek install                                # wire the pre-commit hooks
```

The gates have a local entry point again as of #66 — **prefer it over retyping a command
line**, because it executes the README fence rather than a copy of it:

```bash
python scripts/gates.py              # every gate except the destructive ones
python scripts/gates.py lint test    # just these
python scripts/gates.py --list       # what is defined, without running anything
```

`scripts/gates.py` holds no recipes. It parses the fence under *Running one by hand* in
`README.md` and runs what it finds, and it shares that parser with
`tests/test_readme_gates.py` — so the test's proof that the README equals `ci.yml` is what
makes running the runner equivalent to running CI. Adding a gate means editing `ci.yml` and
the README fence; the runner picks it up with no change.

Two gates have side effects worth knowing before running them:

- `lowest-deps` (`uv sync --resolution lowest-direct`) **rewrites `uv.lock`'s resolution in
  your working tree**. The runner excludes it from a bare run for that reason; naming it (or
  `--all`) is the opt-in. Since #71 it also re-syncs the lock in a `finally` once the gate
  finishes, so a red or interrupted run recovers too — run the bare command line by hand and
  the manual `uv sync` is still yours to remember.
- `rhiza-test` runs this package's own checks against this repository. CI wraps the pytest
  call in a `grep` guard that fails the job if any check *skips*, and checks out with
  `fetch-depth: 0` so the tag-comparing assertions have tags to compare (#34). The README's
  copy stops at the pytest invocation, because the guard is a property of the pipeline —
  `scripts/gates.py` carries the guard, so a local pass means what CI's does. Its job also
  sets `RHIZA_DOCTEST_FOLDERS` to `"src scripts"`, and `GATE_ENV` in `scripts/gates.py`
  carries that for the same reason (#81): the variable's own fallback is `src` alone, so
  leaving it unset held `scripts/` to a docstring *presence* bar with nothing running the
  examples in those docstrings. It cannot live in the README fence — `_run` splits a
  documented line with `shlex.split` and no shell, so a `KEY=value` prefix would become
  `argv[0]` — so the value has two homes, and `tests/test_readme_gates.py` pins them
  together in both directions the way it already pins the README to `ci.yml`.

Thresholds are deliberately single-homed: the 100% docstring floor, the 90% coverage floor
and `mypy`'s `--strict` all live on their CI command lines and are **not** mirrored into
`pyproject.toml`, so there is one place to change each. There is no `[tool.mypy]` table and
adding one would create a second home.

**Type checking runs two checkers** (#67), over `src` and `scripts` but never `tests/`.
`ty` is fast inference; `mypy --strict` additionally demands annotations, which `ty` has no
opinion on — on adoption it found 61 errors in code `ty` passed clean, including a real
disagreement where `bumpversion_table` returned a non-table that `has_bumpversion_section`
called absent. Keep both: dropping `ty` loses speed, dropping `mypy` loses the annotation
floor that keeps `Any` from spreading back in.

## Architecture

**Two halves, because pytest treats them differently.**

*Fixtures* arrive through the `pytest11` entry point (`plugin.py`), so a consumer needs no
`conftest.py`: `root` (the repository under test), `logger`, `latest_tag` (newest `vX.Y.Z`,
skipping when there are none).

*Checks* are tests, which an entry point cannot contribute, so they are named explicitly:
`pytest --pyargs pytest_rhiza.checks.test_readme …`. One module per file the template used
to sync, **names unchanged**. Selection is a property of the consumer's declared layer set
(`[tool.rhiza-task] layers`), never sniffed from its manifest at runtime — a misconfigured
repo should go red, not quietly run a different check set.

### Root resolution is the one behaviour change from the synced suite

`.rhiza/tests/conftest.py` counted directories up from `__file__`, which was sound while
the code lived in the repository and is wrong once installed. `_resolve_root` is now a
three-rung ladder: `--rhiza-root`, then the config file's directory, then **the invocation
directory** — not `config.rootpath`, because with no config file pytest derives rootdir
from the arguments, and under `--pyargs` those point into site-packages.

### Private helpers exist because one distribution is the shared home

`_fences`, `_bumpversion`, `_versions`, `_source_folder`, `_process` hold logic that
upstream was **duplicated across bundles** — a Rust project received one file and not the
other, so a shared helper would have needed a third home both bundles shipped. One
distribution *is* that third home, so the trade reversed. Each module's docstring records
the specific reason; read it before folding one back into a check.

`_toml` is the exception to that story: it holds one type alias, `TomlTable`, and exists
so the reason TOML values are `Any` is written once instead of implied at forty call sites.

Two of them encode non-obvious decisions:

- `_process` gives every child process an explicit timeout. `pytest-timeout` cannot do this
  job: it takes its bound from the **consumer's** ini setting, and nothing here sets a
  default — this repo's own `timeout = 60` is exactly why the gap was invisible (#44).
- `_versions` asserts the declared version is *not behind* the newest tag rather than equal
  to it, because `/rhiza:release` is two-phase: phase A bumps the version on a PR, phase B
  tags the merged commit, and equality cannot hold in between (#62).

## Testing model

Two harnesses, and the distinction matters when adding tests (`tests/conftest.py` documents
it in full):

- **`pytester`** — runs pytest inside pytest, in-process. The honest way to test *fixtures*
  whose job is answering "which repository is this".
- **`subject`** — builds a throwaway git repository and runs the real
  `--pyargs … --rhiza-root …` command line against it **in a subprocess**. This is the only
  way to test the *checks*, because that is the code path every consumer uses; `pytester`
  drives a different one.

Consequence: coverage of `src/pytest_rhiza/checks/` comes entirely from those subprocesses,
which is why `[tool.coverage.run] patch = ["subprocess"]` is set. Without it that whole
directory reads as 0% however well tested it is.

The floor covers **`scripts` as well as `src`** (#69). Nothing under `scripts/` ships in the
wheel, so it was outside the measurement at first — but `gates.py` is what decides whether
every other gate is green, and being typed and interrogated with no coverage behind it left
its whole selection path unreached.

Most subjects need to be a git repo with a tag — the version checks compare a manifest
against tag state, and with no repository they *skip*, which reads as a pass. That failure
mode (#34) is the one this suite is most careful about.

## Conventions with teeth

- **Source modules under `checks/` are named `test_*.py` on purpose** — they are collected
  out of site-packages by name, so that *is* the published interface. Test-layout mirroring
  is therefore opted out of in `[tool.check_test_layout]` with a recorded reason; tests are
  organised by behaviour in `tests/` instead.
- **Docstring coverage is 100% over `src` *and* `tests`** — a test whose name is its only
  explanation is what that bar exists to prevent. Docstrings here carry real doctests (90 of
  them — 84 under `src`, 6 in `scripts/gates.py`); `_resolve_root` documents its ladder by
  example precisely because a fixture needs a live session to exercise. The doctest gate
  walks both folders since #81; before that an example under `scripts/` would have been
  collected by nothing, and `test_doctests` *skips* rather than fails when it attempts
  none.
- **Version numbers live in exactly two places**, kept in step by
  `[[tool.bumpversion.files]]`: `[project].version` (read natively) and
  `pytest_rhiza.__version__`. `tests/test_version.py` asserts both that they agree and that
  the bumpversion entry still exists. It sat three releases stale when that entry was
  described in a comment but never written (#12).
- **No version literal in `README.md`.** The documented pin is a `<version>` placeholder;
  nothing bumps a number written there, so it rotted at `0.1.0` for three releases (#17).
  `tests/test_readme_pin.py` keeps a literal from creeping back.
- **`src/pytest_rhiza/py.typed` is what makes `mypy --strict` worth anything to a consumer.**
  Without the PEP 561 marker a type checker must treat the installed package as untyped, so
  every annotation stops at this repository's edge (#73). `tests/test_py_typed.py` guards it
  in two directions, because the failure is silent here: the suite runs against an editable
  install, which finds the marker in `src` whether or not the wheel would ship it.
- **Nothing here invokes `jebel-quant/rhiza`.** That repo pins pytest-rhiza as a dependency,
  so calling its reusable CI would close a cycle — rhiza's workflow running the gates that
  judge the package rhiza depends on. `rhiza_release.yml` is the one exception, synced
  verbatim because PyPI Trusted Publishing validates the exact workflow path.
- **The `pytest>=8.1` floor is bisected, not guessed.** 8.0.x walks the generic ancestor
  chain of a `--pyargs` argument and dies on an unstat-able `/home` entry on GitHub runners
  (#23). The `lowest-deps` gate is what stops that floor rotting.
- **Third-party actions are SHA-pinned** with the version in a trailing comment, kept moving
  by `.github/dependabot.yml`.
