"""Streaming multipart parser for knowledge uploads.

The request body is parsed as it arrives (python-multipart), each file is written to a spooled temporary
file and the upload is aborted as soon as one file exceeds the per-file limit, so oversized uploads never
reach memory or disk in full.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from typing import IO, Any

from fastapi import Request
from python_multipart.multipart import MultipartParser, parse_options_header

from ...errors import ApiError

SPOOL_BYTES = 8 * 1024 * 1024
MAX_FIELD_BYTES = 64 * 1024


@dataclass
class UploadedFile:
    filename: str
    content_type: str | None
    file: IO[bytes]
    size: int = 0

    def read(self) -> bytes:
        self.file.seek(0)
        return self.file.read()

    def close(self) -> None:
        self.file.close()


@dataclass
class _State:
    headers: dict[str, str] = field(default_factory=dict)
    header_field: bytearray = field(default_factory=bytearray)
    header_value: bytearray = field(default_factory=bytearray)
    current: UploadedFile | None = None
    field_name: str | None = None
    field_value: bytearray = field(default_factory=bytearray)


class UploadTooLarge(ApiError):
    status_code = 413
    code = "file_too_large"


def _decode(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


async def read_files(
    request: Request, *, max_file_bytes: int, max_files: int
) -> tuple[list[UploadedFile], dict[str, str]]:
    """Files and plain fields of a ``multipart/form-data`` request."""
    content_type, params = parse_options_header(request.headers.get("content-type", ""))
    if content_type != b"multipart/form-data" or b"boundary" not in params:
        raise ApiError("Envía los archivos como multipart/form-data", code="invalid_upload", status_code=415)
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > max_files * (max_file_bytes + MAX_FIELD_BYTES):
        raise UploadTooLarge(
            f"La subida supera el máximo de {max_files} archivos de {max_file_bytes // (1024 * 1024)} MB",
            details={"max_bytes": max_file_bytes, "max_files": max_files},
        )

    files: list[UploadedFile] = []
    fields: dict[str, str] = {}
    state = _State()

    def on_part_begin() -> None:
        state.headers = {}
        state.current = None
        state.field_name = None
        state.field_value = bytearray()

    def on_header_field(data: bytes, start: int, end: int) -> None:
        state.header_field += data[start:end]

    def on_header_value(data: bytes, start: int, end: int) -> None:
        state.header_value += data[start:end]

    def on_header_end() -> None:
        state.headers[_decode(bytes(state.header_field)).lower()] = _decode(bytes(state.header_value))
        state.header_field = bytearray()
        state.header_value = bytearray()

    def on_headers_finished() -> None:
        _, disposition = parse_options_header(state.headers.get("content-disposition", ""))
        name = _decode(disposition.get(b"name", b""))
        filename = disposition.get(b"filename")
        if filename is not None:
            if len(files) >= max_files:
                raise ApiError(
                    f"Máximo {max_files} archivos por subida", code="too_many_files", details={"max_files": max_files}
                )
            spool: IO[bytes] = tempfile.SpooledTemporaryFile(max_size=SPOOL_BYTES)
            state.current = UploadedFile(
                filename=_decode(filename) or "archivo", content_type=state.headers.get("content-type"), file=spool
            )
            files.append(state.current)
        else:
            state.field_name = name

    def on_part_data(data: bytes, start: int, end: int) -> None:
        chunk = data[start:end]
        if state.current is not None:
            state.current.size += len(chunk)
            if state.current.size > max_file_bytes:
                raise UploadTooLarge(
                    f"{state.current.filename} supera el máximo de {max_file_bytes // (1024 * 1024)} MB por archivo",
                    details={"filename": state.current.filename, "max_bytes": max_file_bytes},
                )
            state.current.file.write(chunk)
        elif state.field_name is not None:
            state.field_value += chunk
            if len(state.field_value) > MAX_FIELD_BYTES:
                raise ApiError("Campo de formulario demasiado grande", code="invalid_upload")

    def on_part_end() -> None:
        if state.current is None and state.field_name:
            fields[state.field_name] = _decode(bytes(state.field_value))

    callbacks: dict[str, Any] = {
        "on_part_begin": on_part_begin,
        "on_header_field": on_header_field,
        "on_header_value": on_header_value,
        "on_header_end": on_header_end,
        "on_headers_finished": on_headers_finished,
        "on_part_data": on_part_data,
        "on_part_end": on_part_end,
    }
    parser = MultipartParser(params[b"boundary"], callbacks)  # type: ignore[arg-type]
    try:
        async for chunk in request.stream():
            if chunk:
                parser.write(chunk)
        parser.finalize()
    except ApiError:
        for f in files:
            f.close()
        raise
    except Exception as exc:
        for f in files:
            f.close()
        raise ApiError("No se ha podido leer la subida", code="invalid_upload") from exc
    return files, fields


UPLOAD_OPENAPI: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {"files": {"type": "array", "items": {"type": "string", "format": "binary"}}},
                    "required": ["files"],
                }
            }
        },
    }
}
