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

**There is a third home, and it was missed the same way.** ``uv.lock`` records this
project's own version in its ``pytest-rhiza`` package entry, and the v0.5.0 release
commit left it reading ``0.4.1`` — so the tagged tree declared two different versions of
itself. Every release up to v0.4.1 happened to be correct, which is what made it easy to
miss: nothing *asserted* it, so the lock stayed in step only for as long as whoever cut
the release happened to run a ``uv`` command between the bump and the commit. That is #12
again, one file over: a version location kept correct by habit rather than by mechanism.
The two tests below are duplicated for it, for the same reason there are two of them.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404
import tomllib
from pathlib import Path

import pytest

import pytest_rhiza

_GIT = shutil.which("git") or "/usr/bin/git"

# The location bump-my-version must rewrite alongside [project].version, spelled the way
# a TOML `filename` key does — forward slashes on every platform.
VERSION_MODULE = "src/pytest_rhiza/__init__.py"

#: The lockfile also records this project's own version, in its own package entry. Same
#: spelling rule as above: a TOML `filename` key, forward slashes on every platform.
LOCKFILE = "uv.lock"

#: The name uv records this project under in `uv.lock`, which is the distribution name
#: rather than the import name — the underscore form would match nothing.
DISTRIBUTION = "pytest-rhiza"

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _pyproject() -> dict:
    """Return this repository's own pyproject.toml, parsed.

    Returns:
        The parsed manifest. Read at test time rather than captured in a constant so a
        stale value cannot be what the assertions compare against.
    """
    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)


def _committed(path: str) -> str | None:
    """Return the committed content of a repository-relative path.

    **The working tree is the wrong thing to read here, and that is the whole point.**
    ``uv run`` re-locks before it runs anything, so by the time pytest imports this module
    the lockfile on disk has already been repaired to match the manifest — an assertion
    over the file would pass no matter what was committed. That is precisely why the drift
    went unnoticed: the ``test`` gate itself erases the evidence before reading it.

    Args:
        path: Repository-relative path, as git spells it.

    Returns:
        The file's content at ``HEAD``, or None when git cannot answer.
    """
    result = subprocess.run(
        [_GIT, "show", f"HEAD:{path}"],
        cwd=PYPROJECT.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def _locked_version(lock_text: str) -> str | None:
    """Return the version a lockfile records for this project.

    Parsed as TOML rather than matched with a regex: the lockfile *is* TOML, and its
    ``[[package]]`` entries are what carry the version, so reading the structure says
    exactly which package answered. A regex would have to re-derive that from adjacency.

    Args:
        lock_text: The lockfile's content.

    Returns:
        The version in this project's own package entry, or None when there is no entry
        for it.
    """
    for package in tomllib.loads(lock_text).get("package", []):
        if package.get("name") == DISTRIBUTION:
            return str(package.get("version", ""))
    return None


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


def test_the_committed_uv_lock_matches_the_committed_pyproject() -> None:
    """The committed tree must not declare two different versions of itself.

    Both sides are read from ``HEAD`` rather than from disk, and they have to be: see
    :func:`_committed` for why the working tree cannot answer this. Comparing committed
    against committed also keeps the test honest mid-edit — a manifest bumped but not yet
    committed is not drift, and reading one side from disk would report it as such.
    """
    lock_text = _committed(LOCKFILE)
    manifest_text = _committed("pyproject.toml")
    if lock_text is None or manifest_text is None:
        pytest.skip("no committed tree to read — git could not answer")

    locked = _locked_version(lock_text)
    declared = tomllib.loads(manifest_text)["project"]["version"]

    assert locked == declared, (
        f"the committed {LOCKFILE} records {DISTRIBUTION} at {locked!r} while the committed "
        f"[project].version is {declared!r}. A release rewrote the manifest and not the "
        f"lockfile, so the tagged tree declares two versions of itself — which is exactly "
        f"what v0.5.0 shipped."
    )


def test_bumpversion_rewrites_the_uv_lock_version() -> None:
    """A ``[[tool.bumpversion.files]]`` entry must target the lockfile, anchored.

    Anchoring matters more here than anywhere else in this repository. ``uv.lock`` holds a
    ``version`` line for *every* resolved package, so a bare ``{current_version}`` search
    would rewrite whichever one happened to sit at the same number — silently repinning a
    dependency as a side effect of a release. The anchor is the distribution name on the
    preceding line.
    """
    entries = [
        entry
        for entry in _pyproject().get("tool", {}).get("bumpversion", {}).get("files", [])
        if entry.get("filename") == LOCKFILE
    ]

    assert entries, (
        f"no [[tool.bumpversion.files]] entry targets {LOCKFILE}, so a bump would rewrite "
        f"[project].version and leave the lockfile behind. That is not hypothetical: it is "
        f"how the v0.5.0 tag came to carry a lockfile reading 0.4.1."
    )
    for entry in entries:
        search = str(entry.get("search", ""))
        assert DISTRIBUTION in search, (
            f"the {LOCKFILE} entry's search {search!r} is not anchored to {DISTRIBUTION!r}. "
            f"Every resolved package in the lockfile has a version line, so an unanchored "
            f"search can repin a dependency that happens to share this project's number."
        )
