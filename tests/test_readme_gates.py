"""The README's gate commands must be the ones `.github/workflows/ci.yml` runs.

Issue #58. #52 removed the Makefile and made `ci.yml` the definition of every gate command
line, on the grounds that a second home is a second thing to keep correct. The cost,
recorded in `ci.yml`'s own header and in #49 and #32, was that no gate had a local entry
point at all: reproducing a red job meant opening a workflow file and reading YAML.

The README now carries the command lines (see *Running one by hand*), which reintroduces
exactly the duplication #52 argued against — so this module is the price of it. It asserts
that each documented command is the one its job actually runs, and that no gate in `ci.yml`
is undocumented. With that, the copy cannot drift silently, which is the property #52 was
protecting; without it the block would be prose that was true once.

**What is compared: token equality, in both directions (#63).** Until #63 a documented
command matched when its tokens appeared, *in order*, anywhere in one of its job's `run:`
blocks. That pinned every threshold the README claimed, but tolerated anything CI added on
top: a *new* flag on a CI command left the documented line silently wrong, which is the
drift #52 existed to prevent arriving through the door #58 opened.

The comparison is now an equality. What made a subsequence look unavoidable is that CI
legitimately carries scaffolding a contributor should not type — the matrix's
``--python ${{ matrix.python-version }}``, and the ``set -o pipefail`` / ``| tee
checks.log`` skip guard wrapped around ``rhiza-test`` (#34). So that scaffolding is now
*declared*, in :data:`_EXCISE`, :data:`_TRUNCATE_AT` and :data:`_DIAGNOSTIC` below, removed
from the CI side, and what remains has to match token for token.

Declaring it is the whole improvement. An allowlist must be edited when new scaffolding
appears, which puts the exception in a diff where a reviewer sees it; a subsequence match
absorbed the same exception invisibly. :class:`TestTheScaffoldAllowlist` stops it rotting
the other way, by failing when a declared fragment is no longer in `ci.yml` at all — so a
dead entry cannot sit there quietly widening the tolerance.

**The environment is pinned too, in both directions (#81).** A gate's ``run:`` block is
not the whole of what CI runs it with: ``rhiza-test`` also carries an ``env:`` block, and
``RHIZA_DOCTEST_FOLDERS`` there decides which folders the doctest sweep walks. That value
cannot live in the README fence, because :func:`scripts.gates._run` splits a documented
line with :func:`shlex.split` and runs it without a shell, so a ``KEY=value`` prefix would
become ``argv[0]`` rather than an assignment. It therefore has a second home —
:data:`scripts.gates.GATE_ENV` — and :class:`TestTheGateEnvironment` is what stops the two
drifting, the same job the command-line comparison does for the README.

**What is still not caught**, stated rather than hidden, as the subsequence gap was:

* The text *inside* ``rhiza-test``'s skip guard, everything after the ``|``. That is
  pipeline machinery rather than a gate, which is why :data:`_TRUNCATE_AT` cuts there; a
  flag added to the pytest command itself is before the cut and is caught.
* `weekly.yml`. Its two jobs are documented in prose in the README rather than in the
  fence, and nothing here reads that file.

YAML is parsed here by hand. `ci.yml` is read for two things only — job names and `run:`
bodies — and a dependency on PyYAML in a package installed in every rhiza-managed repo's
test environment is the trade #53 already refused once for `python-dotenv`.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.gates import GATE_ENV, documented_gates

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"

# A job key: two-space indent, no value. Matched only inside the `jobs:` block, because
# `on:`'s `push:`/`pull_request:` have the same shape one level up.
_JOB = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")

# `run:` and its inline value, if any.
_RUN = re.compile(r"^(\s*)run:(.*)$")

# The block-scalar indicators that mean "the command is on the following lines".
_BLOCK_SCALARS = ("|", "|-", "|+", ">", ">-", ">+", "")

# An `env:` key with no inline value, at any depth — job-level or step-level, both of which
# apply to the `run:` blocks beneath them.
_ENV = re.compile(r"^(\s*)env:\s*$")

# One `KEY: value` pair inside an `env:` block. The value keeps its quotes here and is
# stripped by the caller, so that `"src scripts"` and `src scripts` compare equal.
_ENV_ENTRY = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*):\s*(.+?)\s*$")

# `ci-gate` runs no gate: it reads `needs.*.result` so branch protection has one required
# check instead of a list that must be edited whenever a job is added. There is nothing for
# a contributor to reproduce, so it is documented in the table above the fence and not in it.
_NOT_A_GATE = frozenset({"ci-gate"})

# A shell line continuation inside a YAML block scalar. Pure line-wrapping: it is never part
# of a command, and dropping it is what lets a wrapped CI command equal a one-line README one.
_CONTINUATION = frozenset({"\\"})

# CI-only scaffolding, declared per gate so the comparison can be an equality (#63).
#
# `_EXCISE` holds token runs deleted wherever they appear in the job's `run:` block.
_EXCISE: dict[str, tuple[tuple[str, ...], ...]] = {
    # The matrix supplies the interpreter; a contributor uses whatever `uv` resolves.
    "test": (("--python", "${{", "matrix.python-version", "}}"),),
    # The skip guard's `pipefail` — without it the `| tee` below would mask a red pytest.
    "rhiza-test": (("set", "-o", "pipefail"),),
}

# The command ends at the first occurrence of this token; everything after is pipeline
# machinery rather than the gate. Only `rhiza-test` has any: the `| tee checks.log` and the
# `grep`/`exit 1` guard that fails the job when a check skips (#34).
_TRUNCATE_AT: dict[str, str] = {
    "rhiza-test": "|",
}

# `run:` blocks that are deliberately not in the README's fence, because they are diagnostics
# rather than gates — nothing fails on them and there is nothing for a contributor to
# reproduce. Declared in full, so a flag added to one of these still has to be declared here.
_DIAGNOSTIC: dict[str, tuple[tuple[str, ...], ...]] = {
    # Prints the resolved licence table for the log. The gate is the `--allow-only` run
    # below it, which *is* documented.
    "license": (("uv", "run", "--with", "pip-licenses", "pip-licenses", "--format", "markdown", "--with-urls"),),
}


def _normalise(text: str) -> list[str]:
    """Return ``text`` as whitespace-separated tokens.

    Collapsing whitespace is what makes a YAML folded scalar (``run: >-``) comparable to
    the single line a contributor copies out of the README.

    Args:
        text: A command, on one line or many.

    Returns:
        The tokens, in order.
    """
    return text.split()


def _drop_fragment(tokens: list[str], fragment: tuple[str, ...]) -> list[str]:
    """Return ``tokens`` with the first contiguous occurrence of ``fragment`` removed.

    Contiguous rather than scattered on purpose: ``--python`` and its matrix expression are
    adjacent in the command, and matching them anywhere would let the allowlist excuse a
    coincidence somewhere else in the line.

    Args:
        tokens: The CI side of the comparison.
        fragment: A declared scaffolding run, from :data:`_EXCISE`.

    Returns:
        ``tokens`` without that run, or unchanged when it does not appear.
    """
    width = len(fragment)
    for start in range(len(tokens) - width + 1):
        if tuple(tokens[start : start + width]) == fragment:
            return tokens[:start] + tokens[start + width :]
    return tokens


def _reduce(gate: str, tokens: list[str]) -> list[str]:
    """Return one CI ``run:`` block with this gate's declared scaffolding removed.

    The order matters: truncating first discards the skip guard, so the ``set -o pipefail``
    excision afterwards works on what is left of the command rather than on the guard.

    Args:
        gate: The job name, which is what the allowlists are keyed by.
        tokens: The block's tokens, from :func:`_ci_jobs`.

    Returns:
        The tokens a contributor should be able to type, in order.
    """
    reduced = [token for token in tokens if token not in _CONTINUATION]

    cut = _TRUNCATE_AT.get(gate)
    if cut is not None and cut in reduced:
        reduced = reduced[: reduced.index(cut)]

    for fragment in _EXCISE.get(gate, ()):
        reduced = _drop_fragment(reduced, fragment)

    return reduced


def _ci_jobs() -> dict[str, list[list[str]]]:
    """Return each job in ``ci.yml`` mapped to the tokens of its ``run:`` blocks.

    Hand-parsed rather than loaded as YAML — see the module docstring. Only two shapes are
    recognised, which are the only two the file uses: an inline ``run: cmd``, and a block
    scalar whose body is every following line indented past the ``run:`` key.

    Returns:
        Job name to one token list per ``run:`` block, in file order.
    """
    jobs: dict[str, list[list[str]]] = {}
    lines = CI.read_text(encoding="utf-8").splitlines()
    in_jobs = False
    job: str | None = None
    index = 0

    while index < len(lines):
        line = lines[index]
        index += 1

        if line.rstrip() == "jobs:":
            in_jobs = True
            continue
        if not in_jobs:
            continue
        # A non-blank line at column zero ends the `jobs:` block.
        if line.strip() and not line.startswith(" "):
            break

        match = _JOB.match(line)
        if match:
            job = match.group(1)
            jobs.setdefault(job, [])
            continue

        run = _RUN.match(line)
        if run is None or job is None:
            continue

        indent, inline = run.group(1), run.group(2).strip()
        if inline not in _BLOCK_SCALARS:
            jobs[job].append(_normalise(inline))
            continue

        body: list[str] = []
        while index < len(lines):
            nxt = lines[index]
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= len(indent):
                break
            body.append(nxt)
            index += 1
        jobs[job].append(_normalise("\n".join(body)))

    return jobs


def _ci_env() -> dict[str, dict[str, str]]:
    """Return every variable each job sets, keyed by job name.

    Hand-parsed for the same reason as :func:`_ci_jobs` — see the module docstring. Both
    ``env:`` depths are collected into one mapping per job, because a job-level block and a
    step-level one are indistinguishable from the point of view of the command that runs
    under them, which is what :data:`scripts.gates.GATE_ENV` models.

    Returns:
        Job name to its variables. A job that sets none is absent rather than empty.
    """
    env: dict[str, dict[str, str]] = {}
    lines = CI.read_text(encoding="utf-8").splitlines()
    in_jobs = False
    job: str | None = None
    index = 0

    while index < len(lines):
        line = lines[index]
        index += 1

        if line.rstrip() == "jobs:":
            in_jobs = True
            continue
        if not in_jobs:
            continue
        if line.strip() and not line.startswith(" "):
            break

        match = _JOB.match(line)
        if match:
            job = match.group(1)
            continue

        block = _ENV.match(line)
        if block is None or job is None:
            continue

        # Every following line indented past the `env:` key is one of its entries.
        indent = len(block.group(1))
        while index < len(lines):
            entry = lines[index]
            if entry.strip() and len(entry) - len(entry.lstrip()) <= indent:
                break
            index += 1
            pair = _ENV_ENTRY.match(entry)
            if pair is not None:
                env.setdefault(job, {})[pair.group(1)] = pair.group(2).strip('"')

    return env


def _documented() -> dict[str, list[str]]:
    """Return each gate documented in the README mapped to its command lines.

    Delegates to :func:`scripts.gates.documented_gates` rather than parsing the fence
    again, and that is load-bearing rather than tidiness (#66). ``scripts/gates.py``
    *executes* this block; if it read the README its own way, everything asserted below
    would pin a parse of the README that nothing actually runs. One parser means the
    equality proven here — README equals ``ci.yml`` — transfers to the runner.

    Returns:
        Gate name to the command lines listed under its ``# <gate>`` comment, in order.
    """
    return documented_gates()


def _reduced_blocks(gate: str, jobs: dict[str, list[list[str]]]) -> list[list[str]]:
    """Return every ``run:`` block of ``gate``, scaffolding removed.

    Args:
        gate: The job name.
        jobs: The parsed workflow, from :func:`_ci_jobs`.

    Returns:
        One token list per block, in file order.
    """
    return [_reduce(gate, block) for block in jobs.get(gate, [])]


def _describe_mismatch(gate: str, command: str, blocks: list[list[str]]) -> str:
    """Return a readable account of one documented command that matched nothing.

    Both sides are printed as reduced token lists rather than as the raw strings, because
    that is what the comparison actually saw — the difference is often one token, and
    showing the original line invites hunting for a whitespace change that is not there.

    Args:
        gate: The job name.
        command: The line as the README documents it.
        blocks: The job's ``run:`` blocks, already reduced.

    Returns:
        A multi-line description, indented to sit under the assertion message.
    """
    if not blocks:
        return f"{gate}: no `run:` block at all\n    README: {' '.join(_normalise(command))}"
    found = "\n            ".join(" ".join(block) for block in blocks)
    return f"{gate}\n    README: {' '.join(_normalise(command))}\n    ci.yml: {found}"


class TestTheHelpers:
    """The parsing and the reduction, on synthetic input.

    The functions above are only ever run against files that are expected to agree, so
    their interesting behaviour — a folded scalar, a fragment that is not there — would
    otherwise never execute.
    """

    def test_folded_scalars_collapse_to_one_command(self) -> None:
        """A `run: >-` body spread over lines is the same token list as one line."""
        assert _normalise("uv run\n  --with ty\n  ty check src") == ["uv", "run", "--with", "ty", "ty", "check", "src"]

    def test_a_fragment_is_removed_where_it_appears(self) -> None:
        """The matrix's interpreter argument is exactly this case."""
        tokens = ["uv", "run", "--python", "${{", "matrix.python-version", "}}", "pytest"]
        assert _drop_fragment(tokens, ("--python", "${{", "matrix.python-version", "}}")) == ["uv", "run", "pytest"]

    def test_a_fragment_must_be_contiguous(self) -> None:
        """Scattered tokens are a coincidence, not the declared scaffolding."""
        assert _drop_fragment(["a", "x", "b"], ("a", "b")) == ["a", "x", "b"]

    def test_an_absent_fragment_leaves_the_tokens_alone(self) -> None:
        """Reduction is not allowed to fail; `TestTheScaffoldAllowlist` reports staleness."""
        assert _drop_fragment(["uv", "run", "pytest"], ("--python",)) == ["uv", "run", "pytest"]

    def test_continuations_are_dropped(self) -> None:
        """A wrapped CI command has to equal the one-line README copy."""
        assert _reduce("nothing-declared", ["uv", "run", "\\", "pytest"]) == ["uv", "run", "pytest"]

    def test_truncation_cuts_the_pipeline_machinery(self) -> None:
        """`rhiza-test`'s skip guard is everything after the pipe."""
        assert _reduce("rhiza-test", ["pytest", "--pyargs", "m", "|", "tee", "checks.log"]) == [
            "pytest",
            "--pyargs",
            "m",
        ]

    def test_a_new_flag_survives_reduction(self) -> None:
        """The whole point of #63: reduction must not absorb an undeclared flag."""
        assert _reduce("test", ["pytest", "--exitfirst"]) == ["pytest", "--exitfirst"]


class TestEveryGateIsDocumented:
    """The two directions: no undocumented job, no documented non-job."""

    def test_every_ci_job_appears_in_the_readme(self) -> None:
        """A gate added to `ci.yml` must be added to the README's fence too.

        This is the half that keeps the block from decaying by omission — the way a gate
        list decays in practice is that a new job is added and the docs are not touched.
        """
        jobs = set(_ci_jobs()) - _NOT_A_GATE
        undocumented = sorted(jobs - set(_documented()))

        assert not undocumented, (
            f"ci.yml defines gates the README does not document: {undocumented}. Add each to "
            "the '#### Running one by hand' fence, or to _NOT_A_GATE here if it runs no "
            "command a contributor could reproduce."
        )

    def test_every_documented_gate_is_a_ci_job(self) -> None:
        """And a gate removed from `ci.yml` must not linger in the README."""
        jobs = set(_ci_jobs())
        stale = sorted(set(_documented()) - jobs)

        assert not stale, (
            f"the README documents gates ci.yml does not define: {stale}. They were probably "
            "renamed or removed; a command for a job that no longer exists is worse than no "
            "command, because it looks current."
        )

    def test_the_fence_is_not_empty(self) -> None:
        """A vacuity guard: both assertions above pass on an empty fence."""
        documented = _documented()

        assert len(documented) >= 8, f"expected the README to document most gates, found {len(documented)}"
        assert all(commands for commands in documented.values()), (
            f"a gate is listed with no command: {sorted(g for g, c in documented.items() if not c)}"
        )


class TestTheScaffoldAllowlist:
    """The allowlist itself, which widens the tolerance and so must not rot.

    Every entry excuses a difference between the README and `ci.yml`. An entry whose
    scaffolding is gone excuses nothing and hides the fact that the tolerance is no longer
    needed, so it is a failure rather than a harmless leftover.
    """

    def test_no_excised_fragment_is_stale(self) -> None:
        """A declared fragment must still appear, contiguously, in its job."""
        jobs = _ci_jobs()
        stale = [
            f"{gate}: {' '.join(fragment)}"
            for gate, fragments in _EXCISE.items()
            for fragment in fragments
            if not any(_drop_fragment(block, fragment) != block for block in jobs.get(gate, []))
        ]

        assert not stale, (
            f"_EXCISE declares scaffolding ci.yml no longer carries: {stale}. Delete the entry — "
            "while it stands it widens the comparison for a difference that no longer exists."
        )

    def test_no_truncation_point_is_stale(self) -> None:
        """And so must a declared truncation token."""
        jobs = _ci_jobs()
        stale = [
            f"{gate}: {cut}"
            for gate, cut in _TRUNCATE_AT.items()
            if not any(cut in block for block in jobs.get(gate, []))
        ]

        assert not stale, (
            f"_TRUNCATE_AT names tokens ci.yml no longer carries: {stale}. Delete the entry — it "
            "silently discards the tail of every command in that job."
        )

    def test_no_diagnostic_block_is_stale(self) -> None:
        """A diagnostic that is gone, or that gained a flag, must be re-declared."""
        jobs = _ci_jobs()
        stale = [
            f"{gate}: {' '.join(declared)}"
            for gate, blocks in _DIAGNOSTIC.items()
            for declared in blocks
            if list(declared) not in _reduced_blocks(gate, jobs)
        ]

        assert not stale, (
            f"_DIAGNOSTIC declares run blocks ci.yml no longer runs verbatim: {stale}. Either the "
            "step was removed — delete the entry — or it changed, in which case update it here so "
            "the change is visible in a diff."
        )


class TestEachCommandMatchesCi:
    """Each documented command against the job it claims to reproduce, and back again."""

    def test_documented_commands_are_the_ones_ci_runs(self) -> None:
        """Every command must equal one `run:` block of its job, scaffolding removed.

        One test over all of them rather than a parametrisation, because the useful failure
        message is the whole set of mismatches: a threshold bump touches several gates at
        once, and finding them one re-run at a time is the slow way.
        """
        jobs = _ci_jobs()
        mismatched = [
            _describe_mismatch(gate, command, _reduced_blocks(gate, jobs))
            for gate, commands in _documented().items()
            for command in commands
            if _normalise(command) not in _reduced_blocks(gate, jobs)
        ]

        assert not mismatched, (
            "the README documents commands no `run:` block in their job matches:\n  "
            + "\n  ".join(mismatched)
            + "\n\nci.yml is the definition (#52). Copy the line from there — or, if the "
            "difference really is CI-only scaffolding, declare it in _EXCISE or _TRUNCATE_AT "
            "above so the exception is visible rather than absorbed (#63)."
        )

    def test_every_ci_run_block_is_documented(self) -> None:
        """And the reverse: a flag added CI-side must not pass silently.

        This is the direction #63 added. It also catches a whole new `run:` block inside an
        already-documented job, which `test_every_ci_job_appears_in_the_readme` cannot see
        because the job name was already there.
        """
        documented = _documented()
        jobs = _ci_jobs()
        undocumented = []

        for gate, blocks in jobs.items():
            if gate in _NOT_A_GATE or gate not in documented:
                continue
            wanted = [_normalise(command) for command in documented[gate]]
            allowed = [list(block) for block in _DIAGNOSTIC.get(gate, ())]
            undocumented += [
                f"{gate}: {' '.join(reduced)}"
                for reduced in (_reduce(gate, block) for block in blocks)
                if reduced not in wanted and reduced not in allowed
            ]

        assert not undocumented, (
            "ci.yml runs gate commands the README does not document:\n  "
            + "\n  ".join(sorted(undocumented))
            + "\n\nUpdate the '#### Running one by hand' fence to match. If the block is a "
            "diagnostic rather than a gate, declare it in _DIAGNOSTIC above."
        )


class TestTheGateEnvironment:
    """`GATE_ENV` must be the environment `ci.yml` sets — in both directions (#81).

    The value it carries decides which folders a gate measures, so a drift here is the
    quiet kind: `RHIZA_DOCTEST_FOLDERS` set in CI but not in `scripts/gates.py` would mean
    a doctest under `scripts/` runs in CI and not locally, and set in neither would mean it
    runs nowhere while `test_doctests` *skips* and reads as a pass (#34).
    """

    def test_every_declared_variable_is_the_one_ci_sets(self) -> None:
        """The runner must not set a value CI does not, or a different value for it."""
        ci = _ci_env()
        mismatched = [
            f"{gate}: {key}={value!r} locally, {ci.get(gate, {}).get(key)!r} in ci.yml"
            for gate, variables in GATE_ENV.items()
            for key, value in variables.items()
            if ci.get(gate, {}).get(key) != value
        ]
        assert not mismatched, (
            "scripts/gates.py sets an environment ci.yml does not:\n  "
            + "\n  ".join(sorted(mismatched))
            + "\n\nGATE_ENV and the job's `env:` block are two homes for one value; update "
            "whichever is wrong so a local run means what CI's does."
        )

    def test_ci_sets_nothing_the_runner_leaves_out(self) -> None:
        """And the reverse, which is the direction that makes a local pass trustworthy.

        `_NOT_A_GATE` is excluded because `ci-gate` sets `RESULTS` to read
        `needs.*.result` — pipeline machinery with no gate for a contributor to reproduce,
        the same reason its `run:` block is not in the README fence.
        """
        documented = _documented()
        missing = [
            f"{gate}: {key}={value!r}"
            for gate, variables in _ci_env().items()
            if gate not in _NOT_A_GATE and gate in documented
            for key, value in variables.items()
            if GATE_ENV.get(gate, {}).get(key) != value
        ]
        assert not missing, (
            "ci.yml sets an environment scripts/gates.py does not:\n  "
            + "\n  ".join(sorted(missing))
            + "\n\nDeclare it in GATE_ENV, so `python scripts/gates.py <gate>` runs the "
            "gate the way CI runs it. If it is pipeline machinery rather than part of the "
            "gate, add its job to _NOT_A_GATE with the reason."
        )
