"""Tests for the shared fence parsing.

These are the ``TestSkipFlag`` classes from the template's ``test_readme.py`` and
``test_readme_validation.py``, moved here. Upstream they shipped into every consumer
repository, where each ``make rhiza-test`` re-tested template-internal helpers against
themselves; they belong to whoever owns the helper, which is now this package.
"""

from __future__ import annotations

import doctest
import json
import subprocess
from pathlib import Path

import pytest

from pytest_rhiza import _fences
from pytest_rhiza._fences import (
    BASH_BLOCK,
    CODE_BLOCK,
    PyconFence,
    TranscriptError,
    bash_usable,
    classify_bash_blocks,
    classify_pycon_blocks,
    pycon_doctest,
    should_skip,
    skip_reason,
)


class TestSkipReason:
    """Tests for the exclusion verdict that decides which bash fences are parsed.

    Extracted from ``checks/test_readme.py`` in #35, where the three exclusions were
    inline ``continue`` branches inside the test and so could only be exercised end to
    end, through a subject repository and a README. They are a pure function of
    ``(flags, code)`` now, so the edges get direct tests.
    """

    def test_a_plain_command_fence_is_parsed(self) -> None:
        """No exclusion applies, so the fence goes to `bash -n`."""
        assert skip_reason("", "make test") is None

    def test_the_skip_flag_excludes(self) -> None:
        """The author's explicit opt-out is honoured and named."""
        assert skip_reason(" +RHIZA_SKIP", "make test") == "+RHIZA_SKIP flag"

    def test_a_directory_tree_is_excluded(self) -> None:
        """Box-drawing characters mean the fence is prose, not shell."""
        assert skip_reason("", "src/\n├── pytest_rhiza/") == "directory tree representation"
        assert skip_reason("", "a\n└── b") == "directory tree representation"
        assert skip_reason("", "a\n│ b") == "directory tree representation"

    def test_a_comment_only_fence_is_excluded(self) -> None:
        """Nothing to parse, and no way for it to be wrong."""
        assert skip_reason("", "# see the Makefile") == "only comments"
        assert skip_reason("", "# one\n# two\n\n") == "only comments"

    def test_an_empty_fence_is_excluded(self) -> None:
        """An empty body holds no command, so it is the comment-only case."""
        assert skip_reason("", "") == "only comments"
        assert skip_reason("", "\n  \n") == "only comments"

    def test_an_inline_comment_does_not_exclude(self) -> None:
        """A trailing comment leaves a command on the line, which must still parse."""
        assert skip_reason("", "make test  # runs the suite") is None

    def test_a_command_after_a_comment_does_not_exclude(self) -> None:
        """One real line among comments is enough to be worth parsing."""
        assert skip_reason("", "# explain\nmake test") is None

    def test_the_flag_is_reported_ahead_of_an_inferred_reason(self) -> None:
        """Where a fence qualifies twice, the explicit instruction is what is reported.

        Not cosmetic: the log line is how a reader learns why a fence went unchecked, and
        "the author excluded it" and "we decided it was a tree" are different facts.
        """
        assert skip_reason(" +RHIZA_SKIP", "# see the Makefile") == "+RHIZA_SKIP flag"
        assert skip_reason(" +RHIZA_SKIP", "a\n└── b") == "+RHIZA_SKIP flag"


class TestClassifyBashBlocks:
    """Tests for enumerating a document's bash fences with their verdicts."""

    def test_indexes_count_every_fence_including_excluded_ones(self) -> None:
        """The index names the fence a reader counting fences would name.

        This is the reason the index is carried rather than recomputed over the parsed
        subset: "Bash block 2 has syntax errors" has to mean the third fence in the file,
        not the third *checked* one.
        """
        doc = "```bash +RHIZA_SKIP\nrm -rf /\n```\n```bash\n# just a note\n```\n```bash\nmake test\n```\n"
        assert [(i, reason) for i, _code, reason in classify_bash_blocks(doc)] == [
            (0, "+RHIZA_SKIP flag"),
            (1, "only comments"),
            (2, None),
        ]

    def test_a_document_with_no_bash_fences_is_empty(self) -> None:
        """A Rust or Go README may legitimately have none; that is not an error."""
        assert classify_bash_blocks("# Title\n\nProse only.\n") == []

    def test_python_fences_are_not_collected(self) -> None:
        """Only bash fences — the python half belongs to test_readme_validation."""
        assert classify_bash_blocks("```python\nprint(1)\n```\n") == []

    def test_the_fence_body_is_returned_verbatim(self) -> None:
        """The body is what gets piped to `bash -n`, so it must not be reshaped."""
        [(_index, code, _reason)] = classify_bash_blocks("```bash\nmake test\nmake lint\n```\n")
        assert code == "make test\nmake lint\n"


class TestSkipFlag:
    """Tests for the +RHIZA_SKIP flag that excludes an individual fence."""

    def test_should_skip_returns_true_for_skip_flag(self) -> None:
        """+RHIZA_SKIP in flags string should cause should_skip to return True."""
        assert should_skip(" +RHIZA_SKIP") is True
        assert should_skip("+RHIZA_SKIP") is True
        assert should_skip(" +RHIZA_SKIP other-flag") is True

    def test_should_skip_returns_false_without_flag(self) -> None:
        """Absence of +RHIZA_SKIP should cause should_skip to return False."""
        assert should_skip("") is False
        assert should_skip(" ") is False
        assert should_skip("other-flag") is False

    def test_bash_block_with_skip_flag_is_excluded(self, tmp_path: Path) -> None:
        """A ```bash +RHIZA_SKIP block should not be syntax-checked."""
        readme = tmp_path / "README.md"
        readme.write_text(
            "```bash +RHIZA_SKIP\nnot-valid-bash @@@@\n```\n```bash\necho hello\n```\n",
            encoding="utf-8",
        )
        all_blocks = BASH_BLOCK.findall(readme.read_text(encoding="utf-8"))
        assert len(all_blocks) == 2
        checked = [code for flags, code in all_blocks if not should_skip(flags)]
        assert len(checked) == 1
        assert "not-valid-bash" not in checked[0]

    def test_python_block_with_skip_flag_is_excluded(self, tmp_path: Path) -> None:
        """A ```python +RHIZA_SKIP block should not appear in the list of blocks to execute."""
        readme = tmp_path / "README.md"
        readme.write_text(
            '```python +RHIZA_SKIP\nraise RuntimeError("should not run")\n```\n'
            "```python\nprint('hello')\n```\n"
            "```result\nhello\n```\n",
            encoding="utf-8",
        )
        all_blocks = CODE_BLOCK.findall(readme.read_text(encoding="utf-8"))
        assert len(all_blocks) == 2
        executed = [code for flags, code in all_blocks if not should_skip(flags)]
        assert len(executed) == 1
        assert "raise RuntimeError" not in executed[0]


class TestClassifyPyconBlocks:
    """Tests for locating the pycon fences — the convention for runnable README examples."""

    def test_the_line_is_where_the_body_starts(self) -> None:
        """Zero-based, and the line *after* the opening fence, so doctest's offset adds to it."""
        doc = "# Title\n\n```pycon\n>>> 1\n1\n```\n"
        [fence] = classify_pycon_blocks(doc)
        assert fence.line == 3
        assert doc.splitlines()[fence.line] == ">>> 1"

    def test_indexes_count_skipped_fences_too(self) -> None:
        """As for bash: the index is the fence a reader counting from the top would name."""
        doc = "```pycon +RHIZA_SKIP\n>>> no()\n```\n```pycon\n>>> 1\n1\n```\n"
        assert [(f.position, f.skipped) for f in classify_pycon_blocks(doc)] == [(0, True), (1, False)]

    def test_an_inline_mention_does_not_open_a_fence(self) -> None:
        """Prose naming the fence in inline code is not a transcript.

        The regression the anchoring exists for: this package's own README says "a
        `pycon` fence" in prose, and an unanchored pattern would have opened a fence there
        and doctested the paragraphs up to the next triple backtick.
        """
        doc = "Use a ` ```pycon ` fence, and ` ```python ` too.\n\n```pycon\n>>> 1\n1\n```\n"
        assert [f.body for f in classify_pycon_blocks(doc)] == [">>> 1\n1\n"]

    def test_an_indented_fence_inside_a_list_item_is_collected(self) -> None:
        """Markdown indents a fence nested in a list; doctest accepts indented transcripts."""
        doc = "- step one:\n\n  ```pycon\n  >>> 1 + 1\n  2\n  ```\n"
        [fence] = classify_pycon_blocks(doc)
        test = pycon_doctest([fence], "README.md", {})
        assert [(e.source, e.want) for e in test.examples] == [("1 + 1\n", "2\n")]

    def test_legacy_fences_are_not_collected(self) -> None:
        """Legacy ``python`` and ``result`` fences stay with the legacy check, so nothing is judged twice."""
        assert classify_pycon_blocks("```python\nprint(1)\n```\n```result\n1\n```\n") == []

    def test_a_document_with_no_pycon_fences_is_empty(self) -> None:
        """Not an error — the checks treat it as nothing to run."""
        assert classify_pycon_blocks("# Title\n\nProse only.\n") == []

    def test_fences_survive_a_json_round_trip(self) -> None:
        """The executing check ships fences to its child as JSON; they must come back equal."""
        fences = classify_pycon_blocks("```pycon +RHIZA_SKIP\n>>> 1\n```\n```pycon\n>>> 'x'\n'x'\n```\n")
        assert [PyconFence(*row) for row in json.loads(json.dumps(fences))] == fences


class TestPyconDoctest:
    """Tests for combining the fences into the one doctest the executing check runs."""

    @staticmethod
    def _run(test: doctest.DocTest) -> doctest.TestResults:
        """Run a doctest quietly, with the flags the check uses."""
        return doctest.DocTestRunner(verbose=False, optionflags=doctest.ELLIPSIS).run(test, out=lambda _text: None)

    def test_fences_share_one_namespace(self) -> None:
        """A name bound in the first fence is visible in the second, as in the joined script."""
        doc = "```pycon\n>>> x = 21\n```\n\nprose\n\n```pycon\n>>> x * 2\n42\n```\n"
        test = pycon_doctest(classify_pycon_blocks(doc), "README.md", {})
        assert self._run(test) == doctest.TestResults(failed=0, attempted=2)

    def test_line_numbers_are_document_lines(self) -> None:
        """Each example's line is its line in the README, which is what the report prints.

        The report prints ``test.lineno + example.lineno + 1``; ``test.lineno`` is 0, so the
        zero-based example line plus one must land on the line holding its prompt.
        """
        doc = "# T\n\n```pycon\n>>> a = 1\n```\n\n```pycon\n>>> a\n1\n```\n"
        test = pycon_doctest(classify_pycon_blocks(doc), "README.md", {})
        lines = doc.splitlines()
        assert [lines[e.lineno] for e in test.examples] == [">>> a = 1", ">>> a"]
        assert test.lineno == 0
        assert test.filename == "README.md"

    def test_skipped_fences_contribute_nothing(self) -> None:
        """Not run, and not even parsed — a skipped body may be a malformed transcript."""
        doc = "```pycon +RHIZA_SKIP\n>>>not even a prompt\n```\n```pycon\n>>> 1\n1\n```\n"
        test = pycon_doctest(classify_pycon_blocks(doc), "README.md", {})
        assert [e.source for e in test.examples] == ["1\n"]

    def test_expected_output_ends_at_the_fence_boundary(self) -> None:
        """A fence ends its last example's output even with no blank line before the next.

        The point of parsing per fence: the closing fence is the boundary, so the next
        fence's prompt can never be mistaken for expected output of the one before it.
        """
        doc = "```pycon\n>>> 1\n1\n```\n```pycon\n>>> 2\n2\n```\n"
        test = pycon_doctest(classify_pycon_blocks(doc), "README.md", {})
        assert [e.want for e in test.examples] == ["1\n", "2\n"]

    def test_ellipsis_matches_under_the_checks_flags(self) -> None:
        """The flag the check passes is what makes an unstable repr documentable."""
        doc = "```pycon\n>>> object()\n<object object at 0x...>\n```\n"
        test = pycon_doctest(classify_pycon_blocks(doc), "README.md", {})
        assert self._run(test) == doctest.TestResults(failed=0, attempted=1)

    def test_a_malformed_prompt_names_fence_and_line(self) -> None:
        """Doctest's own complaint, led by the fence index and the README line.

        The README line is the fence's start plus doctest's own (one-based) line within the
        body: the bad prompt is the body's third line, and the body starts on line 3.
        """
        doc = "# T\n\n```pycon\n>>> 1\n1\n>>>2\n```\n"
        with pytest.raises(TranscriptError, match=r"^pycon fence 0 \(README\.md line 6\): .*lacks blank after >>>"):
            pycon_doctest(classify_pycon_blocks(doc), "README.md", {})
        assert doc.splitlines()[5] == ">>>2"

    def test_a_transcript_error_is_a_value_error(self) -> None:
        """Callers already catching doctest's ``ValueError`` keep catching it."""
        assert issubclass(TranscriptError, ValueError)

    def test_an_unrecognised_parse_message_points_at_the_fence_start(self) -> None:
        """The line pointer degrades rather than raising if doctest rewords its message."""
        error = TranscriptError(PyconFence(3, 10, "", False), "README.md", ValueError("reworded"))
        assert str(error) == "pycon fence 3 (README.md line 11): reworded"


def _parses_cleanly(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
    """Stand in for a bash that parses the probe without complaint."""
    return subprocess.CompletedProcess(args=["bash", "-n"], returncode=0, stdout="", stderr="")


class TestBashUsable:
    """Tests for the probe that decides whether `bash -n` can be trusted.

    The bug this guards against: on a Windows runner ``bash`` resolved to the WSL
    launcher stub, which exits non-zero having written nothing. ``bash -n`` signals a
    syntax error the same way, so every README fence was reported broken with a blank
    error message. Probing a known-good snippet is what tells the two apart.
    """

    def test_agrees_with_the_real_interpreter(self) -> None:
        """The probe's verdict matches what this platform's bash actually does.

        The one test here that talks to the real interpreter, so it asserts agreement
        rather than a fixed answer: True on a developer machine, False on a Windows
        runner, and False again on a POSIX box whose ``bash`` is a stub. An earlier
        version asserted True unless ``os.name == "nt"``, which confused the platform
        for the capability and failed the moment a broken bash was put on PATH.
        """
        bash_usable.cache_clear()
        try:
            direct = subprocess.run([_fences.BASH, "-n"], input=":\n", capture_output=True, text=True)
        except OSError:
            expected = False
        else:
            expected = direct.returncode == 0

        assert bash_usable() is expected

    def test_rejects_an_interpreter_that_fails_silently(self, monkeypatch) -> None:
        """A bash that exits non-zero writing nothing is not usable — the WSL stub case.

        Faked rather than driven through a real binary: the behaviour being reproduced
        belongs to a Windows-only stub, and a stand-in like ``false`` does not exist
        there, so the test would pass on Windows for the wrong reason.
        """
        bash_usable.cache_clear()

        def _silent_failure(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            """Stand in for a bash that exits non-zero saying nothing at all."""
            return subprocess.CompletedProcess(args=["bash", "-n"], returncode=1, stdout="", stderr="")

        monkeypatch.setattr(_fences.subprocess, "run", _silent_failure)
        assert bash_usable() is False

    def test_rejects_a_missing_bash(self, monkeypatch) -> None:
        """No bash on PATH raises OSError, which the probe swallows into False."""
        bash_usable.cache_clear()
        monkeypatch.setattr(_fences, "BASH", "no-such-shell-anywhere")
        assert bash_usable() is False

    def test_rejects_a_bash_that_hangs(self, monkeypatch) -> None:
        """A bash that cannot parse ``:`` inside the budget is not usable either (#44).

        The probe is bounded like every other child process in the package, and the
        verdict on a timeout is the same as on a missing binary rather than a failure:
        this function's whole job is to answer "can this platform parse fences at all",
        and "it never came back" is a no. Reporting it as a failure instead would accuse
        every README of a defect the toolchain invented — the same mistake the WSL-stub
        case above exists to prevent.

        Faked, because a bash that hangs on ``:`` cannot be produced on demand.
        """
        bash_usable.cache_clear()

        def _hangs(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            """Stand in for a bash that never returns."""
            raise subprocess.TimeoutExpired(cmd=["bash", "-n"], timeout=1)

        monkeypatch.setattr(_fences.subprocess, "run", _hangs)
        assert bash_usable() is False
        bash_usable.cache_clear()

    def test_accepts_an_interpreter_that_parses(self, monkeypatch) -> None:
        """A bash that exits zero is usable — the mirror of the silent-failure case."""
        bash_usable.cache_clear()
        monkeypatch.setattr(_fences.subprocess, "run", _parses_cleanly)
        assert bash_usable() is True

    def test_result_is_cached(self, monkeypatch) -> None:
        """The probe runs once per session; every fence would otherwise re-pay it.

        Driven through the fake so it holds on Windows too, where the real probe is
        legitimately False and the caching question is the same either way.
        """
        bash_usable.cache_clear()
        monkeypatch.setattr(_fences.subprocess, "run", _parses_cleanly)
        assert bash_usable() is True

        monkeypatch.setattr(_fences, "BASH", "no-such-shell-anywhere")
        assert bash_usable() is True, "cached result should survive a later BASH change"
        bash_usable.cache_clear()
