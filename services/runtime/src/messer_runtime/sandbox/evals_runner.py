"""Run a workforce member's YAML evals inside the sandbox with the engine eval runner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from messer.evals.models import EvalResult, EvalSummary
from messer.evals.reporters import Reporter
from messer.evals.runner import run_evals
from messer.evals.utils import collect_evals, dump_result


class _Silent(Reporter):
    """No terminal output: results are returned as JSON to the runtime."""

    async def result(self, result: EvalResult) -> None:
        return None

    def finish(self, summary: EvalSummary) -> None:
        return None


async def run_member_evals(member_dir: Path, tags: list[str] | None = None) -> dict[str, Any]:
    evals_dir = member_dir / "evals"
    if not evals_dir.is_dir():
        return {"total": 0, "passed": 0, "failed": 0, "total_duration": 0.0, "results": []}
    try:
        evals = collect_evals(evals_dir, tags=set(tags) if tags else None)
    except (ValueError, FileNotFoundError, ImportError, SyntaxError) as exc:
        return {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "total_duration": 0.0,
            "results": [],
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
    summary = await run_evals(evals, capture=True, reporter=_Silent(), max_concurrency=4)
    return {
        "total": summary.total,
        "passed": summary.passed,
        "failed": summary.failed,
        "total_duration": summary.total_duration,
        "results": [await dump_result(r) for r in summary.results],
    }
