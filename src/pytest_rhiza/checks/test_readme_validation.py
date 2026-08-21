"""Tests for executable Python examples in the README.

Ported from ``jebel-quant/rhiza`` at 89f9298, where bundle ``tests`` synced it
to ``.rhiza/tests/test_readme_validation.py``. It now arrives installed, and is collected by name:
``pytest --pyargs pytest_rhiza.checks.test_readme_validation``.

This module extracts Python code and expected result blocks from README.md,
executes the code, and verifies the output matches the documented result.

The language-neutral half — that the README exists, and that its ``bash`` fences
parse — moved to ``core``'s ``test_readme.py`` in #1472, so a Rust or Go project gets it
too. What stays here only means something where the project itself is Python: running a
``python`` fence and diffing it against the following ``result`` block.

``SKIP_FLAG`` and the fence regexes are shared with that module via
:mod:`pytest_rhiza._fences`. Upstream they were duplicated because bundles are copied
independently and a shared helper would need a third home both bundles ship; one
distribution is that home.
"""

import difflib
import logging
import sys
from pathlib import Path

import pytest

from pytest_rhiza._fences import CODE_BLOCK, RESULT, SKIP_FLAG, should_skip
from pytest_rhiza._process import execute_timeout, run


def _mismatch(code_blocks: list[str], result_blocks: list[str], expected: str, actual: str) -> str:
    """Explain an output mismatch, as the message for the assertion that found it (#46).

    The assertion this serves used to carry no message at all, which mattered more here
    than it looks: every ``python`` fence is executed as *one* script and diffed against
    *all* the ``result`` fences merged, so pytest's own output was two opaque blobs with no
    indication of which fence had drifted. This says how the merge works, so the reader can
    map a diff line back to a fence, and shows the difference as a diff rather than as two
    values to compare by eye.

    Args:
        code_blocks: The non-skipped python fence bodies, in document order.
        result_blocks: The ``result`` fence bodies, in document order.
        expected: The merged documented output.
        actual: What the merged script actually printed.

    Returns:
        The failure message.
    """
    diff = "\n".join(
        difflib.unified_diff(
            expected.strip().splitlines(),
            actual.strip().splitlines(),
            fromfile="documented (```result``` fences)",
            tofile="actual (stdout)",
            lineterm="",
        )
    )
    return (
        f"README output does not match its documented result.\n\n"
        f"{len(code_blocks)} python fence(s) are concatenated into one script and its stdout "
        f"compared against {len(result_blocks)} ```result``` fence(s) concatenated in document "
        f"order — so line N of the diff below is line N of that merged text, and counting "
        f"``result`` fences from the top of the README names the one to fix.\n\n{diff}"
    )


def test_readme_runs(logger: logging.Logger, root: Path) -> None:
    """Execute README code blocks and compare output to documented results."""
    readme = root / "README.md"
    logger.info("Reading README from %s", readme)
    readme_text = readme.read_text(encoding="utf-8")
    all_code_blocks = CODE_BLOCK.findall(readme_text)
    result_blocks = RESULT.findall(readme_text)

    code_blocks = []
    for i, (flags, code) in enumerate(all_code_blocks):
        if should_skip(flags):
            logger.info("Skipping Python code block %d (%s flag)", i, SKIP_FLAG)
        else:
            code_blocks.append(code)

    logger.info(
        "Found %d code block(s) (%d skipped) and %d result block(s) in README",
        len(all_code_blocks),
        len(all_code_blocks) - len(code_blocks),
        len(result_blocks),
    )

    code = "".join(code_blocks)  # merged code
    expected = "".join(result_blocks)  # merged results

    # Trust boundary: we execute Python snippets sourced from README.md in this repo.
    # The README is part of the trusted repository content and reviewed in PRs.
    #
    # Bounded, because this is the one call in the package that runs code somebody wrote
    # rather than inspecting something (#44). An example that waits on `input()` or blocks
    # on a network call used to hang the gate instead of failing it — and a hung CI job
    # reports nothing while spending the whole runner budget.
    logger.debug("Executing README code via %s -c ...", sys.executable)
    result = run(
        [sys.executable, "-c", code],
        cwd=root,
        timeout=execute_timeout(),
        on_timeout=(
            f"the README's python fences did not finish. They are executed as one script, so "
            f"one example waiting for input, blocking on the network, or looping forever stops "
            f"all of them. Make it terminate, or mark that fence ```python {SKIP_FLAG}```."
        ),
    )

    stdout = result.stdout
    logger.debug("Execution finished with return code %d", result.returncode)
    if result.stderr:
        logger.debug("Stderr from README code:\n%s", result.stderr)
    logger.debug("Stdout from README code:\n%s", stdout)

    assert result.returncode == 0, f"README code exited with {result.returncode}. Stderr:\n{result.stderr}"
    logger.info("README code executed successfully; comparing output to expected result")
    assert stdout.strip() == expected.strip(), _mismatch(code_blocks, result_blocks, expected, stdout)
    logger.info("README code output matches expected result")


class TestReadmeTestEdgeCases:
    """Edge cases for README code block testing."""

    def test_readme_code_is_syntactically_valid(self, root: Path) -> None:
        """Python code blocks in README should be syntactically valid (skipped blocks are excluded)."""
        readme = root / "README.md"
        content = readme.read_text(encoding="utf-8")
        all_code_blocks = CODE_BLOCK.findall(content)

        for i, (flags, code) in enumerate(all_code_blocks):
            if should_skip(flags):
                continue
            try:
                compile(code, f"<readme_block_{i}>", "exec")
            except SyntaxError as e:
                pytest.fail(f"Code block {i} has syntax error: {e}")
