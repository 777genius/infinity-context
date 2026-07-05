"""Document ingest API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response, status
from infinity_context_core.application import (
    DeleteDocumentCommand,
    GetDocumentQuery,
    ListDocumentChunksQuery,
    ProcessDocumentCommand,
)
from infinity_context_core.application import (
    IngestDocumentCommand as LegacyIngestDocumentCommand,
)
from infinity_context_core.domain.errors import MemoryValidationError

from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.policy import ensure_server_writes_enabled
from infinity_context_server.api.v1.scope_resolution import resolve_single_scope
from infinity_context_server.backpressure import document_ingest_backpressure_response
from infinity_context_server.composition import Container
from infinity_context_server.features.document_ingestion import public as document_ingestion_server
from infinity_context_server.pagination import cursor_int, cursor_str, decode_cursor, encode_cursor

router = APIRouter(
    prefix="/documents",
    tags=["documents"],
    dependencies=[Depends(require_service_token)],
)

document_to_response = document_ingestion_server.document_to_response
chunk_to_response = document_ingestion_server.chunk_to_response


class IngestDocumentRequest(document_ingestion_server.LegacyIngestDocumentRequest):
    """Legacy /v1 request body; fields live in the document_ingestion seam."""


@router.post("", status_code=status.HTTP_201_CREATED)
async def ingest_document(
    request: IngestDocumentRequest,
    container: Annotated[Container, Depends(get_container)],
    response: Response,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Any:
    ensure_server_writes_enabled(container)
    backpressure = await document_ingest_backpressure_response(container)
    if backpressure is not None:
        return backpressure
    scope = await resolve_single_scope(
        container,
        space_id=request.space_id,
        memory_scope_id=request.memory_scope_id,
        thread_id=request.thread_id,
        space_slug=request.space_slug,
        memory_scope_external_ref=request.memory_scope_external_ref,
        thread_external_ref=request.thread_external_ref,
        thread_required=False,
    )
    try:
        command = document_ingestion_server.legacy_ingest_document_command_from_request(
            request,
            command_factory=LegacyIngestDocumentCommand,
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            thread_id=scope.thread_id,
            idempotency_key=idempotency_key,
        )
    except ValueError as exc:
        raise MemoryValidationError(str(exc)) from exc
    result = await container.ingest_document.execute(command)
    if result.indexing_status == "already_indexed_or_pending":
        response.status_code = status.HTTP_200_OK
    return {
        "data": document_ingestion_server.document_to_response(
            result.document,
            chunks=len(result.chunks),
            chunk_items=result.chunks,
            duplicate_chunks=result.duplicate_chunks,
            indexing_status=result.indexing_status,
        )
    }


@router.get("/{document_id}")
async def get_document(
    document_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    result = await container.get_document.execute(GetDocumentQuery(document_id=document_id))
    return {"data": document_ingestion_server.document_to_response(result.document)}


@router.get("/{document_id}/chunks")
async def list_document_chunks(
    document_id: str,
    container: Annotated[Container, Depends(get_container)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: Annotated[str | None, Query(max_length=1000)] = None,
) -> dict[str, Any]:
    decoded_cursor = decode_cursor(cursor, kind="document_chunks")
    result = await container.list_document_chunks.execute(
        ListDocumentChunksQuery(
            document_id,
            limit=limit + 1,
            cursor_sequence=cursor_int(decoded_cursor, "sequence"),
            cursor_id=cursor_str(decoded_cursor, "id"),
        )
    )
    chunks = list(result.chunks)
    visible_chunks = chunks[:limit]
    next_cursor = None
    if len(chunks) > limit and visible_chunks:
        last = visible_chunks[-1]
        next_cursor = encode_cursor(
            "document_chunks",
            sequence=last.sequence,
            id=str(last.id),
        )
    return {
        "data": [
            document_ingestion_server.chunk_to_response(chunk) for chunk in visible_chunks
        ],
        "next_cursor": next_cursor,
    }


@router.post("/{document_id}/process")
async def process_document(
    document_id: str,
    container: Annotated[Container, Depends(get_container)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.process_document.execute(
        ProcessDocumentCommand(document_id=document_id, idempotency_key=idempotency_key)
    )
    return {
        "data": document_ingestion_server.document_to_response(
            result.document,
            chunks=result.chunks,
            indexing_status=result.indexing_status,
        )
    }


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    ensure_server_writes_enabled(container)
    result = await container.delete_document.execute(DeleteDocumentCommand(document_id=document_id))
    return {
        "data": document_ingestion_server.document_to_response(
            result.document,
            deleted_chunks=result.deleted_chunks,
            deleted_facts=result.deleted_facts,
            indexing_status=result.indexing_status,
        )
    }
