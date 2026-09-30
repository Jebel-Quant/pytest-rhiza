"""Tests for executable Python examples in the README.

Ported from ``jebel-quant/rhiza`` at 89f9298, where bundle ``tests`` synced it
to ``.rhiza/tests/test_readme_validation.py``. It now arrives installed, and is collected by name:
``pytest --pyargs pytest_rhiza.checks.test_readme_validation``.

**The convention: ```pycon fences, run as a doctest.** A runnable README example is a
doctest transcript — ``>>>`` / ``...`` prompts with the expected output written inline
under the statement that produces it. Every such fence in README.md is collected, the
skipped ones (``+RHIZA_SKIP`` after the language, as for any fence) are dropped, and the
rest run as *one* doctest with a shared namespace, ``ELLIPSIS`` enabled and ``__name__``
set to ``"__main__"`` — in a child interpreter, never in this one. A failure is doctest's
own report: which example, at which README line, what was expected and what came out.

**The legacy shape: ```python + ```result.** Before the fleet moved to transcripts, a
README executed its ``python`` fences as one script and diffed the stdout against every
``result`` fence merged. That still runs, unchanged, because consumer repositories migrate
on their own schedule and one that has not yet converted must keep both its coverage and
its green. It is legacy in the sense that nothing new should be written that way: the code
and its output live in separate fences, and a drift can only be reported as "line N of the
merged text", which the reader then has to map back to a fence by counting.

The two are independent tests, so a README holding both shapes has both checked, and one
holding neither passes both — there is nothing to execute, which is not a defect. That is
a pass rather than a skip on purpose: this repository's ``rhiza-test`` job fails on *any*
skip (#34), and a README with no Python examples is an ordinary, correct state for it.

The language-neutral half — that the README exists, and that its ``bash`` fences
parse — moved to ``core``'s ``test_readme.py`` in #1472, so a Rust or Go project gets it
too. What stays here only means something where the project itself is Python.

``SKIP_FLAG`` and the fence regexes are shared with that module via
:mod:`pytest_rhiza._fences`. Upstream they were duplicated because bundles are copied
independently and a shared helper would need a third home both bundles ship; one
distribution is that home.
"""

import difflib
import json
import logging
import sys
from pathlib import Path

import pytest

from pytest_rhiza._fences import (
    CODE_BLOCK,
    RESULT,
    SKIP_FLAG,
    TranscriptError,
    classify_pycon_blocks,
    pycon_doctest,
    should_skip,
)
from pytest_rhiza._process import execute_timeout, run

# The program the child interpreter runs for the pycon check. It is fixed text; the README
# reaches it only as JSON *data* on stdin, never spliced into the source, so no fence body
# can change what this program is — only what the doctest it builds contains.
#
# It imports pytest_rhiza rather than re-implementing the parse, so the child builds the
# very DocTest the in-process syntax check built: one parser, two callers. The report goes
# to stdout (DocTestRunner's default writer), which is what the assertion message shows.
# `verbose=False` is explicit because doctest otherwise infers verbosity from `-v` in
# sys.argv, and the child's argv is not something this check should depend on.
_PYCON_RUNNER = """\
import doctest, json, sys
from pytest_rhiza._fences import PyconFence, pycon_doctest
payload = json.load(sys.stdin)
fences = [PyconFence(*row) for row in payload["fences"]]
test = pycon_doctest(fences, payload["filename"], {"__name__": "__main__"})
runner = doctest.DocTestRunner(verbose=False, optionflags=doctest.ELLIPSIS)
runner.run(test)
sys.exit(1 if runner.failures else 0)
"""


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


def test_readme_pycon_transcripts_hold(logger: logging.Logger, root: Path) -> None:
    """Run every non-skipped ```pycon fence in README.md as one doctest.

    Passes, rather than skipping, when there is no pycon fence to run — see the module
    docstring for why a README without examples is not a skip.
    """
    readme = root / "README.md"
    logger.info("Reading README from %s", readme)
    fences = classify_pycon_blocks(readme.read_text(encoding="utf-8"))
    for fence in fences:
        if fence.skipped:
            logger.info("Skipping pycon fence %d (%s flag)", fence.position, SKIP_FLAG)
    live = [fence for fence in fences if not fence.skipped]
    logger.info("Found %d pycon fence(s) (%d skipped) in README", len(fences), len(fences) - len(live))
    if not live:
        # Nothing to run. Spawning an interpreter to attempt zero examples would prove
        # nothing and cost a process start on every consumer's every run.
        return

    # Trust boundary: as for the legacy check below, the README is trusted repository
    # content reviewed in PRs, and it is executed in a child — bounded by the same
    # execute budget (#44) — never in this interpreter, where a fence could reach into
    # the session that is judging it.
    logger.debug("Doctesting %d pycon fence(s) via %s -c ...", len(live), sys.executable)
    result = run(
        [sys.executable, "-c", _PYCON_RUNNER],
        cwd=root,
        stdin=json.dumps({"filename": "README.md", "fences": fences}),
        timeout=execute_timeout(),
        on_timeout=(
            f"the README's pycon fences did not finish. They run as one doctest, so one "
            f"example waiting for input, blocking on the network, or looping forever stops "
            f"all of them. Make it terminate, or mark that fence ```pycon {SKIP_FLAG}```."
        ),
    )
    logger.debug("Doctest finished with return code %d", result.returncode)

    # Two ways to be red, reported differently. A non-zero exit with a report on stdout is
    # doctest saying an example disagreed — the report *is* the message. A non-zero exit
    # with nothing on stdout means the runner itself died before reporting (a malformed
    # transcript, an import error), and then stderr is the only evidence there is.
    assert result.returncode == 0, (
        f"README pycon fences failed as a doctest ({len(live)} fence(s), one shared namespace, "
        f"ELLIPSIS enabled). Line numbers below are README.md lines.\n\n"
        f"{result.stdout or result.stderr}"
    )
    logger.info("README pycon transcripts hold")


def test_readme_runs(logger: logging.Logger, root: Path) -> None:
    """Execute legacy ```python fences and compare their output to the ```result fences.

    Kept for consumers that have not moved to ```pycon transcripts; see the module
    docstring. A README with no python fences passes: the empty script prints the empty
    string, which equals the empty merged result.
    """
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

    def test_readme_pycon_fences_parse(self, root: Path) -> None:
        """Every non-skipped ```pycon fence is a well-formed transcript of valid Python.

        Two failures this separates from the executing test, each worth its own message:
        doctest refusing the transcript itself — a ``>>>`` with no space after it, an
        indentation mismatch under ``...`` — which in the child would surface as a
        traceback rather than a report; and an example that is not Python at all, which
        would otherwise read as a runtime exception inside an otherwise-green report.
        Parsing and compiling execute nothing, so both happen here, in-process.
        """
        fences = classify_pycon_blocks((root / "README.md").read_text(encoding="utf-8"))
        try:
            test = pycon_doctest(fences, "README.md", {})
        except TranscriptError as error:
            pytest.fail(f"README pycon fence is not a valid doctest transcript: {error}")
        for example in test.examples:
            try:
                # "single" is the mode doctest itself compiles an example in.
                compile(example.source, f"README.md line {example.lineno + 1}", "single")
            except SyntaxError as error:
                pytest.fail(f"README.md line {example.lineno + 1} (pycon example) has syntax error: {error}")

    def test_readme_code_is_syntactically_valid(self, root: Path) -> None:
        """Legacy python code blocks should be syntactically valid (skipped blocks are excluded)."""
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
