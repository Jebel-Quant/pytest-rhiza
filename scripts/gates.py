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
  Its job also sets ``RHIZA_DOCTEST_FOLDERS``, which decides which folders the doctest
  sweep walks; :data:`GATE_ENV` carries that for the same reason (#81).

Usage::

    python scripts/gates.py                  # every gate except the destructive ones
    python scripts/gates.py lint typecheck   # just these
    python scripts/gates.py --all            # including lowest-deps
    python scripts/gates.py --list           # what is defined, without running anything
"""

from __future__ import annotations

import argparse
import os
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

#: Environment a gate's CI job sets, applied here too so a local run means what CI's does
#: (#81). Only ``rhiza-test`` needs any: its doctest sweep resolves which folders to walk
#: from ``RHIZA_DOCTEST_FOLDERS``, whose own fallback is ``src`` alone — a strictly smaller
#: tree than the three gates that already name ``scripts`` (``ty``/``mypy`` in #66,
#: ``--cov=scripts`` in #69, and interrogate's path list). Left unset, a doctest written
#: under ``scripts/`` would never be executed by any gate, and ``test_doctests`` *skips*
#: rather than fails when it attempts none — a check with no subject reading as a pass,
#: which is the #34 failure mode this repository is otherwise most careful about.
#:
#: Declared rather than inferred, for the same reason as :data:`SKIP_GUARD`: it sits in a
#: diff a reviewer sees. The value is written twice — here and on the ``rhiza-test`` job in
#: ``ci.yml`` — because ``tests/test_readme_gates.py`` compares ``run:`` blocks only, so an
#: ``env:`` block is invisible to the pin that would otherwise keep the two in step.
GATE_ENV: dict[str, dict[str, str]] = {
    "rhiza-test": {"RHIZA_DOCTEST_FOLDERS": "src scripts"},
}

#: Gates whose documented command line is scoped by **git** rather than by the filesystem,
#: mapped to the flag that does the scoping (#89). ``prek run --all-files`` means every file
#: *git knows about*, so an untracked one is invisible to it — while `typecheck`,
#: `docs-coverage` and `test` all walk the tree and see it. CI never reproduces the gap,
#: because a fresh checkout has everything tracked, so the gate that exists to make a local
#: pass mean what CI's does could go green on a module CI would reject.
#:
#: That is not a corner case: a brand-new module is exactly where a missing
#: ``[lint.per-file-ignores]`` entry is most likely, because the entry cannot exist yet. It
#: is how #89 was found — ``_release_state.py`` passed this gate while untracked and failed
#: ``ruff check`` the moment it was staged.
#:
#: The second pass is built by swapping this flag for ``--files <paths>`` in the gate's
#: *own* documented command, rather than by writing a second prek invocation here. That
#: keeps the property #66 was careful about: the runner holds no recipes, only the README's.
GIT_SCOPED: dict[str, str] = {
    "lint": "--all-files",
}

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


def _run(command: str, *, capture: bool, env: dict[str, str] | None = None) -> tuple[int, str]:
    """Run one documented command line from the repository root.

    Args:
        command: The line as the README writes it. Split with :func:`shlex.split` and run
            without a shell, so its quoting is honoured and its metacharacters are not.
        capture: Whether to collect stdout for a guard to read afterwards. When false the
            child writes straight through, which is what keeps the slow gates legible.
        env: Variables to add to this process's environment for the child, from
            :data:`GATE_ENV`. Overlaid rather than replacing it, because the command needs
            the ambient ``PATH`` and ``VIRTUAL_ENV`` that ``uv`` reads.

    Returns:
        The exit status, and the captured stdout (empty when ``capture`` is false).
    """
    argv = shlex.split(command)
    child_env = {**os.environ, **env} if env else None

    # S603/B603 are suppressed on both calls below for one reason: the argument list comes
    # from README.md in this repository — reviewed content, and already the trust boundary
    # `checks/test_readme_validation` executes under — or from a constant in this module
    # (:data:`RESTORE_COMMAND`, :func:`untracked_files`'s query). There is no shell, so
    # nothing in it is re-interpreted. The reason lives here rather than trailing the
    # directive, because prose after the code is what ruff reads as a second code.
    if not capture:
        finished = subprocess.run(argv, cwd=ROOT, check=False, env=child_env)  # noqa: S603  # nosec B603
        return finished.returncode, ""

    proc = subprocess.run(  # noqa: S603  # nosec B603
        argv, cwd=ROOT, check=False, capture_output=True, text=True, env=child_env
    )
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    return proc.returncode, proc.stdout


def untracked_files() -> list[str]:
    """Return the files git neither tracks nor ignores.

    ``--exclude-standard`` is what keeps this honest: a path in ``.gitignore`` is a path the
    repository has deliberately disowned, and linting it would turn the fix for a noisy
    scratch file into a lint failure. What is left is the set a contributor is on the way to
    committing.

    Returns:
        Repository-relative paths, or an empty list when git cannot answer — outside a
        repository, or with no git on PATH. Unknown is treated as "nothing extra to lint"
        rather than as an error, because this pass is a supplement to the documented
        command and must not be able to fail a gate on its own.
    """
    status, stdout = _run("git ls-files --others --exclude-standard", capture=True)
    if status != 0:
        return []
    return [line.strip() for line in stdout.splitlines() if line.strip()]


def _files_flag(paths: list[str]) -> str:
    """Render paths as the ``--files`` argument that replaces a whole-tree flag.

    Args:
        paths: Repository-relative paths, from :func:`untracked_files`.

    Returns:
        ``--files`` followed by each path, quoted — the command is re-split with
        :func:`shlex.split`, so a path containing a space has to survive that round trip.
    """
    return "--files " + " ".join(shlex.quote(path) for path in paths)


def _untracked_pass(name: str, commands: list[str]) -> list[str]:
    """Return the extra command lines covering what a git-scoped gate would skip.

    Empty for every gate not in :data:`GIT_SCOPED`, and empty for those too whenever there
    is nothing untracked — which is the normal state of a clean checkout, so this costs a
    single ``git ls-files`` and no extra child process.

    Args:
        name: The gate name.
        commands: Its documented command lines, from :func:`documented_gates`.

    Returns:
        The scoped commands with the whole-tree flag swapped for ``--files <paths>``, in
        the order they are documented.
    """
    flag = GIT_SCOPED.get(name)
    if flag is None:
        return []
    scoped = [command for command in commands if flag in command]
    if not scoped:
        return []  # the documented line no longer carries the flag; nothing to re-scope
    paths = untracked_files()
    if not paths:
        return []
    return [command.replace(flag, _files_flag(paths)) for command in scoped]


def run_gate(name: str, commands: list[str]) -> bool:
    """Run every command of one gate, in order, stopping at the first failure.

    A gate in :data:`DESTRUCTIVE` is followed by :data:`RESTORE_COMMAND`, in a ``finally``
    so that a gate which fails — or one interrupted part-way — restores the working tree as
    well (#71). That is the difference between a gate which perturbs the tree while it runs
    and one which leaves it perturbed.

    Args:
        name: The gate name, which selects the guard in :data:`SKIP_GUARD`, the restore
            in :data:`DESTRUCTIVE` and the environment in :data:`GATE_ENV`.
        commands: Its command lines, from :func:`documented_gates`.

    Returns:
        Whether the gate passed.
    """
    guarded = name in SKIP_GUARD
    env = GATE_ENV.get(name)
    extra = _untracked_pass(name, commands)
    if extra:
        print(
            f"\033[33mnote\033[0m: {name} is scoped by git, so untracked files get a second "
            f"pass (#89). Add a genuinely disposable file to .gitignore to exclude it."
        )
    try:
        for command in [*commands, *extra]:
            print(f"\n\033[1m→ {name}\033[0m: {command}", flush=True)
            status, stdout = _run(command, capture=guarded, env=env)
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

    Examples:
        Selection is ordered by ``documented`` rather than by the command line, so a run
        reads the same way whatever order the arguments arrived in:

        >>> documented = {"lint": [], "lowest-deps": [], "test": []}
        >>> select_gates(["test", "lint"], documented, include_destructive=False)
        ['lint', 'test']

        A bare run leaves out what :data:`DESTRUCTIVE` names, and ``--all`` puts it back:

        >>> select_gates([], documented, include_destructive=False)
        ['lint', 'test']
        >>> select_gates([], documented, include_destructive=True)
        ['lint', 'lowest-deps', 'test']

        Naming a destructive gate is itself the opt-in, so it runs without ``--all``:

        >>> select_gates(["lowest-deps"], documented, include_destructive=False)
        ['lowest-deps']

        An undocumented name is an error rather than a silently smaller run. The message
        is printed rather than left as a traceback, because the exception's qualified name
        depends on whether the module was imported as ``gates`` or ``scripts.gates``:

        >>> try:
        ...     select_gates(["nope"], documented, include_destructive=False)
        ... except GatesError as error:
        ...     print(error)
        no such gate: nope
        known gates: lint, lowest-deps, test
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


def _build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Split out of :func:`main` so that function is the control flow and nothing else; the
    option surface changes for different reasons than the exit-status logic does.

    Returns:
        The parser, with the positional gate list and the two flags.
    """
    parser = argparse.ArgumentParser(
        prog="scripts/gates.py",
        description=__doc__.split("\n\n")[0] if __doc__ else None,
    )
    parser.add_argument("gates", nargs="*", help="gates to run (default: all but the destructive ones)")
    parser.add_argument("--all", action="store_true", help=f"include {', '.join(sorted(DESTRUCTIVE))}")
    parser.add_argument("--list", action="store_true", help="list the documented gates and exit")
    return parser


def _announce_destructive(selected: list[str]) -> None:
    """Print the side-effect warning for each selected gate that has one.

    Printed before anything runs rather than as each gate starts, so a run that will
    perturb the working tree says so while there is still time to interrupt it.

    Args:
        selected: The gates about to run, from :func:`select_gates`.
    """
    for name in selected:
        if name in DESTRUCTIVE:
            print(f"\033[33mnote\033[0m: {name} {DESTRUCTIVE[name]}")


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run the selected gates, and report.

    Every selected gate runs even after one fails, so a single pass shows the whole
    picture rather than stopping at the first red — the same reason ``ci-gate`` aggregates
    instead of the jobs depending on each other.

    The work is in :func:`documented_gates`, :func:`select_gates`, :func:`run_gate`, the
    two printers and :func:`_build_parser`; what is left here is the control flow and the
    exit status. This was one function until #70, where it measured CC 24 — breadth rather
    than nesting, but the selection path it held was also the part no test reached, which is
    the more useful thing the split bought. #87 took the argument surface and the
    destructive-gate notice out for the same reason, bringing it under CC 8.

    Args:
        argv: Command-line arguments, defaulting to :data:`sys.argv`.

    Returns:
        A process exit status: 0 when every selected gate passed, 1 when one failed, 2
        when the selection itself was wrong.
    """
    args = _build_parser().parse_args(argv)

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

    _announce_destructive(selected)

    failed = [name for name in selected if not run_gate(name, documented[name])]
    _print_summary(selected, failed, documented)
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover - exercised by running the script, not the suite
    sys.exit(main())
