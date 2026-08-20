"""``pytest_rhiza.__version__`` and ``[project].version`` are one fact recorded twice.

Issue #12: ``__version__`` read ``"0.1.0"`` while the project was at 0.2.2 — three
releases of drift, from a comment that described a mechanism nobody had built. It claimed
bump-my-version kept the two in step and that "no ``[[files]]`` entry is needed for
pyproject.toml itself, only for this one", while no entry for *this one* existed either.

Two tests, because the drift and its cause become visible at different times:

* :func:`test_dunder_version_matches_pyproject` catches the drift, but only once it has
  happened — which is to say, on the release commit that introduced it.
* :func:`test_bumpversion_rewrites_the_dunder_version` catches the *cause*. Deleting the
  ``[[tool.bumpversion.files]]`` entry produces no drift until the next bump, so without
  this the removal would sail through review and surface one bad release later.

The pattern is borrowed from the checks this package ships: ``checks/test_cargo_toml.py``
and ``checks/test_go_module.py`` both assert that their release config still targets the
file the version actually lives in, and anchor the search rather than trusting a bare
version string. Same invariant, applied to this repository's own manifest.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest_rhiza

# The location bump-my-version must rewrite alongside [project].version, spelled the way
# a TOML `filename` key does — forward slashes on every platform.
VERSION_MODULE = "src/pytest_rhiza/__init__.py"

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _pyproject() -> dict:
    """Return this repository's own pyproject.toml, parsed.

    Returns:
        The parsed manifest. Read at test time rather than captured in a constant so a
        stale value cannot be what the assertions compare against.
    """
    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)


def test_dunder_version_matches_pyproject() -> None:
    """``__version__`` must equal ``[project].version``."""
    declared = _pyproject()["project"]["version"]

    assert pytest_rhiza.__version__ == declared, (
        f"pytest_rhiza.__version__ is {pytest_rhiza.__version__!r} but [project].version "
        f"is {declared!r}. A release rewrote one and not the other, which means the "
        f"[[tool.bumpversion.files]] entry for {VERSION_MODULE} is missing or no longer "
        f"matches the line it targets (#12)."
    )


def test_bumpversion_rewrites_the_dunder_version() -> None:
    """A ``[[tool.bumpversion.files]]`` entry must target the version module, anchored.

    Anchored to ``__version__`` specifically: ``search`` is applied to every occurrence
    in the file, and this module's docstring is prose that could easily come to mention a
    version. A bare number would rewrite that too.
    """
    entries = [
        entry
        for entry in _pyproject().get("tool", {}).get("bumpversion", {}).get("files", [])
        if entry.get("filename") == VERSION_MODULE
    ]

    assert entries, (
        f"no [[tool.bumpversion.files]] entry targets {VERSION_MODULE}, so a bump would "
        f"rewrite [project].version and leave __version__ behind — which is exactly how it "
        f"came to sit three releases stale (#12)."
    )
    for entry in entries:
        search = str(entry.get("search", ""))
        assert "__version__" in search, (
            f"the {VERSION_MODULE} entry's search {search!r} is not anchored to the "
            f"__version__ assignment; applied to every occurrence in the file, a bare "
            f"version would also rewrite one mentioned in the module docstring."
        )
