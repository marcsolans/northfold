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


def _split_tags(tags: list[str] | None) -> tuple[set[str], set[str]]:
    """``["smoke", "!llm"]`` → ({"smoke"}, {"llm"}): plain tags include, ``!``-prefixed tags exclude."""
    include = {t for t in tags or [] if t and not t.startswith("!")}
    exclude = {t[1:] for t in tags or [] if t.startswith("!") and len(t) > 1}
    return include, exclude


async def run_member_evals(member_dir: Path, tags: list[str] | None = None) -> dict[str, Any]:
    evals_dir = member_dir / "evals"
    if not evals_dir.is_dir():
        return {"total": 0, "passed": 0, "failed": 0, "total_duration": 0.0, "results": []}
    # Every YAML file under evals/ is a suite (the engine CLI only picks "eval*.yaml" by name).
    files = sorted(p for p in evals_dir.rglob("*.y*ml") if p.suffix in (".yaml", ".yml") and p.name != "evalconf.yaml")
    include, exclude = _split_tags(tags)
    skipped = 0
    try:
        evals = [e for f in files for e in collect_evals(f, tags=include or None)]
        if exclude:
            kept = [e for e in evals if not exclude & set(e.tags)]
            skipped, evals = len(evals) - len(kept), kept
        names = [e.name for e in evals]
        if len(names) != len(set(names)):
            raise ValueError("Hay evals con el mismo nombre en varios archivos")
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
        "skipped": skipped,
        "total_duration": summary.total_duration,
        "results": [await dump_result(r) for r in summary.results],
    }
