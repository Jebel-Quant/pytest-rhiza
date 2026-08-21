"""The tag-versus-declared-version assertion shared by the language layers.

**Why this is not equality.** Every layer declares its version in a file — Python's
``[project].version``, Rust's ``[package].version``, Go's ``const Version`` — and every
layer wants that number to agree with the newest ``vX.Y.Z`` tag. The obvious way to say
so is ``declared == tag``, and all three layers said exactly that until #62.

That assertion cannot hold during a release, because ``/rhiza:release`` is deliberately
two-phase. Phase A opens a pull request that bumps the declared version and leaves the
tag alone: a tag has to point at a commit that exists on the branch being published, and
a squash-merge replaces the branch's commits with a new one, so a tag cut before the merge
names a SHA that never lands. Phase B tags the merged commit afterwards. Between those two
phases — for the whole life of the release PR, and again after it merges until the tag is
pushed — the declared version is *one step ahead* of the newest tag, by design. Phase B
detects itself by reading precisely that inequality.

So equality forbids a state the release flow requires, and it does it in the worst place:
the check runs in CI, feeds the branch-protection gate, and therefore makes every release
PR unmergeable. That is the same shape as the self-referencing workflow pin the release
skill warns about — a required check that can never go green on a release PR.

**What the invariant actually is.** The defect worth catching is the declared version
falling *behind* the newest tag. That is what drift looks like, and what makes the next
release dangerous: bump-my-version searches the manifest for the version it derived from
the tag and fails to find it, or worse, a release gets cut at a number already published.
A declared version *ahead* of the newest tag is not drift, it is a release in flight.

``max(declared, tag)`` is the floor a new release must beat, and ``declared < tag`` is the
only error — the same rule ``scripts/check_version_bump.py`` already applies when it picks
a floor and refuses anything that does not strictly increase past it. This module states
that rule once so the three layers cannot disagree about it.

**What still varies.** Where the version is written, and what specifically goes wrong when
it lags, which differs enough to be worth saying in the failure message: Rust's bump reads
the tag and then hunts for that number in ``Cargo.toml``; a Go binary reports a version
consumers cannot ``go get``. The caller supplies both.

Security Notes:
- S101 (assert usage): Asserts are appropriate in test code for validating conditions
  and are the mechanism pytest reports failures through.
"""

from __future__ import annotations

from packaging.version import InvalidVersion, Version

__all__ = ["assert_declared_version_not_behind_tag"]


def _as_version(value: str) -> Version | None:
    """Return ``value`` parsed, or ``None`` when it is not a version.

    Split out so the caller can report a malformed version through ``assert`` like
    every other complaint in this package, rather than raising ``AssertionError`` with
    a long message built at the raise site.

    Args:
        value: A version string, without any leading ``v``.

    Returns:
        The parsed version, or ``None`` if it does not parse.

    Examples:
        >>> _as_version("1.2.3")
        <Version('1.2.3')>
        >>> _as_version("not-a-version") is None
        True
    """
    try:
        return Version(value)
    except InvalidVersion:
        return None


def assert_declared_version_not_behind_tag(
    latest_tag: str,
    declared: str,
    *,
    location: str,
    consequence: str,
) -> None:
    """Assert the declared version is the newest tag or ahead of it.

    Ahead is the normal state of a release in flight: ``/rhiza:release`` lands the bump
    by pull request and tags the merged commit afterwards, so the manifest leads the tag
    from the moment the release PR opens until the tag is pushed. Behind is drift, and is
    what this assertion exists to catch.

    Args:
        latest_tag: The newest ``vX.Y.Z`` tag, from the ``latest_tag`` fixture.
        declared: The version the layer's manifest declares.
        location: Where that version is written, for the failure message — for example
            ``"[project].version in pyproject.toml"``.
        consequence: What goes wrong while the two disagree, phrased to follow a
            semicolon. Layer-specific, because it genuinely differs.

    Raises:
        AssertionError: If ``declared`` orders lower than ``latest_tag``, or if either
            value is not a valid version.

    Examples:
        A version ahead of the tag is a release in flight, not a failure:

        >>> assert_declared_version_not_behind_tag(
        ...     "v0.2.2", "0.3.0", location="pyproject.toml", consequence="x"
        ... )

        Equal is the steady state, once the tag has been pushed:

        >>> assert_declared_version_not_behind_tag(
        ...     "v0.3.0", "0.3.0", location="pyproject.toml", consequence="x"
        ... )

        Behind is the drift this catches. The message is printed up to the first
        semicolon rather than shown as a traceback, so the example holds without
        depending on ``NORMALIZE_WHITESPACE``:

        >>> try:
        ...     assert_declared_version_not_behind_tag(
        ...         "v0.3.0", "0.2.2", location="pyproject.toml", consequence="boom"
        ...     )
        ... except AssertionError as exc:
        ...     print(str(exc).split(";")[0])
        Declared version '0.2.2' in pyproject.toml is behind the newest git tag 'v0.3.0'
    """
    tag_version = _as_version(latest_tag.lstrip("v"))
    assert tag_version is not None, f"Latest git tag {latest_tag!r} is not a valid version"

    declared_version = _as_version(declared)
    assert declared_version is not None, f"Declared version {declared!r} in {location} is not a valid version"

    assert declared_version >= tag_version, (
        f"Declared version {declared!r} in {location} is behind the newest git tag "
        f"{latest_tag!r}; {consequence} A version *ahead* of the newest tag is fine — that is "
        f"a release in flight, since /rhiza:release bumps by pull request and tags the merged "
        f"commit afterwards — but behind means the two have drifted apart."
    )
