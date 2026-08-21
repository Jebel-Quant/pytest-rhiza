"""The vocabulary type for a parsed TOML table.

**Why this exists rather than forty copies of ``dict[str, Any]``.** Every manifest check
in this package reads a TOML file and walks the result: ``[project]`` out of
``pyproject.toml``, ``[package]`` out of ``Cargo.toml``, ``[tool.bumpversion]`` out of
whichever config file wins. Those tables were annotated as bare ``dict`` until
``mypy --strict`` was added alongside ``ty``, which is what noticed: bare ``dict`` is
``dict[Any, Any]``, so it silently erased the one half of the shape that *is* known.

The keys are always ``str`` — TOML has no other key type. The values genuinely are
``Any``, and that is a property of the format rather than a gap in the annotation: one
table holds strings, integers, arrays and sub-tables, and a checker that reads
``project["authors"][0]["name"]`` cannot be told the type of each hop without modelling
every manifest this package might ever judge.

Naming that once is the point. ``dict[str, Any]`` repeated at forty call sites reads as
forty separate decisions to give up on typing; one alias says the same thing once, with
the reason attached.
"""

from __future__ import annotations

from typing import Any, TypeAlias

#: A parsed TOML table: ``str`` keys, heterogeneous values. See the module docstring for
#: why the values are ``Any`` by nature rather than by omission.
TomlTable: TypeAlias = dict[str, Any]
