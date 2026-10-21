"""Root pytest configuration for the platform packages (the engine has its own config in packages/messer-core)."""

from messer_common.testing import configure_test_env

configure_test_env()

pytest_plugins = ["messer_common.testing.fixtures", "messer_runtime.testing"]
