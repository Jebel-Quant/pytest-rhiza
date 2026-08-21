"""Tests for pyproject.toml structure and required fields.

Ported from ``jebel-quant/rhiza`` at 89f9298, where bundle ``python-core`` synced it
to ``.rhiza/tests/test_pyproject.py``. It now arrives installed, and is collected by name:
``pytest --pyargs pytest_rhiza.checks.test_pyproject``.

Validates that pyproject.toml:
- is syntactically valid TOML
- contains all required [project] fields
- declares a semver-compatible version
- specifies a minimum Python version via requires-python
- lists at least one named author
- provides [project.urls] with Homepage and Repository
- includes at least one Python version classifier
- declares a [dependency-groups] test group containing pytest
- carries a [tool.bumpversion] table bump-my-version can actually discover
- version matches the latest git tag (vX.Y.Z → X.Y.Z)

Reachability of that tag lives in ``test_release_tags.py``, shipped by ``core``: the
invariant holds for every language layer, not just this one.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from pytest_rhiza._bumpversion import (
    DISCOVERABLE_CONFIGS,
    assert_release_flow_owns_the_commit_and_the_tag,
    discovered_configs,
    legacy_config_hint,
    shadowing_configs,
)
from pytest_rhiza._toml import TomlTable
from pytest_rhiza._versions import assert_declared_version_not_behind_tag

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+")
_REQUIRED_PROJECT_FIELDS = ("name", "version", "description", "readme", "requires-python", "license", "authors")


@pytest.fixture(scope="module")
def pyproject(root: Path) -> TomlTable:
    """Load and return pyproject.toml as a parsed dict."""
    path = root / "pyproject.toml"
    if not path.exists():
        pytest.skip("pyproject.toml not found")
    with path.open("rb") as f:
        return tomllib.load(f)


@pytest.fixture(scope="module")
def project(pyproject: TomlTable) -> TomlTable:
    """Return the [project] table from pyproject.toml."""
    table = pyproject.get("project")
    if not isinstance(table, dict):
        pytest.fail("pyproject.toml is missing a [project] table")
    return table


class TestPyprojectToml:
    """Tests for basic pyproject.toml existence and validity."""

    def test_pyproject_toml_exists(self, root: Path) -> None:
        """pyproject.toml must exist at the project root."""
        assert (root / "pyproject.toml").is_file(), "pyproject.toml not found at project root"

    def test_pyproject_toml_is_valid_toml(self, root: Path) -> None:
        """pyproject.toml must be syntactically valid TOML."""
        with (root / "pyproject.toml").open("rb") as f:
            data = tomllib.load(f)
        assert isinstance(data, dict), "Parsed pyproject.toml must be a TOML table"

    def test_project_table_present(self, pyproject: TomlTable) -> None:
        """pyproject.toml must contain a [project] table."""
        assert "project" in pyproject, "pyproject.toml is missing a [project] table"
        assert isinstance(pyproject["project"], dict), "[project] must be a TOML table"


class TestProjectFields:
    """Tests for required fields within the [project] table."""

    @pytest.mark.parametrize("field", _REQUIRED_PROJECT_FIELDS)
    def test_required_field_present(self, project: TomlTable, field: str) -> None:
        """Each required [project] field must be present."""
        assert field in project, f"[project] is missing required field '{field}'"

    def test_name_is_non_empty_string(self, project: TomlTable) -> None:
        """[project].name must be a non-empty string."""
        name = project.get("name", "")
        assert isinstance(name, str), "[project].name must be a string"
        assert name.strip(), "[project].name must be a non-empty string"

    def test_version_follows_semver(self, project: TomlTable) -> None:
        """[project].version must follow semver (MAJOR.MINOR.PATCH)."""
        version = project.get("version", "")
        assert _SEMVER_RE.match(str(version)), (
            f"[project].version {version!r} does not follow semver (expected MAJOR.MINOR.PATCH)"
        )

    def test_requires_python_is_set(self, project: TomlTable) -> None:
        """[project].requires-python must be set to a non-empty constraint."""
        rp = project.get("requires-python", "")
        assert isinstance(rp, str), "[project].requires-python must be a string"
        assert rp.strip(), "[project].requires-python must be a non-empty version constraint"

    def test_authors_have_names(self, project: TomlTable) -> None:
        """[project].authors must contain at least one entry with a non-empty 'name'."""
        authors = project.get("authors", [])
        assert isinstance(authors, list), "[project].authors must be a list"
        assert len(authors) >= 1, "[project].authors must list at least one author"
        named = [a for a in authors if isinstance(a, dict) and a.get("name", "").strip()]
        assert len(named) >= 1, "At least one entry in [project].authors must have a non-empty 'name'"

    def test_description_is_non_empty_string(self, project: TomlTable) -> None:
        """[project].description must be a non-empty string."""
        desc = project.get("description", "")
        assert isinstance(desc, str), "[project].description must be a string"
        assert desc.strip(), "[project].description must be a non-empty string"


class TestProjectUrls:
    """Tests for [project.urls] — Homepage and Repository links."""

    @pytest.fixture
    def urls(self, project: TomlTable) -> TomlTable:
        """Return the [project.urls] table."""
        table = project.get("urls")
        if not isinstance(table, dict):
            pytest.skip("[project.urls] not present")
        return table

    def test_urls_table_present(self, project: TomlTable) -> None:
        """[project.urls] must be present."""
        assert "urls" in project, "pyproject.toml is missing a [project.urls] table"

    def test_homepage_configured(self, urls: TomlTable) -> None:
        """[project.urls] must include a Homepage entry."""
        assert "Homepage" in urls, "[project.urls] is missing a 'Homepage' entry"
        assert urls["Homepage"].strip(), "[project.urls] 'Homepage' must be non-empty"

    def test_repository_configured(self, urls: TomlTable) -> None:
        """[project.urls] must include a Repository entry."""
        assert "Repository" in urls, "[project.urls] is missing a 'Repository' entry"
        assert urls["Repository"].strip(), "[project.urls] 'Repository' must be non-empty"


class TestProjectClassifiers:
    """Tests for [project].classifiers — Python version entries."""

    @pytest.fixture
    def classifiers(self, project: TomlTable) -> list[str]:
        """Return the classifiers list.

        Entries are coerced with ``str`` rather than trusted: the assertions below match
        them against regexes and prefixes, so a manifest declaring a non-string classifier
        would otherwise fail inside ``re.match`` with a ``TypeError`` instead of a verdict.
        """
        declared = project.get("classifiers", [])
        if not declared:
            pytest.skip("No classifiers declared in [project]")
        return [str(entry) for entry in declared]

    def test_python_version_classifier_present(self, classifiers: list[str]) -> None:
        """At least one 'Programming Language :: Python :: 3.X' classifier must be present."""
        python_classifiers = [c for c in classifiers if re.match(r"Programming Language :: Python :: 3\.\d+", c)]
        assert len(python_classifiers) >= 1, (
            "classifiers must include at least one 'Programming Language :: Python :: 3.X' entry"
        )

    def test_no_license_classifier(self, project: TomlTable) -> None:
        """No deprecated 'License :: ' classifier may be present.

        PyPI has deprecated the ``License ::`` trove classifiers in favor of the SPDX
        ``license`` expression field, so the shipped pyproject must not declare one.
        """
        classifiers = project.get("classifiers", [])
        license_classifiers = [c for c in classifiers if c.startswith("License ::")]
        assert not license_classifiers, (
            f"classifiers must not include any deprecated 'License :: ' entry; found {license_classifiers}"
        )


class TestDependencyGroups:
    """Tests for [dependency-groups] — ensures required groups are declared.

    Only ``test`` is required, and only because ``make test`` has to have somewhere to
    find pytest. There was a ``test_lint_group_present`` here until #1484, and it is
    worth saying why it went: rhiza provisions every linter through prek/uvx, so the
    group it demanded had nothing legitimate to hold, and the mother repo satisfied it
    with a literal ``lint = []``. A required-group check that the reference
    implementation can only pass by declaring an empty list is testing a convention
    rather than a working project, so a project may still declare ``lint`` — nothing
    reads it.
    """

    @pytest.fixture
    def dependency_groups(self, pyproject: TomlTable) -> TomlTable:
        """Return the [dependency-groups] table."""
        dg = pyproject.get("dependency-groups")
        if not isinstance(dg, dict):
            pytest.skip("[dependency-groups] not present")
        return dg

    def test_test_group_present(self, dependency_groups: TomlTable) -> None:
        """A 'test' dependency group must be declared."""
        assert "test" in dependency_groups, "[dependency-groups] must include a 'test' group"

    def test_test_group_includes_pytest(self, dependency_groups: TomlTable) -> None:
        """The 'test' dependency group must include pytest."""
        test_deps = dependency_groups.get("test", [])
        assert any("pytest" in str(dep).lower() for dep in test_deps), (
            "[dependency-groups.test] must list pytest as a dependency"
        )


class TestBumpversionConfigIsDiscoverable:
    """The release flow must find a version config, not silently invent one (#1453).

    bump-my-version searches four filenames and stops. When it finds none it does
    **not** fail — it falls back to ``git describe`` and reports the last reachable
    tag as the current version. Release tooling then computes bump candidates from
    that number rather than the project's, which is how a repo at 0.7.0 with a
    newest reachable tag of v0.6.4 gets offered "minor → v0.7.0", a version it has
    already published.

    Once a ``[tool.bumpversion]`` table exists in pyproject.toml, bump-my-version
    reads and rewrites PEP 621 ``[project].version`` natively, so the minimum
    workable config is three lines and duplicates the version string nowhere::

        [tool.bumpversion]
        allow_dirty = false
        # /rhiza:release commits and tags itself so the changelog lands in the
        # bump commit.
        commit = false
        tag = false

    Add a ``[[tool.bumpversion.files]]`` entry per *additional* location (a plugin
    manifest, a self-referencing CI stub pin) — never for ``[project].version``
    itself.
    """

    @pytest.fixture
    def declared_version(self, project: TomlTable) -> str:
        """The statically declared project version, or skip when it is dynamic."""
        version = project.get("version")
        if not isinstance(version, str):
            pytest.skip("[project].version is dynamic — no static location to bump")
        return version

    def test_a_discoverable_config_exists(self, root: Path, pyproject: TomlTable, declared_version: str) -> None:
        """A bumpversion section must live in a file bump-my-version actually reads."""
        assert discovered_configs(root), (
            f"pyproject.toml declares version {declared_version!r} but no bumpversion config "
            f"was found in any file bump-my-version searches ({', '.join(DISCOVERABLE_CONFIGS)}). "
            f"It will silently fall back to `git describe`, so a release can be cut at a version "
            f"that already exists. Add a [tool.bumpversion] table to pyproject.toml."
            f"{legacy_config_hint(root)}"
        )

    def test_pyproject_is_the_config_that_wins(self, root: Path, declared_version: str) -> None:
        """No earlier-searched file may shadow pyproject.toml's table.

        Search order is significant: a ``.bumpversion.toml`` beats pyproject.toml and
        takes ``[project].version`` out of the picture, so the two version numbers can
        then drift apart unnoticed. A Python project keeps its version in one place.
        """
        shadowing = shadowing_configs(root, "pyproject.toml")
        assert not shadowing, (
            f"{shadowing} is searched before pyproject.toml and would shadow its "
            f"[tool.bumpversion] table, detaching the bump from [project].version "
            f"({declared_version!r})"
        )

    def test_config_does_not_duplicate_the_version(self, pyproject: TomlTable, declared_version: str) -> None:
        """``current_version`` is redundant in pyproject.toml, and drifts once stale."""
        section = pyproject.get("tool", {}).get("bumpversion")
        if not isinstance(section, dict):
            pytest.skip("no [tool.bumpversion] table — reported by test_a_discoverable_config_exists")
        declared_in_config = section.get("current_version")
        assert declared_in_config in (None, declared_version), (
            f"[tool.bumpversion].current_version is {declared_in_config!r} but "
            f"[project].version is {declared_version!r}; bumping from the stale value cannot "
            f"match the version in the file. Drop current_version — bump-my-version reads "
            f"[project].version natively."
        )

    def test_the_release_flow_owns_the_commit_and_the_tag(self, pyproject: TomlTable) -> None:
        """``/rhiza:release`` folds the changelog into the bump commit and tags it itself."""
        section = pyproject.get("tool", {}).get("bumpversion")
        if not isinstance(section, dict):
            pytest.skip("no [tool.bumpversion] table — reported by test_a_discoverable_config_exists")
        assert_release_flow_owns_the_commit_and_the_tag(section)


class TestGitTagVersion:
    """Tests for harmony between the latest git tag and pyproject.toml version.

    Reachability of that tag is asserted by ``test_release_tags.py``, which ``core``
    ships: the invariant is about git rather than about Python, and all three language
    layers need it.
    """

    def test_pyproject_version_is_not_behind_the_latest_tag(self, latest_tag: str, project: TomlTable) -> None:
        """[project].version must be the newest vX.Y.Z tag, or ahead of it.

        Ahead is a release in flight; behind is drift. See
        :mod:`pytest_rhiza._versions` for why this is not an equality check.
        """
        assert_declared_version_not_behind_tag(
            latest_tag,
            str(project.get("version", "")),
            location="[project].version in pyproject.toml",
            consequence=(
                "bump-my-version reads [project].version natively, so the next release would "
                "bump from a number older than what is already published."
            ),
        )
