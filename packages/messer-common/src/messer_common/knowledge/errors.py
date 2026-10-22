"""Errors raised by the knowledge data plane.

They carry a stable ``code``, a user-facing (Spanish) ``message``, an HTTP-like ``status`` and
``details``. The control plane converts them into API errors; the runtime returns them to agents.
"""

from __future__ import annotations

from typing import Any


class KnowledgeError(Exception):
    code = "knowledge_error"
    status = 400

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status:
            self.status = status
        self.details = details or {}


class KbNotFound(KnowledgeError):
    code = "kb_not_found"
    status = 404


class SqlRejected(KnowledgeError):
    """The statement is not allowed by the read-only console rules (never sent to the database)."""

    code = "sql_rejected"
    status = 400


class SqlExecutionError(KnowledgeError):
    """PostgreSQL rejected or failed the statement (syntax, unknown column, permission…)."""

    code = "sql_error"
    status = 400


class SqlTimeout(KnowledgeError):
    code = "sql_timeout"
    status = 408


class EmbeddingUnavailable(KnowledgeError):
    code = "embeddings_unavailable"
    status = 503


class ParseError(KnowledgeError):
    code = "parse_error"
    status = 422


class PolicyError(KnowledgeError):
    code = "policy_invalid"
    status = 422
