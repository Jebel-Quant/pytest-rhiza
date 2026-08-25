"""Tests for go.mod, the Version constant, and the release config that rewrites it.

Ported from ``jebel-quant/rhiza`` at 89f9298, where bundle ``go-core`` synced it
to ``.rhiza/tests/test_go_module.py``. It now arrives installed, and is collected by name:
``pytest --pyargs pytest_rhiza.checks.test_go_module``.

The Go counterpart of ``test_pyproject.py``. Written in Python and run through uv by
``make rhiza-test`` rather than as a ``_test.go``, for the same reason the rest of the
suite is: it validates *configuration*, and the release flow that reads it is Python
tooling. ``uv`` lives in ``core`` precisely so it is available whatever the project's
language.

Where it does **not** overlap with ``internal/version/version_test.go``: that one runs
inside the module and asserts the shape of the constant. This one asserts the wiring
around it — that ``.bumpversion.toml`` still points at the file, and that the constant
agrees with the tag. A Go test could read git too, but the invariants here belong with
the release config rather than with the package.

Validates that:
- go.mod exists, declares a module path, and pins a `go` directive `make deps` supports
- internal/version/version.go still carries the constant the release flow writes to
- .bumpversion.toml is the config bump-my-version discovers, and targets that constant
- the constant matches the latest git tag (vX.Y.Z → X.Y.Z)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pytest_rhiza._bumpversion import SyncedBumpversionConfig
from pytest_rhiza._release_state import assert_release_not_stalled
from pytest_rhiza._versions import assert_declared_version_not_behind_tag

# The one place a Go module's version exists in the source tree.
_VERSION_GO = Path("internal") / "version" / "version.go"

# `const Version = "..."` — the literal .bumpversion.toml searches for.
_VERSION_CONST_RE = re.compile(r'^const\s+Version\s*=\s*"([^"]*)"', re.MULTILINE)

_MODULE_RE = re.compile(r"^module\s+(\S+)", re.MULTILINE)
_GO_DIRECTIVE_RE = re.compile(r"^go\s+(\d+)\.(\d+)", re.MULTILINE)

# `go mod tidy -diff`, which `make deps` is, landed in 1.23. Below that the gate fails
# with an unrecognised flag rather than with a dependency problem.
_MIN_GO = (1, 23)


@pytest.fixture(scope="module")
def go_mod(root: Path) -> str:
    """Return the text of go.mod."""
    path = root / "go.mod"
    if not path.is_file():
        pytest.skip("go.mod not found")
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def declared_version(root: Path) -> str:
    """Return the value of the ``Version`` constant in internal/version/version.go."""
    path = root / _VERSION_GO
    if not path.is_file():
        pytest.fail(
            f"{_VERSION_GO.as_posix()} not found. A Go module's version is its git tag, so this "
            f"constant is the only version location in the tree and .bumpversion.toml writes to "
            f"it; without the file the release flow has nowhere to write. Restore it from the "
            f"go-core bundle."
        )
    match = _VERSION_CONST_RE.search(path.read_text(encoding="utf-8"))
    if match is None:
        pytest.fail(
            f'{_VERSION_GO.as_posix()} declares no `const Version = "..."` line. That literal is '
            f"what .bumpversion.toml searches for, and with ignore_missing_version = false the "
            f"release fails on it rather than warning."
        )
    return match.group(1)


class TestGoMod:
    """Tests for go.mod's presence and the directives the gates depend on."""

    def test_go_mod_exists(self, root: Path) -> None:
        """go.mod must exist at the project root."""
        assert (root / "go.mod").is_file(), "go.mod not found at project root"

    def test_module_path_declared(self, go_mod: str) -> None:
        """go.mod must declare a module path."""
        match = _MODULE_RE.search(go_mod)
        assert match is not None, "go.mod declares no `module` directive"
        assert match.group(1).strip(), "go.mod's `module` directive is empty"

    def test_go_directive_is_recent_enough_for_the_deps_gate(self, go_mod: str) -> None:
        """The `go` directive must be at least 1.23.

        Not a general preference: ``make deps`` is ``go mod tidy -diff``, and that flag
        landed in 1.23. An older directive fails the gate with an unrecognised flag,
        which reads as a tooling break rather than as a version floor. A newer toolchain
        on the machine does not help — the directive is what sets the language version.
        """
        match = _GO_DIRECTIVE_RE.search(go_mod)
        assert match is not None, "go.mod declares no `go` directive"
        found = (int(match.group(1)), int(match.group(2)))
        assert found >= _MIN_GO, (
            f"go.mod pins go {found[0]}.{found[1]}, but `make deps` runs `go mod tidy -diff` "
            f"which requires {_MIN_GO[0]}.{_MIN_GO[1]} or newer"
        )


class TestVersionConstant:
    """The release flow's only writable version location must stay writable."""

    def test_version_file_exists(self, root: Path) -> None:
        """internal/version/version.go must be present."""
        assert (root / _VERSION_GO).is_file(), (
            f"{_VERSION_GO.as_posix()} is missing; it is the only version location in a Go "
            f"module's source tree and .bumpversion.toml writes to it"
        )

    def test_version_is_semver(self, declared_version: str) -> None:
        """The constant must parse as MAJOR.MINOR.PATCH with an optional pre-release.

        ``version_test.go`` asserts the same shape from inside the module. Duplicated
        deliberately: that test can be deleted by a project that adds its own, and this
        invariant belongs to the release config either way.
        """
        assert re.match(r"^\d+\.\d+\.\d+(?:-[a-z]+\.\d+)?$", declared_version), (
            f"Version = {declared_version!r} does not match the shape .bumpversion.toml parses "
            f"(MAJOR.MINOR.PATCH with an optional -pre.N suffix)"
        )


class TestBumpversionConfig(SyncedBumpversionConfig):
    """The release flow must find a version config, not silently invent one (#1453).

    bump-my-version searches four filenames and stops. Finding none it does **not**
    fail — it falls back to ``git describe`` and reports the last reachable tag as the
    current version. For Go that fallback is especially easy to miss, because reading
    the version from the tag is *also* what the shipped config does deliberately; the
    difference is that the real config knows where to write the value back.

    The assertions themselves are :class:`~pytest_rhiza._bumpversion.SyncedBumpversionConfig`,
    shared with the Rust layer (#14). What is Go-specific is declared below. Note
    ``search_is_regex`` is False: ``const Version`` is a literal that appears once as a
    declaration, so no escaping is needed to anchor to it — where Rust has to distinguish
    a crate version from a same-numbered dependency pin, Go only has to avoid prose.
    """

    version_file = _VERSION_GO.as_posix()
    search_anchor = "const Version"
    bundle = "go-core"
    missing_config_consequence = " and write the new version nowhere"
    untargeted_consequence = "a bump would write the new version nowhere"
    unanchored_complaint = (
        "is not anchored to the declaration; it would also rewrite a version appearing in a comment or an example"
    )


class TestGitTagVersion:
    """Harmony between the latest git tag and the Version constant.

    Reachability of that tag is asserted by ``test_release_tags.py``, which ``core``
    ships for every language layer.
    """

    def test_the_version_constant_is_not_behind_the_latest_tag(self, latest_tag: str, declared_version: str) -> None:
        """The ``Version`` constant must be the newest vX.Y.Z tag, or ahead of it.

        For Go the tag is the definition of the version rather than a consistency
        check: consumers resolve the module at the tag, so a constant that has fallen
        *behind* means a built binary reports a version older than what is published.
        A constant ahead of the newest tag is a release in flight — the bump lands by
        pull request and the tag follows. See :mod:`pytest_rhiza._versions`.
        """
        assert_declared_version_not_behind_tag(
            latest_tag,
            declared_version,
            location=f"the Version constant in {_VERSION_GO.as_posix()}",
            consequence=(
                "consumers resolve the module at the tag, so the built binary would report a "
                "version older than the one that can be fetched."
            ),
        )

    def test_the_bump_that_produced_this_version_was_tagged(
        self, latest_tag: str, declared_version: str, root: Path
    ) -> None:
        """The bump that produced this version must have been tagged (#85).

        ``assert_declared_version_not_behind_tag`` permits the manifest to lead the newest
        tag, because that is what a release in flight looks like. Nothing bounded how long
        it may lead for, so a release whose phase B never ran stayed green indefinitely
        while declaring a version that was never tagged and never published. See
        :mod:`pytest_rhiza._release_state`.
        """
        assert_release_not_stalled(
            root,
            latest_tag,
            declared_version,
            manifest=_VERSION_GO.as_posix(),
        )
