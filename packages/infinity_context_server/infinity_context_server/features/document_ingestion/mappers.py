"""Mappers between HTTP contracts and document_ingestion application DTOs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from infinity_context_contracts.features.document_ingestion import (
    DocumentChunkDto,
    DocumentIdentityDto,
    IngestDocumentRequestDto,
    IngestDocumentResultDto,
    MemoryDocumentDto,
)
import infinity_context_core.features.document_ingestion.public as document_ingestion

DEFAULT_DOCUMENT_CLASSIFICATION = "unknown"
DEFAULT_DOCUMENT_SOURCE_TYPE = "document"


def ingest_document_command_from_contract(
    request: IngestDocumentRequestDto,
) -> document_ingestion.IngestDocumentCommand:
    """Map an HTTP contract into the feature application command boundary."""

    metadata = request.metadata
    return document_ingestion.IngestDocumentCommand(
        scope=document_ingestion.DocumentIngestionScope(
            space_id=_required_text(request.space_id, "space_id"),
            memory_scope_id=_required_text(
                request.memory_scope_id,
                "memory_scope_id",
            ),
            thread_id=_optional_text(request.thread_id),
        ),
        title=_required_text(request.title, "title"),
        origin=document_ingestion.SourceDocumentOrigin(
            source_type=_metadata_text(
                metadata,
                "source_type",
                default=DEFAULT_DOCUMENT_SOURCE_TYPE,
            ),
            source_external_id=_source_external_id(request, metadata),
            uri=_optional_text(request.source_uri),
        ),
        text=_required_document_text(request.text, "text"),
        classification=_metadata_text(
            metadata,
            "classification",
            default=DEFAULT_DOCUMENT_CLASSIFICATION,
        ),
        idempotency_key=_optional_text(request.idempotency_key),
    )


def ingest_document_result_to_contract(
    result: document_ingestion.IngestDocumentResult,
) -> IngestDocumentResultDto:
    """Map a feature application result into the public HTTP contract."""

    return IngestDocumentResultDto(
        document=_document_to_contract(result.document),
        chunks=tuple(_chunk_to_contract(chunk) for chunk in result.chunks),
        created=True,
        indexing_status=result.indexing_status,
    )


def _document_to_contract(
    document: document_ingestion.SourceDocument,
) -> MemoryDocumentDto:
    scope = document.identity.scope
    return MemoryDocumentDto(
        identity=DocumentIdentityDto(
            id=document.identity.document_id,
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            thread_id=scope.thread_id,
        ),
        title=document.title,
        source_uri=document.origin.uri,
        status=document.status,
        content_hash=document.content_hash,
        created_at=_datetime_to_string(document.created_at),
        updated_at=_datetime_to_string(document.updated_at),
        metadata={
            "classification": document.classification,
            "source_external_id": document.origin.source_external_id,
            "source_type": document.origin.source_type,
        },
    )


def _chunk_to_contract(
    chunk: document_ingestion.DocumentChunk,
) -> DocumentChunkDto:
    return DocumentChunkDto(
        id=chunk.identity.chunk_id,
        document_id=chunk.identity.document_id,
        chunk_index=chunk.sequence,
        text=chunk.text,
        char_start=chunk.text_range.char_start,
        char_end=chunk.text_range.char_end,
        token_count=chunk.token_estimate,
        content_hash=chunk.content_hash,
        metadata={
            "kind": chunk.kind,
            "source_hash": chunk.source_hash,
            "status": chunk.status,
        },
    )


def _source_external_id(
    request: IngestDocumentRequestDto,
    metadata: Mapping[str, object],
) -> str:
    value = _metadata_optional_text(metadata, "source_external_id")
    if value is not None:
        return value
    return _required_text(request.source_uri, "source_external_id")


def _metadata_text(
    metadata: Mapping[str, object],
    key: str,
    *,
    default: str,
) -> str:
    return _metadata_optional_text(metadata, key) or default


def _metadata_optional_text(
    metadata: Mapping[str, object],
    key: str,
) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    return _optional_text(str(value))


def _required_text(value: str | None, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{field_name} is required")
    return text


def _required_document_text(value: str | None, field_name: str) -> str:
    if value is None or not str(value).strip():
        raise ValueError(f"{field_name} is required")
    return str(value)


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _datetime_to_string(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


__all__ = (
    "DEFAULT_DOCUMENT_CLASSIFICATION",
    "DEFAULT_DOCUMENT_SOURCE_TYPE",
    "ingest_document_command_from_contract",
    "ingest_document_result_to_contract",
)
