"""End-to-end tests for ``--pyargs`` collection of the installed checks.

This is the load-bearing assumption of the whole design: a ``pytest11`` entry point can
ship fixtures but not tests, so the checks are named on the command line and collected out
of site-packages. If that stopped working the package would be inert, and the failure
would look like a green run over zero tests — so these assert the collected *counts*, not
just the exit status.

They also pin the selection property that replaces sync-time file delivery: naming one
check module runs that module and nothing else, which is what lets a Python project stay
unaware of the Cargo checks.
"""

from __future__ import annotations

import subprocess  # nosec B404
import sys
from pathlib import Path

GOOD_README = """# Demo

Install it:

```bash
make install
```

A tree, which is not shell and must not be parsed as shell:

```bash
src/
├── demo
└── other
```
"""

BROKEN_README = """# Demo

```bash
if then fi done esac
```
"""


def _run_checks(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run the installed checks in a subprocess.

    Args:
        args: Arguments appended after ``pytest``.
        cwd: Working directory for the run.

    Returns:
        The completed process, with stdout and stderr captured as text.
    """
    return subprocess.run(  # nosec B603
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_named_check_module_is_collected_and_passes(tmp_path: Path) -> None:
    """The core README check, collected by dotted name, passes on a sound README."""
    (tmp_path / "README.md").write_text(GOOD_README, encoding="utf-8")

    result = _run_checks(
        "--pyargs",
        "pytest_rhiza.checks.test_readme",
        "--rhiza-root",
        str(tmp_path),
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 passed" in result.stdout, result.stdout


def test_a_broken_bash_fence_fails_the_check(tmp_path: Path) -> None:
    """A README whose shell does not parse is a failure, not a skip."""
    (tmp_path / "README.md").write_text(BROKEN_README, encoding="utf-8")

    result = _run_checks(
        "--pyargs",
        "pytest_rhiza.checks.test_readme",
        "--rhiza-root",
        str(tmp_path),
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "syntax errors" in result.stdout, result.stdout


def test_naming_one_module_does_not_collect_the_others(tmp_path: Path) -> None:
    """Selection is by name, so a Python project never collects the Rust or Go checks."""
    (tmp_path / "README.md").write_text(GOOD_README, encoding="utf-8")

    result = _run_checks(
        "--collect-only",
        "-q",
        "--pyargs",
        "pytest_rhiza.checks.test_readme",
        "--rhiza-root",
        str(tmp_path),
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_cargo_toml" not in result.stdout
    assert "test_go_module" not in result.stdout
    assert "test_pyproject" not in result.stdout


def test_two_modules_can_be_named_together(tmp_path: Path) -> None:
    """The make wiring accumulates modules in one variable, so several arrive at once."""
    (tmp_path / "README.md").write_text(GOOD_README, encoding="utf-8")

    result = _run_checks(
        "--collect-only",
        "-q",
        "--pyargs",
        "pytest_rhiza.checks.test_readme",
        "pytest_rhiza.checks.test_release_tags",
        "--rhiza-root",
        str(tmp_path),
        cwd=tmp_path,
    )

    # Node ids come out with an empty file part: `-q` renders them relative to the
    # rootdir, which is the repository under test, while the modules live in
    # site-packages. The test names are the reliable signal.
    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_bash_blocks_basic_syntax" in result.stdout
    assert "test_latest_tag_is_reachable_from_a_branch" in result.stdout
    assert "4 tests collected" in result.stdout
