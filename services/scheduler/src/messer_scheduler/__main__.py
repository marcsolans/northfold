import asyncio

from messer_common.logging import configure_logging

from .core import run_forever

configure_logging("scheduler")
asyncio.run(run_forever())
