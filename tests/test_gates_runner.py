"""The local gate runner: what it selects, and the guard it carries for `rhiza-test`.

Issue #66. ``scripts/gates.py`` exists so a contributor can reproduce a red CI job without
eleven copy-pastes, and it does that by *executing* the README block rather than holding a
copy of it. ``tests/test_readme_gates.py`` already proves that block equals ``ci.yml``, and
the two share :func:`scripts.gates.documented_gates` so the proof transfers — so nothing
here re-checks the command lines. What is left to test is the runner's own behaviour, which
that equality says nothing about:

* the fence parser, on input other than this repository's own README — including the
  restructured-README case, which is the one that silently breaks both consumers;
* the selection rule, because excluding ``lowest-deps`` by default is the difference
  between a runner and a footgun: it rewrites ``uv.lock`` in the working tree;
* the #34 skip guard, the first of three places the runner deliberately does *more* than
  the README line it runs. CI fails ``rhiza-test`` when any check skips, because a skipped
  assertion reads as a pass; a local run that reported green on the same output would be
  worse than no runner at all.
* the environment in :data:`scripts.gates.GATE_ENV`, the second — the value has to reach the
  child process, and the ambient environment has to survive being added to (#81). Whether
  that value is the one ``ci.yml`` sets is ``tests/test_readme_gates.py``'s job, not this
  module's.
* the untracked second pass for the gates in :data:`scripts.gates.GIT_SCOPED`, the third
  (#89). ``prek run --all-files`` means every file *git knows about*, so this gate alone
  could pass a module CI would reject — and a brand-new module is exactly where a missing
  lint exemption is most likely. The rewritten line is derived from the documented one, so
  what is tested here is the rewrite and the paths, never a second copy of the command.

The guard tests drive it with a trivial subprocess that prints the tell-tale word rather
than with a real check run, because what is under test is the reading of the output, not
pytest.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from scripts.gates import (
    DESTRUCTIVE,
    GATE_ENV,
    GIT_SCOPED,
    GatesError,
    documented_gates,
    main,
    run_gate,
    select_gates,
    untracked_files,
)

if TYPE_CHECKING:  # pragma: no cover - import only for the fixture's type
    from conftest import Subject

# A fence with the two shapes that matter: a gate with one command, one with two, and a
# destructive gate whose name is in DESTRUCTIVE.
_FENCE = """
Some prose.

#### Running one by hand

```bash
# lint
uvx prek run --all-files
# typecheck
uv run --with ty ty check src
uv run --with mypy mypy --strict src
# lowest-deps
uv sync --resolution lowest-direct
```

More prose.
"""


def _fence_of(gates: dict[str, list[str]]) -> str:
    """Return a *Running one by hand* fence documenting the given gates.

    The module-level :data:`_FENCE` documents real command lines, which is right for the
    parser and the selection tests because neither executes anything. Tests that drive
    :func:`main` all the way through to a run need commands that are safe to execute, and
    so build their own fence here.

    Args:
        gates: Gate name to its command lines, in the order they should be written.

    Returns:
        Markdown holding a fence the parser will find.
    """
    lines = ["#### Running one by hand", "", "```bash"]
    for name, commands in gates.items():
        lines.append(f"# {name}")
        lines.extend(commands)
    lines.append("```")
    return "\n".join(lines) + "\n"


def _readme(tmp_path: Path, body: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the runner at a synthetic README.

    Args:
        tmp_path: pytest's per-test temporary directory.
        body: Markdown to write.
        monkeypatch: Used to repoint the module-level ``README`` constant.
    """
    path = tmp_path / "README.md"
    path.write_text(body, encoding="utf-8", newline="\n")
    monkeypatch.setattr("scripts.gates.README", path)


def _script(body: str) -> str:
    """Return a command line running ``body`` with this interpreter.

    ``sys.executable`` rather than ``python``, because the suite runs on the Windows leg of
    the matrix too and there is no guarantee which interpreter that name resolves to.

    Args:
        body: Python source for ``-c``.

    Returns:
        A command line for :func:`scripts.gates.run_gate`.
    """
    return f'"{sys.executable}" -c "{body}"'


@pytest.fixture
def stub_restore(monkeypatch: pytest.MonkeyPatch) -> str:
    """Replace the post-destructive ``uv sync`` with a harmless marker-printing script.

    The restore added in #71 has to be exercised through the real code path rather than
    asserted from the source, but a suite that genuinely re-resolved ``uv.lock`` would be
    slow and would rewrite the working tree — the very thing the restore exists to undo.

    Args:
        monkeypatch: Used to repoint the module-level ``RESTORE_COMMAND``.

    Returns:
        The marker the stub prints, for the caller to assert on.
    """
    marker = "RESTORED"
    monkeypatch.setattr("scripts.gates.RESTORE_COMMAND", _script(f"print('{marker}')"))
    return marker


class TestTheFenceParser:
    """:func:`documented_gates`, on input other than this repo's own README."""

    def test_gates_map_to_their_commands_in_order(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A gate may carry more than one command, and their order is the run order."""
        _readme(tmp_path, _FENCE, monkeypatch)

        assert documented_gates() == {
            "lint": ["uvx prek run --all-files"],
            "typecheck": ["uv run --with ty ty check src", "uv run --with mypy mypy --strict src"],
            "lowest-deps": ["uv sync --resolution lowest-direct"],
        }

    def test_a_missing_fence_is_an_error_naming_the_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A restructured README breaks the runner and the pinning test together.

        Raising beats returning ``{}``: an empty mapping would make the runner report
        "nothing to do" and exit 0, which reads as a pass.
        """
        _readme(tmp_path, "# Title\n\nNo fence here.\n", monkeypatch)

        with pytest.raises(GatesError, match="Running one by hand"):
            documented_gates()

    def test_blank_lines_inside_the_fence_are_skipped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A blank line separating two gates is layout, not a command.

        Worth pinning because the parser appends any non-comment line to the current gate:
        without the skip, a gate would carry an empty command line and the runner would
        hand :func:`shlex.split` nothing to run.
        """
        _readme(
            tmp_path,
            "#### Running one by hand\n\n```bash\n# lint\nuvx prek run\n\n# audit\nuvx pip-audit\n```\n",
            monkeypatch,
        )

        assert documented_gates() == {"lint": ["uvx prek run"], "audit": ["uvx pip-audit"]}

    def test_this_repos_readme_still_parses(self) -> None:
        """A vacuity guard on the tests above: the real fence must not be empty."""
        assert len(documented_gates()) >= 8


class TestSelection:
    """Which gates a bare run picks, and how a wrong name is reported."""

    def test_the_destructive_gate_is_listed_but_flagged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--list`` shows every gate, and says which one a bare run will leave out."""
        _readme(tmp_path, _FENCE, monkeypatch)

        assert main(["--list"]) == 0

        out = capsys.readouterr().out
        assert "lowest-deps" in out
        assert DESTRUCTIVE["lowest-deps"] in out
        assert "uvx prek run --all-files" in out

    def test_an_unknown_gate_is_a_usage_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exit 2, and name the gates that do exist — a typo should not run anything."""
        _readme(tmp_path, _FENCE, monkeypatch)

        assert main(["typechek"]) == 2
        assert "no such gate: typechek" in capsys.readouterr().err

    def test_lowest_deps_is_not_run_unless_asked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The whole point of :data:`DESTRUCTIVE`: a bare run must not touch ``uv.lock``.

        Asserted through the summary rather than by watching for a subprocess, because
        "not selected" is exactly what the user needs to be told.
        """
        _readme(
            tmp_path,
            "#### Running one by hand\n\n```bash\n# lowest-deps\nuv sync --resolution lowest-direct\n```\n",
            monkeypatch,
        )

        assert main([]) == 0
        assert "lowest-deps (not selected)" in capsys.readouterr().out

    def test_a_missing_fence_is_a_usage_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A restructured README exits 2 through :func:`main`, not just from the parser.

        :class:`TestTheFenceParser` pins that :func:`documented_gates` raises; this pins
        that the raise becomes a usage exit rather than a traceback, and that the message
        naming the file survives to stderr.
        """
        _readme(tmp_path, "# Title\n\nNo fence here.\n", monkeypatch)

        assert main([]) == 2
        assert "Running one by hand" in capsys.readouterr().err

    def test_a_named_gate_runs_only_itself(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Naming a gate narrows the run, and the summary says so for the rest."""
        _readme(
            tmp_path,
            _fence_of({"lint": [_script("print('lint ran')")], "audit": [_script("print('audit ran')")]}),
            monkeypatch,
        )

        assert main(["lint"]) == 0

        out = capsys.readouterr().out
        assert "lint ran" in out
        assert "audit ran" not in out
        assert "PASS" in out
        assert "audit (not selected)" in out

    def test_a_failing_gate_is_reported_and_sets_the_exit_status(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exit 1, a FAIL line for the gate that failed — and the later gate still runs."""
        _readme(
            tmp_path,
            _fence_of({"lint": [_script("raise SystemExit(1)")], "audit": [_script("print('audit ran')")]}),
            monkeypatch,
        )

        assert main([]) == 1

        out = capsys.readouterr().out
        assert "FAIL" in out
        assert "audit ran" in out, "a red gate must not stop the ones after it"

    def test_all_opts_into_the_destructive_gate(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        stub_restore: str,
    ) -> None:
        """``--all`` selects ``lowest-deps``, and warns before running it."""
        _readme(tmp_path, _fence_of({"lowest-deps": [_script("print('resolved')")]}), monkeypatch)

        assert main(["--all"]) == 0

        out = capsys.readouterr().out
        assert DESTRUCTIVE["lowest-deps"] in out, "the note has to precede the damage"
        assert "resolved" in out
        assert stub_restore in out

    def test_selection_follows_the_readme_order_not_the_command_line(self) -> None:
        """Two gates named back-to-front still run in documented order.

        A run whose order depended on the argument order would make two invocations that
        asked for the same thing produce differently ordered output.
        """
        documented = {"lint": [], "typecheck": [], "test": []}

        assert select_gates(["test", "lint"], documented, include_destructive=False) == ["lint", "test"]


class TestRestoringTheWorkingTree:
    """A destructive gate puts the tree back when it finishes (#71)."""

    def test_a_destructive_gate_is_followed_by_the_restore(
        self, capsys: pytest.CaptureFixture[str], stub_restore: str
    ) -> None:
        """The plain path: ``lowest-deps`` passes, and the lock is re-synced after it."""
        assert run_gate("lowest-deps", [_script("print('resolved')")]) is True

        out = capsys.readouterr().out
        assert "resolved" in out
        assert stub_restore in out

    def test_the_restore_runs_even_when_the_gate_fails(
        self, capsys: pytest.CaptureFixture[str], stub_restore: str
    ) -> None:
        """The reason it is a ``finally``: a red gate is exactly when the tree is dirty.

        Returning early on failure without restoring would leave the lockfile rewritten in
        precisely the case the contributor is already busy debugging.
        """
        assert run_gate("lowest-deps", [_script("raise SystemExit(1)")]) is False
        assert stub_restore in capsys.readouterr().out

    def test_a_harmless_gate_is_not_followed_by_a_restore(
        self, capsys: pytest.CaptureFixture[str], stub_restore: str
    ) -> None:
        """Only :data:`DESTRUCTIVE` gates are restored — the rest must not pay for it."""
        assert run_gate("lint", [_script("print('linted')")]) is True
        assert stub_restore not in capsys.readouterr().out


class TestTheSkipGuard:
    """`rhiza-test` fails locally on the output CI fails on (#34)."""

    def test_a_skip_fails_the_gate(self, capsys: pytest.CaptureFixture[str]) -> None:
        """A zero exit status is not enough for a guarded gate."""
        assert run_gate("rhiza-test", [_script("print('32 passed, 2 skipped')")]) is False
        assert "reads as a pass" in capsys.readouterr().out

    def test_a_clean_run_passes(self) -> None:
        """And the guard must not fire on the output this repo actually produces."""
        assert run_gate("rhiza-test", [_script("print('34 passed in 0.09s')")]) is True

    def test_the_guard_applies_only_where_declared(self) -> None:
        """`test`'s own output says "skipped" routinely; only `rhiza-test` is guarded."""
        assert run_gate("test", [_script("print('170 passed, 6 skipped')")]) is True


class TestRunningCommands:
    """The two properties every gate depends on: exit status, and argument splitting."""

    def test_a_nonzero_exit_fails_the_gate(self) -> None:
        """The ordinary red-gate path."""
        assert run_gate("lint", [_script("raise SystemExit(1)")]) is False

    def test_later_commands_do_not_run_after_a_failure(
        self, capsys: pytest.CaptureFixture[str], stub_restore: str
    ) -> None:
        """``lowest-deps`` is two commands and the second is meaningless if the first fails.

        It takes ``stub_restore`` because the gate it names is destructive: since #71 a real
        run would re-resolve this repository's own lockfile mid-suite.
        """
        marker = "second command ran"
        assert run_gate("lowest-deps", [_script("raise SystemExit(1)"), _script(f"print('{marker}')")]) is False
        assert marker not in capsys.readouterr().out

    def test_quoted_arguments_survive_splitting(self) -> None:
        """The `license` gate passes one argument holding spaces and semicolons.

        Splitting it on whitespace would hand ``pip-licenses`` a dozen bad arguments, so
        this pins that the runner uses :func:`shlex.split` and no shell.
        """
        check = "import sys; raise SystemExit(0 if sys.argv[1] == 'MIT;MIT License' else 1)"
        assert run_gate("license", [f'"{sys.executable}" -c "{check}" "MIT;MIT License"']) is True


class TestTheGateEnvironment:
    """The declared variables must reach the child, without displacing the ambient ones."""

    def test_a_declared_variable_reaches_the_child(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The whole point: `rhiza-test` runs with the folder list CI gives it (#81)."""
        body = "import os; print(os.environ.get('RHIZA_DOCTEST_FOLDERS', 'unset'))"
        assert run_gate("rhiza-test", [_script(body)]) is True
        assert GATE_ENV["rhiza-test"]["RHIZA_DOCTEST_FOLDERS"] in capsys.readouterr().out

    def test_an_undeclared_gate_gets_no_extra_environment(self, capfd: pytest.CaptureFixture[str]) -> None:
        """Only `rhiza-test` is declared; `lint` must not inherit its folder list.

        Asserted because the mapping is keyed by gate: a lookup that fell back to "all of
        it" would leak a doctest folder list into gates that have nothing to do with
        doctests, and nothing else here would notice.

        ``capfd`` rather than ``capsys``, unlike its neighbours: `lint` is not in
        :data:`scripts.gates.SKIP_GUARD`, so its child is run uncaptured and writes to the
        file descriptor directly — which is the point of that branch, and invisible to a
        fixture that only sees ``sys.stdout``.
        """
        body = "import os; print('FOLDERS=' + os.environ.get('RHIZA_DOCTEST_FOLDERS', 'unset'))"
        assert run_gate("lint", [_script(body)]) is True
        assert "FOLDERS=unset" in capfd.readouterr().out

    def test_the_ambient_environment_survives(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Overlaid on `os.environ`, not substituted for it.

        `subprocess.run(env=...)` *replaces* the environment rather than extending it, so
        passing the declared mapping alone would strip `PATH` and `VIRTUAL_ENV` — and every
        gate's command line begins with `uv`, which reads both.
        """
        body = "import os; print('PATH=' + str('PATH' in os.environ))"
        assert run_gate("rhiza-test", [_script(body)]) is True
        assert "PATH=True" in capsys.readouterr().out


def _argv_echo() -> str:
    """Return a command line that prints the arguments it was given.

    The untracked pass is a *rewrite* of a documented command line, so what has to be
    asserted is the argv the child actually received — not that some second process ran.

    Returns:
        A command line for :func:`scripts.gates.run_gate`, ending in the whole-tree flag
        that :data:`scripts.gates.GIT_SCOPED` names for `lint`.
    """
    body = "import sys; print('ARGV=' + ' '.join(sys.argv[1:]))"
    return f"{_script(body)} {GIT_SCOPED['lint']}"


def _argv_lines(out: str) -> list[str]:
    """Return the lines the child processes printed, ignoring the runner's own echo.

    :func:`scripts.gates.run_gate` prints each command line before running it, and the echo
    of :func:`_argv_echo` contains the literal ``ARGV=`` inside its ``-c`` body — so a plain
    substring count sees every command twice. Only the child's output *begins* a line with
    it.

    Args:
        out: Captured stdout.

    Returns:
        One entry per child invocation, in order.
    """
    return [line for line in out.splitlines() if line.startswith("ARGV=")]


@pytest.fixture
def rooted(monkeypatch: pytest.MonkeyPatch, subject: Callable[..., Subject]) -> Callable[..., Subject]:
    """Return a factory building a repository and repointing the runner's ``ROOT`` at it.

    ``untracked_files`` asks git about :data:`scripts.gates.ROOT`, so a test needs a
    repository it controls the untracked set of. Repointing is enough — nothing here runs a
    documented command line, whose ``uvx`` invocations would need the real tree.

    Args:
        monkeypatch: Used to repoint the module-level ``ROOT``.
        subject: The throwaway-repository factory from ``tests/conftest.py``.

    Returns:
        ``make(files=None, *, untracked=None) -> Subject``, where ``files`` are committed
        and ``untracked`` are written afterwards and left uncommitted.
    """

    def make(files: dict[str, str] | None = None, *, untracked: dict[str, str] | None = None) -> Subject:
        """Build the repository and repoint ``ROOT``.

        Args:
            files: Committed content.
            untracked: Content written after the commit, so git neither tracks nor ignores
                it unless a committed ``.gitignore`` says otherwise.

        Returns:
            The built subject.
        """
        repo = subject(files or {"seed.txt": "seed\n"})
        if untracked:
            repo.write(untracked)
        monkeypatch.setattr("scripts.gates.ROOT", repo.path)
        return repo

    return make


class TestUntrackedFiles:
    """What the git-scoped gates cannot see, and what must stay invisible anyway."""

    def test_a_file_git_neither_tracks_nor_ignores_is_listed(self, rooted: Callable[..., Subject]) -> None:
        """The #89 case: a new module, written but not yet staged."""
        rooted(untracked={"fresh.py": "x = 1\n"})

        assert untracked_files() == ["fresh.py"]

    def test_an_ignored_file_is_not_listed(self, rooted: Callable[..., Subject]) -> None:
        """`--exclude-standard` is the escape hatch the note points contributors at.

        A path in `.gitignore` is one the repository has deliberately disowned, so linting
        it would convert the fix for a noisy scratch file into a lint failure.
        """
        rooted({".gitignore": "junk.txt\n"}, untracked={"junk.txt": "noise\n", "real.py": "x = 1\n"})

        assert untracked_files() == ["real.py"]

    def test_a_clean_tree_lists_nothing(self, rooted: Callable[..., Subject]) -> None:
        """The normal state, and the one where this must cost no extra child process."""
        rooted()

        assert untracked_files() == []

    def test_outside_a_repository_it_answers_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unknown is "nothing extra to lint", never an error.

        This pass supplements the documented command; being unable to ask git must not be
        able to fail a gate on its own.
        """
        monkeypatch.setattr("scripts.gates.ROOT", tmp_path)

        assert untracked_files() == []


class TestTheUntrackedPass:
    """The second pass: when it happens, what it runs, and when it must not happen."""

    def test_the_documented_command_runs_again_scoped_to_the_untracked_paths(
        self, rooted: Callable[..., Subject], capfd: pytest.CaptureFixture[str]
    ) -> None:
        """The fix for #89: `--all-files` swapped for `--files <paths>`, same command.

        Derived from the documented line rather than written out here, so the runner still
        holds no recipes (#66) — asserted by the first pass and the second differing in
        exactly that one flag.
        """
        rooted(untracked={"fresh.py": "x = 1\n"})

        assert run_gate("lint", [_argv_echo()]) is True

        out = capfd.readouterr().out
        assert "ARGV=--all-files" in out, out
        assert "ARGV=--files fresh.py" in out, out

    def test_it_announces_itself_and_names_the_escape_hatch(
        self, rooted: Callable[..., Subject], capfd: pytest.CaptureFixture[str]
    ) -> None:
        """A second pass nobody asked for has to say why it is happening."""
        rooted(untracked={"fresh.py": "x = 1\n"})

        run_gate("lint", [_argv_echo()])

        out = capfd.readouterr().out
        assert "#89" in out
        assert ".gitignore" in out

    def test_a_failure_in_the_second_pass_fails_the_gate(
        self, rooted: Callable[..., Subject], capfd: pytest.CaptureFixture[str]
    ) -> None:
        """Otherwise the whole thing is decoration: the gate has to be able to go red.

        The stub fails only when it is given `--files`, which is precisely the shape of the
        defect — a command line that passes over the tracked tree and fails over the new
        file.
        """
        body = "import sys; raise SystemExit('--files' in sys.argv)"
        command = f"{_script(body)} {GIT_SCOPED['lint']}"
        rooted(untracked={"fresh.py": "x = 1\n"})

        assert run_gate("lint", [command]) is False

    def test_a_clean_tree_runs_the_documented_command_once(
        self, rooted: Callable[..., Subject], capfd: pytest.CaptureFixture[str]
    ) -> None:
        """No untracked files means no second pass, and no note either."""
        rooted()

        assert run_gate("lint", [_argv_echo()]) is True

        out = capfd.readouterr().out
        assert _argv_lines(out) == ["ARGV=--all-files"], out
        assert "#89" not in out

    def test_a_gate_that_is_not_git_scoped_gets_no_second_pass(
        self, rooted: Callable[..., Subject], capfd: pytest.CaptureFixture[str]
    ) -> None:
        """`typecheck` walks the filesystem, so it already sees the untracked file.

        Keyed by gate rather than applied to every gate carrying the flag: a second pass
        over a gate that never needed one is wasted work, and `--all-files` means something
        different to tools that are not prek.
        """
        rooted(untracked={"fresh.py": "x = 1\n"})

        assert run_gate("typecheck", [_argv_echo()]) is True

        out = capfd.readouterr().out
        assert _argv_lines(out) == ["ARGV=--all-files"], out

    def test_a_documented_line_without_the_flag_gets_no_second_pass(
        self, rooted: Callable[..., Subject], capfd: pytest.CaptureFixture[str]
    ) -> None:
        """If the README stops scoping by git, this pass has nothing to re-scope.

        Silently running the line unchanged a second time would be worse than not running
        it: two identical passes read as coverage that is not there.
        """
        rooted(untracked={"fresh.py": "x = 1\n"})

        assert run_gate("lint", [_script("import sys; print('ARGV=' + ' '.join(sys.argv[1:]))")]) is True

        out = capfd.readouterr().out
        assert _argv_lines(out) == ["ARGV="], out

    def test_a_path_with_a_space_survives_the_round_trip(
        self, rooted: Callable[..., Subject], capfd: pytest.CaptureFixture[str]
    ) -> None:
        """The rewritten line is re-split with `shlex.split`, so paths need quoting."""
        rooted(untracked={"two words.py": "x = 1\n"})

        assert run_gate("lint", [_argv_echo()]) is True

        assert "ARGV=--files two words.py" in capfd.readouterr().out
