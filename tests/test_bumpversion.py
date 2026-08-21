"""``bumpversion_table`` and ``has_bumpversion_section`` must agree on what counts.

Both answer a question about the same key — ``has_bumpversion_section`` asks whether a file
declares a usable ``[tool.bumpversion]``, and ``bumpversion_table`` returns it — and until
``mypy --strict`` was added alongside ``ty`` they disagreed. ``has_bumpversion_section``
required ``isinstance(..., dict)``; ``bumpversion_table`` returned whatever the key held,
so a ``tool.bumpversion = "yes"`` was reported as *no config* by one and handed back as a
string by the other, to callers that immediately subscript it.

Neither checker could have found that on its own: ``ty`` accepted the bare ``dict``
annotation, and it was ``--strict``'s ``no-any-return`` that made the erased return type
visible. The narrowing that fixed it is a one-line ternary, which coverage.py cannot see
into — a conditional expression is a single line, so both outcomes produce the same arc and
`--cov-branch` reports it fully covered either way. These tests are what actually exercises
the false side.

:func:`test_a_non_table_declaration_reads_as_absent` is the case that was wrong. The other
two pin the ordinary answers, so a future simplification back to a bare ``.get`` chain —
which would look tidier — fails here instead of shipping.
"""

from __future__ import annotations

from pathlib import Path

from pytest_rhiza._bumpversion import bumpversion_table, has_bumpversion_section


def _write(tmp_path: Path, body: str) -> Path:
    """Write a ``pyproject.toml`` holding ``body`` and return its path.

    Args:
        tmp_path: pytest's per-test temporary directory.
        body: TOML source.

    Returns:
        The path written.
    """
    path = tmp_path / "pyproject.toml"
    path.write_text(body, encoding="utf-8", newline="\n")
    return path


def test_a_declared_table_is_returned(tmp_path: Path) -> None:
    """The ordinary case: the table is handed back, and both functions agree it exists."""
    path = _write(tmp_path, "[tool.bumpversion]\nallow_dirty = false\ncommit = false\n")

    assert bumpversion_table(path) == {"allow_dirty": False, "commit": False}
    assert has_bumpversion_section(path)


def test_no_declaration_is_an_empty_table(tmp_path: Path) -> None:
    """A file with no ``[tool.bumpversion]`` yields ``{}`` rather than raising."""
    path = _write(tmp_path, '[project]\nname = "x"\n')

    assert bumpversion_table(path) == {}
    assert not has_bumpversion_section(path)


def test_a_non_table_declaration_reads_as_absent(tmp_path: Path) -> None:
    """The disagreement itself: a scalar under that key is not a config to either function.

    Returning the string here would put it in the hands of the ``SyncedBumpversionConfig``
    assertions, which call ``.get`` on the result — so the failure would have surfaced as an
    ``AttributeError`` inside a check rather than as the verdict "no bumpversion config".
    """
    path = _write(tmp_path, '[tool]\nbumpversion = "yes"\n')

    assert bumpversion_table(path) == {}
    assert not has_bumpversion_section(path)
