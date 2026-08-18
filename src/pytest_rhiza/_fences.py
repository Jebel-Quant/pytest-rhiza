"""Markdown fence parsing shared by the two README checks.

**Why this module exists.** Upstream, ``SKIP_FLAG`` and ``_should_skip`` are duplicated
between ``core``'s ``test_readme.py`` and the ``tests`` bundle's
``test_readme_validation.py``, and both files say why::

    Bundles are copied independently — a Rust project receives this file and not the
    other — so a shared helper would need a third home that both bundles ship, which is
    a worse trade for four lines.

One distribution *is* that third home, so the trade reverses. The duplication also had a
second cost that is easy to miss: the ``TestSkipFlag`` classes exercising these helpers
shipped into every consumer repository, where they tested template code against itself.
They now live in this package's own suite instead.

The regexes and the flag keep their upstream names so the ported checks read as a move.
"""

from __future__ import annotations

import re

# Bash code blocks — captures optional flags (e.g. "+RHIZA_SKIP") and the code body.
BASH_BLOCK = re.compile(r"```bash([^\n]*)\n(.*?)```", re.DOTALL)

# Python code blocks, same shape.
CODE_BLOCK = re.compile(r"```python([^\n]*)\n(.*?)```", re.DOTALL)

# The ```result fences a python fence's stdout is diffed against.
RESULT = re.compile(r"```result\n(.*?)```", re.DOTALL)

# Bash executable used for syntax checking; `bash -n` parses without executing.
BASH = "bash"

# Flag marking a fence as intentionally excluded. Usage: add it after the language
# identifier on the opening fence line, e.g. ```bash +RHIZA_SKIP
SKIP_FLAG = "+RHIZA_SKIP"

# Box-drawing characters mean the fence is a directory tree, not runnable shell.
TREE_MARKERS = ("├──", "└──", "│")


def should_skip(flags: str) -> bool:
    """Return True if the fence flags string contains the +RHIZA_SKIP marker.

    Args:
        flags: Text following the language identifier on the opening fence line.

    Returns:
        True when the block is intentionally excluded.

    Examples:
        >>> should_skip(" +RHIZA_SKIP")
        True
        >>> should_skip("other-flag")
        False
    """
    return SKIP_FLAG in flags
