"""API error model. Every error response is ``{"error": {"code", "message", "details"}}``."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from messer_common.logging import get_logger

log = get_logger("messer.api.errors")


class ApiError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details or {}


class NotFound(ApiError):
    status_code = 404
    code = "not_found"


class Unauthorized(ApiError):
    status_code = 401
    code = "unauthorized"


class Forbidden(ApiError):
    status_code = 403
    code = "forbidden"


class Conflict(ApiError):
    status_code = 409
    code = "conflict"


class PlanLimitExceeded(ApiError):
    """Raised when a plan limit blocks an action. The UI shows an upgrade button."""

    status_code = 402
    code = "plan_limit"


class PaymentRequired(ApiError):
    status_code = 402
    code = "payment_required"


class RateLimited(ApiError):
    status_code = 429
    code = "rate_limited"


def _payload(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


async def api_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return JSONResponse(_payload(exc.code, exc.message, exc.details), status_code=exc.status_code)


async def http_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}.get(
        exc.status_code, "http_error"
    )
    return JSONResponse(_payload(code, str(exc.detail)), status_code=exc.status_code, headers=exc.headers)


async def validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [
        {"loc": [str(p) for p in e.get("loc", [])], "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in exc.errors()
    ]
    return JSONResponse(_payload("validation_error", "Datos no válidos", {"errors": errors}), status_code=422)


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled_error", path=request.url.path, error=str(exc))
    return JSONResponse(_payload("internal_error", "Error interno. Lo hemos registrado."), status_code=500)
