# Messer platform API (control plane). Build context: repository root.
FROM python:3.12-slim AS build
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends git build-essential && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock .python-version .env.example ./
# The whole uv workspace is copied: uv validates every member's pyproject even for one package.
COPY packages packages
COPY services services
COPY apps/api apps/api
COPY infra/migrations infra/migrations
RUN uv sync --frozen --no-dev --package messer-api

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH" MESSER_ENV=production
RUN apt-get update && apt-get install -y --no-install-recommends git libpq5 ca-certificates \
    && rm -rf /var/lib/apt/lists/* && useradd --create-home --uid 10001 messer \
    && mkdir -p /data && chown messer:messer /data
WORKDIR /app
COPY --from=build /app /app
USER messer
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
CMD ["sh", "-c", "alembic -c infra/migrations/alembic.ini upgrade head && uvicorn messer_api.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
