"""Knowledge data plane: embeddings, parsing, chunking, search, read-only SQL and policies.

Used by the control plane (``messer_api.services.knowledge``), the worker and the runtime. This package
never imports ``messer_api``. See ``docs/architecture/contracts.md`` §3.
"""

from __future__ import annotations

from .embeddings import Embedder, default_embedding_model, get_embedder
from .errors import (
    EmbeddingUnavailable,
    KbNotFound,
    KnowledgeError,
    ParseError,
    PolicyError,
    SqlExecutionError,
    SqlRejected,
    SqlTimeout,
)
from .search import SearchHit, search
from .sql import SqlResult, run_readonly

__all__ = [
    "Embedder",
    "EmbeddingUnavailable",
    "KbNotFound",
    "KnowledgeError",
    "ParseError",
    "PolicyError",
    "SearchHit",
    "SqlExecutionError",
    "SqlRejected",
    "SqlResult",
    "SqlTimeout",
    "default_embedding_model",
    "get_embedder",
    "run_readonly",
    "search",
]
