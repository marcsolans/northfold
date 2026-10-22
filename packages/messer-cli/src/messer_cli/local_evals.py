"""Run one member's YAML evals with the engine eval runner (``messer evals run --local`` starts this in a child
process whose environment points the member at the local platform). Prints one JSON summary on stdout.

    python -m messer_cli.local_evals <project_dir> <member> [--tags smoke,fast]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Any


async def run_member_evals(member_dir: Path, tags: set[str] | None) -> dict[str, Any]:
    from messer.evals.models import EvalResult, EvalSummary
    from messer.evals.reporters import Reporter
    from messer.evals.runner import run_evals
    from messer.evals.utils import collect_evals, dump_result

    class Silent(Reporter):
        async def result(self, result: EvalResult) -> None:
            return None

        def finish(self, summary: EvalSummary) -> None:
            return None

    evals_dir = member_dir / "evals"
    empty: dict[str, Any] = {"total": 0, "passed": 0, "failed": 0, "results": []}
    if not evals_dir.is_dir():
        return empty
    files = sorted(p for p in evals_dir.rglob("*") if p.suffix in (".yaml", ".yml") and p.name != "evalconf.yaml")
    try:
        evals = [e for f in files for e in collect_evals(f, tags=tags)]
    except (ValueError, FileNotFoundError, ImportError, SyntaxError) as exc:
        return {**empty, "error": {"type": type(exc).__name__, "message": str(exc)}}
    summary = await run_evals(evals, capture=True, reporter=Silent(), max_concurrency=4)
    return {
        "total": summary.total,
        "passed": summary.passed,
        "failed": summary.failed,
        "results": [await dump_result(r) for r in summary.results],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir")
    parser.add_argument("member")
    parser.add_argument("--tags", default="")
    args = parser.parse_args(argv)
    project_dir = Path(args.project_dir).resolve()
    sys.path.insert(0, str(project_dir))
    tags = {t.strip() for t in args.tags.split(",") if t.strip()} or None
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink):  # keep stdout for the JSON document only
        result = asyncio.run(run_member_evals(project_dir / "workforce" / args.member, tags))
    sys.stdout.write(json.dumps(result, default=str) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
