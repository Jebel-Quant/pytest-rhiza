"""Where a project's Python lives, and the retired file that used to say so.

Two questions, one answer, and they were tangled into the doctest runner until #60:
:func:`doctest_folders` resolves which folders a repository's examples live in, and
:func:`read_rhiza_env` is the compatibility rung that resolution still has to consult.

**Why this is its own module.** ``checks/test_docstrings.py`` had grown to 511 lines — the
largest in the tree, the lowest maintainability index in it (radon A 40.70 against a median
above 60), and the home of the only B-ranked block in ``src``. The cause was two unrelated
jobs in one file: running ``doctest`` over discovered modules, which is what the check *is*,
and parsing a legacy ``.rhiza/.env``, which is a migration concern that happens to feed it.

That second job is also the one with an end date, which is the stronger argument for the
boundary. rhiza retired ``.rhiza/.env`` at v1.4 in favour of ``[tool.rhiza-task]
source-folder``; this rung exists only for repositories that have not migrated. When the
last of them has, closing that out should be deleting a file, not unpicking a parser from a
doctest runner.

**Why it is not under ``checks/``.** A module there is one a consumer can name on a
``pytest --pyargs`` command line, whether or not it holds tests — the same reason
:mod:`pytest_rhiza._bumpversion` sits beside the package rather than inside it. Private
module, public names, as in :mod:`pytest_rhiza._process` and :mod:`pytest_rhiza._fences`.

**The precedence, in one place.** ``RHIZA_DOCTEST_FOLDERS``, then ``SOURCE_FOLDER`` from
``.rhiza/.env``, then ``src``. Nothing sets the variable for you: ``rhiza-task``
deliberately does not export it, so a consumer whose Python lives outside its source root
wraps the gate to pass its own ``source_folder``. That indirection exists because the gate
once resolved ``src`` and nothing else, so a project keeping Python elsewhere had its
examples silently skipped — rhiza's own repo being the extreme case, with no ``src/`` at all
and 23 unchecked examples in ``utils/`` (#1517).
"""

from __future__ import annotations

import os
from pathlib import Path

# Read .rhiza/.env at collection time (no environment side-effects).
RHIZA_ENV_PATH = Path(".rhiza/.env")

# Whitespace-separated. Exported by whatever wraps the gate — `rhiza-task` does not set
# it, so an unset variable means "fall back", not "misconfigured".
DOCTEST_FOLDERS_ENV = "RHIZA_DOCTEST_FOLDERS"


def read_rhiza_env(path: Path) -> dict[str, str]:
    r"""Parse the ``KEY=value`` lines of a legacy ``.rhiza/.env``, if it is there.

    This replaces ``dotenv_values`` from python-dotenv, which was a runtime dependency of
    every rhiza-managed repo for the sake of one lookup — ``SOURCE_FOLDER``, on the
    compatibility rung described in this module's docstring (#53). The file is written by
    rhiza v1.3 and earlier, so its shape is known: ``KEY=value`` lines, comments, and
    occasionally an ``export`` prefix. That is a much smaller grammar than dotenv
    implements, and it is the whole grammar this rung has ever needed.

    A line that does not parse is skipped rather than raised on, for the same reason
    ``_budget`` in :mod:`pytest_rhiza._process` falls back instead of raising: this is a
    compatibility path into a file the current toolchain no longer writes, and a stray
    line in it must not be able to fail every check in the repository.

    Args:
        path: The ``.rhiza/.env`` to read.

    Returns:
        The parsed mapping, empty when the file is absent or unreadable.

    Examples:
        A missing file is the common case rather than an error — every repo on v1.4 or
        later is this case:

        >>> import tempfile
        >>> root = Path(tempfile.mkdtemp())
        >>> read_rhiza_env(root / ".rhiza" / ".env")
        {}

        Blank lines and comments are ignored, ``export`` is tolerated, and quotes around
        the value are stripped:

        >>> env = root / ".env"
        >>> _ = env.write_text(
        ...     "# where the python lives\n"
        ...     "\n"
        ...     'export SOURCE_FOLDER="utils"\n'
        ...     "OTHER = 'spaced'\n"
        ... )
        >>> read_rhiza_env(env) == {"SOURCE_FOLDER": "utils", "OTHER": "spaced"}
        True

        A line with no ``=``, and one with no name, are both skipped rather than raised
        on — and skipping them does not stop the lines around them being read:

        >>> _ = env.write_text("BROKEN\n=novalue\nSOURCE_FOLDER=src\n")
        >>> read_rhiza_env(env)
        {'SOURCE_FOLDER': 'src'}
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.removeprefix("export ").lstrip().partition("=")
        if not separator or not key.strip():
            continue
        values[key.strip()] = value.strip().strip("\"'")
    return values


def doctest_folders(root: Path, values: dict) -> list[Path]:
    """Return the existing folders whose docstrings should be doctested.

    Args:
        root: The repository root.
        values: The parsed ``.rhiza/.env`` mapping.

    Returns:
        Each configured folder that exists, in order, without duplicates.

    Examples:
        The precedence is the whole point of this function, so it is worth one runnable
        example per rung. The environment is saved and restored because these lines
        execute in whatever process is running the doctests.

        >>> import os, tempfile
        >>> root = Path(tempfile.mkdtemp())
        >>> _ = (root / "src").mkdir()
        >>> _ = (root / "utils").mkdir()
        >>> saved = os.environ.pop(DOCTEST_FOLDERS_ENV, None)

        The variable wins, is whitespace-separated, and silently drops what does not
        exist — a configured folder a project has since renamed is not an error:

        >>> os.environ[DOCTEST_FOLDERS_ENV] = "src utils nope"
        >>> [p.name for p in doctest_folders(root, {})]
        ['src', 'utils']

        Unset, it falls back to ``SOURCE_FOLDER`` from ``.rhiza/.env``:

        >>> del os.environ[DOCTEST_FOLDERS_ENV]
        >>> [p.name for p in doctest_folders(root, {"SOURCE_FOLDER": "utils"})]
        ['utils']

        …and to ``src`` when that is absent too:

        >>> [p.name for p in doctest_folders(root, {})]
        ['src']

        Duplicates collapse, so a folder named twice is walked once:

        >>> os.environ[DOCTEST_FOLDERS_ENV] = "src src"
        >>> [p.name for p in doctest_folders(root, {})]
        ['src']

        Nothing configured that exists yields an empty list, which is what makes
        :func:`test_doctests` skip rather than pass vacuously:

        >>> os.environ[DOCTEST_FOLDERS_ENV] = "nope"
        >>> doctest_folders(root, {})
        []

        >>> _ = os.environ.pop(DOCTEST_FOLDERS_ENV, None)
        >>> if saved is not None:
        ...     os.environ[DOCTEST_FOLDERS_ENV] = saved
    """
    configured = os.environ.get(DOCTEST_FOLDERS_ENV, "").split()
    if not configured:
        configured = [values.get("SOURCE_FOLDER") or "src"]

    folders: list[Path] = []
    for name in configured:
        path = root / name
        if path.is_dir() and path not in folders:
            folders.append(path)
    return folders


def configured_label(values: dict) -> str:
    """Return the folder spec as it was configured, for the skip message.

    The skip has to name what was *asked for* rather than what was found — "no doctest
    folder found (looked for: utils)" is actionable and "no doctest folder found" is not.
    That means re-reading the same precedence :func:`doctest_folders` applied, which is
    why this is a function rather than a local.

    Args:
        values: The parsed ``.rhiza/.env`` mapping.

    Returns:
        The environment variable, else ``SOURCE_FOLDER``, else ``src``.
    """
    return os.environ.get(DOCTEST_FOLDERS_ENV) or values.get("SOURCE_FOLDER") or "src"
