"""Subject-repository tests for the two README checks.

``checks/test_readme.py`` parses ``bash`` fences and never runs them;
``checks/test_readme_validation.py`` *executes* Python examples — ``pycon`` transcripts as
one doctest, the convention, and legacy ``python`` fences diffed against the following
``result`` fence. The asymmetry is deliberate in the checks, and the tests keep it
visible: a bash fence is documentation that must parse, a Python example is documentation
that must be true.

``tests/test_checks.py`` already covers the sound and broken bash cases end to end. What
is here is everything a fence can be *besides* code — skipped, a directory tree, all
comments — plus the whole of the Python half, in both its shapes.

``test_readme_validation`` holds four tests — pycon run, pycon parse, legacy run, legacy
compile — and every one of them passes on a README with nothing for it to do. So a count
of ``4 passed`` below means "the shape under test was judged and the other shape found
nothing", which is why the counts are asserted rather than just the exit status.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from pytest_rhiza._fences import bash_usable

if TYPE_CHECKING:  # pragma: no cover - import only for the fixture's type
    from conftest import Subject


class TestBashFenceExclusions:
    """Three kinds of fence are not shell to be parsed, and each is excluded differently."""

    def test_skipped_trees_and_comment_only_fences_are_all_excluded(self, subject: Callable[..., Subject]) -> None:
        """One README carrying all three exclusions still passes.

        Each fence here would fail ``bash -n`` if it reached it, so a pass is evidence
        that all three exclusion paths fired rather than that the fences were benign.
        """
        if not bash_usable():
            pytest.skip("no working `bash -n` on this platform")

        readme = """
        # Demo

        Intentionally excluded, and not valid shell:

        ```bash +RHIZA_SKIP
        if then fi done esac
        ```

        A directory tree, which is not shell:

        ```bash
        src/
        ├── demo
        │   └── inner
        └── other
        ```

        Only commentary, so there is nothing to parse:

        ```bash
        # install the project
        # then run the tests
        ```

        And one fence that is real shell:

        ```bash
        make install
        ```
        """
        repo = subject({"README.md": readme}, tag="v1.2.3")

        result = repo.run("test_readme")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "3 passed" in result.stdout, result.stdout

    def test_an_empty_readme_is_reported(self, subject: Callable[..., Subject]) -> None:
        """A file that exists but says nothing fails the readability assertion."""
        repo = subject({"README.md": "   \n\n"}, tag="v1.2.3")

        result = repo.run("test_readme")

        assert result.returncode != 0
        assert "README.md is empty" in result.stdout, result.stdout

    def test_a_missing_readme_is_reported(self, subject: Callable[..., Subject]) -> None:
        """No README at all: the existence assertion fires before anything is parsed."""
        repo = subject({"other.md": "# Not the readme\n"}, tag="v1.2.3")

        result = repo.run("test_readme")

        assert result.returncode != 0
        assert "README.md not found at project root" in result.stdout, result.stdout

    def test_a_platform_without_bash_skips_rather_than_inventing_errors(
        self, subject: Callable[..., Subject], tmp_path: Path
    ) -> None:
        """With no usable bash, the fence check skips and says so (#45).

        One of the three silent-skip paths #45 was filed for: it was the only uncovered
        line in this module, and an untested skip is the failure mode this package fights
        hardest — a skip reads as a pass (#34).

        Driven by emptying the child's PATH, which is deterministic on every platform this
        is tested on: with nothing to resolve, `bash` raises OSError and the probe answers
        False. On Windows `CreateProcess` can still reach System32's WSL launcher, but that
        stub exits non-zero having written nothing, so the probe answers False there too —
        both roads lead to the skip, which is why this is asserted rather than guarded.
        Only a runner with a working WSL distribution would take the other branch, and the
        images this is tested on have none.
        """
        empty = tmp_path / "no-tools"
        empty.mkdir()
        repo = subject({"README.md": "# Demo\n\n```bash\nmake install\n```\n"}, tag="v1.2.3")

        result = repo.run("test_readme", env={"PATH": str(empty)})

        assert result.returncode == 0, result.stdout + result.stderr
        assert "no working `bash -n` on this platform" in result.stdout, result.stdout
        assert "1 skipped" in result.stdout, result.stdout


class TestPythonFenceExecution:
    """The python half runs the fence and diffs it against the documented result."""

    def test_a_fence_matching_its_result_block_passes(self, subject: Callable[..., Subject]) -> None:
        """The reference case, including a skipped fence that would raise if executed."""
        readme = """
        # Demo

        ```python +RHIZA_SKIP
        raise RuntimeError("this fence must never run")
        ```

        ```python
        print("hello from the readme")
        ```

        ```result
        hello from the readme
        ```
        """
        repo = subject({"README.md": readme}, tag="v1.2.3")

        result = repo.run("test_readme_validation")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "4 passed" in result.stdout, result.stdout

    def test_output_disagreeing_with_the_result_block_is_reported(self, subject: Callable[..., Subject]) -> None:
        """A documented result that the code no longer produces is the defect this catches."""
        readme = """
        # Demo

        ```python
        print("what the code does")
        ```

        ```result
        what the readme claims
        ```
        """
        repo = subject({"README.md": readme}, tag="v1.2.3")

        result = repo.run("test_readme_validation")

        assert result.returncode != 0
        assert "1 failed" in result.stdout, result.stdout

    def test_a_fence_that_raises_is_reported_with_its_stderr(self, subject: Callable[..., Subject]) -> None:
        """The exit status is checked before the diff, so the error is what gets reported."""
        readme = """
        # Demo

        ```python
        raise SystemExit("the example is broken")
        ```

        ```result
        nothing
        ```
        """
        repo = subject({"README.md": readme}, tag="v1.2.3")

        result = repo.run("test_readme_validation")

        assert result.returncode != 0
        assert "README code exited with" in result.stdout, result.stdout

    def test_a_fence_that_does_not_compile_is_reported(self, subject: Callable[..., Subject]) -> None:
        """Syntax is checked separately, so a fence nobody can run is still named."""
        readme = """
        # Demo

        ```python
        def broken(:
        ```
        """
        repo = subject({"README.md": readme}, tag="v1.2.3")

        result = repo.run("test_readme_validation")

        assert result.returncode != 0
        assert "has syntax error" in result.stdout, result.stdout

    def test_the_mismatch_message_explains_the_merge_and_shows_a_diff(self, subject: Callable[..., Subject]) -> None:
        """A drifted result is reported with enough detail to find the fence (#46).

        The assertion that catches this used to carry no message, which mattered because
        of how the check works: all python fences run as *one* script and all ``result``
        fences are compared as *one* string, so pytest's own output was two opaque blobs.
        Two fences here, and the second one drifts, so the message has to do the
        attribution the reader cannot do by eye.

        ``--tb=long`` overrides the harness default of ``--tb=line``, which shows only the
        first line of a failure and would hide the very thing under test.
        """
        readme = """
        # Demo

        ```python
        print("first")
        ```

        ```result
        first
        ```

        ```python
        print("second")
        ```

        ```result
        SECOND
        ```
        """
        repo = subject({"README.md": readme}, tag="v1.2.3")

        result = repo.run("test_readme_validation", args=("--tb=long",))

        assert result.returncode != 0
        assert "2 python fence(s)" in result.stdout, result.stdout
        assert "2 ```result``` fence(s)" in result.stdout, result.stdout
        # The diff names both sides, so the reader sees which is the documentation.
        assert "-SECOND" in result.stdout, result.stdout
        assert "+second" in result.stdout, result.stdout

    def test_a_fence_that_never_terminates_is_killed_rather_than_hanging(self, subject: Callable[..., Subject]) -> None:
        """A blocking example fails the gate instead of stopping it (#44).

        Before the fix this test could not have been written: the call had no timeout, so
        the check would have waited on ``time.sleep`` forever and taken the CI job with it.
        The budget is shortened through the environment so the test costs two seconds
        rather than the default two minutes — which is what that override is for.
        """
        readme = """
        # Demo

        ```python
        import time

        time.sleep(60)
        print("never reached")
        ```

        ```result
        never reached
        ```
        """
        repo = subject({"README.md": readme}, tag="v1.2.3")

        result = repo.run("test_readme_validation", env={"RHIZA_EXECUTE_TIMEOUT": "2"})

        assert result.returncode != 0
        assert "Killed after 2s" in result.stdout, result.stdout
        # The message has to say what to do about it, not just that it happened.
        assert "+RHIZA_SKIP" in result.stdout, result.stdout

    def test_a_readme_with_no_python_fences_passes(self, subject: Callable[..., Subject]) -> None:
        """Nothing to execute is not a defect; the empty code and result strings agree.

        All four tests pass rather than skip — the pycon pair finds no fences either — and
        that is the property ``rhiza-test``'s skip guard (#34) depends on.
        """
        repo = subject({"README.md": "# Demo\n\nProse only.\n"}, tag="v1.2.3")

        result = repo.run("test_readme_validation")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "4 passed" in result.stdout, result.stdout
        assert "skipped" not in result.stdout, result.stdout


class TestPyconFenceExecution:
    """The convention: every ``pycon`` fence runs as one doctest, in a child interpreter."""

    def test_a_transcript_that_holds_passes(self, subject: Callable[..., Subject]) -> None:
        """The reference case: a statement, its inline output, and a multi-line block."""
        readme = """
        # Demo

        ```pycon
        >>> 1 + 1
        2
        >>> for word in ["a", "b"]:
        ...     print(word)
        a
        b
        ```
        """
        repo = subject({"README.md": readme}, tag="v1.2.3")

        result = repo.run("test_readme_validation")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "4 passed" in result.stdout, result.stdout

    def test_wrong_expected_output_is_reported_with_doctests_own_report(self, subject: Callable[..., Subject]) -> None:
        """A drifted transcript fails, and the message is doctest's report of it.

        What the reader needs is which example, where, and expected against actual — all of
        which doctest already says, so the check shows its report rather than paraphrasing
        it. The line number is asserted as a *README* line: the fence body starts on line 4
        and the drifted example is its second, so line 5 is the one to open. ``--tb=long``
        because the harness default shows only a failure's first line.
        """
        readme = """
        # Demo

        ```pycon
        >>> x = 2
        >>> x * 21
        41
        ```
        """
        repo = subject({"README.md": readme}, tag="v1.2.3")

        result = repo.run("test_readme_validation", args=("--tb=long",))

        assert result.returncode != 0
        assert "1 failed" in result.stdout, result.stdout
        assert "README pycon fences failed as a doctest" in result.stdout, result.stdout
        assert 'File "README.md", line 5' in result.stdout, result.stdout
        assert "x * 21" in result.stdout, result.stdout
        assert "Expected:" in result.stdout, result.stdout
        assert "41" in result.stdout, result.stdout
        assert "Got:" in result.stdout, result.stdout
        assert "42" in result.stdout, result.stdout

    def test_a_skipped_fence_is_never_run_or_parsed(self, subject: Callable[..., Subject]) -> None:
        """``+RHIZA_SKIP`` works as for every other fence — the body could not even parse."""
        readme = """
        # Demo

        ```pycon +RHIZA_SKIP
        >>>raise RuntimeError("this fence must never run")
        ```

        ```pycon
        >>> print("ran")
        ran
        ```
        """
        repo = subject({"README.md": readme}, tag="v1.2.3")

        result = repo.run("test_readme_validation")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "4 passed" in result.stdout, result.stdout

    def test_ellipsis_is_enabled(self, subject: Callable[..., Subject]) -> None:
        """``...`` in expected output matches anything, with no per-example directive.

        The case it exists for: an address, a timestamp or a path that differs on every run
        and is not what the example is documenting.
        """
        readme = """
        # Demo

        ```pycon
        >>> object()
        <object object at 0x...>
        ```
        """
        repo = subject({"README.md": readme}, tag="v1.2.3")

        result = repo.run("test_readme_validation")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "4 passed" in result.stdout, result.stdout

    def test_fences_share_one_namespace_and_run_as_main(self, subject: Callable[..., Subject]) -> None:
        """A name bound in one fence is visible in the next, as it was in the joined script.

        Prose between the fences, and a skipped fence in the middle, must not break the
        chain. ``__name__`` is checked too, since the legacy script ran as ``__main__`` and
        an example guarded on it would silently stop printing if that changed.
        """
        readme = """
        # Demo

        ```pycon
        >>> import math
        >>> radius = 2
        ```

        Some prose in between.

        ```pycon +RHIZA_SKIP
        >>> radius = "not a number"
        ```

        ```pycon
        >>> round(math.pi * radius**2, 2)
        12.57
        >>> __name__
        '__main__'
        ```
        """
        repo = subject({"README.md": readme}, tag="v1.2.3")

        result = repo.run("test_readme_validation")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "4 passed" in result.stdout, result.stdout

    def test_examples_run_in_the_repository_root(self, subject: Callable[..., Subject]) -> None:
        """The child's working directory is the subject, so a README may read its own files."""
        readme = """
        # Demo

        ```pycon
        >>> from pathlib import Path
        >>> Path("data.txt").read_text().strip()
        'from the repository'
        ```
        """
        repo = subject({"README.md": readme, "data.txt": "from the repository\n"}, tag="v1.2.3")

        result = repo.run("test_readme_validation")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "4 passed" in result.stdout, result.stdout

    def test_a_malformed_prompt_is_reported_with_its_readme_line(self, subject: Callable[..., Subject]) -> None:
        """Doctest refusing the transcript is named by fence and README line.

        Both pycon tests fail: the parse check with the located message, and the run,
        whose child dies on the same parse before it can report — which is why the run
        falls back to showing stderr rather than an empty report.
        """
        readme = """
        # Demo

        ```pycon
        >>> 1
        1
        >>>2
        ```
        """
        repo = subject({"README.md": readme}, tag="v1.2.3")

        result = repo.run("test_readme_validation", args=("--tb=long",))

        assert result.returncode != 0
        assert "2 failed" in result.stdout, result.stdout
        assert "not a valid doctest transcript: pycon fence 0 (README.md line 6)" in result.stdout, result.stdout
        assert "lacks blank after >>>" in result.stdout, result.stdout

    def test_an_example_that_does_not_compile_is_reported(self, subject: Callable[..., Subject]) -> None:
        """A well-formed prompt holding invalid Python is a syntax error, named by line."""
        readme = """
        # Demo

        ```pycon
        >>> def broken(:
        ```
        """
        repo = subject({"README.md": readme}, tag="v1.2.3")

        result = repo.run("test_readme_validation")

        assert result.returncode != 0
        assert "README.md line 4 (pycon example) has syntax error" in result.stdout, result.stdout

    def test_a_transcript_that_never_terminates_is_killed(self, subject: Callable[..., Subject]) -> None:
        """The pycon run shares the execute budget (#44), and says how to get out of it."""
        readme = """
        # Demo

        ```pycon
        >>> import time
        >>> time.sleep(60)
        ```
        """
        repo = subject({"README.md": readme}, tag="v1.2.3")

        result = repo.run("test_readme_validation", env={"RHIZA_EXECUTE_TIMEOUT": "2"})

        assert result.returncode != 0
        assert "Killed after 2s" in result.stdout, result.stdout
        assert "```pycon +RHIZA_SKIP```" in result.stdout, result.stdout

    def test_a_readme_with_both_shapes_has_both_checked(self, subject: Callable[..., Subject]) -> None:
        """A half-migrated README keeps its legacy coverage while it gains the new one.

        The legacy fence here is wrong, so a green run would mean the pycon check had
        swallowed it; exactly one failure means each shape was judged by its own test.
        """
        readme = """
        # Demo

        ```pycon
        >>> 6 * 7
        42
        ```

        ```python
        print("legacy")
        ```

        ```result
        stale
        ```
        """
        repo = subject({"README.md": readme}, tag="v1.2.3")

        result = repo.run("test_readme_validation")

        assert result.returncode != 0
        assert "1 failed, 3 passed" in result.stdout, result.stdout
        # The legacy check's own message, so the one failure is attributed to it.
        assert "README output does not match its documented result" in result.stdout, result.stdout
