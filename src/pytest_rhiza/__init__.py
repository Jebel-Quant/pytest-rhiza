"""The rhiza repository checks, packaged as a pytest plugin.

Two halves, because pytest treats them differently:

* :mod:`pytest_rhiza.plugin` is the ``pytest11`` entry point. It contributes the
  ``root``, ``logger`` and ``latest_tag`` fixtures to every session, which is what
  removes ``.rhiza/tests/conftest.py`` from consumer repositories.
* :mod:`pytest_rhiza.checks` holds the check modules themselves. An entry point cannot
  contribute *tests*, so these are collected explicitly with ``--pyargs``.

See ``README.md`` for the make wiring that replaces the synced folder.
"""

__all__ = ["__version__"]

# Kept in step with [project].version by bump-my-version via the
# [[tool.bumpversion.files]] entry in pyproject.toml.
__version__ = "0.3.0"
