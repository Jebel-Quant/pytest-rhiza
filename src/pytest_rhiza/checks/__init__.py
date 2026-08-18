"""The check modules, collected with ``--pyargs`` rather than by entry point.

A ``pytest11`` plugin can contribute fixtures, hooks and options; it cannot contribute
tests. So the checks are named explicitly on the command line:

.. code-block:: bash

    pytest --pyargs pytest_rhiza.checks.test_readme pytest_rhiza.checks.test_pyproject

**One module per file the template used to sync**, names unchanged. That is deliberate:
selection stays where it already is — with the make fragment the owning bundle ships, one
``RHIZA_CHECKS +=`` line each — so a Python project never names the Cargo checks and
nothing has to sniff for manifests at runtime to decide what applies.

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
