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
"""

from __future__ import annotations

import re
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


def test_the_readme_pins_no_literal_version() -> None:
    """The documented `[tool.rhiza-task]` example must use a placeholder, not a number."""
    text = README.read_text(encoding="utf-8")

    offenders = [
        f"line {number}: {line.strip()}"
        for number, line in enumerate(text.splitlines(), start=1)
        if _PINNED_LITERAL.search(line)
    ]

    assert not offenders, (
        "README.md pins pytest-rhiza to a literal version:\n"
        + "\n".join(offenders)
        + "\n\nUse a placeholder such as `pytest-rhiza@<version>` instead. The sync "
        "generates the real pin from the template release, and nothing in this repository "
        "bumps or checks a number written here — which is how it came to read 0.1.0 three "
        "releases after 0.1.0 (#17)."
    )


def test_the_placeholder_is_still_there() -> None:
    """The prohibition above passes vacuously if the example is deleted or renamed.

    Cheap, and it is the failure mode a negative assertion always has: a test that only
    says "no literal" is satisfied by a README that no longer documents the wiring at all.
    """
    text = README.read_text(encoding="utf-8")

    assert "pytest-rhiza@<version>" in text, (
        "README.md no longer shows the `pytest-rhiza@<version>` placeholder in the "
        "`[tool.rhiza-task]` example. If the example moved or was rewritten, update this "
        "test to match — it is the only thing keeping a literal version out of that file."
    )
