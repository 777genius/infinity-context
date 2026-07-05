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
from pydantic import BaseModel, ConfigDict, Field

from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.policy import ensure_server_writes_enabled
from infinity_context_server.api.v1.scope_resolution import resolve_single_scope
from infinity_context_server.api.v1.source_refs import SourceRefRequest
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


class IngestDocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    memory_scope_id: str | None = Field(default=None, min_length=1, max_length=80)
    thread_id: str | None = Field(default=None, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    memory_scope_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    thread_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=500_000)
    source_type: str = Field(default="document", min_length=1, max_length=80)
    source_external_id: str = Field(min_length=1, max_length=240)
    classification: str = Field(default="unknown", max_length=40)
    source_refs: list[SourceRefRequest] = Field(default_factory=list, max_length=24)


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
        feature_command = document_ingestion_server.ingest_document_command_from_contract(
            _document_ingestion_feature_request(
                request,
                space_id=str(scope.space_id),
                memory_scope_id=str(scope.memory_scope_id),
                thread_id=str(scope.thread_id) if scope.thread_id else None,
                idempotency_key=idempotency_key,
            ).to_contract()
        )
    except ValueError as exc:
        raise MemoryValidationError(str(exc)) from exc
    result = await container.ingest_document.execute(
        _legacy_ingest_document_command(
            feature_command,
            request,
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            thread_id=scope.thread_id,
        )
    )
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


def _document_chunk_metadata(source_refs: list[SourceRefRequest]) -> dict[str, object] | None:
    if not source_refs:
        return None
    return {
        "source_refs": [
            item.model_dump(exclude_none=True, mode="json") for item in source_refs[:24]
        ],
        "source_ref_count": len(source_refs[:24]),
    }


def _document_ingestion_feature_request(
    request: IngestDocumentRequest,
    *,
    space_id: str,
    memory_scope_id: str,
    thread_id: str | None,
    idempotency_key: str | None,
) -> document_ingestion_server.IngestDocumentHttpRequest:
    return document_ingestion_server.IngestDocumentHttpRequest(
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=thread_id,
        title=request.title,
        text=request.text,
        source_type=request.source_type,
        source_external_id=request.source_external_id,
        classification=request.classification,
        idempotency_key=idempotency_key,
    )


def _legacy_ingest_document_command(
    feature_command: Any,
    request: IngestDocumentRequest,
    *,
    space_id: Any,
    memory_scope_id: Any,
    thread_id: Any,
) -> LegacyIngestDocumentCommand:
    return LegacyIngestDocumentCommand(
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=thread_id,
        title=feature_command.title,
        text=feature_command.text,
        source_type=feature_command.origin.source_type,
        source_external_id=feature_command.origin.source_external_id,
        idempotency_key=feature_command.idempotency_key,
        classification=feature_command.classification,
        chunk_metadata=_document_chunk_metadata(request.source_refs),
    )


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
