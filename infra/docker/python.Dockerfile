# Messer Python services (api, runtime, worker, scheduler) — one image recipe, one package per build.
#   docker build -f infra/docker/python.Dockerfile --build-arg PACKAGE=messer-runtime .
# Build context: repository root. The whole uv workspace is copied because uv validates every member.
ARG PYTHON_IMAGE=python:3.12-slim

FROM ${PYTHON_IMAGE} AS build
ARG PACKAGE=messer-api
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends git build-essential && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock .python-version .env.example ./
COPY packages packages
COPY services services
COPY apps/api apps/api
COPY infra/migrations infra/migrations
RUN uv sync --frozen --no-dev --package "${PACKAGE}"

FROM ${PYTHON_IMAGE}
ENV PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH" MESSER_ENV=production
RUN apt-get update && apt-get install -y --no-install-recommends git libpq5 ca-certificates \
    && rm -rf /var/lib/apt/lists/* && useradd --create-home --uid 10001 messer \
    && mkdir -p /data && chown messer:messer /data
WORKDIR /app
COPY --from=build /app /app
USER messer
