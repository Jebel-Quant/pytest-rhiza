"""Test configuration for pytest-rhiza's own suite.

``pytester`` is what lets a plugin's tests run pytest inside pytest: each test gets a
throwaway directory, and assertions are made about the inner run's outcomes. That is the
only honest way to test fixtures whose whole job is to answer "which repository is this".

The other harness here is :func:`subject`, and it exists because the *checks* cannot be
tested that way. A check module is collected out of site-packages by name — ``pytest
--pyargs pytest_rhiza.checks.test_pyproject`` — and judges a repository it is pointed at
with ``--rhiza-root``. So exercising one means building a repository for it to judge and
running the real command line against it, in a subprocess, exactly as a consumer does.
``pytester`` cannot stand in for that: it drives an *in-process* run over files it writes
itself, which is a different code path from the one every rhiza-managed repo uses.

Two consequences worth knowing before adding tests here:

* Coverage of ``src/pytest_rhiza/checks/`` comes entirely from these subprocesses, which
  is why ``[tool.coverage.run] patch = ["subprocess"]`` is set in pyproject.toml.
* A subject usually needs to be a git repository with a tag, because the version checks
  compare a manifest against ``git describe``-style state. :meth:`Subject.commit` and the
  ``tag`` argument to the factory cover that.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from textwrap import dedent

import pytest

pytest_plugins = ["pytester"]

_GIT = shutil.which("git") or "/usr/bin/git"


class Subject:
    """A throwaway repository the installed checks are run against.

    Attributes:
        path: The repository root, which is what ``--rhiza-root`` is pointed at.
    """

    def __init__(self, path: Path) -> None:
        """Store the repository root.

        Args:
            path: Directory that plays the part of a consumer repository.
        """
        self.path = path

    def write(self, files: Mapping[str, str]) -> None:
        """Write files into the subject, creating parent directories as needed.

        Args:
            files: Repository-relative path to file content. Content is passed through
                :func:`textwrap.dedent` and stripped of one leading newline, so callers
                can use indented triple-quoted strings.
        """
        for name, text in files.items():
            target = self.path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            # newline="\n" rather than the platform default: a subject is *input to a
            # parser*, and the fence regexes in `_fences` are written against "\n". A
            # Windows runner silently rewriting them to "\r\n" would make these tests
            # measure the line-ending translation rather than the check.
            target.write_text(dedent(text).lstrip("\n"), encoding="utf-8", newline="\n")

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run one git command inside the subject.

        Args:
            args: Arguments after the ``git`` executable.

        Returns:
            The completed process; output is captured and stdout/stderr are text.
        """
        return subprocess.run(  # nosec B603
            [_GIT, *args], cwd=self.path, check=True, capture_output=True, text=True
        )

    def commit(self, message: str = "seed", *, tag: str | None = None) -> None:
        """Commit everything currently written, optionally tagging the result.

        Args:
            message: Commit message.
            tag: Tag to place on the new commit, e.g. ``v1.2.3``.
        """
        self.git("add", "-A")
        # --allow-empty: a subject may deliberately hold no files at all (the checks
        # then report the manifest as missing), and it still needs a commit to tag.
        self.git("commit", "-q", "--allow-empty", "-m", message)
        if tag is not None:
            self.git("tag", tag)

    def run(
        self,
        *modules: str,
        args: tuple[str, ...] = (),
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run the named installed check modules against this subject.

        The command line is the one a consumer repository uses, and it is run in a
        subprocess for the same reason: ``--pyargs`` resolves the modules out of
        site-packages, and the plugin's ``root`` fixture has to resolve the repository
        from ``--rhiza-root`` rather than from anything the outer session knows.

        Args:
            modules: Dotted module names, without the ``pytest_rhiza.checks.`` prefix.
            args: Extra arguments appended to the command line.
            env: Environment entries to add for this run. ``make rhiza-test`` configures
                the docstring check through ``RHIZA_DOCTEST_FOLDERS``, so that path is
                only reachable by setting it here.

        Returns:
            The completed process, with stdout and stderr captured as text.
        """
        return subprocess.run(  # nosec B603
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-q",
                "--tb=line",
                # Skip reasons are the check's verdict in the cases where skipping *is*
                # the right answer, so the tests have to be able to read them back.
                "-rs",
                "--pyargs",
                *(f"pytest_rhiza.checks.{name}" for name in modules),
                "--rhiza-root",
                str(self.path),
                *args,
            ],
            cwd=self.path,
            capture_output=True,
            text=True,
            env={**os.environ, **env} if env else None,
        )


@pytest.fixture
def subject(tmp_path_factory: pytest.TempPathFactory) -> Callable[..., Subject]:
    """Return a factory building throwaway repositories for the checks to judge.

    A fresh directory per call, so one test can compare a sound subject against a broken
    one. ``git=True`` is the default because most checks reach for a tag: the version
    tests compare a manifest against the newest ``vX.Y.Z``, and with no repository at all
    they skip rather than judge, which is the failure mode most likely to make a test
    look like it passed when it never ran.

    Args:
        tmp_path_factory: pytest's per-session temporary directory factory.

    Returns:
        ``make(files, *, tag=None, git=True) -> Subject``.
    """
    counter = 0

    def make(files: Mapping[str, str] | None = None, *, tag: str | None = None, git: bool = True) -> Subject:
        """Build one subject repository.

        Args:
            files: Repository-relative path to file content, written before the commit.
            tag: Tag to place on the seed commit, e.g. ``v1.2.3``.
            git: Whether to initialise a repository and commit. ``False`` leaves an empty
                directory, which is what a ``git clone`` target needs.

        Returns:
            The built subject.
        """
        nonlocal counter
        counter += 1
        root = tmp_path_factory.mktemp(f"subject{counter}")
        built = Subject(root)
        if files:
            built.write(files)
        if git:
            built.git("init", "-q")
            built.git("config", "user.email", "test@example.com")
            built.git("config", "user.name", "test")
            built.git("config", "commit.gpgsign", "false")
            built.commit(tag=tag)
        return built

    return make
