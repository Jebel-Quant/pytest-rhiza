"""Tests for the shared fence parsing.

These are the ``TestSkipFlag`` classes from the template's ``test_readme.py`` and
``test_readme_validation.py``, moved here. Upstream they shipped into every consumer
repository, where each ``make rhiza-test`` re-tested template-internal helpers against
themselves; they belong to whoever owns the helper, which is now this package.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pytest_rhiza import _fences
from pytest_rhiza._fences import BASH_BLOCK, CODE_BLOCK, bash_usable, classify_bash_blocks, should_skip, skip_reason


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
