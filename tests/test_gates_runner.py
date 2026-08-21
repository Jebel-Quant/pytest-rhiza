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
* the #34 skip guard, which is the one place the runner deliberately does *more* than the
  README line it runs. CI fails ``rhiza-test`` when any check skips, because a skipped
  assertion reads as a pass; a local run that reported green on the same output would be
  worse than no runner at all.

The guard tests drive it with a trivial subprocess that prints the tell-tale word rather
than with a real check run, because what is under test is the reading of the output, not
pytest.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts.gates import DESTRUCTIVE, GatesError, documented_gates, main, run_gate

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

    def test_later_commands_do_not_run_after_a_failure(self) -> None:
        """``lowest-deps`` is two commands and the second is meaningless if the first fails."""
        marker = "second command ran"
        assert run_gate("lowest-deps", [_script("raise SystemExit(1)"), _script(f"print('{marker}')")]) is False

    def test_quoted_arguments_survive_splitting(self) -> None:
        """The `license` gate passes one argument holding spaces and semicolons.

        Splitting it on whitespace would hand ``pip-licenses`` a dozen bad arguments, so
        this pins that the runner uses :func:`shlex.split` and no shell.
        """
        check = "import sys; raise SystemExit(0 if sys.argv[1] == 'MIT;MIT License' else 1)"
        assert run_gate("license", [f'"{sys.executable}" -c "{check}" "MIT;MIT License"']) is True
