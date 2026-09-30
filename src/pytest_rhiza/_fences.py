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

**The pycon fence is the convention; python + result is legacy.** A runnable README
example is written as a ```pycon fence holding a doctest transcript — ``>>>`` and ``...``
prompts with the expected output inline, underneath the statement that produces it. The
older shape, a ```python fence whose stdout is diffed against a separate ```result fence,
kept the code and its output apart, so a reader had to match them up by eye and the check
could only report a drift as "line N of all the results merged". A transcript keeps each
output next to its cause, and doctest names the exact example that disagreed. Both shapes
are still parsed here: consumer repositories migrate on their own schedule, and one that
has not must not go red because this package moved first.
"""

from __future__ import annotations

import doctest
import functools
import re
import subprocess  # nosec B404
from collections.abc import Sequence
from typing import NamedTuple

from pytest_rhiza._process import inspect_timeout

# Bash code blocks — captures optional flags (e.g. "+RHIZA_SKIP") and the code body.
BASH_BLOCK = re.compile(r"```bash([^\n]*)\n(.*?)```", re.DOTALL)

# Doctest transcripts — the convention for a runnable README example. Same shape as the
# others: optional flags after the language, then the body. Written as its own pattern
# rather than folded into CODE_BLOCK because the two are *judged* differently — a pycon
# body is a doctest, a python body is a script — and a combined pattern would only move
# that decision into every caller.
#
# Unlike the legacy patterns, both fence lines are anchored to the start of a line (after
# optional indentation, for a fence inside a list item). Unanchored, prose that *mentions*
# the fence in inline code — as this package's own README does — would open a "fence" at
# the mention and run everything up to the next triple backtick as a transcript. The
# legacy patterns keep their upstream shape so their behaviour does not move under
# consumers that have not migrated.
PYCON_BLOCK = re.compile(r"^[ \t]*```pycon([^\n]*)\n(.*?)^[ \t]*```", re.DOTALL | re.MULTILINE)

# Legacy: python code blocks whose stdout is diffed against the ```result fences below.
# Still collected so a consumer that has not migrated to ```pycon keeps its coverage.
CODE_BLOCK = re.compile(r"```python([^\n]*)\n(.*?)```", re.DOTALL)

# Legacy: the ```result fences a python fence's stdout is diffed against.
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
            timeout=inspect_timeout(),
        )
    except OSError:
        # bash is absent entirely, or not executable.
        return False
    except subprocess.TimeoutExpired:
        # A `bash` that cannot parse `:` within the budget is not a usable bash. Reported
        # the same way as an absent one rather than as a failure: this function's whole
        # job is to answer "can this platform parse fences at all", and "it hung" is a no.
        return False
    return result.returncode == 0


class PyconFence(NamedTuple):
    """One ```pycon fence, located in its document.

    A named tuple rather than a dataclass for one practical reason: the executing check
    hands these to a child interpreter as JSON, and a named tuple serialises as a plain
    list and rebuilds with ``PyconFence(*row)`` — no custom encoder on either side of the
    process boundary. The one cost of being a tuple is that ``index`` is taken — by
    ``tuple.index`` — which is why the fence's ordinal is called ``position``.

    Attributes:
        position: Position among *all* pycon fences, skipped ones included, so a message
            names the fence a reader counting from the top of the file would name.
        line: Zero-based line of the document on which the fence *body* starts — the
            line after the opening ```pycon. Doctest adds its own offset within the body
            to this, which is what lets a failure report cite a README line number.
        body: The fence body, verbatim.
        skipped: True when the opening line carries :data:`SKIP_FLAG`.
    """

    position: int
    line: int
    body: str
    skipped: bool


def classify_pycon_blocks(content: str) -> list[PyconFence]:
    r"""Return every pycon fence in a markdown document, with where it starts.

    Args:
        content: The markdown source.

    Returns:
        One :class:`PyconFence` per fence, in document order.

    Examples:
        >>> doc = "# Demo\n\n```pycon\n>>> 1 + 1\n2\n```\n\n```pycon +RHIZA_SKIP\n>>> boom()\n```\n"
        >>> [(f.position, f.line, f.skipped) for f in classify_pycon_blocks(doc)]
        [(0, 3, False), (1, 8, True)]
        >>> classify_pycon_blocks(doc)[0].body
        '>>> 1 + 1\n2\n'

        The flag is honoured exactly as for bash and python fences — anywhere after the
        language identifier:

        >>> classify_pycon_blocks("```pycon  other +RHIZA_SKIP\n>>> 1\n```\n")[0].skipped
        True

        A mention in inline code is prose, not a fence:

        >>> [f.line for f in classify_pycon_blocks("Write a ` ```pycon ` fence.\n\n```pycon\n>>> 1\n1\n```\n")]
        [3]

        Neither legacy shape is collected, so the two checks never judge a fence twice:

        >>> classify_pycon_blocks("```python\nprint(1)\n```\n```result\n1\n```\n")
        []
    """
    return [
        PyconFence(index, content.count("\n", 0, match.start(2)), match.group(2), should_skip(match.group(1)))
        for index, match in enumerate(PYCON_BLOCK.finditer(content))
    ]


class TranscriptError(ValueError):
    """A pycon fence that doctest's parser refuses, located in the document.

    A ``ValueError`` subclass because that is what doctest raises and what a caller
    catching doctest's own error would already expect; the subclass exists to carry the
    location. Doctest's message counts lines from the start of the text it was given — a
    fence body the reader never sees on its own — so the message here leads with the fence
    index and the README line instead, and keeps doctest's wording after it.
    """

    def __init__(self, fence: PyconFence, filename: str, error: ValueError) -> None:
        """Build the message from the fence and doctest's own complaint.

        Args:
            fence: The fence that failed to parse.
            filename: What the report calls the document, e.g. ``README.md``.
            error: The ``ValueError`` doctest's parser raised.
        """
        line = fence.line + 1 + _first_offending_line(str(error))
        super().__init__(f"pycon fence {fence.position} ({filename} line {line}): {error}")


def pycon_doctest(fences: Sequence[PyconFence], filename: str, globs: dict[str, object]) -> doctest.DocTest:
    r"""Build *one* doctest out of every non-skipped pycon fence, in document order.

    **Why one test rather than one per fence.** The legacy check concatenated every python
    fence into a single script, so an import in the first fence served the examples in the
    third. READMEs are written that way — set up once, then show things — and splitting
    the transcript per fence would break every one of them for no gain. So the fences
    share a namespace, exactly as the joined script did.

    **Why the examples are parsed per fence and then combined, rather than parsing the
    joined text.** The outcome is the same one doctest over the same examples — a fence
    boundary ends an example's expected output either way, as a blank line would — but
    parsing each body separately lets every example's line number be shifted by the line
    its fence starts on. Doctest's failure report then reads ``File "README.md", line 94``
    and means line 94 *of the README*, which is the line to fix, instead of a line of an
    intermediate text the reader has never seen.

    Parsing executes nothing, which is why this is safe to call in-process: the syntax
    check does exactly that, and only the executing check runs the result — in a child.

    Args:
        fences: Every pycon fence of the document; the skipped ones contribute nothing.
        filename: What the report calls the document, e.g. ``README.md``.
        globs: The namespace the examples run in. The executing check passes
            ``{"__name__": "__main__"}``, which is what the legacy ``python -c`` script saw.

    Returns:
        The doctest, ready for :class:`doctest.DocTestRunner`.

    Raises:
        TranscriptError: A fence is not a well-formed transcript — doctest's own parser
            refuses, e.g., a prompt with no space after it. The message is doctest's,
            prefixed with the fence and README line it concerns.

    Examples:
        >>> fences = [PyconFence(0, 4, ">>> x = 21\n", False), PyconFence(1, 9, ">>> x * 2\n42\n", False)]
        >>> test = pycon_doctest(fences, "README.md", {})
        >>> [(e.source, e.want, e.lineno) for e in test.examples]
        [('x = 21\n', '', 4), ('x * 2\n', '42\n', 9)]
        >>> doctest.DocTestRunner(verbose=False).run(test)
        TestResults(failed=0, attempted=2)

        A skipped fence is not parsed at all, so it may hold anything:

        >>> pycon_doctest([PyconFence(0, 0, ">>>broken", True)], "README.md", {}).examples
        []

        A malformed prompt names the fence and the README line:

        >>> try:
        ...     pycon_doctest([PyconFence(2, 40, ">>> 1\n>>>2\n", False)], "README.md", {})
        ... except TranscriptError as error:
        ...     print(error)
        pycon fence 2 (README.md line 42): line 2 of the docstring for README.md lacks blank after >>>: '>>>2'

        Printed rather than shown as a traceback because a traceback's first token is the
        exception's qualified name, which depends on how this module was imported.
    """
    parser = doctest.DocTestParser()
    examples: list[doctest.Example] = []
    for fence in fences:
        if fence.skipped:
            continue
        try:
            parsed = parser.get_examples(fence.body, filename)
        except ValueError as error:
            # Doctest's own line number is relative to the body; add where the body
            # starts, so the reader is sent to a line of the file they can open.
            raise TranscriptError(fence, filename, error) from error
        for example in parsed:
            example.lineno += fence.line
            examples.append(example)
    docstring = "\n".join(fence.body for fence in fences if not fence.skipped)
    return doctest.DocTest(examples, globs, filename, filename, 0, docstring)


_DOCTEST_LINE = re.compile(r"^line (\d+) of")


def _first_offending_line(message: str) -> int:
    """Return the zero-based body line a doctest parse error names, or 0 if it names none.

    Doctest reports parse errors as ``line N of the docstring for …``, one-based and
    relative to the text it was given. That wording is doctest's, not a contract, so an
    unrecognised message degrades to "the fence's first line" rather than raising — the
    error itself is still shown in full; only the pointer gets coarser.

    Args:
        message: The text of doctest's ``ValueError``.

    Returns:
        The zero-based line within the fence body.

    Examples:
        >>> _first_offending_line("line 3 of the docstring for README.md lacks blank after >>>: '>>>x'")
        2
        >>> _first_offending_line("something doctest has never said")
        0
    """
    match = _DOCTEST_LINE.match(message)
    return int(match.group(1)) - 1 if match else 0
