"""Whether a release that is *in flight* ever actually landed.

:mod:`pytest_rhiza._versions` asserts the declared version is not **behind** the newest
tag, and deliberately permits it to be **ahead**, because ``/rhiza:release`` is two-phase:
phase A bumps the version on a pull request, phase B tags the merged commit, and equality
cannot hold in between (#62). That permission is correct and this module does not touch
it.

**What it lacked was an upper bound (#85).** "Ahead of the newest tag" describes two
states that look identical to :mod:`pytest_rhiza._versions`:

* a release in flight — the PR is open, or was merged moments ago and the tag is coming;
* a release that **stopped** — phase A merged, phase B never ran, and the version the
  manifest declares was never tagged and never published.

The second is not hypothetical. pytest-rhiza itself sat in it: ``0.4.1`` was bumped and
merged, ``CHANGELOG.md`` carried its section, and no ``v0.4.1`` tag existed days later —
while ``rhiza-test`` reported 34 passed, 0 skipped throughout. That is the #34 shape one
level up: not a check that skipped, but a check whose subject was never created.

**The signature this module tests for**, and why each part is needed:

1. the declared version is ahead of the newest tag — a release is in flight at all;
2. the commit that wrote that version into the manifest is reachable from the **default
   branch** — phase A is done, so phase B is what is outstanding. While the release PR is
   still open the bump lives only on its branch, and nothing here fires;
3. that commit is older than :func:`grace_days` — phase B follows a merge by minutes when
   it runs at all, so age is what separates "tagging shortly" from "never tagged".

**Why a grace period rather than "merged implies tagged".** ``rhiza_release.yml`` triggers
on ``push:`` of a tag, so tagging is a deliberate step rather than something the merge sets
off. Failing the instant a bump merges would make the default branch red for the whole
normal window and would fail the release's own required checks. The bound has to be loose
enough to be uninteresting during a healthy release and tight enough that a stalled one
cannot hide behind it.

**What git cannot answer is never a failure — and never a silent pass either.** A
repository with no default branch git can name means this check has no subject, and
reporting it as red would be the mirror of the defect it exists to catch. But until #117
that case *returned*, which a test runner records as a pass: ``actions/checkout`` writes
no ``origin/HEAD``, so in CI the check judged nothing on every run while reading green,
and the no-skip guard that exists for exactly this (#34) could not see it. It is a
``pytest.skip`` now, and :func:`default_branch` falls back to ``origin/main`` and
``origin/master`` so that an ordinary CI checkout has a subject at all.

The other quiet states are verdicts rather than gaps, and stay quiet: no release in
flight, a bump not yet on the default branch (an open release PR, which a shallow clone
also looks like), and a malformed version, which
:func:`~pytest_rhiza._versions.assert_declared_version_not_behind_tag` reports.

Security Notes:
- S101 (assert usage): Asserts are appropriate in test code for validating conditions
  and are the mechanism pytest reports failures through.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from pytest_rhiza._process import budget, git
from pytest_rhiza._versions import as_version

__all__ = ["assert_release_not_stalled", "grace_days", "stalled_for"]

# Days a merged-but-untagged bump may sit before it is reported. Three rather than one:
# a release merged on a Friday should not go red over a weekend. Three rather than ten:
# this package released 0.2.2, 0.3.0, 0.4.0 and 0.4.1 inside a single day, and a bound
# looser than the cadence it guards cannot catch anything.
DEFAULT_GRACE_DAYS = 3
GRACE_DAYS_ENV = "RHIZA_RELEASE_GRACE_DAYS"


def grace_days() -> int:
    """Return how many days a merged bump may go untagged before this is a failure.

    Overridable for a project whose release cadence is genuinely slower than the default
    assumes — the same knob, and the same reasoning, as the timeouts in
    :mod:`pytest_rhiza._process`, whose :func:`~pytest_rhiza._process.budget` this reuses
    rather than re-implementing "a positive integer from the environment, or a default"
    a second time.

    Returns:
        Seconds' worth of days, from :data:`GRACE_DAYS_ENV` or :data:`DEFAULT_GRACE_DAYS`.
    """
    return budget(GRACE_DAYS_ENV, DEFAULT_GRACE_DAYS)


def default_branch(root: Path) -> str | None:
    """Return the default branch as a remote-tracking ref, or None if git cannot say.

    ``origin/HEAD`` is what names the default branch locally, and it is the first answer
    taken. It is also absent exactly where this check matters most: a ``git clone`` sets
    it, but ``actions/checkout`` never does — it initialises a repository and fetches into
    it — so in CI the lookup failed on every run and the check never judged anything
    (#117). This package's own 0.7.1 sat untagged for 24 days behind that while CI reported
    the assertion as passed.

    So when ``origin/HEAD`` is absent, an existing ``origin/main`` and then
    ``origin/master`` are taken instead: the two names a default branch has in practice,
    and the ref ``actions/checkout`` does write for a push to either. A project whose
    default is named otherwise *and* whose checkout has no ``origin/HEAD`` still answers
    None, which the caller reports as a skip rather than a pass.

    Args:
        root: Repository to ask.

    Returns:
        Something like ``origin/main``, or None when git can name no default branch.
    """
    result = git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    for name in ("main", "master"):
        if git(root, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{name}").returncode == 0:
            return f"origin/{name}"
    return None


def merged_bump_date(root: Path, branch: str, manifest: str, declared: str) -> str | None:
    """Return when ``declared`` was written into ``manifest`` on ``branch``.

    Found with git's pickaxe (``-S``), which reports the commits where the number of
    occurrences of a string in a path changed — so the bump commit is the newest one on
    the default branch that changed how often the declared version appears in the
    manifest. Scoping to the one path is what keeps it from matching a version-shaped
    string elsewhere in the tree.

    Args:
        root: Repository to ask.
        branch: The ref to search, from :func:`default_branch`. Searching the default
            branch rather than ``HEAD`` is what distinguishes a merged bump from one
            still on an open release PR.
        manifest: Repository-relative path of the file declaring the version.
        declared: The version string to look for.

    Returns:
        The committer date in ISO 8601, or None when no such commit is on that branch —
        which is the ordinary answer while a release PR is still open.
    """
    result = git(root, "log", "-1", "--format=%cI", f"-S{declared}", branch, "--", manifest)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def stalled_for(committed: str, now: datetime) -> int | None:
    """Return whole days between an ISO 8601 commit date and ``now``.

    Args:
        committed: A committer date as git's ``%cI`` writes it.
        now: The moment to measure against, timezone-aware.

    Returns:
        Whole days elapsed, or None when ``committed`` cannot be read as an aware
        timestamp — unparseable input is unjudgeable, in keeping with the rest of this
        module.

    Examples:
        >>> from datetime import datetime, timezone
        >>> now = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
        >>> stalled_for("2026-08-21T20:16:41+04:00", now)
        3

        The same instant is zero days, not one:

        >>> stalled_for("2026-08-25T12:00:00+00:00", now)
        0

        A date git could not have written is unjudgeable rather than an error:

        >>> stalled_for("last Tuesday", now) is None
        True

        So is one with no offset — comparing it to an aware ``now`` would raise, and a
        naive timestamp genuinely does not identify a moment:

        >>> stalled_for("2026-08-21T20:16:41", now) is None
        True
    """
    try:
        moment = datetime.fromisoformat(committed)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return (now - moment).days


def _stalled_release(
    root: Path,
    latest_tag: str,
    declared: str,
    *,
    manifest: str,
    now: datetime,
) -> tuple[str, int] | None:
    """Return the default branch and how long the bump has sat on it, or None to say nothing.

    Every rung that settles the question returns None, so
    :func:`assert_release_not_stalled` is left holding one decision — fail or not — and
    this function holds the ways there is nothing to decide. The one rung that *cannot*
    be established — no default branch while a release is in flight — skips instead,
    because returning there was indistinguishable from a pass (#117). Split out at CC 9,
    under the bar #87 set for this repository.

    Args:
        root: The repository under test.
        latest_tag: The newest ``vX.Y.Z`` tag.
        declared: The version the manifest declares.
        manifest: Repository-relative path of that manifest.
        now: The moment to measure against, timezone-aware.

    Returns:
        The default branch and whole days since the bump merged into it, or None when
        either version is malformed, no release is in flight, the bump is not on the
        default branch, or its date cannot be read.

    Raises:
        pytest.skip.Exception: When a release is in flight and git cannot name the
            default branch, so nothing can be judged.
    """
    tag_version = as_version(latest_tag.lstrip("v"))
    declared_version = as_version(declared)
    if tag_version is None or declared_version is None:
        return None  # malformed; assert_declared_version_not_behind_tag reports it
    if declared_version <= tag_version:
        return None  # no release in flight — nothing to have stalled

    branch = default_branch(root)
    if branch is None:
        # A release *is* in flight and git cannot say whether it merged. Returning here
        # read as a pass, which the no-skip guard cannot see — the #34 shape that kept
        # #117 green. A skip says honestly that nothing was judged.
        pytest.skip(
            f"Version {declared!r} is ahead of the newest tag {latest_tag!r}, but git cannot "
            "name the default branch (no origin/HEAD, origin/main or origin/master), so "
            "whether the release stalled cannot be judged."
        )

    committed = merged_bump_date(root, branch, manifest, declared)
    if committed is None:
        return None  # the bump is not on the default branch: phase A is still in flight

    elapsed = stalled_for(committed, now)
    if elapsed is None:  # pragma: no cover - defensive; git's %cI is always aware ISO 8601
        return None
    return branch, elapsed


def assert_release_not_stalled(
    root: Path,
    latest_tag: str,
    declared: str,
    *,
    manifest: str,
    now: datetime | None = None,
) -> None:
    """Assert a version ahead of the newest tag is a release in flight, not an abandoned one.

    The states in which there is nothing to judge are :func:`_stalled_release`'s business:
    the settled ones return quietly and the unanswerable one skips; see the module
    docstring for why none of them is a failure. What is left here is the one comparison
    that can fail.

    Args:
        root: The repository under test.
        latest_tag: The newest ``vX.Y.Z`` tag, from the ``latest_tag`` fixture.
        declared: The version the layer's manifest declares.
        manifest: Repository-relative path of that manifest, for the pickaxe and the
            failure message.
        now: The moment to measure against; defaults to the current UTC time. Injected so
            the elapsed-time branch is testable without waiting days for it.

    Raises:
        AssertionError: If the bump merged into the default branch more than
            :func:`grace_days` days ago and no tag names the version it declared.
        pytest.skip.Exception: If a release is in flight and git cannot name the default
            branch to judge it against.
    """
    state = _stalled_release(
        root,
        latest_tag,
        declared,
        manifest=manifest,
        now=now or datetime.now(UTC),
    )
    if state is None:
        return
    branch, elapsed = state

    allowed = grace_days()
    assert elapsed <= allowed, (
        f"Version {declared!r} in {manifest} has been merged into {branch} for {elapsed} days "
        f"with no matching tag — the newest is {latest_tag!r}. /rhiza:release is two-phase and a "
        f"version ahead of the newest tag is normally a release in flight, but phase B tags the "
        f"merged commit within minutes, so {elapsed} days means phase B never ran: v{declared} was "
        f"never tagged and never published. Tag the merged commit to finish the release, or set "
        f"{GRACE_DAYS_ENV} above {allowed} if this project's cadence is genuinely slower."
    )
