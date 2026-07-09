"""Dto Facts DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from infinity_context_core.domain.entities import (
    MemoryChunk,
    MemoryChunkKind,
    MemoryDocument,
    MemoryEpisode,
    MemoryFact,
    MemoryFactRelation,
    MemoryKind,
    MemoryScopeId,
    SourceRef,
    SpaceId,
    SpeakerRole,
    ThreadId,
    TrustLevel,
)
from infinity_context_core.ports.capabilities import ConsistencyMode as ConsistencyMode


@dataclass(frozen=True)
class RememberFactCommand:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    text: str
    kind: MemoryKind
    source_refs: tuple[SourceRef, ...]
    thread_id: ThreadId | None = None
    idempotency_key: str | None = None
    classification: str = "internal"
    category: str | None = None
    tags: tuple[str, ...] = ()
    ttl_policy: str | None = None
    expires_at: datetime | None = None

@dataclass(frozen=True)
class UpdateFactCommand:
    fact_id: str
    expected_version: int
    text: str
    source_refs: tuple[SourceRef, ...]
    reason: str

@dataclass(frozen=True)
class ForgetFactCommand:
    fact_id: str

@dataclass(frozen=True)
class FactResult:
    fact: MemoryFact
    indexing_status: str

@dataclass(frozen=True)
class GetFactQuery:
    fact_id: str

@dataclass(frozen=True)
class FactVersionsQuery:
    fact_id: str

@dataclass(frozen=True)
class RelatedFactsQuery:
    fact_id: str
    limit: int = 10
    include_other_threads: bool = False

@dataclass(frozen=True)
class ListFactsQuery:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    thread_id: ThreadId | None
    status: str | None
    limit: int
    cursor_updated_at: datetime | None = None
    cursor_id: str | None = None
    category: str | None = None
    tag: str | None = None

@dataclass(frozen=True)
class FactQueryResult:
    fact: MemoryFact

@dataclass(frozen=True)
class FactsQueryResult:
    facts: tuple[MemoryFact, ...]

@dataclass(frozen=True)
class RelatedFactItem:
    fact: MemoryFact
    score: float
    relation_reasons: tuple[str, ...]

@dataclass(frozen=True)
class RelatedFactsResult:
    target: MemoryFact
    items: tuple[RelatedFactItem, ...]
    diagnostics: dict[str, object]

@dataclass(frozen=True)
class LinkFactsCommand:
    source_fact_id: str
    target_fact_id: str
    relation_type: str
    reason: str
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None

@dataclass(frozen=True)
class ListFactRelationsQuery:
    fact_id: str
    status: str | None = "active"
    limit: int = 50

@dataclass(frozen=True)
class UnlinkFactRelationCommand:
    relation_id: str

@dataclass(frozen=True)
class FactRelationItem:
    relation: MemoryFactRelation
    related_fact: MemoryFact
    direction: str

@dataclass(frozen=True)
class FactRelationResult:
    relation: MemoryFactRelation

@dataclass(frozen=True)
class FactRelationsResult:
    target: MemoryFact
    items: tuple[FactRelationItem, ...]

@dataclass(frozen=True)
class EnsureScopeCommand:
    space_slug: str
    memory_scope_external_ref: str
    thread_external_ref: str | None = None

@dataclass(frozen=True)
class ScopeResult:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    thread_id: ThreadId | None = None

@dataclass(frozen=True)
class IngestEpisodeCommand:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    thread_id: ThreadId
    source_type: str
    source_external_id: str
    text: str
    occurred_at: object | None = None
    speaker: SpeakerRole = SpeakerRole.UNKNOWN
    trust_level: TrustLevel = TrustLevel.MEDIUM
    kind_hint: MemoryChunkKind | None = None
    language: str | None = None
    metadata: dict[str, object] | None = None
    idempotency_key: str | None = None

@dataclass(frozen=True)
class IngestEpisodeResult:
    episode: MemoryEpisode | None
    stored_chunks: int
    duplicate_chunks: int
    durability: str
    created_suggestions: int = 0
    suggestion_ids: tuple[str, ...] = ()

@dataclass(frozen=True)
class IngestDocumentCommand:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    title: str
    text: str
    source_type: str
    source_external_id: str
    thread_id: ThreadId | None = None
    idempotency_key: str | None = None
    classification: str = "unknown"
    chunk_metadata: dict[str, object] | None = None

@dataclass(frozen=True)
class IngestDocumentResult:
    document: MemoryDocument
    chunks: tuple[MemoryChunk, ...]
    duplicate_chunks: int
    indexing_status: str

@dataclass(frozen=True)
class GetDocumentQuery:
    document_id: str

@dataclass(frozen=True)
class ListDocumentChunksQuery:
    document_id: str
    limit: int
    cursor_sequence: int | None = None
    cursor_id: str | None = None

@dataclass(frozen=True)
class DocumentQueryResult:
    document: MemoryDocument

@dataclass(frozen=True)
class DocumentChunksQueryResult:
    document: MemoryDocument
    chunks: tuple[MemoryChunk, ...]

@dataclass(frozen=True)
class ExportGraphQuery:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    thread_id: ThreadId | None
    include_deleted: bool
    include_restricted: bool
    max_facts: int
    max_documents: int
    max_episodes: int
    max_chunks: int
    max_anchors: int = 100

@dataclass(frozen=True)
class GraphExportNode:
    id: str
    type: str
    label: str
    data: dict[str, object]

@dataclass(frozen=True)
class GraphExportEdge:
    id: str
    type: str
    source: str
    target: str
    label: str
    data: dict[str, object]

@dataclass(frozen=True)
class GraphExportResult:
    schema_version: str
    scope: dict[str, object]
    nodes: tuple[GraphExportNode, ...]
    edges: tuple[GraphExportEdge, ...]
    counts: dict[str, int]
    truncated: bool
    warnings: tuple[str, ...]

@dataclass(frozen=True)
class DeleteDocumentCommand:
    document_id: str

@dataclass(frozen=True)
class ProcessDocumentCommand:
    document_id: str
    idempotency_key: str | None = None

@dataclass(frozen=True)
class DeleteDocumentResult:
    document: MemoryDocument
    deleted_chunks: int
    deleted_facts: int
    indexing_status: str

@dataclass(frozen=True)
class ProcessDocumentResult:
    document: MemoryDocument
    chunks: int
    indexing_status: str
