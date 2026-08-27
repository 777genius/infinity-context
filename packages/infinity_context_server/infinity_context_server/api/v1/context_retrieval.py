"""Strict raw-byte HTTP boundary for locator-only Retrieval."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from infinity_context_contracts.features.context_building import (
    CONTEXT_RETRIEVAL_ERROR_SPECS,
    RetrievalErrorDto,
    RetrievalErrorEnvelopeDto,
    RetrieveContextRequestDto,
    RetrieveContextResponseDto,
    decode_retrieve_context_request,
)
from infinity_context_core.domain.errors import MemoryForbiddenError, MemoryValidationError

from infinity_context_server.api.auth import (
    authorize_resolved_retrieval_scope,
    get_authorized_agent_context,
    require_service_token,
)
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.v1.scope_resolution import resolve_existing_single_scope
from infinity_context_server.auth_tokens import MEMORY_PERMISSION_ADMIN, MEMORY_PERMISSION_READ
from infinity_context_server.composition import Container
from infinity_context_server.features.context_building import public as context_building
from infinity_context_server.retrieval_runtime_lifecycle import complete_despite_cancellation

MAX_RAW_REQUEST_BYTES = 2_097_152
MIN_RESPONSE_BYTES = 16_384
MAX_DEADLINE_SECONDS = 2.0
router = APIRouter(tags=["context_retrieval"], dependencies=[Depends(require_service_token)])


@router.post("/context/retrieve")
async def retrieve_context(
    http_request: Request,
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    started = asyncio.get_running_loop().time()
    try:
        # The maximum contract deadline bounds headers and body ingestion too.
        # Once decoded, reschedule to the caller's narrower attested deadline.
        async with asyncio.timeout_at(started + MAX_DEADLINE_SECONDS) as deadline_scope:
            _validate_media_headers(http_request)
            raw = await _read_raw_body(http_request)
            dto = decode_retrieve_context_request(raw)
            deadline = started + dto.bounds.deadline_ms / 1000
            deadline_scope.reschedule(deadline)
            _check_deadline(deadline)
            _authorize(http_request, dto)
            resolved = await _resolve_scope(dto, container)
            _authorize(http_request, resolved)
            service = container.locator_retrieval
            if service is None:
                return _error(
                    "memory.context_retrieval_unavailable",
                    "Retrieval is unavailable",
                )
            response = await _execute_with_disconnect(
                http_request,
                service.execute(context_building.retrieval_request_to_core(resolved)),
            )
            _check_deadline(deadline)
            body = context_building.retrieval_response_to_contract(response).to_dict()
            encoded = _compact_bytes(body)
            _check_deadline(deadline)
            if len(encoded) > resolved.bounds.response_byte_limit:
                encoded = _oversized_fallback(body)
            if len(encoded) > resolved.bounds.response_byte_limit:
                raise RuntimeError("mandatory Retrieval envelope exceeds attested limit")
            _check_deadline(deadline)
            return Response(content=encoded, media_type="application/json")
    except asyncio.CancelledError:
        raise
    except TimeoutError:
        return _error(
            "memory.context_retrieval_deadline_exceeded",
            "Retrieval deadline exceeded",
        )
    except context_building.RetrievalProfileConflict:
        return _error(
            "memory.context_retrieval_capability_mismatch",
            "Retrieval capability or profile is stale",
        )
    except MemoryForbiddenError:
        return _error("memory.forbidden", "Retrieval scope is forbidden")
    except _ScopeNotFound:
        return _error(
            "memory.context_retrieval_scope_not_found",
            "Retrieval scope was not found",
        )
    except _UnsupportedContract:
        return _error(
            "memory.context_retrieval_unsupported",
            "Retrieval request is unsupported",
        )
    except ValueError as exc:
        message = str(exc).casefold()
        if any(token in message for token in ("unsupported", "out of bounds", "within")):
            return _error(
                "memory.context_retrieval_unsupported",
                "Retrieval request is unsupported",
            )
        return _error(
            "memory.context_retrieval_contract_invalid",
            "Retrieval request does not match the canonical contract",
        )
    except (UnicodeError, json.JSONDecodeError, _InvalidContract):
        return _error(
            "memory.context_retrieval_contract_invalid",
            "Retrieval request does not match the canonical contract",
        )
    except Exception:
        return _error(
            "memory.context_retrieval_unavailable",
            "Retrieval is unavailable",
        )


def _validate_media_headers(request: Request) -> None:
    content_type = request.headers.get("content-type")
    valid_types = {"application/json", "application/json;charset=utf-8"}
    normalized = "" if content_type is None else content_type.casefold().replace(" ", "")
    if normalized not in valid_types:
        raise _InvalidContract
    encoding = request.headers.get("content-encoding")
    if encoding is not None and encoding.strip().casefold() != "identity":
        raise _InvalidContract
    length = request.headers.get("content-length")
    if length is not None:
        try:
            parsed = int(length, 10)
        except ValueError as exc:
            raise _InvalidContract from exc
        if parsed < 0 or parsed > MAX_RAW_REQUEST_BYTES:
            raise _InvalidContract


async def _read_raw_body(request: Request) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_RAW_REQUEST_BYTES:
            raise _InvalidContract
    return bytes(body)


async def _resolve_scope(
    dto: RetrieveContextRequestDto, container: Container
) -> RetrieveContextRequestDto:
    try:
        resolved = await resolve_existing_single_scope(
            container,
            space_id=dto.scope.space_id,
            memory_scope_id=dto.scope.memory_scope_id,
            thread_id=dto.scope.thread_id,
            space_slug=None,
            memory_scope_external_ref=None,
            thread_external_ref=None,
            thread_required=False,
        )
    except MemoryValidationError as exc:
        raise _ScopeNotFound from exc
    if resolved is None:
        raise _ScopeNotFound
    if (
        str(resolved.space_id) != dto.scope.space_id
        or str(resolved.memory_scope_id) != dto.scope.memory_scope_id
        or (str(resolved.thread_id) if resolved.thread_id else None) != dto.scope.thread_id
    ):
        raise _ScopeNotFound
    return dto


def _authorize(http_request: Request, request: RetrieveContextRequestDto) -> None:
    authorize_resolved_retrieval_scope(
        http_request,
        space_id=request.scope.space_id,
        memory_scope_id=request.scope.memory_scope_id,
    )
    context = get_authorized_agent_context(http_request)
    if context is None:
        return
    if context.repository_id is not None or context.code_scope_id is not None:
        raise MemoryForbiddenError("Repository-scoped token is not eligible")
    required = (
        MEMORY_PERMISSION_READ
        if MEMORY_PERMISSION_READ in context.permissions
        else MEMORY_PERMISSION_ADMIN
    )
    try:
        context.authorize(
            requested_space_id=request.scope.space_id,
            requested_memory_scope_ids=(request.scope.memory_scope_id,),
            required_permission=required,
            requested_repository_id=None,
            requested_code_scope_id=None,
        )
    except PermissionError as exc:
        raise MemoryForbiddenError("Retrieval scope is forbidden") from exc


async def _execute_with_disconnect(request: Request, awaitable):
    operation = asyncio.create_task(awaitable)
    disconnected = asyncio.create_task(_wait_for_disconnect(request))
    try:
        done, _ = await asyncio.wait(
            {operation, disconnected},
            return_when=asyncio.FIRST_COMPLETED,
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


async def _wait_for_disconnect(request: Request) -> bool:
    while True:
        try:
            message = await asyncio.wait_for(request.receive(), timeout=0.1)
        except TimeoutError:
            continue
        if message.get("type") == "http.disconnect":
            return True


def _oversized_fallback(body: Mapping[str, object]) -> bytes:
    fallback = dict(body)
    fallback["status"] = "unavailable"
    fallback["candidates"] = []
    fallback["degradation_reason_codes"] = ["response_byte_limit_exceeded"]
    applied = dict(fallback["applied_bounds"])
    applied["returned_seeds"] = 0
    applied["returned_neighbors"] = 0
    fallback["applied_bounds"] = applied
    return _compact_bytes(RetrieveContextResponseDto.from_dict(fallback).to_dict())


def _compact_bytes(value: Mapping[str, object]) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
        "utf-8"
    )


def _error(code: str, message: str) -> Response:
    retryable = CONTEXT_RETRIEVAL_ERROR_SPECS[code][1]
    envelope = RetrievalErrorEnvelopeDto(RetrievalErrorDto(code, message, retryable))
    return Response(
        content=_compact_bytes(envelope.to_dict()),
        status_code=envelope.http_status,
        media_type="application/json",
    )


def _check_deadline(deadline: float) -> None:
    if asyncio.get_running_loop().time() >= deadline:
        raise TimeoutError


def assert_retrieval_envelopes_fit() -> None:
    for code, (_, retryable) in CONTEXT_RETRIEVAL_ERROR_SPECS.items():
        envelope = RetrievalErrorEnvelopeDto(RetrievalErrorDto(code, "x" * 512, retryable))
        if len(_compact_bytes(envelope.to_dict())) > MIN_RESPONSE_BYTES:
            raise RuntimeError("mandatory Retrieval error envelope is oversized")
    mandatory = {
        "status": "unavailable",
        "capability_fingerprint": "f" * 64,
        "profile_id": "p" * 256,
        "applied_bounds": {
            "candidate_limit": 1000,
            "result_limit": 50,
            "neighbor_radius": 2,
            "response_byte_limit": MIN_RESPONSE_BYTES,
            "deadline_ms": 2000,
            "returned_seeds": 0,
            "returned_neighbors": 0,
        },
        "candidates": [],
        "provider_outcomes": [
            {
                "provider_id": f"provider-{index}" + "p" * 240,
                "status": "unavailable",
                "reason_code": "provider_unavailable",
            }
            for index in range(4)
        ],
        "degradation_reason_codes": ["response_byte_limit_exceeded"],
    }
    if len(_compact_bytes(mandatory)) > MIN_RESPONSE_BYTES:
        raise RuntimeError("mandatory Retrieval unavailable envelope is oversized")


class _InvalidContract(Exception):
    pass


class _UnsupportedContract(Exception):
    pass


class _ScopeNotFound(Exception):
    pass


assert_retrieval_envelopes_fit()

__all__ = ("assert_retrieval_envelopes_fit", "router")
