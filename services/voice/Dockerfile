# Messer voice gateway: browser WebSocket sessions, Twilio/Telnyx phone media, LiveKit rooms. Build context:
# repository root. Agents never run here — every turn is a run of the runtime service.
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
RUN uv sync --frozen --no-dev --package messer-voice

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH" MESSER_ENV=production \
    MESSER_VOICE_RECORDING_DIR=/data/voice-recordings
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 ca-certificates \
    && rm -rf /var/lib/apt/lists/* && useradd --create-home --uid 10001 messer \
    && mkdir -p /data/voice-recordings && chown -R messer:messer /data
WORKDIR /app
COPY --from=build /app /app
USER messer
EXPOSE 8300
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8300/health').status==200 else 1)"
CMD ["python", "-m", "messer_voice"]
