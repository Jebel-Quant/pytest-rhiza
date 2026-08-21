"""The tag-versus-declared-version rule is an inequality, and the direction matters.

Issue #62: all three language layers asserted ``declared == newest tag``. That is true of
a repository sitting between releases, and false of one *during* a release — which is the
only time the assertion gets read by anyone. ``/rhiza:release`` is two-phase by necessity
(a squash-merge rewrites the branch's commits, so a tag cut before the merge names a SHA
that never lands), so the bump lands by pull request and the tag follows. For the whole
life of that pull request the manifest leads the newest tag by one step.

The check runs in CI and feeds the branch-protection gate, so equality did not merely
misreport — it made every release pull request unmergeable. It had been dormant only
because CI checked out shallow and the ``latest_tag`` fixture skipped (#34); closing that
is what exposed this.

These tests pin the direction, because a future simplification back to ``==`` would look
tidier and would resurrect the bug:

* :func:`test_ahead_is_a_release_in_flight` is the case equality got wrong.
* :func:`test_behind_is_drift` is the defect the assertion actually exists to catch, and
  must keep failing.
* :func:`test_equal_is_the_steady_state` is the between-releases case, which both the old
  and the new rule accept — it is here so a mistaken inversion cannot pass unnoticed.
"""

from __future__ import annotations

import pytest

from pytest_rhiza._versions import assert_declared_version_not_behind_tag

# The two strings every call needs and no assertion reads for its verdict. Held here so
# the cases below show only the versions under test.
CONTEXT = {"location": "[project].version in pyproject.toml", "consequence": "the next release would misfire."}


def test_ahead_is_a_release_in_flight() -> None:
    """A manifest one step past the newest tag is the normal state of a release PR."""
    assert_declared_version_not_behind_tag("v0.2.2", "0.3.0", **CONTEXT)


def test_equal_is_the_steady_state() -> None:
    """Between releases the two agree, which was the only case equality allowed."""
    assert_declared_version_not_behind_tag("v0.3.0", "0.3.0", **CONTEXT)


def test_behind_is_drift() -> None:
    """A manifest older than the newest tag is the defect, and must still fail."""
    with pytest.raises(AssertionError, match="is behind the newest git tag"):
        assert_declared_version_not_behind_tag("v0.3.0", "0.2.2", **CONTEXT)


def test_comparison_is_semver_not_lexicographic() -> None:
    """``0.10.0`` beats ``0.9.0``; string comparison would call it drift.

    The old assertion compared strings for equality, so it never had to order two
    versions and never met this. An inequality does, and getting it wrong would fail
    exactly one release in ten.
    """
    assert_declared_version_not_behind_tag("v0.9.0", "0.10.0", **CONTEXT)
    with pytest.raises(AssertionError, match="is behind the newest git tag"):
        assert_declared_version_not_behind_tag("v0.10.0", "0.9.0", **CONTEXT)


def test_the_failure_message_names_both_versions_and_the_location() -> None:
    """A drift report is only actionable if it says which two numbers disagree."""
    with pytest.raises(AssertionError) as excinfo:
        assert_declared_version_not_behind_tag(
            "v1.2.0",
            "1.1.0",
            location="the Version constant in internal/version/version.go",
            consequence="consumers would fetch something else.",
        )
    message = str(excinfo.value)
    assert "'1.1.0'" in message
    assert "'v1.2.0'" in message
    assert "internal/version/version.go" in message
    assert "consumers would fetch something else." in message


@pytest.mark.parametrize(
    ("tag", "declared"),
    [
        ("v-not-a-version", "0.3.0"),
        ("v0.3.0", "not-a-version"),
    ],
)
def test_unparseable_versions_fail_as_assertions(tag: str, declared: str) -> None:
    """A malformed version is a failure, not an ``InvalidVersion`` escaping the check.

    These modules are collected as tests in consumer repositories, so an uncaught
    exception reads as an error rather than a legible complaint about the manifest.
    """
    with pytest.raises(AssertionError, match="not a valid version"):
        assert_declared_version_not_behind_tag(tag, declared, **CONTEXT)
