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

import subprocess  # nosec B404
from pathlib import Path

import pytest

from pytest_rhiza._fences import BASH, BASH_BLOCK, SKIP_FLAG, TREE_MARKERS, should_skip


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

    def test_bash_blocks_basic_syntax(self, root: Path, logger) -> None:
        """Every non-skipped bash block should parse under `bash -n`."""
        content = (root / "README.md").read_text(encoding="utf-8")
        bash_blocks = BASH_BLOCK.findall(content)

        logger.info("Found %d bash code block(s) in README", len(bash_blocks))

        for i, (flags, code) in enumerate(bash_blocks):
            if should_skip(flags):
                logger.info("Skipping bash block %d (%s flag)", i, SKIP_FLAG)
                continue

            if any(marker in code for marker in TREE_MARKERS):
                logger.info("Skipping bash block %d (directory tree representation)", i)
                continue

            # A block that is only comments has nothing to parse and no way to be wrong.
            lines = [line.strip() for line in code.split("\n") if line.strip()]
            if not [line for line in lines if not line.startswith("#")]:
                logger.info("Skipping bash block %d (only comments)", i)
                continue

            logger.debug("Checking bash block %d:\n%s", i, code)

            result = subprocess.run(  # nosec B603 B607 - `bash -n` parses without executing
                [BASH, "-n"],
                input=code,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                pytest.fail(f"Bash block {i} has syntax errors:\nCode:\n{code}\nError:\n{result.stderr}")
