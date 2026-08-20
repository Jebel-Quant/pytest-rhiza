"""Tests for Cargo.toml structure and the release config that rewrites it.

Ported from ``jebel-quant/rhiza`` at 89f9298, where bundle ``rust-core`` synced it
to ``.rhiza/tests/test_cargo_toml.py``. It now arrives installed, and is collected by name:
``pytest --pyargs pytest_rhiza.checks.test_cargo_toml``.

The Rust counterpart of ``test_pyproject.py``. Written in Python and run through uv by
``make rhiza-test`` rather than as a ``#[test]``, for the same reason the rest of the
suite is: it validates *configuration*, and the release flow that reads it is Python
tooling. ``uv`` lives in ``core`` precisely so it is available whatever the project's
language.

Validates that Cargo.toml:
- is syntactically valid TOML
- contains the [package] fields cargo publish requires
- declares a semver version
- carries a license or license-file, which deny.toml's allow-list checks against
- version matches the latest git tag (vX.Y.Z → X.Y.Z)

…and that the shipped .bumpversion.toml can still write the version back:
- it is the config bump-my-version discovers, and nothing shadows it
- it points at Cargo.toml's [package] table, anchored
- it leaves the commit and the tag to /rhiza:release
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from pytest_rhiza._bumpversion import SyncedBumpversionConfig

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+")

# cargo tolerates more than this, but a crate that cannot be published is a crate whose
# release flow breaks at the last step rather than the first.
_REQUIRED_PACKAGE_FIELDS = ("name", "version", "edition", "description")


@pytest.fixture(scope="module")
def cargo_toml(root: Path) -> dict:
    """Load and return Cargo.toml as a parsed dict."""
    path = root / "Cargo.toml"
    if not path.exists():
        pytest.skip("Cargo.toml not found")
    with path.open("rb") as handle:
        return tomllib.load(handle)


@pytest.fixture(scope="module")
def package(cargo_toml: dict) -> dict:
    """Return the [package] table, skipping on a virtual workspace manifest.

    A workspace root legitimately has no ``[package]`` — it carries only
    ``[workspace]`` — and its members hold the versions. Nothing here applies.
    """
    table = cargo_toml.get("package")
    if not isinstance(table, dict):
        if "workspace" in cargo_toml:
            pytest.skip("virtual workspace manifest — the members carry the versions")
        pytest.fail("Cargo.toml is missing a [package] table")
    return table


class TestCargoToml:
    """Tests for basic Cargo.toml existence and validity."""

    def test_cargo_toml_exists(self, root: Path) -> None:
        """Cargo.toml must exist at the project root."""
        assert (root / "Cargo.toml").is_file(), "Cargo.toml not found at project root"

    def test_cargo_toml_is_valid_toml(self, root: Path) -> None:
        """Cargo.toml must be syntactically valid TOML."""
        with (root / "Cargo.toml").open("rb") as handle:
            data = tomllib.load(handle)
        assert isinstance(data, dict), "Parsed Cargo.toml must be a TOML table"


class TestPackageFields:
    """Tests for required fields within the [package] table."""

    @pytest.mark.parametrize("field", _REQUIRED_PACKAGE_FIELDS)
    def test_required_field_present(self, package: dict, field: str) -> None:
        """Each required [package] field must be present."""
        assert field in package, f"[package] is missing required field '{field}'"

    def test_name_is_non_empty_string(self, package: dict) -> None:
        """[package].name must be a non-empty string."""
        name = package.get("name", "")
        assert isinstance(name, str), "[package].name must be a string"
        assert name.strip(), "[package].name must be a non-empty string"

    def test_version_follows_semver(self, package: dict) -> None:
        """[package].version must follow semver (MAJOR.MINOR.PATCH).

        Not merely a convention here: ``.bumpversion.toml``'s ``parse`` regex and its
        ``tag_name = "v{new_version}"`` both assume this shape, and a version cargo
        accepts but that regex does not would fail the release rather than the build.
        """
        version = package.get("version", "")
        if isinstance(version, dict):
            pytest.skip("[package].version is inherited from the workspace")
        assert _SEMVER_RE.match(str(version)), (
            f"[package].version {version!r} does not follow semver (expected MAJOR.MINOR.PATCH)"
        )

    def test_description_is_non_empty_string(self, package: dict) -> None:
        """[package].description must be a non-empty string."""
        desc = package.get("description", "")
        if isinstance(desc, dict):
            pytest.skip("[package].description is inherited from the workspace")
        assert isinstance(desc, str), "[package].description must be a string"
        assert desc.strip(), "[package].description must be a non-empty string"

    def test_a_license_is_declared(self, package: dict) -> None:
        """[package] must declare `license` or `license-file`.

        ``make license`` is ``cargo deny check licenses`` and deny.toml is an
        allow-list, so a crate with no licence of its own fails that gate on itself
        rather than on a dependency.
        """
        declared = [key for key in ("license", "license-file") if package.get(key)]
        assert declared, (
            "[package] declares neither 'license' nor 'license-file'; `make license` runs "
            "cargo-deny against an allow-list and fails a crate that does not state its own"
        )


class TestBumpversionConfig(SyncedBumpversionConfig):
    """The release flow must find a version config, not silently invent one (#1453).

    bump-my-version searches four filenames and stops. Finding none it does **not**
    fail — it falls back to ``git describe`` and reports the last reachable tag as the
    current version, so a release can be cut at a version that already exists. A Rust
    project owns none of those four filenames natively, so ``rust-core`` ships a root
    ``.bumpversion.toml``; these tests assert it is still the file that wins and still
    points where the version actually lives.

    The assertions themselves are :class:`~pytest_rhiza._bumpversion.SyncedBumpversionConfig`,
    shared with the Go layer (#14). What is Rust-specific is declared below, and the
    ``[dependencies]`` hazard is the reason ``search_is_regex`` is True here and not
    there: a crate's own version and a dependency pin are both spelled
    ``version = "x.y.z"``, so the pattern has to be anchored to the ``[package]`` table,
    and a literal search cannot express that.
    """

    version_file = "Cargo.toml"
    search_anchor = "[package]"
    search_is_regex = True
    bundle = "rust-core"
    missing_config_consequence = ", so a release can be cut at a version that already exists"
    untargeted_consequence = "a bump would leave [package].version untouched"
    unanchored_complaint = (
        "does not mention the [package] table; an unanchored version pattern also rewrites a "
        "[dependencies] entry that happens to share the crate's number"
    )


class TestGitTagVersion:
    """Harmony between the latest git tag and the crate version.

    Reachability of that tag is asserted by ``test_release_tags.py``, which ``core``
    ships for every language layer.
    """

    def test_latest_tag_matches_cargo_version(self, latest_tag: str, package: dict) -> None:
        """The latest git tag (vX.Y.Z) must match [package].version.

        This is the invariant ``.bumpversion.toml`` relies on rather than a style
        preference. With no ``current_version`` key, bump-my-version reads the current
        version from the newest tag and then searches Cargo.toml for it; if the two
        disagree the next release fails with "did not find current version" — loudly,
        but only at release time, which is the worst moment to find out.
        """
        version = package.get("version")
        if isinstance(version, dict):
            pytest.skip("[package].version is inherited from the workspace")
        assert latest_tag.lstrip("v") == str(version), (
            f"Latest git tag {latest_tag!r} does not match [package].version {version!r}. "
            f"bump-my-version derives the current version from the tag and then looks for it "
            f"in Cargo.toml, so the next release would fail to find it."
        )
