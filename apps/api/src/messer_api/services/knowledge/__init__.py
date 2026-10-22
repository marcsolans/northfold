"""Knowledge control plane (contract §3): lifecycle, files, tables, policies, entities, backups.

``ingest_bytes`` and ``upsert_table`` are the entry points used by connectors and syncs.
"""

from __future__ import annotations

from .files import delete_blobs, delete_file, enqueue_ingestion, ingest_bytes
from .lifecycle import create_kb, delete_kb, kb_stats, update_kb
from .tables import upsert_table

__all__ = [
    "create_kb",
    "delete_blobs",
    "delete_file",
    "delete_kb",
    "enqueue_ingestion",
    "ingest_bytes",
    "kb_stats",
    "update_kb",
    "upsert_table",
]
