# Messer on-prem connector agent. Build from the repository root:
#   docker build -f services/connector-agent/Dockerfile -t messer/connector-agent .
# Run:
#   docker run -d --restart unless-stopped -v messer-agent:/etc/messer-agent \
#     -v $(pwd)/agent.yaml:/etc/messer-agent/agent.yaml:ro messer/connector-agent \
#     enroll-and-run --api https://app.messer.eu --token <TOKEN>
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    MESSER_AGENT_STATE_DIR=/etc/messer-agent MESSER_AGENT_CONFIG=/etc/messer-agent/agent.yaml

WORKDIR /opt/messer-agent
COPY packages/connectors/pyproject.toml packages/connectors/pyproject.toml
COPY packages/connectors/src packages/connectors/src
COPY services/connector-agent/pyproject.toml services/connector-agent/pyproject.toml
COPY services/connector-agent/src services/connector-agent/src

# Only messer_connectors.sql is used at runtime: install the two packages without the platform kernel,
# then the agent's real runtime dependencies.
RUN pip install --no-deps ./packages/connectors ./services/connector-agent \
 && pip install "psycopg[binary]>=3.2.3" "pymysql>=1.1.1" "python-tds>=1.16" "websockets>=13" "pyyaml>=6.0.2" "certifi" \
 && useradd --system --uid 10001 --home /etc/messer-agent messer \
 && mkdir -p /etc/messer-agent && chown messer /etc/messer-agent

USER messer
VOLUME ["/etc/messer-agent"]
ENTRYPOINT ["messer-connector-agent"]
CMD ["run"]
