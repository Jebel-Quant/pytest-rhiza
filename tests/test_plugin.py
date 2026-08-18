"""Tests for the fixtures the ``pytest11`` entry point contributes.

The ``root`` fixture is the one thing this port genuinely changed — the synced conftest
counted directories up from ``__file__``, which stops being the repository once the code
is installed — so its three resolution branches are pinned here individually.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404
from pathlib import Path

import pytest

_GIT = shutil.which("git") or "/usr/bin/git"


def _git(cwd: Path, *args: str) -> None:
    """Run a git command in ``cwd``, failing the test if it errors.

    Args:
        cwd: Directory to run in.
        args: Arguments after the ``git`` executable.
    """
    subprocess.run([_GIT, *args], cwd=cwd, check=True, capture_output=True)  # nosec B603


class TestRootResolution:
    """``root`` must name the project under test, never the installed package."""

    def test_root_is_the_directory_holding_the_config_file(self, pytester: pytest.Pytester) -> None:
        """With an ini file present, the root is its directory."""
        pytester.makeini("[pytest]\n")
        pytester.makepyfile(
            test_root="""
            def test_root_matches_inipath(root, request):
                assert request.config.inipath is not None
                assert root == request.config.inipath.parent
            """
        )
        pytester.runpytest().assert_outcomes(passed=1)

    def test_root_falls_back_to_the_invocation_directory(self, pytester: pytest.Pytester) -> None:
        """With no ini file, the root is where pytest was invoked.

        Not ``config.rootpath``: with no ini file pytest derives the rootdir from the
        arguments, and under ``--pyargs`` those are site-packages paths.
        """
        pytester.makepyfile(
            test_root="""
            from pathlib import Path

            def test_root_matches_invocation_dir(root, request):
                assert request.config.inipath is None
                assert root == Path(request.config.invocation_params.dir)
            """
        )
        pytester.runpytest().assert_outcomes(passed=1)

    def test_rhiza_root_option_wins(self, pytester: pytest.Pytester, tmp_path: Path) -> None:
        """``--rhiza-root`` overrides detection, which is how a repo elsewhere is checked."""
        elsewhere = tmp_path / "some-other-repo"
        elsewhere.mkdir()
        pytester.makeini("[pytest]\n")
        pytester.makepyfile(
            test_root=f"""
            from pathlib import Path

            def test_root_is_the_override(root):
                assert root == Path({str(elsewhere)!r})
            """
        )
        pytester.runpytest("--rhiza-root", str(elsewhere)).assert_outcomes(passed=1)


class TestLatestTag:
    """``latest_tag`` reads git, and skips rather than fails where there is nothing to read."""

    def test_skips_when_the_repository_has_no_tags(self, pytester: pytest.Pytester) -> None:
        """A project that has never released must not fail the version checks."""
        pytester.makeini("[pytest]\n")
        pytester.makepyfile(
            test_tag="""
            def test_needs_a_tag(latest_tag):
                raise AssertionError("should not run")
            """
        )
        pytester.runpytest().assert_outcomes(skipped=1)

    def test_reports_the_newest_tag_by_version_order(self, pytester: pytest.Pytester) -> None:
        """v0.10.0 beats v0.9.0 — version order, not the lexicographic order git defaults to."""
        repo = pytester.path
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "test")
        (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        _git(repo, "add", "seed.txt")
        _git(repo, "commit", "-q", "-m", "seed")
        for tag in ("v0.9.0", "v0.10.0", "v0.2.0"):
            _git(repo, "tag", tag)

        pytester.makeini("[pytest]\n")
        pytester.makepyfile(
            test_tag="""
            def test_newest(latest_tag):
                assert latest_tag == "v0.10.0"
            """
        )
        pytester.runpytest().assert_outcomes(passed=1)
