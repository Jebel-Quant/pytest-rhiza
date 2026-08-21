"""Tests for the release tags every language layer's version config derives from.

Ported from ``jebel-quant/rhiza`` at 89f9298, where bundle ``core`` synced it
to ``.rhiza/tests/test_release_tags.py``. It now arrives installed, and is collected by name:
``pytest --pyargs pytest_rhiza.checks.test_release_tags``.

Owned by ``core`` because the invariant is about git, not about a language. All three
layers depend on it for the same reason: ``python-core``'s ``[tool.bumpversion]`` table
and the root ``.bumpversion.toml`` that ``rust-core`` and ``go-core`` ship both fall back
to reading the newest tag when they cannot read a version from a file, and git-cliff
places changelog boundaries at tags. An unreachable tag breaks both.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_rhiza._process import git


def test_latest_tag_is_reachable_from_a_branch(latest_tag: str, root: Path) -> None:
    """The newest tag must sit on a commit some branch contains (#1454).

    ``git tag --list`` happily reports an orphaned tag, which is how a repo can stay
    green while ``git describe`` disagrees with it. A release cut on a branch that is
    then squash-merged leaves its tag on the pre-squash commit while the content lands
    on the default branch under a new SHA; no branch contains the tagged commit any
    more.

    The consequence is not cosmetic. git-cliff cannot place a boundary at an
    unreachable tag, so regenerating CHANGELOG.md deletes that version's section and
    folds its commits into the next release. Bump tooling reading the version from
    ``git describe`` skips the release for the same reason.
    """
    if git(root, "rev-parse", "--is-shallow-repository").stdout.strip() == "true":
        pytest.skip("shallow clone — the commit graph is incomplete")

    commit = git(root, "rev-parse", f"{latest_tag}^{{commit}}")
    if commit.returncode != 0:
        pytest.skip(f"tagged commit for {latest_tag} is not present locally")

    contains = git(root, "branch", "-a", "--contains", commit.stdout.strip(), "--format=%(refname:short)")
    assert contains.stdout.strip(), (
        f"Tag {latest_tag} points at {commit.stdout.strip()[:12]}, which no branch contains. "
        f"It is most likely the pre-squash commit of a squash-merged release branch: "
        f"`git describe` skips this release and regenerating CHANGELOG.md will delete its "
        f"section. Re-tag the merged commit and delete the orphaned tag."
    )
