# Messer

**Describe your problem. Messer builds the solution and puts it into production.**

Messer is an enterprise platform for building, managing and using AI solutions: a Composer that turns a problem
description into agents, workflows, knowledge bases and interfaces; a Studio to refine them; one-click deployment
with environments, versions and evals; and governance (organizations, roles, SSO, budgets, analytics, audit,
EU data residency). Everything built in Messer is exportable code.

## Quick start (local)

Requirements: Python 3.12 + [uv](https://docs.astral.sh/uv/), Node 22 + pnpm, Postgres 16 with pgvector, Redis 7,
Mailpit (or Docker for all of them).

```bash
cp .env.example .env            # every key is optional; missing integrations run in demo/test mode
uv sync --all-packages && pnpm install
make bootstrap                  # migrations + plans, model prices, templates, superadmin, first organization
make api                        # http://localhost:8000/api/docs
make web                        # http://localhost:3000
```

With Docker: `docker compose up --build` starts Postgres (pgvector), Redis, Mailpit, migrations + bootstrap, the
API, the data plane services and the web app.

## Repository

See `CLAUDE.md` for the architecture, commands and conventions, `DECISIONS.md` for design decisions,
`PROGRESS.md` for status, pending keys and blockers, and `docs/` for user, API and operations documentation.

## License

Apache License 2.0. Parts of the engine derive from an Apache-2.0 open-source framework; see `NOTICE` and
`LICENSE_REVIEW.md`.
