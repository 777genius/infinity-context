"""Public contract DTOs for the document_ingestion feature."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .._json import JsonObject, JsonValue, json_compatible
from ._document_retrieval_projection_v1 import (
    DOCUMENT_RETRIEVAL_PROJECTION_SCHEMA_V1,
    DocumentRetrievalProjectionRelativeTimeIntervalV1Dto,
    DocumentRetrievalProjectionTimeIntervalV1Dto,
    DocumentRetrievalProjectionV1Dto,
    decode_document_retrieval_projection_v1,
)

FEATURE_ID = "document_ingestion"
EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1 = "document-reconciliation.v1"
EXACT_DOCUMENT_RECONCILIATION_MAX_RESPONSE_BYTES = 65_536


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
    retrieval_projection: DocumentRetrievalProjectionV1Dto | None = None

    def __post_init__(self) -> None:
        if self.retrieval_projection is None:
            return
        if not isinstance(self.retrieval_projection, DocumentRetrievalProjectionV1Dto):
            raise ValueError("retrieval_projection has an invalid runtime type")
        projection = self.retrieval_projection
        object.__setattr__(
            self,
            "retrieval_projection",
            DocumentRetrievalProjectionV1Dto(
                locator=projection.locator,
                source_key=projection.source_key,
                projection_generation=projection.projection_generation,
                sequence_ordinal=projection.sequence_ordinal,
                actor_keys=tuple(projection.actor_keys),
                time_interval=projection.time_interval,
                relative_time_interval=projection.relative_time_interval,
                kind=projection.kind,
                category=projection.category,
                tags=tuple(projection.tags),
                schema_version=projection.schema_version,
            ),
        )

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
            "retrieval_projection": (
                None if self.retrieval_projection is None else self.retrieval_projection.to_dict()
            ),
        }


@dataclass(frozen=True, slots=True)
class IngestDocumentResultDto:
    """Stable result wrapper for document ingestion."""

    document: MemoryDocumentDto
    chunks: Sequence[DocumentChunkDto | Mapping[str, JsonValue]] = field(default_factory=tuple)
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


@dataclass(frozen=True, slots=True)
class ReconcileExactDocumentRequestDto:
    """Exact canonical scope plus opaque source/document identity."""

    space_id: str
    memory_scope_id: str
    source_type: str
    source_external_id: str
    thread_id: str | None = None
    projection_generation: str | None = None
    profile_generation: str | None = None
    idempotency_key: str | None = None
    deadline_ms: int = 5_000
    contract_version: str = EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1

    def __post_init__(self) -> None:
        for name in ("space_id", "memory_scope_id", "source_type", "source_external_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")
        if self.contract_version != EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1:
            raise ValueError("unsupported exact document reconciliation contract_version")
        if not isinstance(self.deadline_ms, int) or isinstance(self.deadline_ms, bool):
            raise ValueError("deadline_ms must be an integer")
        if not 50 <= self.deadline_ms <= 10_000:
            raise ValueError("deadline_ms must be between 50 and 10000")

    def to_dict(self) -> JsonObject:
        return {
            "contract_version": self.contract_version,
            "space_id": self.space_id,
            "memory_scope_id": self.memory_scope_id,
            "thread_id": self.thread_id,
            "source_type": self.source_type,
            "source_external_id": self.source_external_id,
            "projection_generation": self.projection_generation,
            "profile_generation": self.profile_generation,
            "idempotency_key": self.idempotency_key,
            "deadline_ms": self.deadline_ms,
        }


@dataclass(frozen=True, slots=True)
class ExactDocumentReconciliationResultDto:
    contract_version: str
    state: str
    source_type: str
    source_external_id: str
    space_id: str
    memory_scope_id: str
    thread_id: str | None
    document_id: str | None = None
    canonical_status: str | None = None
    projection_generation: str | None = None
    profile_generation: str | None = None
    visibility: str = "not_queryable"
    idempotency_key_matches: bool | None = None

    def to_dict(self) -> JsonObject:
        return {
            "data": {
                "contract_version": self.contract_version,
                "state": self.state,
                "scope": {
                    "space_id": self.space_id,
                    "memory_scope_id": self.memory_scope_id,
                    "thread_id": self.thread_id,
                },
                "source_type": self.source_type,
                "source_external_id": self.source_external_id,
                "document_id": self.document_id,
                "canonical_status": self.canonical_status,
                "projection_generation": self.projection_generation,
                "profile_generation": self.profile_generation,
                "visibility": self.visibility,
                "idempotency_key_matches": self.idempotency_key_matches,
            }
        }


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
        source_type=str(_source_field("source_type", metadata=metadata, default="document")),
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
    return any(key in metadata for key in ("source_type", "source_external_id", "classification"))


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
    "EXACT_DOCUMENT_RECONCILIATION_CONTRACT_V1",
    "EXACT_DOCUMENT_RECONCILIATION_MAX_RESPONSE_BYTES",
    "DocumentChunkDto",
    "DocumentIdentityDto",
    "DocumentSourceDto",
    "DOCUMENT_RETRIEVAL_PROJECTION_SCHEMA_V1",
    "DocumentRetrievalProjectionTimeIntervalV1Dto",
    "DocumentRetrievalProjectionRelativeTimeIntervalV1Dto",
    "DocumentRetrievalProjectionV1Dto",
    "decode_document_retrieval_projection_v1",
    "IngestDocumentRequestDto",
    "IngestDocumentResultDto",
    "MemoryDocumentDto",
    "ReconcileExactDocumentRequestDto",
    "ExactDocumentReconciliationResultDto",
]
