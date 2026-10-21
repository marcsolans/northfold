# Messer

[![PyPI](https://img.shields.io/pypi/v/messer)](https://pypi.org/project/messer/)
[![Python](https://img.shields.io/pypi/pyversions/messer)](https://pypi.org/project/messer/)
[![License](https://img.shields.io/github/license/messer/messer)](LICENSE)

Simple, performant, battle-tested framework for building reliable AI applications.

Messer gives you **Agents** (autonomous reasoning) and **Workflows** (explicit pipelines) behind one interface. No hidden magic: async functions, Pydantic validation, and event-driven streaming. If you know `async`/`await`, you already know how it works.

**Documentation:** [docs.messer.local](https://docs.messer.local)

---

## Quickstart

```bash
pip install messer
```

```python
import asyncio

from messer import Agent
from messer.tools import WebSearch

agent = Agent(
    name="assistant",
    model="anthropic/claude-sonnet-4-6",
    tools=[WebSearch()],
    max_tokens=1024,
)

async def main():
    result = await agent(prompt="What's new in AI this week?").collect()
    print(result.output)

asyncio.run(main())
```

Set `ANTHROPIC_API_KEY` (or the key for your chosen provider) in a `.env` file or your environment.

Workflows use the same interface:

```python
import asyncio
import httpx

from messer import Workflow
from messer.state import get_run_context

async def fetch(url: str) -> str:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        return (await client.get(url)).text

workflow = (
    Workflow(name="scraper")
    .step(fetch)
    .step(
        lambda content: len(content),
        content=lambda: get_run_context().step_span("fetch").output,
    )
)

async def main():
    result = await workflow.collect(url="https://messer.local")
    print(result.output)

asyncio.run(main())
```

See the [Quickstart](https://docs.messer.local/quickstart) for the full app flow (`messer create` → `messer start`).

---

## Why Messer

**The most performant agent framework.** In overhead benchmarks against LangGraph, CrewAI, the OpenAI Agents SDK, PydanticAI, and Agno (observability on both sides, faked LLMs), Messer runs agent loops several times faster with a fraction of the memory. See [Benchmarks](#benchmarks).

**Small and hackable.** The core framework is under 10k lines. Easy to read, modify, and fork. Other frameworks are bloated with legacy, indirection, and abstraction.

**One interface.** Agents, Workflows, and Tools share the same calling convention and event stream. Compose them freely.

**Human in the loop.** [Approval gates](https://docs.messer.local/human-in-the-loop/approval-gates) and [`suspend()`](https://docs.messer.local/human-in-the-loop/suspend) pause any run for a human, persist state, and resume across process restarts. Works on agents, workflow steps, and tools.

**Provider-agnostic.** Swap models by changing a string (`anthropic/claude-sonnet-4-6` → `openai/gpt-5.5`). Built-in `FallbackModel` chains providers for automatic failover.

---

## Features

| | |
|---|---|
| [Memory & compaction](https://docs.messer.local/agents/memory) | Persistent context with strategies to stay under the context window |
| [Tools](https://docs.messer.local/agents/tools) & [MCP](https://docs.messer.local/agents/mcp) | Built-in tool library, your own functions, any MCP server |
| [Structured output](https://docs.messer.local/agents/structured-output) | Typed Pydantic models instead of raw text |
| [Skills](https://docs.messer.local/agents/skills) | Reusable tool packages the agent loads on demand |
| [Tracing](https://docs.messer.local/core-concepts/tracing) | Full span traces, exportable over OTLP |
| [Evals](https://docs.messer.local/evals) | Declarative YAML evaluation suite with built-in validators |
| [Deployment](https://docs.messer.local/deployment) | Run locally with `messer start`, ship to the platform or self-host |

Install extras as needed:

```bash
pip install 'messer[server]'      # HTTP serving
pip install 'messer[documents]'   # PDF, Excel, Word
pip install 'messer[evals]'       # evals CLI
pip install 'messer[all]'         # everything
```

---

## Benchmarks

Pure framework-overhead benchmarks: trivial handlers, faked LLM calls, observability on both sides.

| Metric (single tool call) | Messer | LangGraph + LangSmith | CrewAI |
|---|---|---|---|
| p50 latency | **1.1 ms** | 5.2 ms | 3.2 ms |
| memory / run | **2.2 KB** | 110 KB | 10 KB |
| throughput @ c=10 | **1716/s** | 224/s | 31/s |

Reproduce with [`benchmarks/README.md`](benchmarks/README.md). Full suite covers LangGraph, CrewAI, Agno, PydanticAI, OpenAI Agents SDK, and Google ADK.

---

## Full app

The CLI scaffolds and runs a complete application (UI + API + workforce of Python agents/workflows):

```bash
messer create my-project
cd my-project
messer start
```

Deploy by connecting the repo to the [Messer Platform](https://app.messer.local), or self-host the components yourself. See [deployment docs](https://docs.messer.local/deployment).

---

## Development

```bash
git clone https://github.com/marcsolans/northfold.git
cd messer
uv sync --dev
uv run pytest
```

Contributor reference: [`CLAUDE.md`](CLAUDE.md), [`benchmarks/README.md`](benchmarks/README.md).

---

## Documentation

[docs.messer.local](https://docs.messer.local)

## Contributing

Pull requests and issues welcome.

## License

Apache 2.0. See [LICENSE](LICENSE).
