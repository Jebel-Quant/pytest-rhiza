"""Subject-repository tests for ``checks/test_docstrings.py``.

The check discovers Python under configured folders, imports each module and runs its
doctests. Three properties are worth pinning, and none of them could be observed before
this file existed:

* **Where it looks.** ``RHIZA_DOCTEST_FOLDERS``, then ``SOURCE_FOLDER`` from
  ``.rhiza/.env``, then ``src``. #1517 is the bug that ordering exists to fix — a project
  keeping Python outside its source root had its examples silently skipped.
* **What it reaches.** Packages, namespace-nested packages, and loose scripts in a folder
  with no ``__init__.py`` are three different discovery paths.
* **How it fails.** A wrong example fails; a module that cannot be *imported* warns and
  is skipped, because "we could not measure this" is a different statement.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import only for the fixture's type
    from conftest import Subject

PASSING_PACKAGE = '''
"""A demonstration package.

Examples:
    >>> 1 + 1
    2
"""
'''

# Imports its sibling, so that by the time the walk reaches `beta` it is already in
# sys.modules — resolved from the folder under test, which is the case eviction must not
# disturb. Discovery is sorted, so `alpha` reliably comes first.
IMPORTS_A_SIBLING = '''
"""A package that imports its sibling.

Examples:
    >>> 1
    1
"""

import beta  # noqa: F401
'''

PASSING_MODULE = '''
"""A demonstration module.

Examples:
    >>> "rhiza".upper()
    'RHIZA'
"""
'''

FAILING_MODULE = '''
"""A module whose example is wrong.

Examples:
    >>> 2 + 2
    5
"""
'''


class TestDiscoveryScope:
    """Which folders the check looks in, and what it does when it finds nothing."""

    def test_it_defaults_to_src_and_runs_the_examples_it_finds(self, subject: Callable[..., Subject]) -> None:
        """With nothing configured the folder is ``src``, covering both file shapes.

        ``__init__.py`` and a sibling module are separate branches of the module-name
        derivation — one names the package, the other the file — so both are present.
        """
        repo = subject(
            {"src/demopkg/__init__.py": PASSING_PACKAGE, "src/demopkg/greet.py": PASSING_MODULE},
            tag="v1.2.3",
        )

        result = repo.run("test_docstrings")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "1 passed" in result.stdout, result.stdout

    def test_a_repository_with_no_source_folder_skips(self, subject: Callable[..., Subject]) -> None:
        """Nothing to measure is a skip that names what it looked for, not a pass."""
        repo = subject({"README.md": "# Demo\n"}, tag="v1.2.3")

        result = repo.run("test_docstrings")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "No doctest folder found (looked for: src)" in result.stdout, result.stdout

    def test_source_folder_from_the_rhiza_env_file_is_honoured(self, subject: Callable[..., Subject]) -> None:
        """A project whose Python lives outside ``src`` declares it in ``.rhiza/.env``."""
        repo = subject(
            {".rhiza/.env": "SOURCE_FOLDER=lib\n", "lib/demopkg/__init__.py": PASSING_PACKAGE},
            tag="v1.2.3",
        )

        result = repo.run("test_docstrings")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "1 passed" in result.stdout, result.stdout

    def test_an_env_file_pointing_at_nothing_skips_naming_the_folder(self, subject: Callable[..., Subject]) -> None:
        """The skip reason has to name the configured folder, or it is unactionable."""
        repo = subject({".rhiza/.env": "SOURCE_FOLDER=nowhere\n"}, tag="v1.2.3")

        result = repo.run("test_docstrings")

        assert "No doctest folder found (looked for: nowhere)" in result.stdout, result.stdout

    def test_the_environment_variable_overrides_the_env_file(self, subject: Callable[..., Subject]) -> None:
        """``make rhiza-test`` sets ``RHIZA_DOCTEST_FOLDERS`` from the accumulated list.

        Also the multi-folder and duplicate cases: the value is whitespace-separated and
        ``src`` appears twice, which must not run the same folder's examples twice.
        """
        repo = subject(
            {
                ".rhiza/.env": "SOURCE_FOLDER=ignored\n",
                "src/demopkg/__init__.py": PASSING_PACKAGE,
                "utils/greet.py": PASSING_MODULE,
            },
            tag="v1.2.3",
        )

        result = repo.run("test_docstrings", env={"RHIZA_DOCTEST_FOLDERS": "src utils src missing"})

        assert result.returncode == 0, result.stdout + result.stderr
        assert "1 passed" in result.stdout, result.stdout

    def test_a_configured_folder_that_does_not_exist_skips(self, subject: Callable[..., Subject]) -> None:
        """A folder named but absent leaves nothing configured, which is the skip case."""
        repo = subject({"src/demopkg/__init__.py": PASSING_PACKAGE}, tag="v1.2.3")

        result = repo.run("test_docstrings", env={"RHIZA_DOCTEST_FOLDERS": "not-here"})

        assert "No doctest folder found (looked for: not-here)" in result.stdout, result.stdout


class TestDiscoveryPaths:
    """Packages, namespace-nested packages and loose scripts are three different walks."""

    def test_a_namespace_nested_package_is_discovered(self, subject: Callable[..., Subject]) -> None:
        """``src/ns/pkg`` with no ``src/ns/__init__.py`` is still a package to walk."""
        repo = subject({"src/ns/pkg/__init__.py": PASSING_PACKAGE}, tag="v1.2.3")

        result = repo.run("test_docstrings")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "1 passed" in result.stdout, result.stdout

    def test_loose_scripts_in_a_folder_without_an_init_are_run(self, subject: Callable[..., Subject]) -> None:
        """A ``utils/`` of standalone scripts is what #1517 was about — no package walk reaches it."""
        repo = subject({"utils/greet.py": PASSING_MODULE}, tag="v1.2.3")

        result = repo.run("test_docstrings", env={"RHIZA_DOCTEST_FOLDERS": "utils"})

        assert result.returncode == 0, result.stdout + result.stderr
        assert "1 passed" in result.stdout, result.stdout

    def test_a_folder_that_is_itself_a_package_is_left_to_the_package_walk(
        self, subject: Callable[..., Subject]
    ) -> None:
        """With an ``__init__.py`` at its root the folder is a package, and is walked once."""
        repo = subject(
            {"pkgroot/__init__.py": PASSING_PACKAGE, "pkgroot/greet.py": PASSING_MODULE},
            tag="v1.2.3",
        )

        result = repo.run("test_docstrings", env={"RHIZA_DOCTEST_FOLDERS": "pkgroot"})

        assert result.returncode == 0, result.stdout + result.stderr
        assert "1 passed" in result.stdout, result.stdout


class TestFailureModes:
    """A wrong example fails; a module that cannot be imported warns and is skipped."""

    def test_a_wrong_example_fails_and_the_summary_names_the_module(self, subject: Callable[..., Subject]) -> None:
        """The count in the summary is what makes the failure actionable.

        Asserted against doctest's own report rather than the traceback: the summary is a
        multi-line assertion message, and how much of one a traceback shows depends on the
        pytest version — which would make this test measure the reporter.
        """
        repo = subject(
            {"src/demopkg/__init__.py": PASSING_PACKAGE, "src/demopkg/wrong.py": FAILING_MODULE},
            tag="v1.2.3",
        )

        result = repo.run("test_docstrings")

        assert result.returncode != 0
        assert "in demopkg.wrong" in result.stdout, result.stdout
        assert "Doctest summary" in result.stdout, result.stdout

    def test_an_unimportable_module_in_a_package_warns_rather_than_failing(
        self, subject: Callable[..., Subject]
    ) -> None:
        """Being unable to measure an example is not the same as the example being wrong."""
        repo = subject(
            {
                "src/demopkg/__init__.py": PASSING_PACKAGE,
                "src/demopkg/absent.py": "import no_such_module_anywhere  # noqa: F401\n",
            },
            tag="v1.2.3",
        )

        result = repo.run("test_docstrings")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "Could not import demopkg.absent" in result.stdout, result.stdout

    def test_a_loose_script_that_raises_on_import_warns_rather_than_failing(
        self, subject: Callable[..., Subject]
    ) -> None:
        """A standalone script may run code — or exit — at import time, which is not a defect here."""
        repo = subject(
            {"utils/greet.py": PASSING_MODULE, "utils/boom.py": 'raise SystemExit("scripts run on import")\n'},
            tag="v1.2.3",
        )

        result = repo.run("test_docstrings", env={"RHIZA_DOCTEST_FOLDERS": "utils"})

        assert result.returncode == 0, result.stdout + result.stderr
        assert "Could not import" in result.stdout, result.stdout

    def test_a_package_shadowed_by_an_installed_distribution_is_still_measured(
        self, subject: Callable[..., Subject]
    ) -> None:
        """The folder under test wins over a same-named package already imported.

        ``dotenv`` is the sharpest case available: the check module imports it itself, so
        it is guaranteed to be in ``sys.modules`` before the walk starts. Without the fix
        ``import_module("dotenv")`` returns the *installed* python-dotenv and the subject's
        own package is never opened — the gate reports a pass having measured somebody
        else's code, which is the failure mode that hid this for three releases of
        pytest-rhiza's own ``_bumpversion`` module.
        """
        repo = subject({"src/dotenv/__init__.py": FAILING_MODULE}, tag="v1.2.3")

        result = repo.run("test_docstrings")

        assert result.returncode != 0, result.stdout + result.stderr
        assert "Doctest summary" in result.stdout, result.stdout

    def test_a_package_already_imported_from_the_folder_is_left_alone(self, subject: Callable[..., Subject]) -> None:
        """Eviction must not fire when the cached package is *already* the right one.

        ``alpha`` imports ``beta``, so by the time the walk reaches ``beta`` it is in
        ``sys.modules`` — resolved from the folder under test, which is the case eviction
        must leave alone. Dropping and re-importing it there would be pointless work at
        best, and at worst would re-run import-time code that ``alpha`` is holding a
        reference to. Package discovery is sorted, which is what makes ``alpha`` reliably
        come first.
        """
        repo = subject(
            {
                "src/alpha/__init__.py": IMPORTS_A_SIBLING,
                "src/beta/__init__.py": PASSING_MODULE,
            },
            tag="v1.2.3",
        )

        result = repo.run("test_docstrings")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "1 passed" in result.stdout, result.stdout

    def test_a_source_folder_with_no_examples_at_all_skips(self, subject: Callable[..., Subject]) -> None:
        """Docstrings without examples are not a failure — there is simply nothing to run."""
        repo = subject({"src/demopkg/__init__.py": '"""A package with prose and no examples."""\n'}, tag="v1.2.3")

        result = repo.run("test_docstrings")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "No doctests were found in any module" in result.stdout, result.stdout
