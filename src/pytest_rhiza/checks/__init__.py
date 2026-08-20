"""The check modules, collected with ``--pyargs`` rather than by entry point.

A ``pytest11`` plugin can contribute fixtures, hooks and options; it cannot contribute
tests. So the checks are named explicitly on the command line:

.. code-block:: bash

    pytest --pyargs pytest_rhiza.checks.test_readme pytest_rhiza.checks.test_pyproject

**One module per file the template used to sync**, names unchanged. That is deliberate:
selection stays a property of the project's *layer set*, so a Python project never names
the Cargo checks and nothing has to sniff for manifests at runtime to decide what applies.

Where that resolution lives changed at rhiza v1.4. Up to v1.3 each bundle shipped a make
fragment appending to a ``RHIZA_CHECKS`` accumulator; the synced make layer is gone, and
the list is now derived from ``[tool.rhiza-task] layers`` in the consumer's
``pyproject.toml``. The ownership model is unchanged — the column below still says which
bundle owns each assertion.

| module | bundle that names it | replaces |
| --- | --- | --- |
| ``test_readme`` | ``core`` | ``.rhiza/tests/test_readme.py`` |
| ``test_release_tags`` | ``core`` | ``.rhiza/tests/test_release_tags.py`` |
| ``test_pyproject`` | ``python-core`` | ``.rhiza/tests/test_pyproject.py`` |
| ``test_docstrings`` | ``python-core`` | ``.rhiza/tests/test_docstrings.py`` |
| ``test_readme_validation`` | ``tests`` | ``.rhiza/tests/test_readme_validation.py`` |
| ``test_cargo_toml`` | ``rust-core`` | ``.rhiza/tests/test_cargo_toml.py`` |
| ``test_go_module`` | ``go-core`` | ``.rhiza/tests/test_go_module.py`` |
"""
