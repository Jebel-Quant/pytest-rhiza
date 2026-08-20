"""Tests for the bounded-subprocess layer every check shells out through.

The module under test exists because none of those calls used to carry a ``timeout``
(#44), so a README example that waited on ``input()`` made the gate *hang* rather than
fail. What is asserted here is the half of that which no other test can reach: that a
child outliving its budget is killed and reported, and that the budget is a number the
environment can move — which is what makes the kill path testable in the first place, and
therefore what stops this from being a safety net nobody has ever seen work.

``_budget``'s precedence is doctested where it lives, so it is not re-asserted here. Its
*refusals* are, because those are a safety property rather than documentation: a malformed
override must not be able to remove the bound the module exists to provide.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from pytest_rhiza._process import (
    EXECUTE_TIMEOUT,
    EXECUTE_TIMEOUT_ENV,
    GIT,
    INSPECT_TIMEOUT,
    INSPECT_TIMEOUT_ENV,
    execute_timeout,
    git,
    inspect_timeout,
    run,
)

if TYPE_CHECKING:  # pragma: no cover - import only for the fixture's type
    from conftest import Subject

# Long enough that no machine finishes it inside the one-second budget below, short enough
# that a leaked child cannot outlive the suite.
_SLEEP = "import time; time.sleep(30)"


class TestBudgets:
    """The two budgets, and the environment variables that move them."""

    def test_the_defaults_apply_when_nothing_is_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unconfigured consumer still gets a bound — the whole point of #44."""
        monkeypatch.delenv(INSPECT_TIMEOUT_ENV, raising=False)
        monkeypatch.delenv(EXECUTE_TIMEOUT_ENV, raising=False)

        assert inspect_timeout() == INSPECT_TIMEOUT
        assert execute_timeout() == EXECUTE_TIMEOUT

    def test_executing_gets_a_longer_budget_than_inspecting(self) -> None:
        """The ordering is the design, not an accident of two literals.

        Inspecting is git answering a question and `bash -n` parsing a string; executing
        runs code somebody wrote. If these ever crossed, the generous budget would be on
        the call that cannot legitimately need it.
        """
        assert EXECUTE_TIMEOUT > INSPECT_TIMEOUT

    def test_the_environment_can_move_each_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Independently, so shortening one for a test does not loosen the other."""
        monkeypatch.setenv(INSPECT_TIMEOUT_ENV, "7")
        monkeypatch.setenv(EXECUTE_TIMEOUT_ENV, "11")

        assert inspect_timeout() == 7
        assert execute_timeout() == 11

    def test_an_unusable_override_falls_back_rather_than_removing_the_bound(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A typo must neither disable the timeout nor break every check.

        Both halves matter. Falling back keeps the safety net that a malformed value would
        otherwise remove; not raising keeps one stray environment variable from failing
        every check in the repository with a traceback about ``int()``. Zero and negatives
        are refused because neither means what someone setting them intended:
        ``subprocess.run(timeout=0)`` kills the child immediately, and a negative raises
        inside ``subprocess`` itself.
        """
        for value in ("soon", "", "1.5", "0", "-5"):
            monkeypatch.setenv(EXECUTE_TIMEOUT_ENV, value)

            assert execute_timeout() == EXECUTE_TIMEOUT, f"{value!r} should have fallen back to the default"


class TestRun:
    """Running one child to completion, and killing one that will not finish."""

    def test_a_child_that_finishes_is_returned_verbatim(self) -> None:
        """The ordinary case: output captured as text, return code untouched."""
        result = run([sys.executable, "-c", "print('hello')"])

        assert result.returncode == 0
        assert result.stdout.strip() == "hello"

    def test_a_non_zero_exit_is_returned_rather_than_raised(self) -> None:
        """Callers decide what a failure means — several treat one as a skip."""
        result = run([sys.executable, "-c", "raise SystemExit(3)"])

        assert result.returncode == 3

    def test_stdin_reaches_the_child(self) -> None:
        """`bash -n` is fed its fence this way, so the plumbing is worth asserting."""
        result = run([sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"], stdin="fence")

        assert result.stdout.strip() == "FENCE"

    def test_a_child_that_outlives_its_budget_is_killed_and_reported(self) -> None:
        """The defect #44 was filed for: a hang becomes a failure instead of a hang.

        Driven at a one-second budget rather than through the real 120s one, which is the
        reason the budgets are overridable at all — a test that waited out the default
        would be a test nobody runs.
        """
        with pytest.raises(pytest.fail.Exception) as failure:
            run([sys.executable, "-c", _SLEEP], timeout=1, on_timeout="the probe never came back")

        assert "Killed after 1s" in str(failure.value)
        assert "the probe never came back" in str(failure.value)

    def test_the_budget_used_is_the_inspect_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An omitted `timeout` resolves through the environment, not to an unbounded wait.

        Asserted through the failure message, which names the budget it exceeded: that
        string is the only externally visible evidence of which number was applied.
        """
        monkeypatch.setenv(INSPECT_TIMEOUT_ENV, "1")

        with pytest.raises(pytest.fail.Exception) as failure:
            run([sys.executable, "-c", _SLEEP], on_timeout="unused")

        assert "Killed after 1s" in str(failure.value)


class TestGit:
    """The shared git entry point, which every git-dependent check now goes through."""

    def test_a_query_answers_from_the_given_root(self, subject: Callable[..., Subject]) -> None:
        """`cwd` is the repository, not the directory the suite happens to run in."""
        repo = subject({"README.md": "# Demo\n"}, tag="v1.2.3")

        result = git(repo.path, "tag", "--list", "v*")

        assert result.returncode == 0
        assert result.stdout.strip() == "v1.2.3"

    def test_a_failing_query_is_reported_by_return_code(self, subject: Callable[..., Subject]) -> None:
        """Not raised: `test_release_tags` reads a non-zero exit here as a reason to skip."""
        repo = subject({"README.md": "# Demo\n"})

        result = git(repo.path, "rev-parse", "v9.9.9^{commit}")

        assert result.returncode != 0

    def test_the_executable_is_resolved_through_path(self) -> None:
        """Resolved once at import, which is what makes the Windows leg work.

        Neither assertion names a location — the path differs per platform and per runner,
        and pinning one would be a test about this machine. What is asserted is the two
        properties the resolution has to have: it is git, and it is a full path rather than
        the bare name that `subprocess` would otherwise re-search on every call.
        """
        assert Path(GIT).stem == "git", GIT
        assert Path(GIT).is_absolute(), GIT


def test_no_check_shells_out_unbounded() -> None:
    """No module under `checks/` may call `subprocess.run` directly (#44).

    The regression guard for the whole issue. Bounding the seven call sites that existed
    is a fix; routing every future one through :func:`run` is what stops the eighth from
    reintroducing the hang. `_fences` is the one exception, and it is exempt on purpose:
    its probe has to answer False on a timeout rather than fail, so it owns its own call —
    with a `timeout=` argument, which is what the sibling test in `test_fences.py` covers.
    """
    import pytest_rhiza.checks as checks

    offenders = [
        path.name
        for path in sorted(Path(next(iter(checks.__path__))).glob("*.py"))
        if "subprocess.run" in path.read_text(encoding="utf-8")
    ]

    assert not offenders, (
        f"{offenders} call subprocess.run directly instead of pytest_rhiza._process.run, so "
        f"their children are bounded only by whatever the consumer happened to configure — "
        f"which is the unbounded-wait defect in #44."
    )
