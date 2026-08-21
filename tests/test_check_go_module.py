"""Subject-repository tests for ``checks/test_go_module.py``.

The Go check is the other one issue #10 flagged as shipping untested: nothing here is a
Go module, so its 91 statements ran for the first time in a consumer's CI. What it
asserts is the *wiring* around the version constant rather than the module's behaviour —
that ``.bumpversion.toml`` still points at the one writable version location a Go tree
has, and that the constant agrees with the tag.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import only for the fixture's type
    from conftest import Subject

SOUND_GO_MOD = """
module example.com/demo

go 1.23
"""

SOUND_VERSION_GO = """
// Package version carries the module version the release flow rewrites.
package version

// Version is written by bump-my-version; see .bumpversion.toml. Mentioning 1.2.3 in
// this comment is deliberate: an unanchored search would rewrite it too.
const Version = "1.2.3"
"""

SOUND_BUMPVERSION = """
[tool.bumpversion]
allow_dirty = false
commit = false
tag = false
tag_name = "v{new_version}"

[[tool.bumpversion.files]]
filename = "internal/version/version.go"
search = 'const Version = "{current_version}"'
replace = 'const Version = "{new_version}"'
"""

VERSION_GO = "internal/version/version.go"

TOTAL_CHECKS = 12


def _module(**extra: str) -> dict[str, str]:
    """Return the file map for a sound Go module, with any extra files merged in.

    Args:
        extra: Additional repository-relative files, overriding the sound ones by name.

    Returns:
        The file map to hand to the ``subject`` factory.
    """
    return {
        "go.mod": SOUND_GO_MOD,
        VERSION_GO: SOUND_VERSION_GO,
        ".bumpversion.toml": SOUND_BUMPVERSION,
        **extra,
    }


class TestSoundSubject:
    """A module carrying everything the check asks for passes all of it."""

    def test_a_complete_module_passes_every_check(self, subject: Callable[..., Subject]) -> None:
        """The reference case, and the only test here that proves the check can pass."""
        repo = subject(_module(), tag="v1.2.3")

        result = repo.run("test_go_module")

        assert result.returncode == 0, result.stdout + result.stderr
        assert f"{TOTAL_CHECKS} passed" in result.stdout, result.stdout


class TestGoMod:
    """go.mod's presence and the directives the gates depend on."""

    def test_a_repository_without_go_mod_is_reported(self, subject: Callable[..., Subject]) -> None:
        """No go.mod: the existence assertion fires and the directive tests skip."""
        repo = subject(_module(**{"go.mod": ""}), tag="v1.2.3")
        (repo.path / "go.mod").unlink()

        result = repo.run("test_go_module")

        assert result.returncode != 0
        assert "go.mod not found at project root" in result.stdout, result.stdout

    def test_a_go_mod_without_a_module_directive_is_reported(self, subject: Callable[..., Subject]) -> None:
        """Without ``module`` there is no import path, and nothing resolves the package."""
        repo = subject(_module(**{"go.mod": "go 1.23\n"}), tag="v1.2.3")

        result = repo.run("test_go_module")

        assert result.returncode != 0
        assert "declares no `module` directive" in result.stdout, result.stdout

    def test_a_go_mod_without_a_go_directive_is_reported(self, subject: Callable[..., Subject]) -> None:
        """The directive sets the language version, which is what the deps gate reads."""
        repo = subject(_module(**{"go.mod": "module example.com/demo\n"}), tag="v1.2.3")

        result = repo.run("test_go_module")

        assert result.returncode != 0
        assert "declares no `go` directive" in result.stdout, result.stdout

    def test_a_go_directive_below_the_deps_gate_floor_is_reported(self, subject: Callable[..., Subject]) -> None:
        """``go mod tidy -diff`` landed in 1.23; below it the gate fails on the flag, not the deps."""
        repo = subject(_module(**{"go.mod": SOUND_GO_MOD.replace("go 1.23", "go 1.22")}), tag="v1.2.3")

        result = repo.run("test_go_module")

        assert result.returncode != 0
        assert "which requires 1.23 or newer" in result.stdout, result.stdout


class TestVersionConstant:
    """The release flow's only writable version location must stay writable."""

    def test_a_missing_version_file_is_reported(self, subject: Callable[..., Subject]) -> None:
        """A Go module has no manifest, so the constant is the whole story."""
        repo = subject({"go.mod": SOUND_GO_MOD, ".bumpversion.toml": SOUND_BUMPVERSION}, tag="v1.2.3")

        result = repo.run("test_go_module")

        assert result.returncode != 0
        assert "is the only version location in a Go" in result.stdout, result.stdout

    def test_a_version_file_without_the_constant_is_reported(self, subject: Callable[..., Subject]) -> None:
        """The literal ``const Version = "..."`` is what .bumpversion.toml searches for."""
        repo = subject(_module(**{VERSION_GO: 'package version\n\nvar Version = "1.2.3"\n'}), tag="v1.2.3")

        result = repo.run("test_go_module")

        assert result.returncode != 0
        assert "declares no `const Version" in result.stdout, result.stdout

    def test_a_constant_that_is_not_semver_is_reported(self, subject: Callable[..., Subject]) -> None:
        """``.bumpversion.toml``'s parse regex accepts MAJOR.MINOR.PATCH with an optional pre-release."""
        repo = subject(_module(**{VERSION_GO: 'package version\n\nconst Version = "1.2"\n'}), tag="v1.2.3")

        result = repo.run("test_go_module")

        assert result.returncode != 0
        assert "does not match the shape .bumpversion.toml parses" in result.stdout, result.stdout

    def test_a_prerelease_constant_is_accepted(self, subject: Callable[..., Subject]) -> None:
        """``1.2.3-rc.1`` is the one suffix the parse regex allows, so it must not be rejected."""
        repo = subject(
            _module(**{VERSION_GO: 'package version\n\nconst Version = "1.2.3-rc.1"\n'}),
            tag="v1.2.3-rc.1",
        )

        result = repo.run("test_go_module")

        assert result.returncode == 0, result.stdout + result.stderr


class TestBumpversionConfig:
    """The shipped ``.bumpversion.toml`` must stay the config that wins, pointed at the constant."""

    def test_no_config_anywhere_is_reported(self, subject: Callable[..., Subject]) -> None:
        """A Go module owns none of the four discoverable filenames, so go-core ships one."""
        repo = subject({"go.mod": SOUND_GO_MOD, VERSION_GO: SOUND_VERSION_GO}, tag="v1.2.3")

        result = repo.run("test_go_module")

        assert result.returncode != 0
        assert "No bumpversion config was found" in result.stdout, result.stdout
        assert ".bumpversion.toml not found" in result.stdout, result.stdout

    def test_a_leftover_cfg_toml_earns_the_extra_hint(self, subject: Callable[..., Subject]) -> None:
        """``.rhiza/.cfg.toml`` is never auto-discovered; the failure should say so."""
        repo = subject(
            {
                "go.mod": SOUND_GO_MOD,
                VERSION_GO: SOUND_VERSION_GO,
                ".rhiza/.cfg.toml": '[tool.bumpversion]\ncurrent_version = "1.2.3"\n',
            },
            tag="v1.2.3",
        )

        result = repo.run("test_go_module")

        assert result.returncode != 0
        assert "A leftover .rhiza/.cfg.toml is present" in result.stdout, result.stdout

    def test_an_unparseable_config_counts_as_absent(self, subject: Callable[..., Subject]) -> None:
        """Malformed TOML cannot be the config that runs, so it is reported as missing."""
        repo = subject(_module(**{".bumpversion.toml": "not = = toml\n"}), tag="v1.2.3")

        result = repo.run("test_go_module")

        assert result.returncode != 0
        assert "No bumpversion config was found" in result.stdout, result.stdout

    def test_a_second_config_in_pyproject_is_reported(self, subject: Callable[..., Subject]) -> None:
        """A pyproject.toml carried for tooling declares an inert table, and inert configs drift."""
        repo = subject(
            _module(**{"pyproject.toml": '[project]\nname = "helper"\n\n[tool.bumpversion]\ncommit = false\n'}),
            tag="v1.2.3",
        )

        result = repo.run("test_go_module")

        assert result.returncode != 0
        assert "also declares a bumpversion section" in result.stdout, result.stdout

    def test_an_ini_config_is_detected_by_text(self, subject: Callable[..., Subject]) -> None:
        """``.bumpversion.cfg`` is INI, so presence is a substring test rather than a TOML lookup."""
        repo = subject(_module(**{".bumpversion.cfg": "[bumpversion]\ncurrent_version = 1.2.3\n"}), tag="v1.2.3")

        result = repo.run("test_go_module")

        assert result.returncode != 0
        assert "'.bumpversion.cfg'" in result.stdout, result.stdout

    def test_a_pinned_current_version_is_reported(self, subject: Callable[..., Subject]) -> None:
        """For Go the tag *is* the version, so pinning it in a synced file is pure drift."""
        config = SOUND_BUMPVERSION.replace("[tool.bumpversion]", '[tool.bumpversion]\ncurrent_version = "1.2.3"')
        repo = subject(_module(**{".bumpversion.toml": config}), tag="v1.2.3")

        result = repo.run("test_go_module")

        assert result.returncode != 0
        assert "current_version is set in a file rhiza syncs" in result.stdout, result.stdout

    def test_a_config_targeting_nothing_is_reported(self, subject: Callable[..., Subject]) -> None:
        """With no ``[[files]]`` entry the bump writes the new version nowhere at all."""
        repo = subject(
            _module(**{".bumpversion.toml": "[tool.bumpversion]\ncommit = false\ntag = false\n"}), tag="v1.2.3"
        )

        result = repo.run("test_go_module")

        assert result.returncode != 0
        assert f"entry targets {VERSION_GO}" in result.stdout, result.stdout
        assert "no version.go entry" in result.stdout, result.stdout

    def test_an_unanchored_search_is_reported(self, subject: Callable[..., Subject]) -> None:
        """version.go's doc comment mentions the version, so a bare number rewrites prose."""
        config = SOUND_BUMPVERSION.replace(
            "search = 'const Version = \"{current_version}\"'", "search = '\"{current_version}\"'"
        )
        repo = subject(_module(**{".bumpversion.toml": config}), tag="v1.2.3")

        result = repo.run("test_go_module")

        assert result.returncode != 0
        assert "is not anchored to the declaration" in result.stdout, result.stdout

    def test_committing_and_tagging_from_the_bump_is_reported(self, subject: Callable[..., Subject]) -> None:
        """``/rhiza:release`` owns both; a config doing them adds a duplicate tag."""
        config = SOUND_BUMPVERSION.replace("commit = false\ntag = false", "commit = true\ntag = true")
        repo = subject(_module(**{".bumpversion.toml": config}), tag="v1.2.3")

        result = repo.run("test_go_module")

        assert result.returncode != 0
        assert "must be false: the release flow commits and tags" in result.stdout, result.stdout


class TestTagAgreement:
    """The constant must be the newest tag or ahead of it, never behind.

    See :class:`tests.test_check_pyproject.TestTagAgreement` for why equality was wrong
    (#62). A constant behind the tag is the harmful direction: the binary reports a
    version older than what consumers can already fetch.
    """

    def test_a_constant_behind_the_tag_is_reported(self, subject: Callable[..., Subject]) -> None:
        """Consumers resolve the module at the tag, so a lagging constant misreports."""
        repo = subject(_module(**{VERSION_GO: 'package version\n\nconst Version = "1.1.0"\n'}), tag="v1.2.3")

        result = repo.run("test_go_module")

        assert result.returncode != 0
        assert "would report a version older than the one that can be fetched" in result.stdout, result.stdout

    def test_a_constant_ahead_of_the_tag_is_a_release_in_flight(self, subject: Callable[..., Subject]) -> None:
        """A module whose bump has landed but whose tag has not is not drift."""
        repo = subject(_module(**{VERSION_GO: 'package version\n\nconst Version = "9.9.9"\n'}), tag="v1.2.3")

        result = repo.run("test_go_module")

        assert result.returncode == 0, result.stdout + result.stderr

    def test_an_untagged_repository_skips_the_comparison(self, subject: Callable[..., Subject]) -> None:
        """A module that has never released must not fail the version checks."""
        repo = subject(_module())

        result = repo.run("test_go_module")

        assert result.returncode == 0, result.stdout + result.stderr
        assert "No version tags found" in result.stdout, result.stdout
