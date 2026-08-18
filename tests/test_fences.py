"""Tests for the shared fence parsing.

These are the ``TestSkipFlag`` classes from the template's ``test_readme.py`` and
``test_readme_validation.py``, moved here. Upstream they shipped into every consumer
repository, where each ``make rhiza-test`` re-tested template-internal helpers against
themselves; they belong to whoever owns the helper, which is now this package.
"""

from __future__ import annotations

from pathlib import Path

from pytest_rhiza._fences import BASH_BLOCK, CODE_BLOCK, should_skip


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
