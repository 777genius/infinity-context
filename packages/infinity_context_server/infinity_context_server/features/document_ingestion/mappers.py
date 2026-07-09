"""Mappers between HTTP contracts and document_ingestion application DTOs."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import infinity_context_core.features.document_ingestion.public as document_ingestion
from infinity_context_contracts.features.document_ingestion import (
    DocumentChunkDto,
    DocumentIdentityDto,
    IngestDocumentRequestDto,
    IngestDocumentResultDto,
    MemoryDocumentDto,
)

from infinity_context_server.api.public_payload import safe_public_metadata
from infinity_context_server.features.document_ingestion.contracts import (
    IngestDocumentHttpRequest,
    LegacyDocumentSourceRefRequest,
    LegacyIngestDocumentRequest,
)

DEFAULT_DOCUMENT_CLASSIFICATION = "unknown"
DEFAULT_DOCUMENT_SOURCE_TYPE = "document"


@dataclass(frozen=True, slots=True)
class _LegacyIngestDocumentCommandPayload:
    space_id: Any
    memory_scope_id: Any
    title: str
    text: str
    source_type: str
    source_external_id: str
    thread_id: Any
    idempotency_key: str | None
    classification: str
    chunk_metadata: dict[str, object] | None

    def to_kwargs(self) -> dict[str, Any]:
        return {
            "space_id": self.space_id,
            "memory_scope_id": self.memory_scope_id,
            "thread_id": self.thread_id,
            "title": self.title,
            "text": self.text,
            "source_type": self.source_type,
            "source_external_id": self.source_external_id,
            "idempotency_key": self.idempotency_key,
            "classification": self.classification,
            "chunk_metadata": self.chunk_metadata,
        }


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


def legacy_ingest_document_command_from_request(
    request: LegacyIngestDocumentRequest,
    *,
    command_factory: Callable[..., Any],
    space_id: Any,
    memory_scope_id: Any,
    thread_id: Any,
    idempotency_key: str | None,
) -> Any:
    """Map legacy /v1/documents input into the command consumed by the route."""

    feature_command = ingest_document_command_from_contract(
        _legacy_ingest_document_http_request(
            request,
            space_id=str(space_id),
            memory_scope_id=str(memory_scope_id),
            thread_id=str(thread_id) if thread_id else None,
            idempotency_key=idempotency_key,
        ).to_contract()
    )
    payload = _LegacyIngestDocumentCommandPayload(
        space_id=space_id,
        memory_scope_id=memory_scope_id,
        thread_id=thread_id,
        title=feature_command.title,
        text=feature_command.text,
        source_type=feature_command.origin.source_type,
        source_external_id=feature_command.origin.source_external_id,
        idempotency_key=feature_command.idempotency_key,
        classification=feature_command.classification,
        chunk_metadata=_legacy_document_chunk_metadata(request.source_refs),
    )
    return command_factory(**payload.to_kwargs())


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


def document_to_response(
    document: Any,
    *,
    chunks: int | None = None,
    chunk_items: Iterable[Any] = (),
    duplicate_chunks: int | None = None,
    indexing_status: str | None = None,
    deleted_chunks: int | None = None,
    deleted_facts: int | None = None,
) -> dict[str, Any]:
    """Map the legacy document read model to the stable v1 HTTP response."""

    body: dict[str, Any] = {
        "id": str(document.id),
        "space_id": str(document.space_id),
        "memory_scope_id": str(document.memory_scope_id),
        "thread_id": str(document.thread_id) if document.thread_id else None,
        "title": document.title,
        "source_type": document.source_type,
        "source_external_id": document.source_external_id,
        "content_hash": document.content_hash,
        "classification": document.classification,
        "status": _raw_value(document.status),
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }
    if chunks is not None:
        body["chunks"] = chunks
        chunk_tuple = tuple(chunk_items)
        if chunk_tuple:
            body["fragment_summary"] = _document_fragment_summary_from_nodes(
                (_chunk_node_kind(chunk), chunk.sequence) for chunk in chunk_tuple
            )
    if duplicate_chunks is not None:
        body["duplicate_chunks"] = duplicate_chunks
    if indexing_status is not None:
        body["indexing_status"] = indexing_status
    if deleted_chunks is not None:
        body["deleted_chunks"] = deleted_chunks
    if deleted_facts is not None:
        body["deleted_facts"] = deleted_facts
    return body


def chunk_to_response(chunk: Any) -> dict[str, Any]:
    """Map the legacy chunk read model to the stable v1 HTTP response."""

    return {
        "id": str(chunk.id),
        "document_id": str(chunk.document_id) if chunk.document_id else None,
        "episode_id": str(chunk.episode_id) if chunk.episode_id else None,
        "source_type": chunk.source_type,
        "source_external_id": chunk.source_external_id,
        "text": chunk.text,
        "kind": _raw_value(chunk.kind),
        "sequence": chunk.sequence,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "status": _raw_value(chunk.status),
        "classification": chunk.classification,
        "source_refs": _source_refs_from_metadata(chunk.metadata),
        "metadata": safe_public_metadata(chunk.metadata),
    }


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
    text = str(value)
    return text or None


def _datetime_to_string(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _chunk_node_kind(chunk: Any) -> str:
    metadata = chunk.metadata if isinstance(chunk.metadata, Mapping) else {}
    node_kind = metadata.get("node_kind")
    if node_kind:
        return str(node_kind)
    return str(_raw_value(chunk.kind))


def _document_fragment_summary_from_nodes(
    nodes: Iterable[tuple[str, int]],
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    node_map: dict[str, list[int]] = {}
    total = 0
    for node_kind, sequence in nodes:
        counts[node_kind] = counts.get(node_kind, 0) + 1
        node_map.setdefault(node_kind, []).append(sequence)
        total += 1
    return {
        "fragment_count": total,
        "node_counts": counts,
        "node_map": node_map,
    }


def _source_refs_from_metadata(metadata: Any) -> list[dict[str, Any]]:
    refs = metadata.get("source_refs") if isinstance(metadata, Mapping) else None
    if not isinstance(refs, list):
        return []
    return [safe_public_metadata(item) for item in refs if isinstance(item, Mapping)]


def _legacy_ingest_document_http_request(
    request: LegacyIngestDocumentRequest,
    *,
    space_id: str,
    memory_scope_id: str,
    thread_id: str | None,
    idempotency_key: str | None,
) -> IngestDocumentHttpRequest:
    return IngestDocumentHttpRequest(
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


def _legacy_document_chunk_metadata(
    source_refs: Sequence[LegacyDocumentSourceRefRequest],
) -> dict[str, object] | None:
    refs = tuple(source_refs[:24])
    if not refs:
        return None
    return {
        "source_refs": [
            item.model_dump(exclude_none=True, mode="json") for item in refs
        ],
        "source_ref_count": len(refs),
    }


def _raw_value(value: Any) -> Any:
    return getattr(value, "value", value)


__all__ = (
    "DEFAULT_DOCUMENT_CLASSIFICATION",
    "DEFAULT_DOCUMENT_SOURCE_TYPE",
    "chunk_to_response",
    "document_to_response",
    "ingest_document_command_from_contract",
    "ingest_document_result_to_contract",
    "legacy_ingest_document_command_from_request",
)
