"""Knowledge bases, files, chunks, tables, policies, entities, connectors and syncs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, CreatedMixin, IdMixin, OrgScoped, TimestampMixin, rls


class KnowledgeBase(Base, IdMixin, OrgScoped, TimestampMixin):
    __tablename__ = "knowledge_bases"

    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    embedding_model: Mapped[str] = mapped_column(String(120))
    embedding_dim: Mapped[int] = mapped_column()
    governance_mode: Mapped[str] = mapped_column(String(10), default="off", server_default="off")  # off|shadow|enforce
    schema_name: Mapped[str] = mapped_column(String(63), unique=True)
    reader_role: Mapped[str] = mapped_column(String(63))
    chunk_size_tokens: Mapped[int] = mapped_column(default=800, server_default="800")
    chunk_overlap_tokens: Mapped[int] = mapped_column(default=120, server_default="120")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


rls("knowledge_bases", read="viewer", write="builder", delete="admin")


class KbFile(Base, IdMixin, OrgScoped, CreatedMixin):
    __tablename__ = "kb_files"
    __table_args__ = (
        Index("ix_kb_files_kb", "kb_id", "created_at"),
        # Connector files are identified by external_id within a knowledge base (migration 0005).
        Index(
            "uq_kb_files_kb_external",
            "kb_id",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(Text)  # storage key
    filename: Mapped[str] = mapped_column(Text)
    mime: Mapped[str] = mapped_column(String(200))
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="upload", server_default="upload")  # upload|connector|agent
    connection_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # queued | parsing | chunking | embedding | indexing | ready | error
    status: Mapped[str] = mapped_column(String(20), default="queued", server_default="queued")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    pages: Mapped[int | None] = mapped_column(nullable=True)
    chunk_count: Mapped[int] = mapped_column(default=0, server_default="0")
    table_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)  # CSV/Excel files become tables
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", default=dict, server_default=text("'{}'::jsonb"))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


rls("kb_files", read="viewer", write="builder")


class KbChunk(Base, IdMixin, OrgScoped):
    __tablename__ = "kb_chunks"
    __table_args__ = (
        Index("ix_kb_chunks_kb_file", "kb_id", "file_id", "ordinal"),
        Index("ix_kb_chunks_tsv", "tsv", postgresql_using="gin"),
    )

    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"))
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_files.id", ondelete="CASCADE"))
    ordinal: Mapped[int] = mapped_column()
    content: Mapped[str] = mapped_column(Text)
    heading: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_from: Mapped[int | None] = mapped_column(nullable=True)
    page_to: Mapped[int | None] = mapped_column(nullable=True)
    token_count: Mapped[int] = mapped_column(default=0, server_default="0")
    # Untyped vector: each knowledge base fixes its own dimension (see embedding_dim).
    embedding: Mapped[Any] = mapped_column(Vector(), nullable=True)
    tsv: Mapped[Any] = mapped_column(TSVECTOR, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", default=dict, server_default=text("'{}'::jsonb"))
    edited_at: Mapped[datetime | None] = mapped_column(nullable=True)


rls("kb_chunks", read="viewer", write="builder")


class KbTable(Base, IdMixin, OrgScoped, TimestampMixin):
    __tablename__ = "kb_tables"
    __table_args__ = (UniqueConstraint("kb_id", "name", name="uq_kb_tables_kb_name"),)

    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(63))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    # {"columns": [{"name","type","nullable","pk","comment"}], "primary_key": [...], "foreign_keys": [...]}
    schema_json: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    row_count: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    source: Mapped[str] = mapped_column(String(20), default="upload", server_default="upload")  # upload|sync|manual
    sync_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


rls("kb_tables", read="viewer", write="builder")


class KbPolicy(Base, IdMixin, OrgScoped, TimestampMixin):
    __tablename__ = "kb_policies"

    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"))
    table: Mapped[str] = mapped_column(String(63))  # table name, or "*documents*" for chunks
    role: Mapped[str] = mapped_column(String(20))  # org role the policy applies to
    row_filter_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    # {"column": "redact" | "hash" | "truncate:4"}
    masked_columns: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    compliance_tags: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'::jsonb"))
    break_glass: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


rls("kb_policies", read="viewer", write="admin")


class KbEntity(Base, IdMixin, OrgScoped, TimestampMixin):
    """Suggested duplicate groups across sources, and their merge decision."""

    __tablename__ = "kb_entities"
    # One suggestion per match key and knowledge base (migration 0005).
    __table_args__ = (UniqueConstraint("kb_id", "match_key", name="uq_kb_entities_kb_match_key"),)

    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))  # company | person | generic
    match_key: Mapped[str] = mapped_column(Text)  # e.g. "tax_id:B12345678" or "similar:acme"
    method: Mapped[str] = mapped_column(String(20))  # deterministic | similarity
    score: Mapped[float] = mapped_column(default=1.0, server_default="1")
    # [{"table": "...", "pk": {...}, "values": {...}}]
    records: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'::jsonb"))
    status: Mapped[str] = mapped_column(
        String(20), default="suggested", server_default="suggested"
    )  # suggested|merged|dismissed
    golden_record: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)


rls("kb_entities", read="viewer", write="builder")


class KbBackup(Base, IdMixin, OrgScoped, CreatedMixin):
    __tablename__ = "kb_backups"

    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True)
    path: Mapped[str] = mapped_column(Text)
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    stats: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    restored_at: Mapped[datetime | None] = mapped_column(nullable=True)


rls("kb_backups", read="viewer", write="admin")


class Connector(Base):
    """Global connector catalog (seeded from packages/connectors)."""

    __tablename__ = "connectors"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(60))
    auth_type: Mapped[str] = mapped_column(String(20))  # oauth2 | api_key | connection_string | none | mcp
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    capabilities: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    icon: Mapped[str | None] = mapped_column(String(60), nullable=True)


class Connection(Base, IdMixin, OrgScoped, TimestampMixin):
    __tablename__ = "connections"

    connector_key: Mapped[str] = mapped_column(ForeignKey("connectors.key"))
    name: Mapped[str] = mapped_column(String(200))
    credentials: Mapped[str | None] = mapped_column(Text, nullable=True)  # encrypted JSON
    scopes: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'::jsonb"))
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active"
    )  # active|error|demo|revoked
    demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    config: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    agent_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)  # on-prem connector agent
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


rls("connections", read="viewer", write="builder", delete="admin")


class Sync(Base, IdMixin, OrgScoped, TimestampMixin):
    __tablename__ = "syncs"

    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connections.id", ondelete="CASCADE"))
    kb_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_bases.id", ondelete="CASCADE"))
    resource: Mapped[str] = mapped_column(Text)  # e.g. "folder:<id>" or "table:public.invoices"
    mode: Mapped[str] = mapped_column(String(12), default="full", server_default="full")  # full | incremental
    cursor_field: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_key: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'::jsonb"))
    schedule: Mapped[str | None] = mapped_column(String(120), nullable=True)  # cron expression
    last_run_at: Mapped[datetime | None] = mapped_column(nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="idle", server_default="idle")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    # Adapter options: target table, recursion, selected fields/columns… (column added by migration 0006).
    options: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))


rls("syncs", read="viewer", write="builder")


class ConnectorAgent(Base, IdMixin, OrgScoped, CreatedMixin):
    """On-premise connector agent enrolled with a token; connects outbound to the control plane."""

    __tablename__ = "connector_agents"

    name: Mapped[str] = mapped_column(String(200))
    enrollment_token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    agent_secret_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending"
    )  # pending|online|offline
    version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    capabilities: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    last_seen_at: Mapped[datetime | None] = mapped_column(nullable=True)
    enrolled_at: Mapped[datetime | None] = mapped_column(nullable=True)


rls("connector_agents", read="viewer", write="admin")
