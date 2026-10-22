# Added by Messer: standalone platform for exported projects (see NOTICE).
"""Run the standalone platform: ``python -m messer.platform.standalone [--host 0.0.0.0] [--port 8000]``."""

from __future__ import annotations

import argparse
import os


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Messer standalone platform for exported projects.")
    parser.add_argument("--host", default=os.environ.get("MESSER_STANDALONE_HOST", "0.0.0.0"))  # noqa: S104
    parser.add_argument("--port", type=int, default=int(os.environ.get("MESSER_STANDALONE_PORT", "8000")))
    args = parser.parse_args(argv)

    import uvicorn

    from .app import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level=os.environ.get("LOG_LEVEL", "info").lower())


if __name__ == "__main__":
    main()
