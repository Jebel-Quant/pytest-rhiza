"""Tests for module docstrings using doctest.

Ported from ``jebel-quant/rhiza`` at 89f9298, where bundle ``python-core`` synced it
to ``.rhiza/tests/test_docstrings.py``. It now arrives installed, and is collected by name:
``pytest --pyargs pytest_rhiza.checks.test_docstrings``.

Automatically discovers all packages and runs doctests for each.

**Scope lives next door.** Which folders are searched — ``RHIZA_DOCTEST_FOLDERS``, then
``SOURCE_FOLDER`` from a legacy ``.rhiza/.env``, then ``src`` — is resolved by
:mod:`pytest_rhiza._source_folder`, which also holds the reasons that ladder has three
rungs. It moved out in #60: it is a migration concern with an end date, while running
``doctest`` over what it returns is what this module *is*. What remains here is the walk,
the measurement and the tally.

**Two layouts, deliberately.** A folder may hold packages (``src/mypkg/__init__.py``) or
loose scripts (``utils/link_dogfood.py``); both carry docstrings worth checking, so both
are discovered. A module that cannot be imported is reported as a warning and skipped, not
failed: a loose script may execute at import, and "we could not measure this" is a
different statement from "this example is wrong".
"""

from __future__ import annotations

import doctest
import importlib
import importlib.util
import logging
import sys
import warnings
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from pytest_rhiza._source_folder import RHIZA_ENV_PATH, configured_label, doctest_folders, read_rhiza_env


def _iter_modules_from_path(logger: logging.Logger, package_path: Path, src_path: Path) -> Iterator[ModuleType]:
    """Recursively find all Python modules in a directory."""
    for path in package_path.rglob("*.py"):
        if path.name == "__init__.py":
            module_path = path.parent.relative_to(src_path)
        else:
            module_path = path.relative_to(src_path).with_suffix("")

        # Convert path to module name in an OS-independent way
        module_name = ".".join(module_path.parts)

        try:
            yield importlib.import_module(module_name)
        except ImportError as e:
            warnings.warn(f"Could not import {module_name}: {e}", stacklevel=2)
            logger.warning("Could not import module %s: %s", module_name, e)
            continue


def _find_packages(src_path: Path) -> Iterator[Path]:
    """Find all packages in the source path, including those nested under namespace packages.

    Sorted, like :func:`_iter_loose_modules` already sorts its files: ``rglob`` yields in
    filesystem order, so without this the packages are doctested in an order that varies
    between machines — and one package importing another makes that order observable.
    """
    for init_file in sorted(src_path.rglob("__init__.py")):
        package_dir = init_file.parent
        # Only yield top-level packages (those whose parent doesn't have __init__.py or is src_path)
        parent = package_dir.parent
        if parent == src_path or not (parent / "__init__.py").exists():
            yield package_dir


def _import_locations(module: ModuleType) -> list[Path]:
    """Return the resolved directories ``module`` was imported from.

    A package carries ``__path__``; a plain module does not, and ``getattr`` returning
    ``[]`` for it is deliberate. A same-named *module* shadowing a package cannot be the
    folder under test, so an empty list correctly falls through to eviction.

    Args:
        module: An entry from ``sys.modules``.

    Returns:
        Its ``__path__`` entries, resolved, or an empty list when it has none.
    """
    return [Path(entry).resolve() for entry in getattr(module, "__path__", [])]


def _describe(located: list[Path]) -> list[str] | str:
    """Render import locations for the eviction log line.

    Args:
        located: The paths from :func:`_import_locations`.

    Returns:
        The paths as strings, or a stand-in phrase when there are none — a namespace
        package or a C extension can be in ``sys.modules`` with nothing to point at, and
        an empty list in the log reads as a bug rather than as an answer.
    """
    return [str(path) for path in located] or "an unknown location"


def _cached_names(top_level: str) -> list[str]:
    """Return every ``sys.modules`` key belonging to one top-level package.

    Materialised into a list before the caller deletes anything, because deleting from
    ``sys.modules`` while iterating it raises.

    Args:
        top_level: The package name, without dots.

    Returns:
        The package itself and each of its imported submodules.
    """
    return [name for name in list(sys.modules) if name == top_level or name.startswith(f"{top_level}.")]


def _evict_shadowing_package(
    monkeypatch: pytest.MonkeyPatch, logger: logging.Logger, import_root: Path, package_dir: Path
) -> None:
    """Drop a same-named package already imported from somewhere other than this folder.

    Without this the gate can report a pass having measured code that is not in the tree.
    ``importlib.import_module`` resolves a submodule against the *already-imported*
    parent's ``__path__``, and prepending a folder to ``sys.path`` does not change a
    parent that is in ``sys.modules`` already. So where a package under the configured
    folder shares its top-level name with an installed distribution, the installed copy is
    what gets doctested — silently, and reported as a skip when it happens to carry no
    examples.

    That is not hypothetical for pytest-rhiza itself, which is always installed (it is the
    plugin running this check), so for three releases its own new modules were invisible
    here. Any project whose source package name collides with something in its environment
    inherits the same hole.

    Args:
        monkeypatch: The test's monkeypatch fixture, so ``sys.modules`` is restored at
            teardown rather than left mutated for the rest of the session.
        logger: The test logger.
        import_root: The directory prepended to ``sys.path`` for this folder.
        package_dir: The package about to be walked.
    """
    top_level = package_dir.relative_to(import_root).parts[0]
    existing = sys.modules.get(top_level)
    if existing is None:
        return
    located = _import_locations(existing)
    if (import_root / top_level).resolve() in located:
        return  # already the folder under test; nothing is being shadowed
    logger.info(
        "Evicting cached package %s (imported from %s) so %s is what gets measured",
        top_level,
        _describe(located),
        import_root / top_level,
    )
    for cached in _cached_names(top_level):
        monkeypatch.delitem(sys.modules, cached, raising=False)


def _iter_loose_modules(logger: logging.Logger, folder: Path) -> Iterator[ModuleType]:
    """Import the top-level ``*.py`` files in ``folder`` that are not part of a package.

    A folder of standalone scripts (``utils/``, ``scripts/``, ``tools/``) has no
    ``__init__.py``, so :func:`_find_packages` never reaches it even though its docstrings
    may carry examples. Each file is loaded from its path rather than by module name, so
    no ``sys.path`` manipulation is needed and two folders may hold same-named scripts.

    Args:
        logger: The test logger.
        folder: The directory to scan (not recursed — a package below it is the other
            discovery path's job).

    Yields:
        Each imported module. A module that raises on import is warned about and skipped:
        a loose script may run code at import time, and being unable to measure an example
        is not the same as the example being wrong.
    """
    if (folder / "__init__.py").exists():
        return  # a package; _find_packages handles it

    for path in sorted(folder.glob("*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:  # pragma: no cover - defensive
            continue
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except BaseException as e:  # noqa: BLE001 - a script may raise or SystemExit on import
            warnings.warn(f"Could not import {path}: {e}", stacklevel=2)
            logger.warning("Could not import loose module %s: %s", path, e)
            continue
        yield module


def _iter_package_modules(
    logger: logging.Logger, monkeypatch: pytest.MonkeyPatch, src_path: Path, import_root: Path
) -> Iterator[ModuleType]:
    """Yield the modules of every package under one configured folder.

    Args:
        logger: The test logger.
        monkeypatch: The test's monkeypatch fixture, for :func:`_evict_shadowing_package`.
        src_path: The configured folder being walked.
        import_root: The directory prepended to ``sys.path`` for that folder.

    Yields:
        Each imported module. A module that cannot be imported is warned about and skipped
        by :func:`_iter_modules_from_path`, one module at a time — not measuring something
        is a different statement from finding it wrong.
    """
    # No `is_dir() and (package_dir / "__init__.py").exists()` guard: the inline version
    # had one, and inverting it to a `continue` made visible that it can never fire.
    # `_find_packages` globs `__init__.py` and yields each match's parent, so both halves
    # are true by construction — the guard was an uncoverable branch asserting the
    # postcondition of the generator two lines above it.
    #
    # And no `except ImportError` around the `list()` either, for the same reason (#45).
    # `_iter_modules_from_path` catches ImportError around its own `import_module` call and
    # continues, so no ImportError can escape the generator for a handler here to see —
    # the walk raising one would mean that handler had stopped working. It was 4 of the 6
    # uncovered lines in the package and could not be tested, because there is no repo
    # state that reaches it. Per-module is also the better granularity: one unimportable
    # module no longer costs the measurement of its siblings.
    for package_dir in _find_packages(src_path):
        package_name = package_dir.name
        logger.info("Discovered package: %s", package_name)
        _evict_shadowing_package(monkeypatch, logger, import_root, package_dir)
        modules = list(_iter_modules_from_path(logger, package_dir, import_root))
        logger.debug("%d module(s) found in package %s", len(modules), package_name)
        yield from modules


def _iter_doctest_modules(
    logger: logging.Logger, monkeypatch: pytest.MonkeyPatch, folders: list[Path]
) -> Iterator[ModuleType]:
    """Yield every module to doctest, across folders, packages and loose scripts.

    The three-deep walk that used to sit inline in :func:`test_doctests`. Pulling it out
    is what lets that test read as "measure each module, then report", because the
    discovery rules — which folder is its own package, which packages a folder holds,
    which scripts no package walk reaches — are all answered here.

    Args:
        logger: The test logger.
        monkeypatch: The test's monkeypatch fixture, so both the ``sys.path`` prepend and
            any ``sys.modules`` eviction are undone at teardown.
        folders: The configured folders that exist, from :func:`doctest_folders`.

    Yields:
        Every importable module found, packages first and then loose scripts, in folder
        order.
    """
    for src_path in folders:
        # A configured folder may *be* a package rather than contain them: a flat-layout
        # project names its package directly, so `SOURCE_FOLDER=mypackage`. Its modules
        # are then importable relative to the folder's parent, and resolving them against
        # the folder itself derives an empty module name for `__init__.py` — which is a
        # ValueError from importlib rather than the ImportError the walk expects, so the
        # whole gate crashed instead of reporting anything.
        import_root = src_path.parent if (src_path / "__init__.py").exists() else src_path

        # Add the folder to sys.path with automatic cleanup
        monkeypatch.syspath_prepend(str(import_root))
        logger.debug("Prepended to sys.path: %s", import_root)

        yield from _iter_package_modules(logger, monkeypatch, src_path, import_root)

        # And the loose scripts, which no package walk reaches
        yield from _iter_loose_modules(logger, src_path)


class _Tally:
    """Running doctest totals across every module measured.

    Replaces three locals and a ``nonlocal`` closure. The closure worked, but it meant
    the accumulation could only be read inside :func:`test_doctests` — and the failure
    message had to be assembled there too, which is most of why that function ranked
    C (19).

    Attributes:
        attempted: Examples run across all modules.
        failed: Examples that failed across all modules.
        failures: One ``(module name, failed, attempted)`` triple per failing module.
    """

    def __init__(self) -> None:
        """Start empty."""
        self.attempted = 0
        self.failed = 0
        self.failures: list[tuple[str, int, int]] = []

    def record(self, name: str, attempted: int, failed: int) -> None:
        """Fold one module's result into the totals.

        Args:
            name: The module's dotted name, as it should appear in the summary.
            attempted: Examples run in that module.
            failed: Examples that failed in that module.
        """
        self.attempted += attempted
        self.failed += failed
        if failed:
            self.failures.append((name, failed, attempted))

    @property
    def message(self) -> str:
        """Return the assertion message naming every failing module.

        Returns:
            The summary, unchanged from the inline version — ``tests/`` asserts on the
            ``"Doctest summary"`` prefix, and a reader who has seen a red run before
            should not have to learn a new shape.
        """
        formatted = "\n".join(f"  {name}: {failed}/{attempted} failed" for name, failed, attempted in self.failures)
        return (
            f"Doctest summary: {self.attempted} tests across {len(self.failures)} module(s)\n"
            f"Failures: {self.failed}\n"
            f"Failed modules:\n{formatted}"
        )


def _measure(logger: logging.Logger, capsys: pytest.CaptureFixture[str], module: ModuleType) -> doctest.TestResults:
    """Run one module's doctests.

    Args:
        logger: The test logger.
        capsys: The capture fixture, disabled around the run so doctest's own comparison
            of stdout is not competing with pytest's.
        module: The imported module to measure.

    Returns:
        doctest's attempted/failed counts for that module.
    """
    logger.debug("Running doctests for module: %s", module.__name__)
    with capsys.disabled():
        return doctest.testmod(
            module,
            verbose=False,
            optionflags=(doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE),
        )


def _measure_all(
    logger: logging.Logger,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    folders: list[Path],
) -> _Tally:
    """Doctest every module the folders yield and return the totals.

    Args:
        logger: The test logger.
        capsys: The capture fixture, passed through to :func:`_measure`.
        monkeypatch: The test's monkeypatch fixture, passed through to the walk.
        folders: The configured folders that exist.

    Returns:
        The tally, whose ``failures`` is what the gate asserts on.
    """
    tally = _Tally()
    for module in _iter_doctest_modules(logger, monkeypatch, folders):
        results = _measure(logger, capsys, module)
        tally.record(module.__name__, results.attempted, results.failed)
        if results.failed:
            logger.warning(
                "Doctests failed for %s: %d/%d failed",
                module.__name__,
                results.failed,
                results.attempted,
            )
        else:
            logger.debug("Doctests passed for %s (%d test(s))", module.__name__, results.attempted)
    return tally


def test_doctests(
    logger: logging.Logger, root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Run doctests for every module in the configured folders."""
    values = read_rhiza_env(root / RHIZA_ENV_PATH)
    folders = doctest_folders(root, values)

    logger.info("Starting doctest discovery in: %s", [str(f) for f in folders] or "(nothing configured)")
    if not folders:
        configured = configured_label(values)
        logger.info("No doctest folder exists (looked for: %s) — skipping doctests", configured)
        pytest.skip(f"No doctest folder found (looked for: {configured})")

    tally = _measure_all(logger, capsys, monkeypatch, folders)

    if tally.failures:
        logger.error("%s", tally.message)
        assert not tally.failures, tally.message

    logger.info("Doctest summary: %d tests, 0 failures", tally.attempted)

    if tally.attempted == 0:
        logger.info("No doctests were found in any module — skipping")
        pytest.skip("No doctests were found in any module")
