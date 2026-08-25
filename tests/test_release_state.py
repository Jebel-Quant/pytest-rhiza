"""Unit tests for ``_release_state``: the bound on how long a release may stay in flight.

``_versions`` permits the declared version to lead the newest tag, because that is what a
release in flight looks like (#62). ``_release_state`` bounds how long it may lead for
(#85). Both halves matter here: a release that is genuinely in flight must stay green, and
one that stopped must go red, so most of these tests are about the *quiet* paths.

The git-backed functions are exercised against real throwaway repositories from the
``subject`` factory rather than against a mocked ``git``, for the same reason the checks
are: what is being asserted is what git actually answers.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from pytest_rhiza._release_state import (
    DEFAULT_GRACE_DAYS,
    GRACE_DAYS_ENV,
    assert_release_not_stalled,
    default_branch,
    grace_days,
    merged_bump_date,
    stalled_for,
)

if TYPE_CHECKING:  # pragma: no cover - import only for the fixture's type
    from conftest import Subject

PYPROJECT = """
[project]
name = "demo"
version = "0.4.1"
"""


def _with_origin(repo: Subject) -> Subject:
    """Give a subject an ``origin/HEAD`` without giving it a remote.

    ``default_branch`` reads ``refs/remotes/origin/HEAD``, which a bare ``git init`` never
    writes. Creating the two refs by hand is enough and avoids a second repository: what
    is under test is the lookup, not git's clone machinery.

    Args:
        repo: The subject to annotate.

    Returns:
        The same subject, now with ``origin/HEAD`` pointing at ``origin/main``.
    """
    repo.git("update-ref", "refs/remotes/origin/main", "HEAD")
    repo.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    return repo


class TestGraceDays:
    """The bound is a default with an environment override, like the process timeouts."""

    def test_the_default_applies_when_nothing_is_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unset variable means the default rather than no bound at all."""
        monkeypatch.delenv(GRACE_DAYS_ENV, raising=False)
        assert grace_days() == DEFAULT_GRACE_DAYS

    def test_a_slower_cadence_can_raise_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A project that genuinely releases less often is the case the knob exists for."""
        monkeypatch.setenv(GRACE_DAYS_ENV, "30")
        assert grace_days() == 30

    def test_a_typo_falls_back_rather_than_removing_the_bound(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A misspelled value must not be able to disable the check silently."""
        monkeypatch.setenv(GRACE_DAYS_ENV, "soon")
        assert grace_days() == DEFAULT_GRACE_DAYS


class TestDefaultBranch:
    """Naming the default branch, and admitting when git cannot."""

    def test_it_reads_origin_head(self, subject: Callable[..., Subject]) -> None:
        """The ordinary case: a clone has origin/HEAD and it names the default branch."""
        repo = _with_origin(subject({"pyproject.toml": PYPROJECT}, tag="v0.4.0"))

        assert default_branch(repo.path) == "origin/main"

    def test_a_repository_without_a_remote_answers_none(self, subject: Callable[..., Subject]) -> None:
        """`git init` writes no origin/HEAD, and that is unjudgeable rather than wrong."""
        repo = subject({"pyproject.toml": PYPROJECT}, tag="v0.4.0")

        assert default_branch(repo.path) is None


class TestMergedBumpDate:
    """Finding the commit that wrote the declared version into the manifest."""

    def test_it_finds_the_commit_that_introduced_the_version(self, subject: Callable[..., Subject]) -> None:
        """The pickaxe reports the commit where the version's occurrence count changed."""
        repo = _with_origin(subject({"pyproject.toml": PYPROJECT}, tag="v0.4.0"))

        found = merged_bump_date(repo.path, "origin/main", "pyproject.toml", "0.4.1")

        assert found is not None
        assert stalled_for(found, datetime.now(UTC)) == 0

    def test_a_version_never_written_to_the_manifest_answers_none(self, subject: Callable[..., Subject]) -> None:
        """Nothing on the default branch introduced it, which is phase A still in flight."""
        repo = _with_origin(subject({"pyproject.toml": PYPROJECT}, tag="v0.4.0"))

        assert merged_bump_date(repo.path, "origin/main", "pyproject.toml", "9.9.9") is None

    def test_a_ref_git_cannot_resolve_answers_none(self, subject: Callable[..., Subject]) -> None:
        """A branch that does not exist is unjudgeable, not a stalled release."""
        repo = subject({"pyproject.toml": PYPROJECT}, tag="v0.4.0")

        assert merged_bump_date(repo.path, "origin/nope", "pyproject.toml", "0.4.1") is None


class TestStalledFor:
    """Reading git's committer date, and refusing the values it cannot have written."""

    def test_whole_days_elapsed(self) -> None:
        """The number in the failure message is whole days, not a fraction."""
        now = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)

        assert stalled_for("2026-08-21T20:16:41+04:00", now) == 3

    def test_an_unparseable_date_is_unjudgeable(self) -> None:
        """Something git could not have written means no verdict, rather than a failure."""
        assert stalled_for("last Tuesday", datetime.now(UTC)) is None

    def test_a_naive_timestamp_is_unjudgeable(self) -> None:
        """Comparing naive to aware raises; a naive stamp also names no actual moment."""
        assert stalled_for("2026-08-21T20:16:41", datetime.now(UTC)) is None


class TestAssertReleaseNotStalled:
    """The assertion itself: quiet in every state but the one it exists to catch."""

    def test_a_bump_merged_long_ago_and_never_tagged_fails(self, subject: Callable[..., Subject]) -> None:
        """The #85 state: phase A merged, phase B never ran, and nothing said so."""
        repo = _with_origin(subject({"pyproject.toml": PYPROJECT}, tag="v0.4.0"))
        later = datetime.now(UTC) + timedelta(days=10)

        with pytest.raises(AssertionError, match="never tagged and never published"):
            assert_release_not_stalled(repo.path, "v0.4.0", "0.4.1", manifest="pyproject.toml", now=later)

    def test_a_release_merged_moments_ago_is_still_in_flight(self, subject: Callable[..., Subject]) -> None:
        """Phase B follows a merge by minutes, and that window must stay green."""
        repo = _with_origin(subject({"pyproject.toml": PYPROJECT}, tag="v0.4.0"))

        assert_release_not_stalled(repo.path, "v0.4.0", "0.4.1", manifest="pyproject.toml")

    def test_the_steady_state_is_quiet(self, subject: Callable[..., Subject]) -> None:
        """Declared equals the newest tag: no release in flight, nothing to bound."""
        repo = _with_origin(subject({"pyproject.toml": PYPROJECT}, tag="v0.4.1"))
        later = datetime.now(UTC) + timedelta(days=365)

        assert_release_not_stalled(repo.path, "v0.4.1", "0.4.1", manifest="pyproject.toml", now=later)

    def test_an_open_release_pr_is_quiet(self, subject: Callable[..., Subject]) -> None:
        """While the bump is only on the PR branch it is not on the default branch."""
        repo = subject({"pyproject.toml": PYPROJECT}, tag="v0.4.0")
        repo.git("update-ref", "refs/remotes/origin/main", "HEAD")
        repo.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        repo.write({"pyproject.toml": PYPROJECT.replace("0.4.1", "0.5.0")})
        repo.commit("chore: release v0.5.0")
        later = datetime.now(UTC) + timedelta(days=10)

        # origin/main still points at the seed commit, so 0.5.0 is not merged.
        assert_release_not_stalled(repo.path, "v0.4.0", "0.5.0", manifest="pyproject.toml", now=later)

    def test_a_repository_without_origin_head_is_quiet(self, subject: Callable[..., Subject]) -> None:
        """With no default branch, "merged" has no meaning and there is nothing to judge."""
        repo = subject({"pyproject.toml": PYPROJECT}, tag="v0.4.0")
        later = datetime.now(UTC) + timedelta(days=10)

        assert_release_not_stalled(repo.path, "v0.4.0", "0.4.1", manifest="pyproject.toml", now=later)

    def test_a_malformed_version_is_left_to_the_other_assertion(self, subject: Callable[..., Subject]) -> None:
        """`assert_declared_version_not_behind_tag` reports these; two reports is noise."""
        repo = _with_origin(subject({"pyproject.toml": PYPROJECT}, tag="v0.4.0"))

        assert_release_not_stalled(repo.path, "v0.4.0", "not-a-version", manifest="pyproject.toml")
        assert_release_not_stalled(repo.path, "vNOPE", "0.4.1", manifest="pyproject.toml")
