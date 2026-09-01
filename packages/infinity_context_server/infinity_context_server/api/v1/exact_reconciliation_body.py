"""Bounded request boundary for exact document reconciliation."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Mapping
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from infinity_context_contracts.features.document_ingestion import (
    EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1,
    ExactDocumentReconciliationResultDto,
)
from pydantic import ValidationError
from starlette.requests import ClientDisconnect

from infinity_context_server.features.document_ingestion import public as document_ingestion
from infinity_context_server.retrieval_runtime_lifecycle import complete_despite_cancellation

MAX_EXACT_RECONCILIATION_BODY_BYTES = 16_384
MAX_EXACT_RECONCILIATION_DEADLINE_SECONDS = 10.0
_BODY_STATE_KEY = "exact_reconciliation_body"
_DTO_STATE_KEY = "exact_reconciliation_request"


class ExactReconciliationRoute(APIRoute):
    """Apply the caller-visible deadline before dependencies consume the body."""

    def get_route_handler(self):
        original = super().get_route_handler()
        if not self.path.endswith("/reconcile-exact"):
            return original

        async def bounded_handler(request: Request) -> Response:
            started = asyncio.get_running_loop().time()
            dto: document_ingestion.ReconcileExactDocumentHttpRequest | None = None
            try:
                async with asyncio.timeout_at(
                    started + MAX_EXACT_RECONCILIATION_DEADLINE_SECONDS
                ) as deadline_scope:
                    body = await _decode_body(request)
                    dto = _validate_body(body)
                    setattr(request.state, _BODY_STATE_KEY, body)
                    setattr(request.state, _DTO_STATE_KEY, dto)
                    deadline_scope.reschedule(started + dto.deadline_ms / 1000)
                    await asyncio.sleep(0)
                    return await original(request)
            except (asyncio.CancelledError, ClientDisconnect):
                raise
            except TimeoutError as exc:
                if dto is None:
                    raise HTTPException(
                        status_code=status.HTTP_408_REQUEST_TIMEOUT,
                        detail="Exact document reconciliation request deadline exceeded",
                    ) from exc
                return _unavailable_response(dto)

        return bounded_handler


def cached_exact_reconciliation_body(request: Request) -> dict[str, Any] | None:
    value = getattr(request.state, _BODY_STATE_KEY, None)
    return value if isinstance(value, dict) else None


def cached_exact_reconciliation_request(
    request: Request,
) -> document_ingestion.ReconcileExactDocumentHttpRequest:
    value = getattr(request.state, _DTO_STATE_KEY, None)
    if not isinstance(value, document_ingestion.ReconcileExactDocumentHttpRequest):
        raise RuntimeError("exact reconciliation request boundary was not applied")
    return value


async def execute_with_disconnect(request: Request, awaitable: Awaitable[Any]) -> Any:
    operation = asyncio.create_task(awaitable)
    disconnected = asyncio.create_task(_wait_for_disconnect(request))
    try:
        done, _ = await asyncio.wait(
            {operation, disconnected}, return_when=asyncio.FIRST_COMPLETED
        )
        if disconnected in done and disconnected.result():
            raise asyncio.CancelledError
        return await operation
    finally:
        for task in (operation, disconnected):
            if not task.done():
                task.cancel()
        _, cleanup_cancellation = await complete_despite_cancellation(
            asyncio.gather(operation, disconnected, return_exceptions=True)
        )
        if cleanup_cancellation is not None:
            raise cleanup_cancellation


async def _decode_body(request: Request) -> dict[str, Any]:
    _validate_headers(request)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_EXACT_RECONCILIATION_BODY_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Exact document reconciliation request body is too large",
            )
    try:
        decoded = json.loads(bytes(raw))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RequestValidationError(
            [
                {
                    "type": "json_invalid",
                    "loc": ("body",),
                    "msg": "Invalid JSON body",
                    "input": None,
                    "ctx": {"error": str(exc)},
                }
            ]
        ) from exc
    if not isinstance(decoded, dict):
        raise RequestValidationError(
            [
                {
                    "type": "dict_type",
                    "loc": ("body",),
                    "msg": "Input should be an object",
                    "input": decoded,
                }
            ]
        )
    return decoded


def _validate_headers(request: Request) -> None:
    content_type = request.headers.get("content-type")
    normalized = "" if content_type is None else content_type.casefold().replace(" ", "")
    if normalized not in {"application/json", "application/json;charset=utf-8"}:
        raise HTTPException(status_code=415, detail="Content-Type must be application/json")
    encoding = request.headers.get("content-encoding")
    if encoding is not None and encoding.strip().casefold() != "identity":
        raise HTTPException(status_code=415, detail="Content-Encoding is not supported")
    length = request.headers.get("content-length")
    if length is None:
        return
    try:
        parsed = int(length, 10)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
    if parsed < 0:
        raise HTTPException(status_code=400, detail="Invalid Content-Length")
    if parsed > MAX_EXACT_RECONCILIATION_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Exact document reconciliation request body is too large",
        )


def _validate_body(
    body: Mapping[str, Any],
) -> document_ingestion.ReconcileExactDocumentHttpRequest:
    try:
        return document_ingestion.ReconcileExactDocumentHttpRequest.model_validate(body)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


def _unavailable_response(
    request: document_ingestion.ReconcileExactDocumentHttpRequest,
) -> JSONResponse:
    body = ExactDocumentReconciliationResultDto(
        contract_version=EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1,
        state="unavailable",
        source_type=request.source_type,
        source_external_id=request.source_external_id,
        space_id=request.space_id,
        memory_scope_id=request.memory_scope_id,
        thread_id=request.thread_id,
        visibility="unavailable",
    ).to_dict()
    return JSONResponse(content=body)


async def _wait_for_disconnect(request: Request) -> bool:
    while True:
        try:
            message = await asyncio.wait_for(request.receive(), timeout=0.1)
        except TimeoutError:
            continue
        if message.get("type") == "http.disconnect":
            return True


__all__ = (
    "ExactReconciliationRoute",
    "MAX_EXACT_RECONCILIATION_BODY_BYTES",
    "cached_exact_reconciliation_body",
    "cached_exact_reconciliation_request",
    "execute_with_disconnect",
)
