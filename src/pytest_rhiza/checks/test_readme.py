"""Tests for the README that hold whatever the project is written in.

Ported from ``jebel-quant/rhiza`` at 89f9298, where bundle ``core`` synced it
to ``.rhiza/tests/test_readme.py``. It now arrives installed, and is collected by name:
``pytest --pyargs pytest_rhiza.checks.test_readme``.

Owned by ``core`` because none of it is language-specific: every synced README documents
its gates in ``bash`` fences — ``make install``, ``make test``, ``make all`` — and a
fence with a syntax error is broken the same way in a Rust, Go or Python project. Before
this split (#1472) all of it lived in the ``tests`` bundle, which requires
``python-core``, so a Rust or Go repo had no README coverage at all.

The Python-block half stays behind in ``tests`` as ``test_readme_validation.py``: it
executes ``python`` fences and diffs them against a ``result`` block, which only means
something where the project *is* Python.

The fence flag helpers moved to :mod:`pytest_rhiza._fences`, shared with
``test_readme_validation``. Upstream they were duplicated because bundles are copied
independently and a shared helper would need a third home both bundles ship; one
distribution is that home.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from pytest_rhiza._fences import BASH, bash_usable, classify_bash_blocks
from pytest_rhiza._process import run


def _assert_parses(index: int, code: str) -> None:
    """Fail the test unless ``bash -n`` accepts one fence.

    Args:
        index: The fence's position among all bash fences, for the failure message.
        code: The fence body.

    Raises:
        Failed: via :func:`pytest.fail`, when bash rejects the snippet.
    """
    result = run(
        [BASH, "-n"],
        stdin=code,
        on_timeout=(
            f"`bash -n` never finished parsing block {index}. It parses without executing, "
            f"so this is the shell itself wedging rather than the fence running — see "
            f"`pytest_rhiza._fences.bash_usable` for the platform this tends to be."
        ),
    )
    if result.returncode == 0:
        return
    # stdout as well as stderr: a bash that fails for a reason other than syntax tends to
    # explain itself on stdout, and a blank error is the least actionable failure there is.
    detail = (result.stderr + result.stdout).strip() or f"exited {result.returncode}, saying nothing"
    pytest.fail(f"Bash block {index} has syntax errors:\nCode:\n{code}\nError:\n{detail}")


class TestReadmeExists:
    """The README has to be there and be readable before anything else applies."""

    def test_readme_file_exists_at_root(self, root: Path) -> None:
        """README.md should exist at repository root."""
        readme = root / "README.md"
        assert readme.exists(), "README.md not found at project root"
        assert readme.is_file(), "README.md is not a regular file"

    def test_readme_is_readable(self, root: Path) -> None:
        """README.md should be readable with UTF-8 encoding and non-empty."""
        content = (root / "README.md").read_text(encoding="utf-8")
        assert content.strip(), "README.md is empty"


class TestReadmeBashFragments:
    """Bash fences must parse, in any language's project.

    Only ``bash -n`` — the blocks are parsed, never executed. A README's shell examples
    are usually destructive-adjacent (`make clean`, `git push`) and running them is not
    what this is for; a fence that cannot even parse is a documentation bug regardless.
    """

    def test_bash_blocks_basic_syntax(self, root: Path, logger: logging.Logger) -> None:
        """Every non-skipped bash block should parse under `bash -n`.

        Skips where no working bash exists — see :func:`pytest_rhiza._fences.bash_usable`.
        A README's fences are the same text on every platform, so one runner that can
        parse them is enough; a runner that cannot must not invent syntax errors.

        Which fences are excluded, and why, is
        :func:`pytest_rhiza._fences.classify_bash_blocks` — doctested there rather than
        settled inline here.
        """
        if not bash_usable():
            pytest.skip("no working `bash -n` on this platform; README fences unchecked")

        blocks = classify_bash_blocks((root / "README.md").read_text(encoding="utf-8"))
        logger.info("Found %d bash code block(s) in README", len(blocks))

        for index, code, reason in blocks:
            if reason is not None:
                logger.info("Skipping bash block %d (%s)", index, reason)
                continue
            logger.debug("Checking bash block %d:\n%s", index, code)
            _assert_parses(index, code)
