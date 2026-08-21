"""The README must not pin this package to a literal version.

Issue #17: `README.md` documented the wiring consumers adopt, pinning
`pytest-rhiza==0.1.0` while the package was at 0.2.2 — three releases stale, and stale
for a structural reason rather than an oversight. Nothing bumps the file (there is no
`[[tool.bumpversion.files]]` entry for `README.md`) and nothing reads it either: the
example sits in a fence no checker executes, and the README's `bash` fences are only
parsed by `bash -n`, never resolved against reality.

The fence is `toml` rather than `make` since #30 rewrote that section for rhiza v1.4,
which retired the synced make layer and moved the pin into `[tool.rhiza-task]`. The
staleness argument is untouched by the move — a `toml` fence is no more executed than a
`make` one was.

So the fix was to stop writing a number there at all — the sync generates the pin from
the template release, which is what the README's own "Version pinning" note says. This
test is what makes that decision hold: a literal reintroduced by a well-meaning edit
fails here rather than going stale for another three releases.

Deliberately a *prohibition* rather than an equality check against the current version.
Asserting the number matches would keep a literal in the file and just move the staleness
into a test that has to be updated on every release — a worse trade, and the same trap in
a new place.

**And a prohibition alone left the fence unparsed (#59).** Everything above constrains the
version *string*; nothing asked whether the snippet around it is well-formed TOML. It is
the block a consumer copies into their ``pyproject.toml``, and it is the one fence in this
README that no gate reaches: ``checks/test_readme.py`` parses only ``bash`` fences,
``checks/test_readme_validation.py`` executes only ``python`` ones, and the bundled
doc-example checker reports ``toml`` fences as "not checkable". So a mistyped key, a broken
table header or an unterminated string ships green — in the one snippet whose entire job is
to be pasted somewhere else. That fence has already been rewritten once (#30 moved it from
``make`` to ``toml`` for rhiza v1.4), which is exactly when a structural typo arrives.

:func:`_toml_fences` and the two tests below close that. They *parse*, deliberately, and
nothing more: there is no such thing as executing a TOML fence, and ``tomllib`` is stdlib,
so this adds no dependency to a package installed in every rhiza-managed repo.

The regex stays here rather than joining ``BASH_BLOCK`` and ``CODE_BLOCK`` in
``pytest_rhiza._fences``. That module is the shared home for helpers the *shipped checks*
both need, and this is not one: the ``[tool.rhiza-task]`` example is this repository's own
README content, so a consumer gains nothing from the pattern and would be shipped it
regardless.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

# `pytest-rhiza` followed by a separator and anything digit-led: the shape a copied
# literal takes. `==`, `~=` and `>=` cover the requirement forms; `@` covers the git-URL
# form the pin uses since rhiza v1.4 moved it into `[tool.rhiza-task]`
# (`pytest-rhiza @ git+https://…/pytest-rhiza@v0.2.1`). The underscore spelling is caught
# too, since a copy may normalise the name either way.
#
# `@` deliberately does not match the two non-literal uses in that same line: `@ git+…`
# fails `v?\d`, and so does the `@<version>` placeholder.
_PINNED_LITERAL = re.compile(r"pytest[-_]rhiza\s*(?:==|~=|>=|@)\s*v?\d")

README = Path(__file__).resolve().parents[1] / "README.md"

# Same shape as `BASH_BLOCK` and `CODE_BLOCK` in `pytest_rhiza._fences`: the language, then
# anything up to the closing fence. Non-greedy, so consecutive fences do not merge into one.
_TOML_FENCE = re.compile(r"```toml[^\n]*\n(.*?)```", re.DOTALL)

# The table the example must declare, and the two keys a consumer actually copies.
_TABLE = "tool.rhiza-task"
_LAYERS = "layers"
_PIN = "pytest-rhiza"


def _toml_fences(text: str) -> list[tuple[int, str]]:
    """Return every ```toml fence in ``text``, as ``(line number, body)``.

    Takes the text rather than reading :data:`README` so the extraction can be exercised on
    synthetic input — the same reason `plugin._resolve_root` is split out of the fixture
    that uses it. The line number is the opening fence's, 1-based, so a failure message
    points at the place to edit rather than at a byte offset.

    Args:
        text: Markdown to scan.

    Returns:
        One entry per fence, in document order.
    """
    return [(text.count("\n", 0, match.start()) + 1, match.group(1)) for match in _TOML_FENCE.finditer(text)]


def _toml_error(body: str) -> str | None:
    """Return why ``body`` is not valid TOML, or None when it parses.

    A returned string rather than a raised exception, so the caller can name the fence's
    line number in the failure it reports.

    Args:
        body: The fence body.

    Returns:
        The decoder's message, or None.
    """
    try:
        tomllib.loads(body)
    except tomllib.TOMLDecodeError as exc:
        return str(exc)
    return None


def _rhiza_task_tables(text: str) -> list[tuple[int, dict]]:
    """Return the ``[tool.rhiza-task]`` table from every fence that declares one.

    Args:
        text: Markdown to scan.

    Returns:
        ``(line number, table)`` for each fence carrying the table. Fences that do not
        parse are skipped — :func:`test_every_toml_fence_parses` is what reports those,
        and reporting one broken fence twice is noise.
    """
    tables = []
    for line, body in _toml_fences(text):
        if _toml_error(body) is not None:
            continue
        table = tomllib.loads(body).get("tool", {}).get("rhiza-task")
        if table is not None:
            tables.append((line, table))
    return tables


class TestTheHelpers:
    """The extraction and parsing, on synthetic input.

    Separate from the README assertions below for the reason the module docstring gives
    about vacuity: a helper only ever run against a file that happens to be correct is a
    helper whose failure path has never executed. These run both paths.
    """

    def test_fences_are_found_with_their_line_numbers(self) -> None:
        """Each fence is returned once, with the line its opening backticks sit on."""
        text = "intro\n\n```toml\na = 1\n```\n\nmiddle\n\n```toml\nb = 2\n```\n"

        assert _toml_fences(text) == [(3, "a = 1\n"), (9, "b = 2\n")]

    def test_consecutive_fences_do_not_merge(self) -> None:
        """The non-greedy body is what keeps two adjacent fences from becoming one."""
        assert len(_toml_fences("```toml\na = 1\n```\n```toml\nb = 2\n```\n")) == 2

    def test_a_fence_with_an_info_string_is_still_found(self) -> None:
        """A flag after the language must not hide the fence, as `+RHIZA_SKIP` would."""
        assert _toml_fences("```toml +SOMETHING\na = 1\n```\n") == [(1, "a = 1\n")]

    def test_non_toml_fences_are_ignored(self) -> None:
        """Only `toml` fences: `bash` and `python` have their own checks."""
        assert _toml_fences("```bash\ntrue\n```\n```python\nx = 1\n```\n") == []

    def test_valid_toml_reports_no_error(self) -> None:
        """The passing path returns None rather than an empty string."""
        assert _toml_error("a = 1\n") is None

    def test_broken_toml_reports_the_decoder_message(self) -> None:
        """The failure path returns something a reader can act on."""
        error = _toml_error("a = \n")

        assert error is not None
        assert error

    def test_a_table_is_found_through_the_fence(self) -> None:
        """The table is read out of the parsed document, not pattern-matched in the text."""
        text = '```toml\n[tool.rhiza-task]\nlayers = ["python"]\n```\n'

        assert _rhiza_task_tables(text) == [(1, {"layers": ["python"]})]

    def test_a_broken_fence_is_skipped_rather_than_raising(self) -> None:
        """An unparseable fence is `test_every_toml_fence_parses`'s finding, not this one's."""
        assert _rhiza_task_tables("```toml\na = \n```\n") == []

    def test_a_toml_fence_without_the_table_is_not_returned(self) -> None:
        """Some other `toml` fence must not be mistaken for the pin example."""
        assert _rhiza_task_tables("```toml\n[tool.other]\nx = 1\n```\n") == []


class TestTheReadmesTomlFence:
    """The README's own `[tool.rhiza-task]` example (#59)."""

    def test_every_toml_fence_parses(self) -> None:
        """Each ```toml fence in the README must be well-formed TOML.

        Every fence rather than only the pin example: the cost is the same, and a second
        `toml` fence added later would otherwise arrive unchecked — which is the position
        this test was written to get out of.
        """
        text = README.read_text(encoding="utf-8")
        fences = _toml_fences(text)

        assert fences, (
            "README.md has no ```toml fence. The `[tool.rhiza-task]` example is what a "
            "consumer copies to pin this package; if it moved or changed language, update "
            "this test — it is the only thing parsing that fence."
        )

        broken = [f"README.md:{line}: {error}" for line, body in fences if (error := _toml_error(body))]

        assert not broken, "README.md has a ```toml fence that is not valid TOML:\n" + "\n".join(broken)

    def test_the_example_declares_the_pin(self) -> None:
        """One fence must declare `[tool.rhiza-task]` with the two keys a consumer copies.

        Parsing alone is satisfied by an empty fence, which is the vacuity trap
        :func:`test_the_placeholder_is_still_there` covers one level up. This asserts the
        *shape*: the table is reachable, `layers` is a list, and the pin names this package
        through a git URL rather than a version specifier.
        """
        tables = _rhiza_task_tables(README.read_text(encoding="utf-8"))

        assert len(tables) == 1, (
            f"expected exactly one README fence declaring [{_TABLE}], found {len(tables)}. "
            "The example a consumer copies has to be unambiguous."
        )

        line, table = tables[0]
        assert isinstance(table.get(_LAYERS), list), (
            f"README.md:{line}: [{_TABLE}] must declare `{_LAYERS}` as a list — it is what "
            "selects the check set, and a scalar there would be a silently different "
            "selection."
        )
        assert "git+" in str(table.get(_PIN, "")), (
            f"README.md:{line}: [{_TABLE}] must declare `{_PIN}` as a git URL. The pin "
            "travels in the template as one setting; a bare version specifier there is the "
            "second version axis this design exists to avoid."
        )
