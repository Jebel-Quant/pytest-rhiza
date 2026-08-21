"""Repo-local developer tooling, deliberately outside the distribution.

Nothing here ships in the wheel. ``[tool.hatch.build.targets.wheel]`` packages
``src/pytest_rhiza`` only, which is the point: this package is installed into every
rhiza-managed repo's test environment, and a gate runner is of no use there.

It is a package rather than a loose script folder so ``tests/test_readme_gates.py`` can
import :mod:`scripts.gates` by name — see ``pythonpath = .`` in ``pytest.ini``.
"""
