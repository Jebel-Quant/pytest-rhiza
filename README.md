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
four small packages — folding them into `rhiza` would pull `jinja2`, `typer`, `rich` and
`loguru` into every test environment, and into `rhiza-tools` would add `pandas` and
`plotly`.

## Install

```bash
uv add --dev pytest-rhiza
```

Or, the way `make rhiza-test` does it, without touching the project's dependencies:

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
ships, and `make rhiza-test` executes it against this README — so adding or removing a
check without updating the list above turns this block red:

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

## Two things still to decide

**Version pinning.** Today the checks and the template move as one — `template.lock` pins
a ref and the files come with it. A separate distribution adds a second version axis. The
recipe above pins an exact version so there is still one number to reason about, but the
sync has to *generate* that pin from the template release. The alternative is aligning
this package's `major.minor` with template releases and pinning `~=`.

**Removing the old folder.** A consumer on the current template has `.rhiza/tests/` on
disk. The sync ceasing to deliver it does not delete it, and a leftover copy would run
twice as long as `pythonpath` still finds it. The migration PR needs an explicit removal
step.

## Development

```bash
uv sync
uv run pytest
```

The checks run against this repository too — it is a Python project with a README, a
`pyproject.toml` and a release config, so it is a valid subject for its own assertions:

```bash
uv run pytest --pyargs pytest_rhiza.checks.test_readme pytest_rhiza.checks.test_pyproject
```

## License

MIT — see [LICENSE](LICENSE).
