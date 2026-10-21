import sys


def codegen_cmd(*args: str) -> list[str]:
    """Build argv for ``python -m messer.codegen ...`` using the active interpreter."""
    return [sys.executable, "-m", "messer.codegen", *args]
