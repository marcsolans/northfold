"""Database objects of a knowledge base (owner connection).

For a knowledge base with id ``<uuid>`` and ``<hex>`` = its random suffix:

* schema ``kb_<hex>`` holding its tables and three owner-defined ``security_barrier`` views over the
  shared tables, filtered by ``kb_id``: ``documents`` (files), ``chunks`` (with the embedding cast to the
  knowledge base dimension) and ``entities`` (merged golden records);
* NOLOGIN role ``kb_<hex>_reader``: USAGE on the schema, SELECT on every table/view (default privileges
  for future tables), member of ``messer_kb_reader`` (EXECUTE on ``kb_*_search``), granted to
  ``messer_readonly`` without inheritance (the console switches to it with ``SET LOCAL ROLE``);
* partial HNSW index ``ix_kb_chunks_vec_<hex>`` on ``public.kb_chunks ((embedding::vector(dim)))
  WHERE kb_id = <uuid>``, built concurrently outside the creating transaction.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import get_owner_engine
from messer_common.db.models import KnowledgeBase
from messer_common.knowledge.sqlcheck import quote_ident, quote_literal
from messer_common.logging import get_logger
from messer_common.settings import get_settings

log = get_logger("messer.api.knowledge.provisioning")

KB_GROUP_ROLE = "messer_kb_reader"


def kb_hex(kb: KnowledgeBase) -> str:
    return kb.schema_name.removeprefix("kb_")


def vector_index_name(kb: KnowledgeBase) -> str:
    return f"ix_kb_chunks_vec_{kb_hex(kb)}"


def readonly_role() -> str:
    username = make_url(get_settings().database_readonly_url).username
    if not username:
        raise RuntimeError("DATABASE_READONLY_URL must include a username")
    return username


async def _server_version(session: AsyncSession) -> int:
    return int((await session.execute(text("SHOW server_version_num"))).scalar_one())


def view_statements(kb: KnowledgeBase) -> list[str]:
    schema = quote_ident(kb.schema_name)
    kb_lit = quote_literal(str(kb.id)) + "::uuid"
    dim = int(kb.embedding_dim)
    return [
        f"""CREATE OR REPLACE VIEW {schema}.documents WITH (security_barrier = true) AS
            SELECT f.id, f.filename, f.mime, f.size, f.source, f.status, f.pages, f.chunk_count, f.table_id,
                   f.external_id, f.metadata, f.created_at
            FROM public.kb_files f WHERE f.kb_id = {kb_lit}""",
        f"""CREATE OR REPLACE VIEW {schema}.chunks WITH (security_barrier = true) AS
            SELECT c.id, c.file_id, f.filename, c.ordinal, c.content, c.heading, c.page_from, c.page_to,
                   c.token_count, c.metadata, (c.embedding::vector({dim})) AS embedding
            FROM public.kb_chunks c JOIN public.kb_files f ON f.id = c.file_id
            WHERE c.kb_id = {kb_lit}""",
        f"""CREATE OR REPLACE VIEW {schema}.entities WITH (security_barrier = true) AS
            SELECT e.id, e.entity_type, e.match_key, e.method, e.score, e.records, e.golden_record,
                   e.decided_at AS merged_at
            FROM public.kb_entities e WHERE e.kb_id = {kb_lit} AND e.status = 'merged'""",
    ]


async def provision(session: AsyncSession, kb: KnowledgeBase) -> None:
    """Create schema, reader role, views and grants in the caller's (owner) transaction."""
    schema = quote_ident(kb.schema_name)
    reader = quote_ident(kb.reader_role)
    statements = [
        f"CREATE SCHEMA {schema}",
        f"COMMENT ON SCHEMA {schema} IS {quote_literal(f'Messer knowledge base {kb.id}')}",
        f"CREATE ROLE {reader} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION",
        f"COMMENT ON ROLE {reader} IS {quote_literal(f'Read-only access to Messer knowledge base {kb.id}')}",
        f"GRANT {quote_ident(KB_GROUP_ROLE)} TO {reader}",
        f"GRANT USAGE ON SCHEMA {schema} TO {reader}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT ON TABLES TO {reader}",
        *view_statements(kb),
        f"GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {reader}",
    ]
    for statement in statements:
        await session.execute(text(statement))
    grant = f"GRANT {reader} TO {quote_ident(readonly_role())}"
    if await _server_version(session) >= 160000:
        grant += " WITH INHERIT FALSE, SET TRUE"
    await session.execute(text(grant))


async def deprovision(session: AsyncSession, kb: KnowledgeBase) -> None:
    """Drop schema (tables, views) and reader role in the caller's (owner) transaction."""
    await session.execute(text(f"DROP SCHEMA IF EXISTS {quote_ident(kb.schema_name)} CASCADE"))
    exists = (await session.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": kb.reader_role})).first()
    if exists:
        await session.execute(text(f"DROP ROLE {quote_ident(kb.reader_role)}"))


async def _autocommit(statement: str) -> None:
    async with get_owner_engine().connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text("SET lock_timeout = '10s'"))
        try:
            await conn.execute(text(statement))
        finally:
            await conn.execute(text("RESET lock_timeout"))


async def ensure_vector_index(kb: KnowledgeBase) -> bool:
    """Create the knowledge base's partial HNSW index if missing (or invalid). Never raises."""
    name = vector_index_name(kb)
    try:
        async with get_owner_engine().connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT i.indisvalid FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relname = :n"
                    ),
                    {"n": name},
                )
            ).first()
            await conn.rollback()
        if row is not None and row[0]:
            return True
        if row is not None:
            await _autocommit(f"DROP INDEX CONCURRENTLY IF EXISTS public.{quote_ident(name)}")
        await _autocommit(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {quote_ident(name)} ON public.kb_chunks "
            f"USING hnsw ((embedding::vector({int(kb.embedding_dim)})) vector_cosine_ops) "
            f"WHERE kb_id = {quote_literal(str(kb.id))}::uuid"
        )
        return True
    except Exception as exc:
        log.warning("knowledge.vector_index_failed", kb_id=str(kb.id), error=str(exc)[:300])
        return False


async def drop_vector_index(kb_schema_name: str) -> None:
    name = f"ix_kb_chunks_vec_{kb_schema_name.removeprefix('kb_')}"
    try:
        await _autocommit(f"DROP INDEX CONCURRENTLY IF EXISTS public.{quote_ident(name)}")
    except Exception as exc:
        log.warning("knowledge.vector_index_drop_failed", index=name, error=str(exc)[:300])


def new_kb_identifiers() -> tuple[str, str]:
    """(schema_name, reader_role) for a new knowledge base."""
    suffix = uuid.uuid4().hex
    return f"kb_{suffix}", f"kb_{suffix}_reader"
