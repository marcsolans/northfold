# Messer MCP server (streamable HTTP on :8400). Build context: repository root. A thin client of the platform
# API: every tool call is an API request made with the caller's own bearer token (API key or OAuth token).
FROM python:3.12-slim AS build
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock .python-version .env.example ./
COPY packages packages
COPY services services
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/api/src apps/api/src
RUN uv sync --frozen --no-dev --package messer-mcp

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH" MESSER_ENV=production MESSER_MCP_HOST=0.0.0.0
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* && useradd --create-home --uid 10001 messer
WORKDIR /app
COPY --from=build /app /app
USER messer
EXPOSE 8400
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8400/healthcheck').status==200 else 1)"
CMD ["python", "-m", "messer_mcp"]
