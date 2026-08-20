"""Markdown fence parsing shared by the two README checks.

**Why this module exists.** Upstream, ``SKIP_FLAG`` and ``_should_skip`` are duplicated
between ``core``'s ``test_readme.py`` and the ``tests`` bundle's
``test_readme_validation.py``, and both files say why::

    Bundles are copied independently — a Rust project receives this file and not the
    other — so a shared helper would need a third home that both bundles ship, which is
    a worse trade for four lines.

One distribution *is* that third home, so the trade reverses. The duplication also had a
second cost that is easy to miss: the ``TestSkipFlag`` classes exercising these helpers
shipped into every consumer repository, where they tested template code against itself.
They now live in this package's own suite instead.

The regexes and the flag keep their upstream names so the ported checks read as a move.
"""

from __future__ import annotations

import functools
import re
import subprocess  # nosec B404

# Bash code blocks — captures optional flags (e.g. "+RHIZA_SKIP") and the code body.
BASH_BLOCK = re.compile(r"```bash([^\n]*)\n(.*?)```", re.DOTALL)

# Python code blocks, same shape.
CODE_BLOCK = re.compile(r"```python([^\n]*)\n(.*?)```", re.DOTALL)

# The ```result fences a python fence's stdout is diffed against.
RESULT = re.compile(r"```result\n(.*?)```", re.DOTALL)

# Bash executable used for syntax checking; `bash -n` parses without executing.
BASH = "bash"

# A snippet that is unambiguously valid bash: `:` is the no-op builtin. Used to probe
# the toolchain rather than the README.
_PROBE = ":\n"

# Flag marking a fence as intentionally excluded. Usage: add it after the language
# identifier on the opening fence line, e.g. ```bash +RHIZA_SKIP
SKIP_FLAG = "+RHIZA_SKIP"

# Box-drawing characters mean the fence is a directory tree, not runnable shell.
TREE_MARKERS = ("├──", "└──", "│")


def should_skip(flags: str) -> bool:
    """Return True if the fence flags string contains the +RHIZA_SKIP marker.

    Args:
        flags: Text following the language identifier on the opening fence line.

    Returns:
        True when the block is intentionally excluded.

    Examples:
        >>> should_skip(" +RHIZA_SKIP")
        True
        >>> should_skip("other-flag")
        False
    """
    return SKIP_FLAG in flags


def _holds_a_command(code: str) -> bool:
    r"""Report whether a fence holds anything besides blank lines and comments.

    Args:
        code: The fence body.

    Returns:
        True when at least one non-comment, non-blank line is present.

    Examples:
        >>> _holds_a_command("make test\n")
        True
        >>> _holds_a_command("# just explaining\n#\n\n")
        False
        >>> _holds_a_command("")
        False

        An inline comment does not make the line a comment:

        >>> _holds_a_command("make test  # runs the suite")
        True
    """
    lines = [line.strip() for line in code.split("\n") if line.strip()]
    return any(not line.startswith("#") for line in lines)


def skip_reason(flags: str, code: str) -> str | None:
    r"""Return why a bash fence needs no parsing, or None when it should be parsed.

    The three exclusions are each here for a different reason, which is why this returns
    the reason rather than a bool: the caller logs it, and "skipped 4 of 6 fences" with
    no explanation is the kind of green that hides a mistake.

    Args:
        flags: Text following the language identifier on the opening fence line.
        code: The fence body.

    Returns:
        A short phrase naming the exclusion, or None to parse the fence.

    Examples:
        >>> skip_reason("", "make test") is None
        True
        >>> skip_reason(" +RHIZA_SKIP", "make test")
        '+RHIZA_SKIP flag'

        A directory tree is prose drawn with box characters, not shell:

        >>> skip_reason("", "src/\n\u251c\u2500\u2500 pytest_rhiza/")
        'directory tree representation'

        A comment-only fence has nothing to parse and no way to be wrong:

        >>> skip_reason("", "# see the Makefile")
        'only comments'

        Order matters where a fence qualifies twice — the flag is the author's explicit
        instruction, so it is reported ahead of anything inferred:

        >>> skip_reason(" +RHIZA_SKIP", "# see the Makefile")
        '+RHIZA_SKIP flag'
    """
    if should_skip(flags):
        return f"{SKIP_FLAG} flag"
    if any(marker in code for marker in TREE_MARKERS):
        return "directory tree representation"
    if not _holds_a_command(code):
        return "only comments"
    return None


def classify_bash_blocks(content: str) -> list[tuple[int, str, str | None]]:
    r"""Return every bash fence in a markdown document, with its exclusion verdict.

    Args:
        content: The markdown source.

    Returns:
        One ``(index, code, skip_reason)`` triple per fence, in document order. The index
        is the fence's position among *all* bash fences, so a failure message names the
        same block a reader counting fences would.

    Examples:
        >>> doc = "```bash\nmake test\n```\n\n```bash +RHIZA_SKIP\nrm -rf /\n```\n"
        >>> [(i, reason) for i, _code, reason in classify_bash_blocks(doc)]
        [(0, None), (1, '+RHIZA_SKIP flag')]

        A document with no bash fences is empty rather than an error — a Rust project's
        README may legitimately have none:

        >>> classify_bash_blocks("# Title\n")
        []
    """
    return [(index, code, skip_reason(flags, code)) for index, (flags, code) in enumerate(BASH_BLOCK.findall(content))]


@functools.cache
def bash_usable() -> bool:
    r"""Return True when ``bash -n`` actually parses a trivially valid snippet.

    **Why probe instead of just running the check.** ``bash -n`` reports a syntax error
    by exiting non-zero, so anything else that exits non-zero is indistinguishable from
    one. On Windows that is not hypothetical: ``bash`` can resolve to
    ``C:\Windows\System32\bash.exe``, the WSL launcher, which exits non-zero having
    written nothing to stderr when no distribution is installed. The README checks then
    fail on ``make install`` and print an empty error, which is worse than not running:
    it accuses the project of a defect the tool invented.

    Probing with :data:`_PROBE` separates "this fence is broken" from "there is no usable
    bash here", so the checks can skip honestly in the second case. The result is cached
    because it cannot change within a session and every fence would otherwise re-pay it.

    Returns:
        True when a working bash was found, False otherwise.
    """
    try:
        result = subprocess.run(  # noqa: S603 - fixed argument list, no shell  # nosec B603
            [BASH, "-n"],
            input=_PROBE,
            capture_output=True,
            text=True,
        )
    except OSError:
        # bash is absent entirely, or not executable.
        return False
    return result.returncode == 0
