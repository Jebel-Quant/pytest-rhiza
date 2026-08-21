"""The README's gate commands must be the ones `.github/workflows/ci.yml` runs.

Issue #58. #52 removed the Makefile and made `ci.yml` the single home for every gate
command line, on the grounds that a second home is a second thing to keep correct. The
cost, recorded in `ci.yml`'s own header and in #49 and #32, was that no gate had a local
entry point at all: reproducing a red job meant opening a workflow file and reading YAML.

The README now carries the command lines (see *Running one by hand*), which reintroduces
exactly the duplication #52 argued against — so this module is the price of it. It asserts
that each documented command is the one its job actually runs, and that no gate in `ci.yml`
is undocumented. With that, the copy cannot drift silently, which is the property #52 was
protecting; without it the block would be prose that was true once.

**What is compared, and what is deliberately tolerated.** A documented command matches when
its whitespace-separated tokens appear, *in order*, in one of its job's `run:` blocks. The
tolerance is one-directional on purpose:

* A token the README has and CI does not is a **failure** — that covers every threshold
  (`--cov-fail-under=90`, `--fail-under 100`, `-ll`), every path, and every flag.
* A token CI has and the README does not is **allowed**, because CI legitimately carries
  scaffolding a contributor should not type: `--python ${{ matrix.python-version }}` from
  the matrix, the `| tee checks.log` pipeline behind `rhiza-test`'s skip guard, and the
  `set -o pipefail` around it.

The second half is a real gap and is stated rather than hidden: a *new* flag added to a CI
command will not fail this suite. Catching that would mean asserting equality, which the
matrix expression makes impossible without teaching this module about GitHub's template
syntax. The threshold and the flag set the README claims are pinned; a CI-side addition is
not.

YAML is parsed here by hand. `ci.yml` is read for two things only — job names and `run:`
bodies — and a dependency on PyYAML in a package installed in every rhiza-managed repo's
test environment is the trade #53 already refused once for `python-dotenv`.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
CI = ROOT / ".github" / "workflows" / "ci.yml"

# The fence under "Running one by hand": `# <gate>` lines, each followed by its command(s).
_FENCE = re.compile(r"#### Running one by hand\n+```bash\n(.*?)```", re.DOTALL)

# A job key: two-space indent, no value. Matched only inside the `jobs:` block, because
# `on:`'s `push:`/`pull_request:` have the same shape one level up.
_JOB = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")

# `run:` and its inline value, if any.
_RUN = re.compile(r"^(\s*)run:(.*)$")

# The block-scalar indicators that mean "the command is on the following lines".
_BLOCK_SCALARS = ("|", "|-", "|+", ">", ">-", ">+", "")

# `ci-gate` runs no gate: it reads `needs.*.result` so branch protection has one required
# check instead of a list that must be edited whenever a job is added. There is nothing for
# a contributor to reproduce, so it is documented in the table above the fence and not in it.
_NOT_A_GATE = frozenset({"ci-gate"})


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


def _is_subsequence(needle: list[str], haystack: list[str]) -> bool:
    """Return whether every token of ``needle`` appears in ``haystack``, in order.

    Args:
        needle: Tokens the README documents.
        haystack: Tokens the workflow runs.

    Returns:
        True when the documented command is contained in the CI one.
    """
    remaining = iter(haystack)
    return all(token in remaining for token in needle)


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


def _documented() -> dict[str, list[str]]:
    """Return each gate documented in the README mapped to its command lines.

    Returns:
        Gate name to the command lines listed under its ``# <gate>`` comment, in order.
    """
    fence = _FENCE.search(README.read_text(encoding="utf-8"))
    assert fence is not None, (
        "README.md has no '#### Running one by hand' bash fence. It is the local entry "
        "point for every gate (#58); if it moved or was renamed, update this test — it is "
        "the only thing keeping those commands in step with ci.yml."
    )

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


class TestTheHelpers:
    """The parsing, on synthetic input.

    The two functions above are only ever run against files that are expected to agree, so
    their interesting behaviour — a folded scalar, a subsequence that should *not* match —
    would otherwise never execute.
    """

    def test_a_subsequence_matches_even_with_extra_ci_tokens(self) -> None:
        """The matrix's `--python` argument is exactly this case."""
        assert _is_subsequence(["uv", "run", "pytest"], ["uv", "run", "--python", "3.12", "pytest"])

    def test_order_is_required(self) -> None:
        """Tokens out of order are a different command, not the same one."""
        assert not _is_subsequence(["pytest", "uv"], ["uv", "run", "pytest"])

    def test_a_missing_token_does_not_match(self) -> None:
        """A threshold dropped from CI must not still match the README."""
        assert not _is_subsequence(["--cov-fail-under=90"], ["pytest", "-ra"])

    def test_a_changed_threshold_does_not_match(self) -> None:
        """The failure this module exists for: 90 in the README, 95 in CI."""
        assert not _is_subsequence(["--cov-fail-under=90"], ["pytest", "--cov-fail-under=95"])

    def test_folded_scalars_collapse_to_one_command(self) -> None:
        """A `run: >-` body spread over lines is the same token list as one line."""
        assert _normalise("uv run\n  --with ty\n  ty check src") == ["uv", "run", "--with", "ty", "ty", "check", "src"]


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


class TestEachCommandMatchesCi:
    """Each documented command against the job it claims to reproduce."""

    def test_documented_commands_are_the_ones_ci_runs(self) -> None:
        """Every command must be a token-subsequence of one `run:` block in its job.

        One test over all of them rather than a parametrisation, because the useful failure
        message is the whole set of mismatches: a threshold bump touches several gates at
        once, and finding them one re-run at a time is the slow way.
        """
        jobs = _ci_jobs()
        mismatched = [
            f"{gate}: {command}"
            for gate, commands in _documented().items()
            for command in commands
            if not any(_is_subsequence(_normalise(command), block) for block in jobs.get(gate, []))
        ]

        assert not mismatched, (
            "the README documents commands that no `run:` block in their job matches:\n  "
            + "\n  ".join(mismatched)
            + "\n\nci.yml is the definition (#52). Copy the line from there, or — if the "
            "difference is CI-only scaffolding — trim the documented command to the part a "
            "contributor should type."
        )
