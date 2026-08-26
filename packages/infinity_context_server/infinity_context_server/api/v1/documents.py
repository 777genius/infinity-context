"""Document ingest API."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Response, status
from fastapi.responses import JSONResponse
from infinity_context_contracts.features.context_building import (
    ContextRetrievalV2ErrorDto,
    ContextRetrievalV2ErrorEnvelopeDto,
)
from infinity_context_core.application import (
    DeleteDocumentCommand,
    GetDocumentQuery,
    ListDocumentChunksQuery,
    ListDocumentsQuery,
    ProcessDocumentCommand,
)
from infinity_context_core.application import (
    IngestDocumentCommand as LegacyIngestDocumentCommand,
)
from infinity_context_core.domain.errors import MemoryValidationError
from pydantic import BaseModel, ConfigDict

from infinity_context_server.api.auth import require_service_token
from infinity_context_server.api.dependencies import get_container
from infinity_context_server.api.policy import ensure_server_writes_enabled
from infinity_context_server.api.v1.scope_resolution import (
    resolve_existing_single_scope,
    resolve_single_scope,
)
from infinity_context_server.backpressure import document_ingest_backpressure_response
from infinity_context_server.composition import Container
from infinity_context_server.features.document_ingestion import public as document_ingestion_server
from infinity_context_server.pagination import (
    cursor_datetime,
    cursor_int,
    cursor_str,
    decode_cursor,
    encode_cursor,
)

router = APIRouter(
    prefix="/documents",
    tags=["documents"],
    dependencies=[Depends(require_service_token)],
)

document_to_response = document_ingestion_server.document_to_response
chunk_to_response = document_ingestion_server.chunk_to_response


class IngestDocumentRequest(document_ingestion_server.LegacyIngestDocumentRequest):
    """Legacy /v1 request body; fields live in the document_ingestion seam."""


class DocumentRecordResponse(BaseModel):
    """Stable document record shared by OpenAPI and the official SDK."""

    model_config = ConfigDict(extra="forbid")

    id: str
    space_id: str
    memory_scope_id: str
    thread_id: str | None
    title: str
    source_type: str
    source_external_id: str
    content_hash: str
    classification: str
    status: str
    created_at: str
    updated_at: str


class DocumentListResponse(BaseModel):
    """Stable paginated response envelope for exact-scope document listing."""

    model_config = ConfigDict(extra="forbid")

    data: list[DocumentRecordResponse]
    next_cursor: str | None


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
        if request.retrieval_projection is not None:
            return _projection_error(
                "memory.document_projection_invalid",
                "Document retrieval projection is invalid",
            )
        raise MemoryValidationError(str(exc)) from exc
    try:
        result = await (
            container.projected_document_ingestion.execute(command)
            if request.retrieval_projection is not None
            else container.ingest_document.execute(command)
        )
    except document_ingestion_server.DocumentProjectionLocatorConflictError:
        return _projection_error("memory.document_projection_locator_conflict")
    except document_ingestion_server.DocumentProjectionOrdinalConflictError:
        return _projection_error("memory.document_projection_ordinal_conflict")
    except document_ingestion_server.DocumentProjectionIdempotencyConflictError:
        return _projection_error("memory.document_projection_idempotency_conflict")
    except ValueError:
        return _projection_error(
            "memory.document_projection_invalid",
            "Document retrieval projection is invalid",
        )
    if result.indexing_status == "already_indexed_or_pending":
        response.status_code = status.HTTP_200_OK
    data = document_ingestion_server.document_to_response(
        result.document,
        chunks=len(result.chunks),
        chunk_items=result.chunks,
        duplicate_chunks=result.duplicate_chunks,
        indexing_status=result.indexing_status,
    )
    if request.retrieval_projection is not None:
        data["created"] = result.indexing_status != "already_indexed_or_pending"
    return {"data": data}


def _projection_error(
    code: str, message: str = "Document retrieval projection conflicted"
) -> JSONResponse:
    envelope = ContextRetrievalV2ErrorEnvelopeDto(ContextRetrievalV2ErrorDto(code, message, False))
    return JSONResponse(status_code=envelope.http_status, content=envelope.to_dict())


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    container: Annotated[Container, Depends(get_container)],
    space_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    memory_scope_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    thread_id: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    space_slug: Annotated[str | None, Query(min_length=1, max_length=160)] = None,
    memory_scope_external_ref: Annotated[
        str | None, Query(min_length=1, max_length=200)
    ] = None,
    thread_external_ref: Annotated[
        str | None, Query(min_length=1, max_length=200)
    ] = None,
    status_filter: Annotated[Literal["active"], Query(alias="status")] = "active",
    source_external_id: Annotated[
        str | None, Query(min_length=1, max_length=240)
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: Annotated[str | None, Query(max_length=1000)] = None,
) -> dict[str, Any]:
    _require_explicit_document_list_scope(
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=thread_id,
        space_slug=space_slug,
        memory_scope_external_ref=memory_scope_external_ref,
        thread_external_ref=thread_external_ref,
    )
    decoded_cursor = decode_cursor(cursor, kind="documents")
    scope = await resolve_existing_single_scope(
        container,
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=thread_id,
        space_slug=space_slug,
        memory_scope_external_ref=memory_scope_external_ref,
        thread_external_ref=thread_external_ref,
        thread_required=False,
    )
    if scope is None:
        if decoded_cursor is not None:
            raise MemoryValidationError("Invalid cursor")
        return {"data": [], "next_cursor": None}

    scope_fingerprint = _document_list_fingerprint(
        space_id=str(scope.space_id),
        memory_scope_id=str(scope.memory_scope_id),
        thread_id=str(scope.thread_id) if scope.thread_id else None,
        status=status_filter,
        source_external_id=source_external_id,
    )
    if (
        decoded_cursor is not None
        and cursor_str(decoded_cursor, "scope") != scope_fingerprint
    ):
        raise MemoryValidationError("Invalid cursor")

    result = await container.list_documents.execute(
        ListDocumentsQuery(
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            thread_id=scope.thread_id,
            status=status_filter,
            source_external_id=source_external_id,
            limit=limit + 1,
            cursor_updated_at=cursor_datetime(decoded_cursor, "updated_at"),
            cursor_id=cursor_str(decoded_cursor, "id"),
        )
    )
    documents = list(result.documents)
    visible_documents = documents[:limit]
    next_cursor = None
    if len(documents) > limit and visible_documents:
        last = visible_documents[-1]
        next_cursor = encode_cursor(
            "documents",
            scope=scope_fingerprint,
            updated_at=last.updated_at.isoformat(),
            id=str(last.id),
        )
    return {
        "data": [
            document_ingestion_server.document_to_response(document)
            for document in visible_documents
        ],
        "next_cursor": next_cursor,
    }


def _require_explicit_document_list_scope(
    *,
    space_id: str | None,
    memory_scope_id: str | None,
    thread_id: str | None,
    space_slug: str | None,
    memory_scope_external_ref: str | None,
    thread_external_ref: str | None,
) -> None:
    uses_canonical = any((space_id, memory_scope_id, thread_id))
    uses_external = any((space_slug, memory_scope_external_ref, thread_external_ref))
    if uses_canonical and uses_external:
        raise MemoryValidationError("Use either canonical ids or external scope refs, not both")
    if uses_canonical:
        if not space_id or not memory_scope_id:
            raise MemoryValidationError(
                "space_id and memory_scope_id are required with canonical scope"
            )
        return
    if not uses_external or not space_slug or not memory_scope_external_ref:
        raise MemoryValidationError(
            "space_slug and memory_scope_external_ref are required with external scope"
        )


def _document_list_fingerprint(
    *,
    space_id: str,
    memory_scope_id: str,
    thread_id: str | None,
    status: str,
    source_external_id: str | None,
) -> str:
    normalized = json.dumps(
        [space_id, memory_scope_id, thread_id, status, source_external_id],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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
        "data": [document_ingestion_server.chunk_to_response(chunk) for chunk in visible_chunks],
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
