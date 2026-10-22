"""``python -m messer_voice`` — serve the voice gateway with uvicorn."""

from __future__ import annotations

import uvicorn

from .config import get_voice_settings


def main() -> None:
    settings = get_voice_settings()
    uvicorn.run(
        "messer_voice.main:app",
        host=settings.messer_voice_host,
        port=settings.messer_voice_port,
        proxy_headers=True,
        ws="websockets-sansio",
        log_level="info",
    )


if __name__ == "__main__":
    main()
