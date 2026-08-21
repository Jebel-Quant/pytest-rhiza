"""Bounded child processes for the checks, and the one git executable they share.

**Why every child needs an explicit timeout (#44).** The checks shell out for four
things: git queries, ``bash -n`` fence parsing, the ``bash`` probe, and — the one that
matters — executing the ``python`` fences out of a consumer's README. None of those calls
carried a ``timeout`` before, so a fence that waits on ``input()``, blocks on a network
call, or loops forever made the check *hang* rather than fail.

It is tempting to answer that with ``pytest-timeout``, which this package depends on. That
does not work, and the reason is worth writing down: pytest-timeout takes its bound from
the ``timeout`` ini setting in the **consumer's** config, and nothing here sets a default.
This repository's own ``pytest.ini`` says ``timeout = 60``, which is exactly why the gap
was invisible from inside it. A consumer repository that never set the option gets no
bound at all — and since pytest-rhiza is a runtime dependency of every rhiza-managed
repository, an unbounded wait propagates into every consumer's CI, where a hung job is
worse than a red one: it burns the runner's whole budget and reports nothing.

So the bound lives here, in the code that spawns the process, where it does not depend on
what the consumer configured.

**Two budgets, because the calls differ in kind.** :data:`INSPECT_TIMEOUT` covers the
processes that only *look* at something — git answering a question about its own object
database, ``bash -n`` parsing a snippet it will never run. Those are sub-second
operations; 30s is already pathological. :data:`EXECUTE_TIMEOUT` covers the single call
that runs code someone wrote, where a legitimately slow example is imaginable, so it is
generous by comparison.

**Both are overridable, and that is not decoration.** The kill path is the whole point of
the module, so it has to be testable, and no test can wait out a 120s budget — this
package's own suite runs the hanging-fence case with ``RHIZA_EXECUTE_TIMEOUT=2``. Having
built the knob for that, it is also the answer for a consumer whose example genuinely
needs longer, which is the case the defaults cannot know about.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404
from pathlib import Path

import pytest

# Resolved once, through PATH rather than at a fixed location: the Windows leg of the
# matrix has git somewhere else entirely, and `shutil.which` is what makes the same code
# work there. The fallback is for the case where PATH has been emptied deliberately —
# some of this package's own tests do exactly that — and is expected to fail loudly rather
# than silently resolve something else.
GIT = shutil.which("git") or "/usr/bin/git"

# Processes that only inspect: git queries, `bash -n`, the bash probe.
INSPECT_TIMEOUT = 30
INSPECT_TIMEOUT_ENV = "RHIZA_INSPECT_TIMEOUT"

# The one process that executes documentation: a README's python fences.
EXECUTE_TIMEOUT = 120
EXECUTE_TIMEOUT_ENV = "RHIZA_EXECUTE_TIMEOUT"


def _budget(name: str, default: int) -> int:
    """Return the timeout named by an environment variable, or ``default``.

    A value that is not a positive integer falls back to the default rather than raising.
    The reason is what this number *is*: a safety net over a child process. A typo in an
    environment variable must not be able to remove the net, and must not be able to break
    every check in the repository either — both of which a propagating ``ValueError`` here
    would do, at the cost of a setting nobody needs to get right for the gate to work.

    Args:
        name: The environment variable to read.
        default: Seconds to use when it is unset or unusable.

    Returns:
        The budget in seconds.

    Examples:
        Unset means the default:

        >>> import os
        >>> _budget("RHIZA_BUDGET_EXAMPLE", 30)
        30

        A positive integer wins:

        >>> os.environ["RHIZA_BUDGET_EXAMPLE"] = "5"
        >>> _budget("RHIZA_BUDGET_EXAMPLE", 30)
        5

        Anything else falls back, rather than raising or disabling the bound — a typo and
        a deliberate zero are both refused:

        >>> os.environ["RHIZA_BUDGET_EXAMPLE"] = "soon"
        >>> _budget("RHIZA_BUDGET_EXAMPLE", 30)
        30
        >>> os.environ["RHIZA_BUDGET_EXAMPLE"] = "0"
        >>> _budget("RHIZA_BUDGET_EXAMPLE", 30)
        30
        >>> del os.environ["RHIZA_BUDGET_EXAMPLE"]
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        seconds = int(raw)
    except ValueError:
        return default
    return seconds if seconds > 0 else default


def inspect_timeout() -> int:
    """Return the budget for a child that only inspects something.

    Returns:
        Seconds, from :data:`INSPECT_TIMEOUT_ENV` or :data:`INSPECT_TIMEOUT`.
    """
    return _budget(INSPECT_TIMEOUT_ENV, INSPECT_TIMEOUT)


def execute_timeout() -> int:
    """Return the budget for the child that executes a README's python fences.

    Returns:
        Seconds, from :data:`EXECUTE_TIMEOUT_ENV` or :data:`EXECUTE_TIMEOUT`.
    """
    return _budget(EXECUTE_TIMEOUT_ENV, EXECUTE_TIMEOUT)


def run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    stdin: str | None = None,
    timeout: int | None = None,
    on_timeout: str = "the child process did not terminate",
) -> subprocess.CompletedProcess[str]:
    """Run one child process to completion, failing the test if it outlives its budget.

    Args:
        argv: The argument list. Always a list, never a string — there is no shell here.
        cwd: Directory to run in, or None for the current one.
        stdin: Text to write to the child's stdin, or None to give it none.
        timeout: Seconds to wait before killing it, or None for :func:`inspect_timeout`.
        on_timeout: What to tell the reader when it is killed. Callers supply this because
            only they know what a hang *means* — a fence that never returns and a git
            query that never answers need different next steps.

    Returns:
        The completed process, with stdout and stderr captured as text.

    Raises:
        Failed: via :func:`pytest.fail`, when the child exceeds its budget. Reported as a
            failure rather than a skip: a process that had to be killed is a finding about
            the repository under test, and a skip here would read as a pass — the failure
            mode this package already fights elsewhere (#34).
    """
    budget = inspect_timeout() if timeout is None else timeout
    try:
        return subprocess.run(  # noqa: S603 - fixed argument list, no shell  # nosec B603
            argv,
            capture_output=True,
            text=True,
            cwd=cwd,
            input=stdin,
            timeout=budget,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"Killed after {budget}s: {on_timeout}")


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one read-only git query inside ``root``.

    The return code is deliberately not checked. Every caller here distinguishes "git said
    no" from "git failed" itself, and several treat a non-zero exit as a skip rather than
    an error.

    Args:
        root: Repository to run in.
        args: Arguments after the git executable.

    Returns:
        The completed process, with stdout and stderr captured as text.
    """
    return run(
        [GIT, *args],
        cwd=root,
        on_timeout=(
            f"`git {args[0] if args else ''}` never answered in {root}. The repository may be "
            f"mid-operation (an index lock, an interrupted rebase) or very large; `git status` "
            f"there is the first thing to check."
        ),
    )
