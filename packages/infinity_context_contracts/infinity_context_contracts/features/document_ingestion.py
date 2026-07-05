"""Public contract DTOs for the document_ingestion feature."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .._json import JsonObject, JsonValue, json_compatible

FEATURE_ID = "document_ingestion"


@dataclass(frozen=True, slots=True)
class DocumentIdentityDto:
    """Stable public identity fields for an ingested document."""

    id: str
    space_id: str
    memory_scope_id: str
    thread_id: str | None = None

    def to_dict(self) -> JsonObject:
        return {
            "id": self.id,
            "space_id": self.space_id,
            "memory_scope_id": self.memory_scope_id,
            "thread_id": self.thread_id,
        }


@dataclass(frozen=True, slots=True)
class DocumentChunkDto:
    """Retrievable chunk derived from a canonical document."""

    id: str
    document_id: str
    chunk_index: int
    text: str
    char_start: int | None = None
    char_end: int | None = None
    token_count: int | None = None
    content_hash: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "token_count": self.token_count,
            "content_hash": self.content_hash,
            "metadata": json_compatible(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class MemoryDocumentDto:
    """Stable read model for an ingested document."""

    identity: DocumentIdentityDto
    title: str | None = None
    source_uri: str | None = None
    media_type: str = "text/plain"
    status: str = "processed"
    content_hash: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        return {
            **self.identity.to_dict(),
            "title": self.title,
            "source_uri": self.source_uri,
            "media_type": self.media_type,
            "status": self.status,
            "content_hash": self.content_hash,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": json_compatible(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class IngestDocumentRequestDto:
    """Stable request shape for canonical document ingestion."""

    text: str
    title: str | None = None
    source_uri: str | None = None
    media_type: str = "text/plain"
    space_id: str | None = None
    memory_scope_id: str | None = None
    thread_id: str | None = None
    space_slug: str | None = None
    memory_scope_external_ref: str | None = None
    thread_external_ref: str | None = None
    content_hash: str | None = None
    idempotency_key: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        return {
            "text": self.text,
            "title": self.title,
            "source_uri": self.source_uri,
            "media_type": self.media_type,
            "space_id": self.space_id,
            "memory_scope_id": self.memory_scope_id,
            "thread_id": self.thread_id,
            "space_slug": self.space_slug,
            "memory_scope_external_ref": self.memory_scope_external_ref,
            "thread_external_ref": self.thread_external_ref,
            "content_hash": self.content_hash,
            "idempotency_key": self.idempotency_key,
            "metadata": json_compatible(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class IngestDocumentResultDto:
    """Stable result wrapper for document ingestion."""

    document: MemoryDocumentDto
    chunks: Sequence[DocumentChunkDto | Mapping[str, JsonValue]] = field(
        default_factory=tuple
    )
    created: bool = True
    indexing_status: str | None = None

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "document": self.document.to_dict(),
            "chunks": _chunks_to_dicts(self.chunks),
            "created": self.created,
        }
        if self.indexing_status is not None:
            payload["indexing_status"] = self.indexing_status
        return {"data": payload}


def _chunks_to_dicts(
    chunks: Sequence[DocumentChunkDto | Mapping[str, JsonValue]],
) -> JsonValue:
    return json_compatible(
        [
            chunk.to_dict() if isinstance(chunk, DocumentChunkDto) else dict(chunk)
            for chunk in chunks
        ]
    )


__all__ = [
    "FEATURE_ID",
    "DocumentChunkDto",
    "DocumentIdentityDto",
    "IngestDocumentRequestDto",
    "IngestDocumentResultDto",
    "MemoryDocumentDto",
]
