"""The ``pytest11`` entry point: shared fixtures for the rhiza checks.

This is ``.rhiza/tests/conftest.py`` from the template, with one necessary change. The
synced file resolved the repository root by counting directories up from ``__file__``,
which worked because it *was* in the repository. Installed into site-packages it no
longer is, so the root is taken from pytest instead — see :func:`root`.

Everything here is language-neutral (paths and git), which is why the template made
``core`` rather than a language layer own it. That property is what lets one
distribution serve Python, Rust and Go projects alike.

Security Notes:
- S101 (assert usage): Asserts are appropriate in test code for validating conditions
"""

from __future__ import annotations

import logging
import pathlib
import shutil
import subprocess  # nosec B404

import pytest

_GIT = shutil.which("git") or "/usr/bin/git"


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register ``--rhiza-root``, the manual override for root detection.

    Needed for two cases: a repository whose layout defeats the inference in
    :func:`root`, and this package's own test suite, which points the checks at throwaway
    repositories under ``tmp_path``.

    Args:
        parser: The pytest option parser.
    """
    group = parser.getgroup("rhiza", "rhiza repository checks")
    group.addoption(
        "--rhiza-root",
        action="store",
        default=None,
        metavar="DIR",
        help="Repository to check, overriding automatic detection (default: the rootdir).",
    )


def _resolve_root(
    override: str | None,
    inipath: pathlib.Path | None,
    invocation_dir: pathlib.Path,
) -> pathlib.Path:
    """Pick the repository root from the three things that can name it.

    Split out of the :func:`root` fixture so the resolution order is documented by
    something that runs. A fixture needs a live pytest session to exercise, which is why
    this ladder went undocumented-by-example for so long.

    Args:
        override: The ``--rhiza-root`` value, or None.
        inipath: Path to the config file pytest found, or None when there is none.
        invocation_dir: The directory pytest was invoked from.

    Returns:
        The repository root.

    Examples:
        These read results back through ``.as_posix()`` and ``.name`` rather than
        repr'ing the ``Path``. ``repr`` would print ``PosixPath`` here and
        ``WindowsPath`` on the Windows leg of the matrix, so a doctest asserting it
        would measure the platform instead of the ladder.

        ``--rhiza-root`` wins outright, over both of the other two:

        >>> _resolve_root("/repo", pathlib.Path("/ini/pytest.ini"), pathlib.Path("/cwd")).name
        'repo'

        With no override, the directory holding the config file:

        >>> _resolve_root(None, pathlib.Path("/repo/pytest.ini"), pathlib.Path("/cwd")).as_posix()
        '/repo'

        With neither, the invocation directory — *not* ``rootpath``, which under
        ``--pyargs`` can point into site-packages:

        >>> _resolve_root(None, None, pathlib.Path("/repo")).as_posix()
        '/repo'

        An empty ``--rhiza-root`` is treated as absent rather than as the current
        directory, so a shell expanding an unset variable falls through to the ladder
        instead of silently checking the wrong tree:

        >>> _resolve_root("", pathlib.Path("/repo/pytest.ini"), pathlib.Path("/cwd")).as_posix()
        '/repo'
    """
    if override:
        return pathlib.Path(override).absolute()
    if inipath is not None:
        return inipath.parent
    return pathlib.Path(invocation_dir)


@pytest.fixture(scope="session")
def root(pytestconfig: pytest.Config) -> pathlib.Path:
    """Return the repository under test as a :class:`pathlib.Path`.

    Resolution order, and the reason it is not simply ``config.rootpath``:

    1. ``--rhiza-root``, when given.
    2. The directory holding the config file (``pytest.ini``, ``pyproject.toml``, …).
    3. The directory pytest was invoked from.

    Step 3 is the one that matters. With no config file present, pytest computes its
    rootdir from the *arguments*, and ``--pyargs pytest_rhiza.checks...`` resolves to
    paths inside site-packages — so ``rootpath`` can point at the installed package
    rather than at the project. The invocation directory cannot: ``make rhiza-test``
    runs at the repository root.

    The ladder itself lives in :func:`_resolve_root`, where it is doctested.

    Args:
        pytestconfig: The session's pytest config.

    Returns:
        The repository root.
    """
    return _resolve_root(
        pytestconfig.getoption("rhiza_root"),
        pytestconfig.inipath,
        pathlib.Path(pytestconfig.invocation_params.dir),
    )


@pytest.fixture(scope="session")
def logger() -> logging.Logger:
    """Provide a session-scoped logger for the checks.

    Returns:
        logging.Logger: Logger configured for the test session.
    """
    return logging.getLogger("pytest_rhiza")


@pytest.fixture(scope="session")
def latest_tag(root: pathlib.Path) -> str:
    """Return the newest ``vX.Y.Z`` git tag, skipping when the repo has none.

    Shared rather than per-module because each language layer asserts the same thing
    against a different file — ``[project].version``, ``[package].version``, or Go's
    ``Version`` constant — and because every layer's release config derives its current
    version from this tag.

    Args:
        root: Repository root, from the :func:`root` fixture.

    Returns:
        str: The highest version tag, e.g. ``v1.3.1``.
    """
    result = subprocess.run(  # noqa: S603 - fixed argument list, no shell  # nosec B603
        [_GIT, "tag", "--list", "v*", "--sort=-version:refname"],
        capture_output=True,
        text=True,
        cwd=root,
    )
    tags = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not tags:
        pytest.skip("No version tags found in repository")
    return tags[0]
