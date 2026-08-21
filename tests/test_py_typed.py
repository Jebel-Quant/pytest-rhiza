"""The ``py.typed`` marker is what makes this package's annotations reach a consumer.

Issue #73: ``ci.yml`` runs ``ty check src scripts`` *and* ``mypy --strict src scripts``, and
``CLAUDE.md`` records that the second was adopted specifically for the annotation floor the
first has no opinion on. All of that stopped at this repository's own boundary. Under PEP
561 a type checker must treat an installed package as untyped unless it ships a ``py.typed``
marker, so a consumer's ``mypy`` saw ``Any`` for the ``root``, ``logger`` and ``latest_tag``
fixtures — a package holding itself to ``--strict`` while enforcing nothing it could pass on.

**Why this is tested at all**, given that the fix is one empty file: an empty file is exactly
the kind of thing that gets lost. Nothing imports it, no gate reads it, and deleting it
changes no behaviour *in this repository* — the suite runs against an editable install, so
``pytest_rhiza.__file__`` points into ``src`` and the marker is found whether or not it would
ever be packaged. The failure is silent, lands in the wheel, and shows up as "your types
don't work" in somebody else's repo.

**Two tests, because there are two ways to lose it**, the same split as
:mod:`tests.test_version`: one catches the marker going missing, the other catches the
mechanism that ships it being narrowed.

**Why neither builds a wheel.** Asserting on a built artefact is the most direct statement of
the invariant, and it was checked that way once by hand — ``uv build --wheel`` puts
``pytest_rhiza/py.typed`` in the archive at 0 bytes. Doing it per-run would make a fast suite
shell out to a build backend for one bit of information that
:func:`test_marker_is_inside_the_packaged_directory` already pins: hatchling ships a
``packages`` entry whole, so a marker inside one is a marker in the wheel.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PYPROJECT = ROOT / "pyproject.toml"

# Spelled the way the pyproject key does — forward slashes on every platform — because that
# is what the assertion below compares against.
MARKER = "src/pytest_rhiza/py.typed"


def _wheel_packages() -> list[str]:
    """Return the directories ``[tool.hatch.build.targets.wheel] packages`` ships.

    Returns:
        The declared package paths, read at test time so a stale copy cannot be what the
        assertions compare against.
    """
    with PYPROJECT.open("rb") as handle:
        manifest = tomllib.load(handle)

    packages = manifest["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    return [str(entry) for entry in packages]


def test_marker_exists() -> None:
    """A ``py.typed`` file must sit beside the package's modules."""
    assert (ROOT / MARKER).is_file(), (
        f"{MARKER} is missing, so PEP 561 says every consumer's type checker must treat "
        f"pytest_rhiza as untyped — the fixtures this package exists to provide come back "
        f"as Any, however clean `mypy --strict` is here (#73)."
    )


def test_marker_is_inside_the_packaged_directory() -> None:
    """The marker must lie under a declared ``packages`` entry, which is what ships it.

    hatchling ships a ``packages`` entry as a whole directory, so this is the mechanism that
    puts the marker in the wheel — and the thing that would quietly stop doing so if the
    entry were ever narrowed to a module list or moved.
    """
    packages = _wheel_packages()

    covered = [entry for entry in packages if MARKER.startswith(f"{entry.rstrip('/')}/")]

    assert covered, (
        f"{MARKER} is not inside any [tool.hatch.build.targets.wheel] packages entry "
        f"({packages}), so hatchling will not ship it and the marker is present in the "
        f"source tree only. The editable install this suite runs against would still find "
        f"it, which is why nothing else here would notice (#73)."
    )
