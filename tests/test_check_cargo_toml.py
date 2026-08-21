"""Subject-repository tests for ``checks/test_cargo_toml.py``.

This module and ``test_check_go_module.py`` are the ones issue #10 called out as
mattering most: the Rust and Go checks can only ever fire inside a Rust or Go consumer
repository, so before these tests a regression in them shipped silently and surfaced on
somebody else's CI. Nothing in this repository is a crate, which is exactly why the
subject has to be built rather than found.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import only for the fixture's type
    from conftest import Subject

SOUND_CARGO = """
[package]
name = "demo"
version = "1.2.3"
edition = "2021"
description = "A demonstration crate"
license = "MIT"

[dependencies]
serde = "1.2.3"
"""

# Anchored to the [package] table, which is the property
# ``test_the_cargo_toml_pattern_is_anchored_to_the_package_table`` exists to defend: the
# [dependencies] entry above shares the crate's version number on purpose.
SOUND_BUMPVERSION = """
[tool.bumpversion]
allow_dirty = false
commit = false
tag = false
tag_name = "v{new_version}"

[[tool.bumpversion.files]]
filename = "Cargo.toml"
regex = true
search = '\\[package\\]([\\s\\S]*?)version = "{current_version}"'
replace = '[package]\\1version = "{new_version}"'
"""

TOTAL_CHECKS = 17


def _crate(**extra: str) -> dict[str, str]:
    """Return the file map for a sound crate, with any extra files merged in.

    Args:
        extra: Additional repository-relative files, overriding the sound ones by name.

    Returns:
        The file map to hand to the ``subject`` factory.
    """
    return {"Cargo.toml": SOUND_CARGO, ".bumpversion.toml": SOUND_BUMPVERSION, **extra}


class TestSoundSubject:
    """A crate carrying everything the check asks for passes all of it."""

    def test_a_complete_crate_passes_every_check(self, subject: Callable[..., Subject]) -> None:
        """The reference case, and the only test here that proves the check can pass."""
        repo = subject(_crate(), tag="v1.2.3")

        result = repo.run("test_cargo_toml")

        assert result.returncode == 0, result.stdout + result.stderr
        assert f"{TOTAL_CHECKS} passed" in result.stdout, result.stdout


class TestManifestShape:
    """Cargo.toml's presence, parseability, and the fields cargo publish requires."""

    def test_a_repository_without_a_manifest_is_reported(self, subject: Callable[..., Subject]) -> None:
        """No Cargo.toml: the existence assertion fires and the rest skip."""
        repo = subject({".bumpversion.toml": SOUND_BUMPVERSION}, tag="v1.2.3")

        result = repo.run("test_cargo_toml")

        assert result.returncode != 0
        assert "Cargo.toml not found at project root" in result.stdout, result.stdout

    def test_a_virtual_workspace_manifest_skips_the_package_checks(self, subject: Callable[..., Subject]) -> None:
        """A workspace root legitimately has no ``[package]`` — its members hold versions."""
        repo = subject(_crate(**{"Cargo.toml": '[workspace]\nmembers = ["crates/*"]\n'}), tag="v1.2.3")

        result = repo.run("test_cargo_toml")

        assert "virtual workspace manifest" in result.stdout, result.stdout

    def test_a_manifest_that_is_neither_package_nor_workspace_fails(self, subject: Callable[..., Subject]) -> None:
        """Without either table there is nothing legitimate to skip for."""
        repo = subject(_crate(**{"Cargo.toml": '[dependencies]\nserde = "1"\n'}), tag="v1.2.3")

        result = repo.run("test_cargo_toml")

        assert result.returncode != 0
        assert "Cargo.toml is missing a [package] table" in result.stdout, result.stdout

    def test_missing_package_fields_are_each_reported(self, subject: Callable[..., Subject]) -> None:
        """One failure per absent field: name, version, edition, description."""
        repo = subject(_crate(**{"Cargo.toml": '[package]\nlicense = "MIT"\n'}), tag="v1.2.3")

        result = repo.run("test_cargo_toml")

        assert result.returncode != 0
        for field in ("name", "version", "edition", "description"):
            assert f"missing required field '{field}'" in result.stdout, result.stdout

    def test_a_blank_name_or_description_is_rejected(self, subject: Callable[..., Subject]) -> None:
        """Present-but-whitespace is the same defect as absent, and looks configured."""
        manifest = SOUND_CARGO.replace('name = "demo"', 'name = " "').replace(
            'description = "A demonstration crate"', 'description = "  "'
        )
        repo = subject(_crate(**{"Cargo.toml": manifest}), tag="v1.2.3")

        result = repo.run("test_cargo_toml")

        assert result.returncode != 0
        assert "[package].name must be a non-empty string" in result.stdout, result.stdout
        assert "[package].description must be a non-empty string" in result.stdout, result.stdout

    def test_a_non_semver_version_is_rejected(self, subject: Callable[..., Subject]) -> None:
        """``.bumpversion.toml``'s parse regex assumes MAJOR.MINOR.PATCH, so cargo's laxity is not enough."""
        manifest = SOUND_CARGO.replace('version = "1.2.3"', 'version = "1.2"')
        repo = subject(_crate(**{"Cargo.toml": manifest}))

        result = repo.run("test_cargo_toml")

        assert result.returncode != 0
        assert "does not follow semver" in result.stdout, result.stdout

    def test_workspace_inherited_fields_skip_rather_than_fail(self, subject: Callable[..., Subject]) -> None:
        """``version.workspace = true`` parses as a table, and the member has nothing to assert."""
        manifest = SOUND_CARGO.replace('version = "1.2.3"', "version.workspace = true").replace(
            'description = "A demonstration crate"', "description.workspace = true"
        )
        repo = subject(_crate(**{"Cargo.toml": manifest}), tag="v1.2.3")

        result = repo.run("test_cargo_toml")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "inherited from the workspace" in result.stdout, result.stdout

    def test_a_crate_stating_no_licence_is_reported(self, subject: Callable[..., Subject]) -> None:
        """``cargo deny check licenses`` is an allow-list and fails the crate on itself."""
        manifest = SOUND_CARGO.replace('license = "MIT"\n', "")
        repo = subject(_crate(**{"Cargo.toml": manifest}), tag="v1.2.3")

        result = repo.run("test_cargo_toml")

        assert result.returncode != 0
        assert "declares neither 'license' nor 'license-file'" in result.stdout, result.stdout

    def test_a_licence_file_satisfies_the_licence_assertion(self, subject: Callable[..., Subject]) -> None:
        """``license-file`` is the other accepted form, for a licence cargo cannot name."""
        manifest = SOUND_CARGO.replace('license = "MIT"', 'license-file = "LICENSE"')
        repo = subject(_crate(**{"Cargo.toml": manifest, "LICENSE": "Custom terms\n"}), tag="v1.2.3")

        result = repo.run("test_cargo_toml")

        assert result.returncode == 0, result.stdout + result.stderr


class TestBumpversionConfig:
    """The shipped ``.bumpversion.toml`` must stay the config that wins, and stay pointed at Cargo.toml."""

    def test_no_config_anywhere_is_reported(self, subject: Callable[..., Subject]) -> None:
        """A Rust project owns none of the four discoverable filenames, so rust-core ships one."""
        repo = subject({"Cargo.toml": SOUND_CARGO}, tag="v1.2.3")

        result = repo.run("test_cargo_toml")

        assert result.returncode != 0
        assert "No bumpversion config was found" in result.stdout, result.stdout
        assert ".bumpversion.toml not found" in result.stdout, result.stdout

    def test_a_leftover_cfg_toml_earns_the_extra_hint(self, subject: Callable[..., Subject]) -> None:
        """``.rhiza/.cfg.toml`` is never auto-discovered; the failure should say so."""
        repo = subject(
            {"Cargo.toml": SOUND_CARGO, ".rhiza/.cfg.toml": '[tool.bumpversion]\ncurrent_version = "1.2.3"\n'},
            tag="v1.2.3",
        )

        result = repo.run("test_cargo_toml")

        assert result.returncode != 0
        assert "A leftover .rhiza/.cfg.toml is present" in result.stdout, result.stdout

    def test_an_unparseable_config_counts_as_absent(self, subject: Callable[..., Subject]) -> None:
        """Malformed TOML cannot be the config that runs, so it is reported as missing."""
        repo = subject({"Cargo.toml": SOUND_CARGO, ".bumpversion.toml": "not = = toml\n"}, tag="v1.2.3")

        result = repo.run("test_cargo_toml")

        assert result.returncode != 0
        assert "No bumpversion config was found" in result.stdout, result.stdout

    def test_a_second_config_in_pyproject_is_reported(self, subject: Callable[..., Subject]) -> None:
        """The reverse mistake: a Rust repo carrying a Python manifest declares the table twice."""
        repo = subject(
            _crate(**{"pyproject.toml": '[project]\nname = "helper"\n\n[tool.bumpversion]\ncommit = false\n'}),
            tag="v1.2.3",
        )

        result = repo.run("test_cargo_toml")

        assert result.returncode != 0
        assert "also declares a bumpversion section" in result.stdout, result.stdout

    def test_an_ini_config_is_detected_by_text(self, subject: Callable[..., Subject]) -> None:
        """``setup.cfg`` is INI, so presence is a substring test rather than a TOML lookup."""
        repo = subject(_crate(**{"setup.cfg": "[bumpversion]\ncurrent_version = 1.2.3\n"}), tag="v1.2.3")

        result = repo.run("test_cargo_toml")

        assert result.returncode != 0
        assert "'setup.cfg'" in result.stdout, result.stdout

    def test_a_pinned_current_version_is_reported(self, subject: Callable[..., Subject]) -> None:
        """The file is synced, so a value only the consumer maintains gets overwritten."""
        config = SOUND_BUMPVERSION.replace("[tool.bumpversion]", '[tool.bumpversion]\ncurrent_version = "1.2.3"')
        repo = subject(_crate(**{".bumpversion.toml": config}), tag="v1.2.3")

        result = repo.run("test_cargo_toml")

        assert result.returncode != 0
        assert "current_version is set in a file rhiza syncs" in result.stdout, result.stdout

    def test_a_config_targeting_nothing_is_reported(self, subject: Callable[..., Subject]) -> None:
        """With no ``[[files]]`` entry the bump succeeds while rewriting nothing."""
        config = "[tool.bumpversion]\ncommit = false\ntag = false\n"
        repo = subject(_crate(**{".bumpversion.toml": config}), tag="v1.2.3")

        result = repo.run("test_cargo_toml")

        assert result.returncode != 0
        assert "no [[tool.bumpversion.files]] entry targets Cargo.toml" in result.stdout, result.stdout
        assert "no Cargo.toml entry" in result.stdout, result.stdout

    def test_a_non_regex_search_is_reported(self, subject: Callable[..., Subject]) -> None:
        """A plain search cannot be anchored, so it also rewrites a same-numbered dependency."""
        config = SOUND_BUMPVERSION.replace("regex = true\n", "").replace(
            "search = '\\[package\\]([\\s\\S]*?)version = \"{current_version}\"'",
            "search = 'version = \"{current_version}\"'",
        )
        repo = subject(_crate(**{".bumpversion.toml": config}), tag="v1.2.3")

        result = repo.run("test_cargo_toml")

        assert result.returncode != 0
        assert "is not a regex" in result.stdout, result.stdout

    def test_a_regex_search_that_is_not_anchored_is_reported(self, subject: Callable[..., Subject]) -> None:
        """Regex alone is not enough — it has to mention the ``[package]`` table."""
        config = SOUND_BUMPVERSION.replace(
            "search = '\\[package\\]([\\s\\S]*?)version = \"{current_version}\"'",
            "search = 'version = \"{current_version}\"'",
        )
        repo = subject(_crate(**{".bumpversion.toml": config}), tag="v1.2.3")

        result = repo.run("test_cargo_toml")

        assert result.returncode != 0
        assert "does not mention the [package] table" in result.stdout, result.stdout

    def test_committing_and_tagging_from_the_bump_is_reported(self, subject: Callable[..., Subject]) -> None:
        """``/rhiza:release`` owns both; a config doing them adds a duplicate tag."""
        config = SOUND_BUMPVERSION.replace("commit = false\ntag = false", "commit = true\ntag = true")
        repo = subject(_crate(**{".bumpversion.toml": config}), tag="v1.2.3")

        result = repo.run("test_cargo_toml")

        assert result.returncode != 0
        assert "must be false: the release flow commits and tags" in result.stdout, result.stdout


class TestTagAgreement:
    """The crate version must be the newest tag or ahead of it, never behind.

    See :class:`tests.test_check_pyproject.TestTagAgreement` for why equality was wrong
    (#62). Only a manifest that has fallen behind breaks the next bump, which reads the
    current version from the tag and then searches Cargo.toml for it.
    """

    def test_a_version_behind_the_tag_is_reported(self, subject: Callable[..., Subject]) -> None:
        """bump-my-version reads the version from the tag and then looks for it in Cargo.toml."""
        manifest = SOUND_CARGO.replace('version = "1.2.3"', 'version = "1.1.0"')
        repo = subject(_crate(**{"Cargo.toml": manifest}), tag="v1.2.3")

        result = repo.run("test_cargo_toml")

        assert result.returncode != 0
        assert "bump-my-version derives the current version from the tag" in result.stdout, result.stdout

    def test_a_version_ahead_of_the_tag_is_a_release_in_flight(self, subject: Callable[..., Subject]) -> None:
        """A crate whose bump has landed but whose tag has not is not drift."""
        manifest = SOUND_CARGO.replace('version = "1.2.3"', 'version = "9.9.9"')
        repo = subject(_crate(**{"Cargo.toml": manifest}), tag="v1.2.3")

        result = repo.run("test_cargo_toml")

        assert result.returncode == 0, result.stdout + result.stderr

    def test_an_untagged_repository_skips_the_comparison(self, subject: Callable[..., Subject]) -> None:
        """A crate that has never released must not fail the version checks."""
        repo = subject(_crate())

        result = repo.run("test_cargo_toml")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "No version tags found" in result.stdout, result.stdout
