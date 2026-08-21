"""Run the gates locally, by executing the README block rather than restating it.

Issue #66. #52 removed the Makefile and made ``.github/workflows/ci.yml`` the single
definition of every gate command line, on the grounds that a second home is a second thing
to keep correct. The cost — recorded in that file's header, in #49 and in #32 — was that no
gate had a local entry point at all: reproducing a red job meant reading YAML, and after
#58 it meant eleven copy-pastes out of ``README.md``.

**Why this does not reopen #52.** A runner that held its own copy of the recipes would
recreate exactly the duplication #52 removed, and this one holds none. It reads the fenced
block under *Running one by hand* in ``README.md`` and runs what is written there, so the
only thing added is a way to *execute* a list that already existed. ``ci.yml`` stays the
definition; the README stays a copy; ``tests/test_readme_gates.py`` still pins the two
token for token in both directions, which is what makes running the README equivalent to
running CI.

That test and this module share :func:`documented_gates` for the same reason. If the runner
parsed the block its own way, the test's guarantee would cover the README rather than the
thing actually executed — the parser has to be the same one for the chain to hold.

**The two gates that are not a plain copy**, both already flagged in the README:

* ``lowest-deps`` rewrites ``uv.lock``'s resolution in the working tree, so it is excluded
  from a bare run and reported as skipped. Naming it, or ``--all``, is the opt-in.
* ``rhiza-test``'s documented line stops at the pytest invocation. CI wraps it in a guard
  that fails the job when any check *skips*, because a skipped assertion reads as a pass
  (#34) — :data:`SKIP_GUARD` carries that guard here, so a local pass means what CI's does.

Usage::

    python scripts/gates.py                  # every gate except the destructive ones
    python scripts/gates.py lint typecheck   # just these
    python scripts/gates.py --all            # including lowest-deps
    python scripts/gates.py --list           # what is defined, without running anything
"""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess  # nosec B404
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"

# The same pattern `tests/test_readme_gates.py` used before it imported this module: the
# `# <gate>` comment lines under the fence, each followed by its command(s).
_FENCE = re.compile(r"#### Running one by hand\n+```bash\n(.*?)```", re.DOTALL)

#: Gates excluded from a bare run because they change the working tree, mapped to what
#: they do to it. The README says the same thing in prose; naming one on the command line
#: is the opt-in.
DESTRUCTIVE: dict[str, str] = {
    "lowest-deps": "rewrites uv.lock's resolution — run `uv sync` afterwards to restore it",
}

#: Gates whose CI job wraps the documented command in the #34 skip guard. Declared rather
#: than inferred, so it sits in a diff a reviewer sees — the same reasoning as the
#: scaffolding allowlists in `tests/test_readme_gates.py`, which is the other side of this
#: fact: `_TRUNCATE_AT` there cuts the guard off the CI side of the comparison.
SKIP_GUARD = frozenset({"rhiza-test"})

_SKIPPED_MESSAGE = (
    "A self-applied check skipped. A skipped assertion reads as a pass, which is the "
    "defect this guard exists to prevent (#34)."
)


class GatesError(RuntimeError):
    """The README's gate block is missing or empty, so there is nothing to run."""


def documented_gates() -> dict[str, list[str]]:
    """Return each gate the README documents, mapped to its command lines in order.

    Shared with ``tests/test_readme_gates.py``, which compares the result against
    ``ci.yml``. One parser, so what that test pins is what this module runs.

    Returns:
        Gate name to the command lines listed under its ``# <gate>`` comment.

    Raises:
        GatesError: The fence is absent, which means the README was restructured and
            both this runner and the pinning test have lost their input.
    """
    fence = _FENCE.search(README.read_text(encoding="utf-8"))
    if fence is None:
        message = (
            f"{README} has no '#### Running one by hand' bash fence. It is the local entry "
            "point for every gate (#58) and the input to both this runner and "
            "tests/test_readme_gates.py; if it moved or was renamed, update _FENCE here."
        )
        raise GatesError(message)

    commands: dict[str, list[str]] = {}
    gate: str | None = None
    for line in fence.group(1).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            gate = stripped.lstrip("#").strip()
            commands.setdefault(gate, [])
        elif gate is not None:
            commands[gate].append(stripped)
    return commands


def _run(command: str, *, capture: bool) -> tuple[int, str]:
    """Run one documented command line from the repository root.

    Args:
        command: The line as the README writes it. Split with :func:`shlex.split` and run
            without a shell, so its quoting is honoured and its metacharacters are not.
        capture: Whether to collect stdout for a guard to read afterwards. When false the
            child writes straight through, which is what keeps the slow gates legible.

    Returns:
        The exit status, and the captured stdout (empty when ``capture`` is false).
    """
    argv = shlex.split(command)

    # S603/B603 are suppressed on both calls below for one reason: the argument list comes
    # from README.md in this repository — reviewed content, and already the trust boundary
    # `checks/test_readme_validation` executes under — and there is no shell, so nothing in
    # it is re-interpreted. The reason lives here rather than trailing the directive,
    # because prose after the code is what ruff reads as a second code.
    if not capture:
        finished = subprocess.run(argv, cwd=ROOT, check=False)  # noqa: S603  # nosec B603
        return finished.returncode, ""

    proc = subprocess.run(  # noqa: S603  # nosec B603
        argv, cwd=ROOT, check=False, capture_output=True, text=True
    )
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return proc.returncode, proc.stdout


def run_gate(name: str, commands: list[str]) -> bool:
    """Run every command of one gate, in order, stopping at the first failure.

    Args:
        name: The gate name, which selects the guard in :data:`SKIP_GUARD`.
        commands: Its command lines, from :func:`documented_gates`.

    Returns:
        Whether the gate passed.
    """
    guarded = name in SKIP_GUARD
    for command in commands:
        print(f"\n\033[1m→ {name}\033[0m: {command}", flush=True)
        status, stdout = _run(command, capture=guarded)
        if status != 0:
            return False
        if guarded and "skipped" in stdout:
            print(f"\033[31m{_SKIPPED_MESSAGE}\033[0m")
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run the selected gates, and report.

    Every selected gate runs even after one fails, so a single pass shows the whole
    picture rather than stopping at the first red — the same reason ``ci-gate`` aggregates
    instead of the jobs depending on each other.

    Args:
        argv: Command-line arguments, defaulting to :data:`sys.argv`.

    Returns:
        A process exit status: 0 when every selected gate passed, 1 when one failed, 2
        when the selection itself was wrong.
    """
    parser = argparse.ArgumentParser(
        prog="scripts/gates.py",
        description=__doc__.split("\n\n")[0] if __doc__ else None,
    )
    parser.add_argument("gates", nargs="*", help="gates to run (default: all but the destructive ones)")
    parser.add_argument("--all", action="store_true", help=f"include {', '.join(sorted(DESTRUCTIVE))}")
    parser.add_argument("--list", action="store_true", help="list the documented gates and exit")
    args = parser.parse_args(argv)

    try:
        documented = documented_gates()
    except GatesError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.list:
        for name, commands in documented.items():
            note = f"  [skipped by default: {DESTRUCTIVE[name]}]" if name in DESTRUCTIVE else ""
            print(f"{name}{note}")
            for command in commands:
                print(f"    {command}")
        return 0

    unknown = sorted(set(args.gates) - set(documented))
    if unknown:
        print(f"error: no such gate: {', '.join(unknown)}", file=sys.stderr)
        print(f"known gates: {', '.join(documented)}", file=sys.stderr)
        return 2

    if args.gates:
        selected = [name for name in documented if name in set(args.gates)]
    else:
        selected = [name for name in documented if args.all or name not in DESTRUCTIVE]

    for name in selected:
        if name in DESTRUCTIVE:
            print(f"\033[33mnote\033[0m: {name} {DESTRUCTIVE[name]}")

    failed = [name for name in selected if not run_gate(name, documented[name])]
    skipped = [name for name in documented if name not in selected]

    print("\n\033[1msummary\033[0m")
    for name in selected:
        mark = "\033[31mFAIL\033[0m" if name in failed else "\033[32mPASS\033[0m"
        print(f"  {mark}  {name}")
    for name in skipped:
        print(f"  ----  {name} (not selected)")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
