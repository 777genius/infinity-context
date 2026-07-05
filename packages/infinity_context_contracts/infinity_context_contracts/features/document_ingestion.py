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
class DocumentSourceDto:
    """Stable public source fields for an ingested document."""

    source_type: str = "document"
    source_external_id: str | None = None
    source_uri: str | None = None
    media_type: str = "text/plain"
    classification: str = "unknown"

    def to_dict(self) -> JsonObject:
        return {
            "source_type": self.source_type,
            "source_external_id": self.source_external_id,
            "source_uri": self.source_uri,
            "media_type": self.media_type,
            "classification": self.classification,
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
    source: DocumentSourceDto | Mapping[str, JsonValue] | None = None
    source_uri: str | None = None
    media_type: str = "text/plain"
    classification: str | None = None
    status: str = "processed"
    content_hash: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        source = _document_source_to_dict(
            source=self.source,
            source_uri=self.source_uri,
            media_type=self.media_type,
            classification=self.classification,
            metadata=self.metadata,
        )
        return {
            **self.identity.to_dict(),
            "title": self.title,
            "source": source,
            "source_uri": self.source_uri,
            "media_type": self.media_type,
            "classification": _source_field(
                "classification",
                explicit=self.classification,
                metadata=self.metadata,
                default="unknown",
            ),
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
    source_type: str | None = None
    source_external_id: str | None = None
    source_uri: str | None = None
    media_type: str = "text/plain"
    classification: str | None = None
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
            "source_type": _source_field(
                "source_type",
                explicit=self.source_type,
                metadata=self.metadata,
                default="document",
            ),
            "source_external_id": _source_field(
                "source_external_id",
                explicit=self.source_external_id,
                metadata=self.metadata,
            ),
            "source_uri": self.source_uri,
            "media_type": self.media_type,
            "classification": _source_field(
                "classification",
                explicit=self.classification,
                metadata=self.metadata,
                default="unknown",
            ),
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


def _document_source_to_dict(
    *,
    source: DocumentSourceDto | Mapping[str, JsonValue] | None,
    source_uri: str | None,
    media_type: str,
    classification: str | None,
    metadata: Mapping[str, JsonValue],
) -> JsonValue:
    if source is not None:
        return json_compatible(source)
    if not _has_source_metadata(metadata) and source_uri is None:
        return None
    return DocumentSourceDto(
        source_type=str(
            _source_field("source_type", metadata=metadata, default="document")
        ),
        source_external_id=_optional_source_text(
            _source_field("source_external_id", metadata=metadata)
        ),
        source_uri=source_uri,
        media_type=media_type,
        classification=str(
            _source_field(
                "classification",
                explicit=classification,
                metadata=metadata,
                default="unknown",
            )
        ),
    ).to_dict()


def _has_source_metadata(metadata: Mapping[str, JsonValue]) -> bool:
    return any(
        key in metadata
        for key in ("source_type", "source_external_id", "classification")
    )


def _source_field(
    key: str,
    *,
    explicit: str | None = None,
    metadata: Mapping[str, JsonValue],
    default: str | None = None,
) -> JsonValue:
    if explicit is not None:
        return explicit
    return metadata.get(key, default)


def _optional_source_text(value: JsonValue) -> str | None:
    if value is None:
        return None
    return str(value)


__all__ = [
    "FEATURE_ID",
    "DocumentChunkDto",
    "DocumentIdentityDto",
    "DocumentSourceDto",
    "IngestDocumentRequestDto",
    "IngestDocumentResultDto",
    "MemoryDocumentDto",
]
