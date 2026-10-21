"""Declarative base, shared column types and mixins."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, MetaData, Numeric, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from uuid_extensions import uuid7

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def new_id() -> uuid.UUID:
    """Time-ordered UUIDv7 primary keys (index-friendly, sortable)."""
    value = uuid7()
    assert isinstance(value, uuid.UUID)
    return value


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
        uuid.UUID: UUID(as_uuid=True),
        datetime: DateTime(timezone=True),
        Decimal: Numeric(18, 6),
    }


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class CreatedMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class OrgScoped:
    """Every business table carries org_id so RLS policies are uniform."""

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)


# Tables protected by row level security. The policy role column tells the
# migration which minimum org role may write; "system" means the application
# role may only read (writes happen through the owner connection).
RLS_TABLES: dict[str, dict[str, str]] = {}


def rls(table: str, *, read: str = "viewer", write: str = "builder", delete: str | None = None) -> None:
    RLS_TABLES[table] = {"read": read, "write": write, "delete": delete or write}
