"""Test configuration for pytest-rhiza's own suite.

``pytester`` is what lets a plugin's tests run pytest inside pytest: each test gets a
throwaway directory, and assertions are made about the inner run's outcomes. That is the
only honest way to test fixtures whose whole job is to answer "which repository is this".
"""

pytest_plugins = ["pytester"]
