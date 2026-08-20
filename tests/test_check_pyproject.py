"""Subject-repository tests for ``checks/test_pyproject.py``.

Every test here builds a throwaway repository, runs the installed check against it with
the command line a consumer uses, and asserts what the check *said*. The pairing is
deliberate and is what issue #10 asked for: a sound subject proves the check passes
something legitimate, and a broken subject proves it would have caught the defect. A
check that only ever meets a sound subject is indistinguishable from one that asserts
nothing.

The count assertions matter as much as the exit statuses, for the reason
``test_checks.py`` gives: a check module whose collection silently produced nothing
reports success, and "0 passed" is the shape that failure takes.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import only for the fixture's type
    from conftest import Subject

# A manifest that satisfies every assertion in the module. Deliberately spelled out in
# full rather than built from the sound copy by mutation: the broken subjects below are
# each one edit away from this, and that edit is the point of the test.
SOUND_PYPROJECT = """
[project]
name = "demo"
version = "1.2.3"
description = "A demonstration project"
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
authors = [{ name = "Demo Author" }]
classifiers = ["Programming Language :: Python :: 3.11"]

[project.urls]
Homepage = "https://example.com/demo"
Repository = "https://example.com/demo"

[dependency-groups]
test = ["pytest>=8.1"]

[tool.bumpversion]
allow_dirty = false
commit = false
tag = false
"""

# Every test in the module, for the sound case. Asserted as a number so that a check
# lost to a collection change shows up here rather than passing quietly.
TOTAL_CHECKS = 27


class TestSoundSubject:
    """A manifest carrying everything the check asks for passes all of it."""

    def test_a_complete_manifest_passes_every_check(self, subject: Callable[..., Subject]) -> None:
        """The reference case: nothing skipped, nothing failed."""
        repo = subject({"pyproject.toml": SOUND_PYPROJECT, "README.md": "# Demo\n"}, tag="v1.2.3")

        result = repo.run("test_pyproject")

        assert result.returncode == 0, result.stdout + result.stderr
        assert f"{TOTAL_CHECKS} passed" in result.stdout, result.stdout


class TestMissingManifest:
    """With no pyproject.toml the check reports its absence rather than skipping away."""

    def test_a_repository_without_a_manifest_is_reported(self, subject: Callable[..., Subject]) -> None:
        """The existence assertion fires, and the rest skip on the missing file."""
        repo = subject({"README.md": "# Demo\n"}, tag="v1.2.3")

        result = repo.run("test_pyproject")

        assert result.returncode != 0
        assert "pyproject.toml not found at project root" in result.stdout, result.stdout

    def test_a_manifest_without_a_project_table_fails_loudly(self, subject: Callable[..., Subject]) -> None:
        """``[project]`` missing is a failure, not a skip — the fixture calls fail()."""
        repo = subject({"pyproject.toml": '[tool.other]\nkey = "value"\n'}, tag="v1.2.3")

        result = repo.run("test_pyproject")

        assert result.returncode != 0
        assert "missing a [project] table" in result.stdout, result.stdout


class TestRequiredFields:
    """The field assertions have to fail on a manifest that omits them."""

    def test_a_manifest_missing_required_fields_reports_each_one(self, subject: Callable[..., Subject]) -> None:
        """One failure per absent field, so the report names all of them at once."""
        repo = subject({"pyproject.toml": '[project]\nname = "demo"\n'}, tag="v1.2.3")

        result = repo.run("test_pyproject")

        assert result.returncode != 0
        for field in ("version", "description", "readme", "requires-python", "license", "authors"):
            assert f"missing required field '{field}'" in result.stdout, result.stdout

    def test_a_non_semver_version_is_rejected(self, subject: Callable[..., Subject]) -> None:
        """``1.2`` is not MAJOR.MINOR.PATCH, whatever pip makes of it."""
        repo = subject({"pyproject.toml": SOUND_PYPROJECT.replace('version = "1.2.3"', 'version = "1.2"')})

        result = repo.run("test_pyproject")

        assert result.returncode != 0
        assert "does not follow semver" in result.stdout, result.stdout

    def test_blank_strings_do_not_count_as_present(self, subject: Callable[..., Subject]) -> None:
        """A key whose value is whitespace is the same defect as a missing key."""
        manifest = (
            SOUND_PYPROJECT.replace('name = "demo"', 'name = "   "')
            .replace('description = "A demonstration project"', 'description = "  "')
            .replace('requires-python = ">=3.11"', 'requires-python = " "')
            .replace('authors = [{ name = "Demo Author" }]', 'authors = [{ email = "nobody@example.com" }]')
        )
        repo = subject({"pyproject.toml": manifest})

        result = repo.run("test_pyproject")

        assert result.returncode != 0
        assert "must be a non-empty string" in result.stdout, result.stdout
        assert "must have a non-empty 'name'" in result.stdout, result.stdout


class TestOptionalTablesSkipRatherThanFail:
    """Tables the check treats as optional must skip, and say so, not fail."""

    def test_absent_urls_classifiers_and_groups_skip_their_tests(self, subject: Callable[..., Subject]) -> None:
        """Three fixtures skip; the three assertions that *require* the tables still fire.

        The asymmetry is the check's design, not an accident: ``[project.urls]`` being
        absent is reported by ``test_urls_table_present`` while the two entry assertions
        skip, because "no table" and "table without Homepage" are different defects.
        """
        manifest = """
        [project]
        name = "demo"
        version = "1.2.3"
        description = "A demonstration project"
        readme = "README.md"
        requires-python = ">=3.11"
        license = "MIT"
        authors = [{ name = "Demo Author" }]

        [tool.bumpversion]
        commit = false
        tag = false
        """
        repo = subject({"pyproject.toml": manifest}, tag="v1.2.3")

        result = repo.run("test_pyproject")

        assert result.returncode != 0
        assert "missing a [project.urls] table" in result.stdout, result.stdout
        # Homepage + Repository, the Python classifier, and the two dependency-group
        # assertions: five skips behind three absent tables.
        assert "5 skipped" in result.stdout, result.stdout

    def test_empty_url_entries_are_rejected(self, subject: Callable[..., Subject]) -> None:
        """A present-but-blank Homepage is worse than an absent one — it looks configured."""
        manifest = SOUND_PYPROJECT.replace('Homepage = "https://example.com/demo"', 'Homepage = "  "')
        repo = subject({"pyproject.toml": manifest}, tag="v1.2.3")

        result = repo.run("test_pyproject")

        assert result.returncode != 0
        assert "'Homepage' must be non-empty" in result.stdout, result.stdout

    def test_a_deprecated_license_classifier_is_rejected(self, subject: Callable[..., Subject]) -> None:
        """PyPI deprecated the trove classifiers in favour of the SPDX expression."""
        manifest = SOUND_PYPROJECT.replace(
            'classifiers = ["Programming Language :: Python :: 3.11"]',
            'classifiers = ["Programming Language :: Python :: 3.11", "License :: OSI Approved :: MIT License"]',
        )
        repo = subject({"pyproject.toml": manifest}, tag="v1.2.3")

        result = repo.run("test_pyproject")

        assert result.returncode != 0
        assert "must not include any deprecated 'License :: ' entry" in result.stdout, result.stdout

    def test_a_test_group_without_pytest_is_rejected(self, subject: Callable[..., Subject]) -> None:
        """``make test`` has to find pytest somewhere, which is the group's only job."""
        manifest = SOUND_PYPROJECT.replace('test = ["pytest>=8.1"]', 'test = ["coverage"]')
        repo = subject({"pyproject.toml": manifest}, tag="v1.2.3")

        result = repo.run("test_pyproject")

        assert result.returncode != 0
        assert "must list pytest as a dependency" in result.stdout, result.stdout


class TestBumpversionDiscovery:
    """The #1453 family: bump-my-version must find the right config, not fall back."""

    def test_no_config_anywhere_is_reported_with_the_search_list(self, subject: Callable[..., Subject]) -> None:
        """The failure has to name the four filenames, since that list *is* the rule."""
        manifest = SOUND_PYPROJECT.replace("[tool.bumpversion]\nallow_dirty = false\ncommit = false\ntag = false\n", "")
        repo = subject({"pyproject.toml": manifest}, tag="v1.2.3")

        result = repo.run("test_pyproject")

        assert result.returncode != 0
        assert "no bumpversion config was found" in result.stdout, result.stdout
        assert ".bumpversion.toml, .bumpversion.cfg, setup.cfg, pyproject.toml" in result.stdout, result.stdout

    def test_a_leftover_cfg_toml_earns_the_extra_hint(self, subject: Callable[..., Subject]) -> None:
        """``.rhiza/.cfg.toml`` predates the fix and is never discovered; say so."""
        manifest = SOUND_PYPROJECT.replace("[tool.bumpversion]\nallow_dirty = false\ncommit = false\ntag = false\n", "")
        repo = subject(
            {"pyproject.toml": manifest, ".rhiza/.cfg.toml": '[tool.bumpversion]\ncurrent_version = "1.2.3"\n'},
            tag="v1.2.3",
        )

        result = repo.run("test_pyproject")

        assert result.returncode != 0
        assert "A leftover .rhiza/.cfg.toml is present" in result.stdout, result.stdout

    def test_a_toml_config_shadowing_pyproject_is_reported(self, subject: Callable[..., Subject]) -> None:
        """``.bumpversion.toml`` is searched first, which detaches the bump from the manifest."""
        repo = subject(
            {"pyproject.toml": SOUND_PYPROJECT, ".bumpversion.toml": "[tool.bumpversion]\ncommit = false\n"},
            tag="v1.2.3",
        )

        result = repo.run("test_pyproject")

        assert result.returncode != 0
        assert "is searched before pyproject.toml" in result.stdout, result.stdout

    def test_an_ini_config_shadowing_pyproject_is_reported(self, subject: Callable[..., Subject]) -> None:
        """The ``.cfg`` form is detected by text, since it is INI rather than TOML."""
        repo = subject(
            {"pyproject.toml": SOUND_PYPROJECT, ".bumpversion.cfg": "[bumpversion]\ncurrent_version = 1.2.3\n"},
            tag="v1.2.3",
        )

        result = repo.run("test_pyproject")

        assert result.returncode != 0
        assert "'.bumpversion.cfg'" in result.stdout, result.stdout

    def test_an_unparseable_config_counts_as_absent(self, subject: Callable[..., Subject]) -> None:
        """Malformed TOML is not a shadowing config, so the sound manifest still wins.

        The alternative reading — treating a file that cannot be parsed as present —
        would report the *wrong* defect: the repo's problem is the broken file, and the
        bumpversion table in pyproject.toml is genuinely still the one that runs.
        """
        repo = subject(
            {"pyproject.toml": SOUND_PYPROJECT, ".bumpversion.toml": "this is not = = toml\n"},
            tag="v1.2.3",
        )

        result = repo.run("test_pyproject")

        assert result.returncode == 0, result.stdout + result.stderr
        assert f"{TOTAL_CHECKS} passed" in result.stdout, result.stdout

    def test_a_stale_current_version_is_reported(self, subject: Callable[..., Subject]) -> None:
        """``current_version`` duplicates ``[project].version`` and then drifts from it."""
        manifest = SOUND_PYPROJECT.replace(
            "[tool.bumpversion]\nallow_dirty = false",
            '[tool.bumpversion]\ncurrent_version = "1.0.0"\nallow_dirty = false',
        )
        repo = subject({"pyproject.toml": manifest}, tag="v1.2.3")

        result = repo.run("test_pyproject")

        assert result.returncode != 0
        assert "bumping from the stale value cannot match" in result.stdout, result.stdout

    def test_committing_and_tagging_from_the_bump_is_reported(self, subject: Callable[..., Subject]) -> None:
        """``/rhiza:release`` owns both, so a config doing them adds a duplicate tag."""
        manifest = SOUND_PYPROJECT.replace("commit = false\ntag = false", "commit = true\ntag = true")
        repo = subject({"pyproject.toml": manifest}, tag="v1.2.3")

        result = repo.run("test_pyproject")

        assert result.returncode != 0
        assert "must be false: the release flow commits and tags" in result.stdout, result.stdout

    def test_a_dynamic_version_skips_the_bump_assertions(self, subject: Callable[..., Subject]) -> None:
        """With no static version there is no location to bump, so there is nothing to assert.

        The manifest still fails overall — ``version`` is a required field and a dynamic
        one is not declared here — but the three bump assertions skip with a reason
        rather than judging a version that does not exist yet.
        """
        manifest = SOUND_PYPROJECT.replace('version = "1.2.3"', 'dynamic = ["version"]')
        repo = subject({"pyproject.toml": manifest}, tag="v1.2.3")

        result = repo.run("test_pyproject")

        assert "dynamic \u2014 no static location to bump" in result.stdout, result.stdout


class TestTagAgreement:
    """The manifest version and the newest tag are one fact recorded twice."""

    def test_a_version_disagreeing_with_the_tag_is_reported(self, subject: Callable[..., Subject]) -> None:
        """v1.2.3 against 9.9.9 is drift someone introduced by hand."""
        manifest = SOUND_PYPROJECT.replace('version = "1.2.3"', 'version = "9.9.9"')
        repo = subject({"pyproject.toml": manifest}, tag="v1.2.3")

        result = repo.run("test_pyproject")

        assert result.returncode != 0
        assert "does not match" in result.stdout, result.stdout

    def test_an_untagged_repository_skips_the_comparison(self, subject: Callable[..., Subject]) -> None:
        """A project that has never released must not fail the version checks."""
        repo = subject({"pyproject.toml": SOUND_PYPROJECT})

        result = repo.run("test_pyproject")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "No version tags found" in result.stdout, result.stdout



class TestPackageVersionConsistency:
    """``pytest_rhiza.__version__`` must stay in step with ``[project].version``."""

    def test_dunder_version_matches_pyproject(self) -> None:
        """``__version__`` must equal the version declared in pyproject.toml.

        bump-my-version updates both through the ``[[tool.bumpversion.files]]`` entry
        in pyproject.toml.  If the two drift the entry is missing or misconfigured.
        """
        import tomllib

        import pytest_rhiza

        root = Path(__file__).parent.parent
        with (root / "pyproject.toml").open("rb") as fh:
            pyproject_version = tomllib.load(fh)["project"]["version"]

        assert pytest_rhiza.__version__ == pyproject_version, (
            f"pytest_rhiza.__version__ {pytest_rhiza.__version__!r} does not match "
            f"[project].version {pyproject_version!r} in pyproject.toml. "
            "Ensure [[tool.bumpversion.files]] targets src/pytest_rhiza/__init__.py."
        )
