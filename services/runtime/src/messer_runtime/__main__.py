"""``python -m messer_runtime`` — serve the runtime with uvicorn."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "messer_runtime.main:app",
        host=os.environ.get("MESSER_RUNTIME_HOST", "0.0.0.0"),  # noqa: S104 - container entrypoint
        port=int(os.environ.get("MESSER_RUNTIME_PORT", "8100")),
        proxy_headers=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
