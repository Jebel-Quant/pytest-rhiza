"""Tests for pyproject.toml structure and required fields.

Ported from ``jebel-quant/rhiza`` at 89f9298, where bundle ``python-core`` synced it
to ``.rhiza/tests/test_pyproject.py``. It now arrives installed, and is collected by name:
``pytest --pyargs pytest_rhiza.checks.test_pyproject``.

Validates that pyproject.toml:
- is syntactically valid TOML
- contains all required [project] fields
- declares a version, statically or as ``dynamic = ["version"]``
- declares a semver-compatible version, when that version is static
- specifies a minimum Python version via requires-python
- lists at least one named author
- provides [project.urls] with Homepage and Repository
- includes at least one Python version classifier
- declares a [dependency-groups] test group containing pytest
- carries a [tool.bumpversion] table bump-my-version can actually discover
- version matches the latest git tag (vX.Y.Z → X.Y.Z)

Reachability of that tag lives in ``test_release_tags.py``, shipped by ``core``: the
invariant holds for every language layer, not just this one.

**Dynamic versions.** A project may derive ``[project].version`` from its VCS instead of
declaring it -- ``dynamic = ["version"]`` plus a backend plugin such as hatch-vcs. Six
assertions here are about a *written* version, and each of them skips with a reason on
such a project rather than judging a string that does not exist: the semver shape, the
three bump-config assertions, and the two tag-agreement ones.

That is not a gap in coverage, it is the same coverage arriving for free. Every defect
those six catch -- a version behind the newest tag, a bump computed from `git describe`
because no config was discoverable, a release stalled between its bump and its tag -- is
a disagreement between a number in a file and a number in git. A version *derived* from
git cannot disagree with git. What the six assert is that a project which keeps the two
in step by hand has actually done so.

One defect does not go away, and it is worth knowing because it is silent: a VCS-derived
version resolves to something like ``0.1.dev1+g1234567`` in a clone with no tags, so a
release built from a shallow checkout publishes at a version nobody asked for. That is a
property of the checkout rather than of the manifest, so it is not assertable from here --
fetch the full history (``fetch-depth: 0``) in any job that builds a distribution.
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
from pytest_rhiza._release_state import assert_release_not_stalled
from pytest_rhiza._toml import TomlTable
from pytest_rhiza._versions import assert_declared_version_not_behind_tag

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+")
# ``version`` is deliberately absent: it may be declared statically *or* derived from the
# VCS, and ``test_a_version_is_declared`` states that either-or rather than this list
# demanding the key. Everything here is required unconditionally.
_REQUIRED_PROJECT_FIELDS = ("name", "description", "readme", "requires-python", "license", "authors")


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


def _version_is_dynamic(project: TomlTable) -> bool:
    """Report whether the project derives its version rather than declaring it.

    PEP 621's rule is that a key the backend supplies must be named in ``dynamic`` and
    must *not* also be written in the table. Read the declaration rather than inferring
    from an absent ``version``, so that a manifest which simply forgot the field is
    reported by :meth:`TestProjectFields.test_a_version_is_declared` instead of being
    silently excused from six assertions.

    Args:
        project: The parsed ``[project]`` table.

    Returns:
        True when ``version`` is listed in ``[project].dynamic``.

    Examples:
        >>> _version_is_dynamic({"dynamic": ["version"]})
        True
        >>> _version_is_dynamic({"version": "1.2.3"})
        False
        >>> _version_is_dynamic({})
        False
    """
    dynamic = project.get("dynamic")
    return isinstance(dynamic, list) and "version" in dynamic


@pytest.fixture(scope="module")
def static_version(project: TomlTable) -> str:
    """The version as written in the manifest, or skip when it is derived from the VCS.

    One fixture for every assertion that needs a written version, so that a dynamic
    project reports the same reason six times rather than six different ones -- and so
    that adding such an assertion cannot forget to handle the dynamic case.
    """
    if _version_is_dynamic(project):
        pytest.skip("[project].version is dynamic — no written version to compare against git")
    version = project.get("version")
    if not isinstance(version, str):
        pytest.skip("[project].version is dynamic — no written version to compare against git")
    return version


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

    def test_a_version_is_declared(self, project: TomlTable) -> None:
        """The project must say what its version is, in one of the two PEP 621 ways.

        Either ``version = "1.2.3"`` or ``dynamic = ["version"]`` with a backend that
        supplies it. Neither is an error, and it is not a cosmetic one: a wheel cannot be
        built without a version, so this fails fast on a manifest that would otherwise
        fail at build time with a message about metadata rather than about the omission.

        Whether the backend can actually produce a dynamic version is the backend's own
        error, raised loudly at build time. This check does not second-guess it, because
        the list of plugins that can is open-ended and a stale allowlist here would fail
        a project that builds perfectly well.
        """
        static = isinstance(project.get("version"), str)
        assert static or _version_is_dynamic(project), (
            '[project] declares no version. Write one (`version = "1.2.3"`), or derive it '
            'from the VCS by listing it in `dynamic` (`dynamic = ["version"]`) with a '
            "backend plugin such as hatch-vcs."
        )
        assert not (static and _version_is_dynamic(project)), (
            "[project] both writes `version` and lists it in `dynamic`, which PEP 621 "
            "forbids: the two can disagree and nothing says which wins. Keep whichever is "
            "the source of truth and delete the other."
        )

    def test_version_follows_semver(self, static_version: str) -> None:
        """[project].version must follow semver (MAJOR.MINOR.PATCH).

        Skipped on a dynamic version: the shape is then whatever the backend derives from
        the tag, and a tag's own shape is asserted by ``test_release_tags.py``.
        """
        assert _SEMVER_RE.match(static_version), (
            f"[project].version {static_version!r} does not follow semver (expected MAJOR.MINOR.PATCH)"
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

    def test_a_discoverable_config_exists(self, root: Path, pyproject: TomlTable, static_version: str) -> None:
        """A bumpversion section must live in a file bump-my-version actually reads."""
        assert discovered_configs(root), (
            f"pyproject.toml declares version {static_version!r} but no bumpversion config "
            f"was found in any file bump-my-version searches ({', '.join(DISCOVERABLE_CONFIGS)}). "
            f"It will silently fall back to `git describe`, so a release can be cut at a version "
            f"that already exists. Add a [tool.bumpversion] table to pyproject.toml."
            f"{legacy_config_hint(root)}"
        )

    def test_pyproject_is_the_config_that_wins(self, root: Path, static_version: str) -> None:
        """No earlier-searched file may shadow pyproject.toml's table.

        Search order is significant: a ``.bumpversion.toml`` beats pyproject.toml and
        takes ``[project].version`` out of the picture, so the two version numbers can
        then drift apart unnoticed. A Python project keeps its version in one place.
        """
        shadowing = shadowing_configs(root, "pyproject.toml")
        assert not shadowing, (
            f"{shadowing} is searched before pyproject.toml and would shadow its "
            f"[tool.bumpversion] table, detaching the bump from [project].version "
            f"({static_version!r})"
        )

    def test_config_does_not_duplicate_the_version(self, pyproject: TomlTable, static_version: str) -> None:
        """``current_version`` is redundant in pyproject.toml, and drifts once stale."""
        section = pyproject.get("tool", {}).get("bumpversion")
        if not isinstance(section, dict):
            pytest.skip("no [tool.bumpversion] table — reported by test_a_discoverable_config_exists")
        declared_in_config = section.get("current_version")
        assert declared_in_config in (None, static_version), (
            f"[tool.bumpversion].current_version is {declared_in_config!r} but "
            f"[project].version is {static_version!r}; bumping from the stale value cannot "
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

    def test_pyproject_version_is_not_behind_the_latest_tag(self, latest_tag: str, static_version: str) -> None:
        """[project].version must be the newest vX.Y.Z tag, or ahead of it.

        Ahead is a release in flight; behind is drift. See
        :mod:`pytest_rhiza._versions` for why this is not an equality check.

        Skipped on a dynamic version, where the two cannot disagree: the number *is*
        derived from the tag, so there is no second copy to drift.
        """
        assert_declared_version_not_behind_tag(
            latest_tag,
            static_version,
            location="[project].version in pyproject.toml",
            consequence=(
                "bump-my-version reads [project].version natively, so the next release would "
                "bump from a number older than what is already published."
            ),
        )

    def test_the_bump_that_produced_this_version_was_tagged(
        self, latest_tag: str, static_version: str, root: Path
    ) -> None:
        """The bump that produced this version must have been tagged (#85).

        ``assert_declared_version_not_behind_tag`` permits the manifest to lead the newest
        tag, because that is what a release in flight looks like. Nothing bounded how long
        it may lead for, so a release whose phase B never ran stayed green indefinitely
        while declaring a version that was never tagged and never published. See
        :mod:`pytest_rhiza._release_state`.

        Skipped on a dynamic version, and this is the assertion that dynamic versioning
        makes unnecessary rather than merely unassertable: there is no bump to leave
        untagged. The version does not move until the tag does.
        """
        assert_release_not_stalled(
            root,
            latest_tag,
            static_version,
            manifest="pyproject.toml",
        )
