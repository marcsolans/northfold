"""Pydantic request/response models for the knowledge API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from messer_common.db.models import KbBackup, KbChunk, KbEntity, KbFile, KbPolicy, KbTable, KnowledgeBase

GovernanceMode = Literal["off", "shadow", "enforce"]
SearchMode = Literal["vector", "keyword", "hybrid"]


class KbStats(BaseModel):
    files: int = 0
    files_ready: int = 0
    files_processing: int = 0
    files_error: int = 0
    size: int = 0
    chunks: int = 0
    tables: int = 0


class KbOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    project_id: uuid.UUID | None
    embedding_model: str
    embedding_dim: int
    governance_mode: str
    schema_name: str
    chunk_size_tokens: int
    chunk_overlap_tokens: int
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    stats: KbStats

    @classmethod
    def build(cls, kb: KnowledgeBase, stats: dict[str, Any] | None = None) -> KbOut:
        return cls(
            id=kb.id,
            name=kb.name,
            description=kb.description,
            project_id=kb.project_id,
            embedding_model=kb.embedding_model,
            embedding_dim=kb.embedding_dim,
            governance_mode=kb.governance_mode,
            schema_name=kb.schema_name,
            chunk_size_tokens=kb.chunk_size_tokens,
            chunk_overlap_tokens=kb.chunk_overlap_tokens,
            created_by=kb.created_by,
            created_at=kb.created_at,
            updated_at=kb.updated_at,
            stats=KbStats(**(stats or {})),
        )


class KbCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    embedding_model: str | None = Field(default=None, max_length=120)
    project_id: uuid.UUID | None = None
    chunk_size_tokens: int = Field(default=800, ge=100, le=4000)
    chunk_overlap_tokens: int = Field(default=120, ge=0, le=1000)


class KbUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    governance_mode: GovernanceMode | None = None
    chunk_size_tokens: int | None = Field(default=None, ge=100, le=4000)
    chunk_overlap_tokens: int | None = Field(default=None, ge=0, le=1000)


class EmbeddingModelOut(BaseModel):
    id: str
    dim: int
    kind: str
    available: bool
    default: bool = False


class FileOut(BaseModel):
    id: uuid.UUID
    kb_id: uuid.UUID
    filename: str
    mime: str
    size: int
    source: str
    status: str
    error: str | None
    pages: int | None
    chunk_count: int
    table_id: uuid.UUID | None
    external_id: str | None
    connection_id: uuid.UUID | None
    metadata: dict[str, Any]
    uploaded_by: uuid.UUID | None
    created_at: datetime

    @classmethod
    def build(cls, f: KbFile) -> FileOut:
        return cls(
            id=f.id,
            kb_id=f.kb_id,
            filename=f.filename,
            mime=f.mime,
            size=f.size,
            source=f.source,
            status=f.status,
            error=f.error,
            pages=f.pages,
            chunk_count=f.chunk_count,
            table_id=f.table_id,
            external_id=f.external_id,
            connection_id=f.connection_id,
            metadata=f.meta or {},
            uploaded_by=f.uploaded_by,
            created_at=f.created_at,
        )


class FileList(BaseModel):
    items: list[FileOut]
    total: int


class UploadError(BaseModel):
    filename: str
    code: str
    message: str


class UploadResult(BaseModel):
    files: list[FileOut]
    errors: list[UploadError]


class ChunkOut(BaseModel):
    id: uuid.UUID
    file_id: uuid.UUID
    filename: str
    ordinal: int
    content: str
    heading: str | None
    page_from: int | None
    page_to: int | None
    token_count: int
    metadata: dict[str, Any]
    edited_at: datetime | None
    has_embedding: bool

    @classmethod
    def build(cls, c: KbChunk, filename: str) -> ChunkOut:
        return cls(
            id=c.id,
            file_id=c.file_id,
            filename=filename,
            ordinal=c.ordinal,
            content=c.content,
            heading=c.heading,
            page_from=c.page_from,
            page_to=c.page_to,
            token_count=c.token_count,
            metadata=c.meta or {},
            edited_at=c.edited_at,
            has_embedding=c.embedding is not None,
        )


class ChunkList(BaseModel):
    items: list[ChunkOut]
    total: int


class ChunkUpdate(BaseModel):
    content: str | None = Field(default=None, max_length=50_000)
    heading: str | None = Field(default=None, max_length=1000)


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    mode: SearchMode = "hybrid"
    k: int = Field(default=8, ge=1, le=50)


class SearchHitOut(BaseModel):
    chunk_id: str
    file_id: str
    filename: str
    content: str
    heading: str | None
    page_from: int | None
    page_to: int | None
    score: float
    metadata: dict[str, Any]


class SearchOut(BaseModel):
    hits: list[SearchHitOut]
    mode: SearchMode
    took_ms: float


class BreakGlass(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


class QueryIn(BaseModel):
    sql: str = Field(min_length=1, max_length=100_000)
    params: list[Any] = Field(default_factory=list, max_length=100)
    explain: bool = False
    limit: int | None = Field(default=None, ge=1, le=10_000)
    break_glass: BreakGlass | None = None


class QueryOut(BaseModel):
    columns: list[str]
    column_types: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    elapsed_ms: float
    plan: Any | None = None
    policy: dict[str, Any] | None = None


class SchemaColumn(BaseModel):
    name: str
    type: str


class SchemaRelation(BaseModel):
    name: str
    kind: Literal["table", "view"]
    columns: list[SchemaColumn]
    row_count: int | None = None
    description: str = ""


class SchemaOut(BaseModel):
    schema_name: str
    relations: list[SchemaRelation]
    functions: list[str]


class TableColumnOut(BaseModel):
    name: str
    type: str
    nullable: bool = True
    pk: bool = False
    comment: str | None = None
    source_name: str | None = None


class TableOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    columns: list[TableColumnOut]
    primary_key: list[str]
    row_count: int
    source: str
    sync_id: uuid.UUID | None
    file_id: uuid.UUID | None
    last_load: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, t: KbTable) -> TableOut:
        schema = t.schema_json or {}
        file_id = schema.get("file_id")
        return cls(
            id=t.id,
            name=t.name,
            description=t.description,
            columns=[TableColumnOut(**c) for c in schema.get("columns", [])],
            primary_key=list(schema.get("primary_key", [])),
            row_count=t.row_count,
            source=t.source,
            sync_id=t.sync_id,
            file_id=uuid.UUID(file_id) if file_id else None,
            last_load=schema.get("last_load"),
            created_at=t.created_at,
            updated_at=t.updated_at,
        )


class TableUpdate(BaseModel):
    description: str = Field(max_length=2000)


class RowsColumn(BaseModel):
    name: str
    type: str
    pk: bool
    masked: bool


class RowsOut(BaseModel):
    columns: list[RowsColumn]
    rows: list[list[Any]]
    total: int
    limit: int
    offset: int
    policy: dict[str, Any] | None = None


class CellUpdate(BaseModel):
    pk: dict[str, Any]
    column: str = Field(min_length=1, max_length=63)
    value: Any = None


class ColumnTypeUpdate(BaseModel):
    type: Literal["text", "integer", "numeric", "boolean", "date", "timestamp", "json"]
    force: bool = False


class PolicyIn(BaseModel):
    table: str = Field(min_length=1, max_length=63)
    role: Literal["viewer", "builder", "admin", "owner", "agent", "*"]
    row_filter_sql: str | None = Field(default=None, max_length=4000)
    masked_columns: dict[str, str] = Field(default_factory=dict)
    compliance_tags: list[str] = Field(default_factory=list, max_length=20)
    break_glass: bool = False
    enabled: bool = True


class PolicyOut(BaseModel):
    id: uuid.UUID
    table: str
    role: str
    row_filter_sql: str | None
    masked_columns: dict[str, Any]
    compliance_tags: list[Any]
    break_glass: bool
    enabled: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, p: KbPolicy) -> PolicyOut:
        return cls(
            id=p.id,
            table=p.table,
            role=p.role,
            row_filter_sql=p.row_filter_sql,
            masked_columns=p.masked_columns or {},
            compliance_tags=p.compliance_tags or [],
            break_glass=p.break_glass,
            enabled=p.enabled,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )


class EntityOut(BaseModel):
    id: uuid.UUID
    entity_type: str
    match_key: str
    method: str
    score: float
    records: list[Any]
    status: str
    golden_record: dict[str, Any] | None
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    created_at: datetime

    @classmethod
    def build(cls, e: KbEntity) -> EntityOut:
        return cls(
            id=e.id,
            entity_type=e.entity_type,
            match_key=e.match_key,
            method=e.method,
            score=e.score,
            records=e.records or [],
            status=e.status,
            golden_record=e.golden_record,
            decided_by=e.decided_by,
            decided_at=e.decided_at,
            created_at=e.created_at,
        )


class EntityList(BaseModel):
    items: list[EntityOut]
    total: int


class MergeIn(BaseModel):
    golden_record: dict[str, Any] | None = None


class BackupOut(BaseModel):
    id: uuid.UUID
    status: str
    size: int
    stats: dict[str, Any]
    created_by: uuid.UUID | None
    created_at: datetime
    restored_at: datetime | None

    @classmethod
    def build(cls, b: KbBackup) -> BackupOut:
        return cls(
            id=b.id,
            status=b.status,
            size=b.size,
            stats=b.stats or {},
            created_by=b.created_by,
            created_at=b.created_at,
            restored_at=b.restored_at,
        )


class Queued(BaseModel):
    queued: bool = True
    job: str
