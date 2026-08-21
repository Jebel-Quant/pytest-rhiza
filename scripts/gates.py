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
    "lowest-deps": "rewrites uv.lock's resolution — restored with `uv sync` when the gate finishes",
}

#: Run after a gate in :data:`DESTRUCTIVE` to put the working tree back (#71). Running the
#: README's command line by hand still needs this done by hand; doing it here is what makes
#: the destructive gate repeat-safe, so that even ``--all`` leaves ``git status`` clean.
RESTORE_COMMAND = "uv sync"

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

    A gate in :data:`DESTRUCTIVE` is followed by :data:`RESTORE_COMMAND`, in a ``finally``
    so that a gate which fails — or one interrupted part-way — restores the working tree as
    well (#71). That is the difference between a gate which perturbs the tree while it runs
    and one which leaves it perturbed.

    Args:
        name: The gate name, which selects the guard in :data:`SKIP_GUARD` and the restore
            in :data:`DESTRUCTIVE`.
        commands: Its command lines, from :func:`documented_gates`.

    Returns:
        Whether the gate passed.
    """
    guarded = name in SKIP_GUARD
    try:
        for command in commands:
            print(f"\n\033[1m→ {name}\033[0m: {command}", flush=True)
            status, stdout = _run(command, capture=guarded)
            if status != 0:
                return False
            if guarded and "skipped" in stdout:
                print(f"\033[31m{_SKIPPED_MESSAGE}\033[0m")
                return False
        return True
    finally:
        if name in DESTRUCTIVE:
            print(f"\n\033[1m→ {name}\033[0m: {RESTORE_COMMAND}  [restoring the working tree]", flush=True)
            _run(RESTORE_COMMAND, capture=False)


def _print_listing(documented: dict[str, list[str]]) -> None:
    """Print every documented gate and its command lines, for ``--list``.

    Args:
        documented: The mapping from :func:`documented_gates`.
    """
    for name, commands in documented.items():
        note = f"  [skipped by default: {DESTRUCTIVE[name]}]" if name in DESTRUCTIVE else ""
        print(f"{name}{note}")
        for command in commands:
            print(f"    {command}")


def select_gates(requested: list[str], documented: dict[str, list[str]], *, include_destructive: bool) -> list[str]:
    """Resolve which gates to run, in the order the README documents them.

    Args:
        requested: Gate names from the command line. Empty means the default set.
        documented: The mapping from :func:`documented_gates`.
        include_destructive: Whether ``--all`` was given. It only affects the default set —
            naming a gate in :data:`DESTRUCTIVE` explicitly is itself the opt-in.

    Returns:
        The selected names, ordered as ``documented`` orders them rather than as they were
        typed, so a run reads the same way whatever order the arguments arrived in.

    Raises:
        GatesError: A requested gate is not documented. Raising beats skipping it silently,
            which would run a smaller set than was asked for and still exit 0.
    """
    unknown = sorted(set(requested) - set(documented))
    if unknown:
        message = f"no such gate: {', '.join(unknown)}\nknown gates: {', '.join(documented)}"
        raise GatesError(message)

    if requested:
        return [name for name in documented if name in set(requested)]
    return [name for name in documented if include_destructive or name not in DESTRUCTIVE]


def _print_summary(selected: list[str], failed: list[str], documented: dict[str, list[str]]) -> None:
    """Print the per-gate verdict, including the gates this run left out.

    The not-selected lines are the point rather than padding: a summary listing only what
    ran cannot be told apart from one where a gate was silently dropped.

    Args:
        selected: The gates that ran, in run order.
        failed: Those of them that failed.
        documented: The mapping from :func:`documented_gates`, for the not-selected lines.
    """
    print("\n\033[1msummary\033[0m")
    for name in selected:
        mark = "\033[31mFAIL\033[0m" if name in failed else "\033[32mPASS\033[0m"
        print(f"  {mark}  {name}")
    for name in documented:
        if name not in selected:
            print(f"  ----  {name} (not selected)")


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run the selected gates, and report.

    Every selected gate runs even after one fails, so a single pass shows the whole
    picture rather than stopping at the first red — the same reason ``ci-gate`` aggregates
    instead of the jobs depending on each other.

    The work is in :func:`documented_gates`, :func:`select_gates`, :func:`run_gate` and the
    two printers; what is left here is the argument surface and the exit status. This was
    one function until #70, where it measured CC 24 — breadth rather than nesting, but the
    selection path it held was also the part no test reached, which is the more useful thing
    the split bought.

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

    # One handler for both failures, because they are the same answer to the user: a README
    # with no fence leaves nothing to choose from, and a typo names something that does not
    # exist. Neither ran a gate, so neither is a gate failure — hence 2 rather than 1.
    try:
        documented = documented_gates()
        if args.list:
            _print_listing(documented)
            return 0
        selected = select_gates(args.gates, documented, include_destructive=args.all)
    except GatesError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    for name in selected:
        if name in DESTRUCTIVE:
            print(f"\033[33mnote\033[0m: {name} {DESTRUCTIVE[name]}")

    failed = [name for name in selected if not run_gate(name, documented[name])]
    _print_summary(selected, failed, documented)
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover - exercised by running the script, not the suite
    sys.exit(main())
