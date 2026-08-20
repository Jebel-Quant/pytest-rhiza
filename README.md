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

### Which repository is "root"

The one deliberate behaviour change from the synced suite. `.rhiza/tests/conftest.py`
resolved the root by counting directories up from `__file__` — sound while the code lived
*in* the repository, wrong once it is installed. Resolution is now:

1. `--rhiza-root`, when given
2. the directory holding the config file (`pytest.ini`, `pyproject.toml`, …)
3. the directory pytest was invoked from

Step 3 rather than `config.rootpath` on purpose: with no config file, pytest derives its
rootdir from the arguments, and under `--pyargs` those are paths inside site-packages.

## The make wiring this expects

Selection stays exactly where the template already has it — with the bundle that owns the
assertion, resolved at sync time — because each bundle's make fragment names its own check
modules. No runtime manifest sniffing decides what applies, so a misconfigured repo still
goes red instead of quietly skipping.

`core`'s `quality.mk`:

```make
RHIZA_CHECKS ?= pytest_rhiza.checks.test_readme pytest_rhiza.checks.test_release_tags

rhiza-test: install ## run the rhiza repository checks
	@${UV_BIN} run --with 'pytest-rhiza==<version>' pytest --pyargs ${RHIZA_CHECKS}
```

`<version>` is a placeholder, not a value to copy. The sync generates the pin from the
template release — see [Version pinning](#two-things-still-to-decide) — so the number that
lands in a consumer's `quality.mk` is never written by hand here. It is also spelled this
way because a literal cannot survive: nothing bumps this file (there is no
`[[tool.bumpversion.files]]` entry for it) and nothing checks it either — a ```` ```make ````
fence is reported by the docs check as *skipped — make fences are not checkable*, and the
README's `bash` fences are only parsed by `bash -n`, never resolved against reality. The
pin here read `0.1.0` for three releases for exactly that reason. `tests/test_readme_pin.py`
is now the thing that notices.

`python-core`'s `python.mk` appends its own, and `rust-core` / `go-core` / `tests` do the
same with theirs:

```make
RHIZA_CHECKS += pytest_rhiza.checks.test_pyproject pytest_rhiza.checks.test_docstrings
```

That is one `+=` line per bundle, replacing one synced file per bundle.

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

`make help` lists the gates. Every one of them is what CI runs, so a green local sweep
means a green pipeline:

| target | what it runs |
| --- | --- |
| `make lint` | all pre-commit hooks, via prek |
| `make typecheck` | `ty check src` |
| `make docs-coverage` | interrogate over `src` and `tests`, at a 100% floor |
| `make security` | bandit over `src` |
| `make test` | the suite, with the 90% coverage gate |

`typecheck`, `docs-coverage` and `security` take their flags from the reusable workflow
`jebel-quant/rhiza/.github/workflows/rhiza_ci.yml`, so the recipes mirror those jobs
rather than setting a threshold of their own — see the comment above them in the
`Makefile`.

The checks run against this repository too — it is a Python project with a README, a
`pyproject.toml` and a release config, so it is a valid subject for its own assertions:

```bash
uv run pytest --pyargs pytest_rhiza.checks.test_readme pytest_rhiza.checks.test_pyproject
```

## License

MIT — see [LICENSE](LICENSE).
