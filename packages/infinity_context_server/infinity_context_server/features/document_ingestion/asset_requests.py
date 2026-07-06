"""Asset upload request helpers owned by the document_ingestion server seam."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from typing import Protocol

ExceptionFactory = Callable[[str], Exception]


class AssetUploadRequest(Protocol):
    headers: Mapping[str, str]

    def stream(self) -> AsyncIterator[bytes]: ...


async def read_limited_asset_upload_body(
    request: AssetUploadRequest,
    *,
    max_bytes: int,
    ingress_limit_error: ExceptionFactory,
    validation_error: ExceptionFactory,
) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_size = int(content_length)
        except ValueError as exc:
            raise validation_error("Invalid Content-Length header") from exc
        if declared_size > max_bytes:
            raise ingress_limit_error("Asset exceeds configured upload limit")

    chunks: list[bytes] = []
    total_bytes = 0
    async for chunk in request.stream():
        if not chunk:
            continue
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise ingress_limit_error("Asset exceeds configured upload limit")
        chunks.append(chunk)
    return b"".join(chunks)


__all__ = ("read_limited_asset_upload_body",)
