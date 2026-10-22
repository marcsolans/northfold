# Cross-workstream contracts

Interfaces shared between areas of the codebase. Implement them exactly; change them only with a note in
DECISIONS.md.

## 1. Plans (public) — owner: business

`GET /api/v1/plans` (no auth) →

```json
[{"id": "pro", "name": "Pro", "description": "…", "price_month_eur": "199.00", "price_year_eur": "1990.00",
  "price_is_starting": false, "self_serve": true, "sort_order": 2,
  "limits": {"seats": 10, "projects": 5, "runs_month": 20000, "credits_month": 10000, "storage_gb": 50,
             "features": ["public_chat", "api", "connectors", "channels", "deployments"]}}]
```
Only `public = true` plans, ordered by `sort_order`. `-1` means unlimited. Feature keys and labels:
`messer_common.plans.FEATURES`. `GET /api/v1/credit-packs` returns `CREDIT_PACKS`.

## 2. Plan limits and credits — owner: business

`messer_api.services.limits`:
- `async def require_feature(session, org_id, feature: str) -> None` → raises `PlanLimitExceeded` (402, details
  `{"feature": ..., "upgrade_to": <cheapest plan with it>}`).
- `async def require_capacity(session, org_id, limit_key: str, used: int) -> None` (e.g. `"projects"`).

`messer_common.credits` (data plane safe, used by the runtime):
- `async def balance(session, org_id) -> Decimal`  (sum of `credit_ledger.amount`)
- `async def charge_usage(session, *, org_id, run_id, project_id, cost_usd, credits, note) -> None`
  (idempotent on `idempotency_key = f"usage:{run_id}"`)

## 3. Knowledge (shared with the runtime and connectors) — owner: knowledge

Data-plane code lives in `messer_common.knowledge` (no imports from `messer_api`):
- `embeddings.get_embedder(model: str) -> Embedder` with `dim: int`, `async def embed(texts: list[str]) -> list[list[float]]`.
  Model `"hash-384"` is a deterministic offline embedder (used in tests and when no model is available).
- `search.search(session, *, kb_id, query, mode: Literal["vector","keyword","hybrid"]="hybrid", k=8) -> list[SearchHit]`
  where `SearchHit` = `{chunk_id, file_id, filename, content, heading, page_from, page_to, score, metadata}`.
- `sql.run_readonly(*, kb_id, sql, params: list, limit=settings.sql_row_limit, explain=False, role: str | None) -> SqlResult`
  (`{columns: [...], rows: [[...]], row_count, truncated, elapsed_ms, plan?}`) — read-only role, per-KB reader role,
  `statement_timeout`, row limit, `embed('text')` placeholder expansion, policies applied for `role`.

Control-plane helpers in `messer_api.services.knowledge` used by connectors:
- `async def ingest_bytes(session, *, org_id, kb_id, filename, data: bytes, mime: str | None, source: str,
  connection_id: UUID | None = None, external_id: str | None = None, uploaded_by: UUID | None = None) -> KbFile`
  (stores the file, creates/updates the `kb_files` row — same `external_id` replaces content — and enqueues
  `Jobs.INGEST_FILE`).
- `async def upsert_table(session, *, org_id, kb_id, table: str, columns: list[dict], rows: list[dict],
  primary_key: list[str], source: str = "sync", sync_id: UUID | None = None) -> KbTable`
  (`columns`: `{"name", "type": "text|integer|numeric|boolean|date|timestamp|json", "nullable", "comment"}`;
  creates or evolves the table in the KB schema, merges on primary key).

## 4. Connectors (shared with the runtime) — owner: connectors

Package `packages/connectors` → `messer_connectors` (depends only on `messer_common`):
- `registry.get_adapter(key: str) -> ConnectorAdapter`, `registry.catalog() -> list[ConnectorSpec]`
- `ConnectorAdapter.actions() -> list[ActionSpec]` with `ActionSpec{name, title, description, input_schema (JSON
  Schema), side_effect: bool}` — side-effect actions require approval by default.
- `async ConnectorAdapter.run_action(ctx: ConnectionContext, action: str, args: dict) -> Any`
  where `ConnectionContext{connection_id, org_id, credentials: dict, config: dict, demo: bool}`.
- `async credentials.load_context(session, connection_id) -> ConnectionContext` (decrypts, refreshes OAuth tokens).
Demo connections (`connections.demo = true`) return realistic sample data from fixtures shipped in the package,
clearly labelled as demo in the UI.

### 4.1 Additions (connectors workstream)

- `ConnectionContext` also carries `connector_key: str` and `agent_id: UUID | None` (connections routed through an
  on-prem agent). `ConnectorAdapter.actions_for(ctx)` (databases) adds `execute` (side effect) only when the
  connection is not read-only; `actions()` stays the static list.
- `ConnectorSpec{key, name, category, auth_type, description, capabilities{actions, sync, sync_resources, events,
  introspection, demo, agent}, icon, oauth{provider, authorize_url, token_url, scopes}, config_fields, events}`.
  `events` is `list[{name, event, title, title_en, description, delivery: "poll"|"push"}]`, e.g.
  `{"name": "gmail.new_email", "event": "new_email", …}`; served by `GET /api/v1/connectors[/{key}]` (`events`).
- Errors: adapters raise `messer_connectors.base.ConnectorError` subclasses (`code`, `status_code`, `details`):
  `ConnectorAuthError` (reconnect), `InvalidArguments`, `ReadOnlyViolation`, `ProviderError`, `AgentUnavailable`…
- Agent RPC from any process: `await messer_connectors.agent_rpc.call(agent_id, method, params, timeout_s=…)`
  (Redis channel `agent-rpc:<agent_id>` → API instance holding the agent's WebSocket → reply list
  `agent-rpc-reply:<request_id>`). Methods: `ping`, `sql.ping|query|introspect|fetch_batch`, `files.list|read`.
- Credentials for the engine (`Integration.resolve()`): `GET /api/v1/orgs/{org_id}/connections/{id}/credentials`
  authorized by `Authorization: Bearer <MESSER_SERVICE_TOKEN>`, an org API key with scope `connections:read`, or a
  token signed with `security.sign_payload({"typ": "runtime", "org_id": …})`. Returns
  `{token, token_type, expires_at, provider, scopes, demo, agent_id, config, credentials}` (refreshed).

### 4.2 Connector events (workflow triggers)

Adapters with `capabilities.events` implement
`async poll_events(ctx, event: str, cursor: str | None) -> tuple[list[dict], str | None]`; each item is
`{"id": <stable provider id>, "event", "occurred_at", "data": {...}}`. `cursor=None` returns `([], baseline)` — no
backfill. Cursors are opaque strings stored by the caller.

| Trigger event (`config.event`) | Adapter event | Delivery | Cursor | Notes |
|---|---|---|---|---|
| `gmail.new_email` | `new_email` | poll | `internalDate` (ms) | inbox; `config.event_query` adds a Gmail filter |
| `outlook.new_email` | `new_email` | poll | `receivedDateTime` | inbox |
| `hubspot.new_contact` | `new_contact` | poll | `createdate` (ms) | |
| `salesforce.new_record` | `new_record` | poll | `CreatedDate` | object `config.event_object` (default Lead) |
| `google_drive.new_file` | `new_file` | poll | `createdTime` | folder `config.event_folder_id` (optional) |
| `webhooks.received` | `received` | push | `created_at\|id` | HMAC-verified request to `/api/v1/webhooks/connections/{id}` |
| `<connector>.sync_completed` | — | push | — | after every sync run of a syncable connector |

Emission: the scheduler task `connector_events.poll` (every 60 s) polls only connections referenced by enabled
`connector_event` triggers (`config.connection_id`, `config.event` = name or `*`), keeps cursors in
`connections.config["_event_cursors"]` (hidden from the API) and calls
`messer_common.triggers.emit(session, org_id=…, event="<connector>.<event>", connection_id=…, event_id=<id>,
payload={connector, connection_id, event, event_id, occurred_at, data, [from, subject, snippet, email]})`.
Push events call `emit` when they happen. Inbound webhook events are also stored in `connector_events` (30-day
retention) and published on the Redis channel `connector-events`.

## 5. Model access (shared) — owner: runtime

All model calls go through the runtime **model gateway** (`POST {MESSER_RUNTIME_URL}/internal/v1/orgs/{org_id}/proxies/anthropic/v1/messages`,
Anthropic Messages API compatible, streaming supported) authenticated with a service or per-run token.
`messer_common.llm.complete(...)` (owner: runtime) is the helper for control-plane features (Composer, Guard, evals
judges, playbook generation). Without `ANTHROPIC_API_KEY`, the gateway serves the deterministic demo model
`messer/demo`.

## 6. Activation checklist — owner: website/onboarding

`GET /api/v1/onboarding/checklist` → `{"steps": [{"key": "describe"|"template"|"data"|"test"|"deploy", "done": bool, "href": str}], "complete": bool}`
computed from real data (projects, kb files/connections, runs, deployments).
