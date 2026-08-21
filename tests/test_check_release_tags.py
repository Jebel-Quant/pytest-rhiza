"""Subject-repository tests for ``checks/test_release_tags.py``.

The check exists because ``git tag --list`` happily reports a tag no branch contains,
which is how a repository stays green while ``git describe`` disagrees with it. Testing it
means building that state on purpose: a tag left behind on the pre-squash commit of a
merged release branch.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import only for the fixture's type
    from conftest import Subject


class TestReachability:
    """A tag on a commit some branch contains, versus one orphaned by a squash merge."""

    def test_a_tag_on_the_current_branch_passes(self, subject: Callable[..., Subject]) -> None:
        """The ordinary case: the release was cut on the branch it lives on."""
        repo = subject({"README.md": "# Demo\n"}, tag="v1.2.3")

        result = repo.run("test_release_tags")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "1 passed" in result.stdout, result.stdout

    def test_a_tag_no_branch_contains_is_reported(self, subject: Callable[..., Subject]) -> None:
        """The squash-merge case, reconstructed: tag a commit, then move the branch off it.

        This is what a squash-merged release branch leaves behind — the content lands on
        the default branch under a new SHA while the tag stays on the pre-squash commit.
        git-cliff then cannot place a changelog boundary at the tag, so regenerating
        CHANGELOG.md deletes that version's section.
        """
        repo = subject({"README.md": "# Demo\n"})
        base = repo.git("rev-parse", "HEAD").stdout.strip()
        repo.write({"README.md": "# Demo\n\nRelease content.\n"})
        repo.commit("release", tag="v2.0.0")
        repo.git("reset", "--hard", base)

        result = repo.run("test_release_tags")

        assert result.returncode != 0
        assert "which no branch contains" in result.stdout, result.stdout

    def test_an_untagged_repository_skips(self, subject: Callable[..., Subject]) -> None:
        """A project that has never released has nothing to be unreachable."""
        repo = subject({"README.md": "# Demo\n"})

        result = repo.run("test_release_tags")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "No version tags found" in result.stdout, result.stdout

    def test_a_tag_that_does_not_resolve_to_a_commit_skips(self, subject: Callable[..., Subject]) -> None:
        """A tag git cannot dereference to a commit is unjudgeable, not a failure (#45).

        The third of the silent-skip paths #45 was filed for, and the one that looked
        untestable: it needs ``git tag --list`` to report a tag while
        ``git rev-parse <tag>^{commit}`` fails, on a repository that is *not* shallow — the
        shallow branch above would otherwise fire first.

        Tagging a tree object rather than a commit produces exactly that state. It is also
        a real way to reach it: ``git tag v1 $(git rev-parse HEAD^{tree})`` is a plausible
        slip, and the tag it leaves behind is reported by every listing while dereferencing
        to a commit is an error. Reachability genuinely cannot be judged from it, so
        skipping is right — but it has to be a skip that says why.
        """
        repo = subject({"README.md": "# Demo\n"})
        tree = repo.git("rev-parse", "HEAD^{tree}").stdout.strip()
        repo.git("tag", "v3.0.0", tree)

        result = repo.run("test_release_tags")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "tagged commit for v3.0.0 is not present locally" in result.stdout, result.stdout

    def test_a_shallow_clone_skips_because_the_graph_is_incomplete(self, subject: Callable[..., Subject]) -> None:
        """CI clones shallowly by default, and reachability cannot be judged from a truncated graph.

        Without this branch the check would fail every shallow CI run — the tagged commit
        is present but no branch in the clone contains it — which is the false positive
        that would get the whole check disabled.
        """
        origin = subject({"README.md": "# Demo\n"}, tag="v1.2.3")
        clone = subject(git=False)
        clone.git("clone", "--quiet", "--depth", "1", "--branch", "v1.2.3", origin.path.as_uri(), ".")

        result = clone.run("test_release_tags")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "shallow clone" in result.stdout, result.stdout
