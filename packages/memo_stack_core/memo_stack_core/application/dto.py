"""Application command/result DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from memo_stack_core.domain.capture import CanonicalCapture
from memo_stack_core.domain.entities import (
    MemoryChunk,
    MemoryChunkKind,
    MemoryDocument,
    MemoryEpisode,
    MemoryFact,
    MemoryFactRelation,
    MemoryKind,
    MemoryProfile,
    MemorySpace,
    MemorySuggestion,
    ProfileId,
    SourceRef,
    SpaceId,
    SpeakerRole,
    ThreadId,
    TrustLevel,
)
from memo_stack_core.ports.capabilities import ConsistencyMode as ConsistencyMode


@dataclass(frozen=True)
class CreateSpaceCommand:
    slug: str
    name: str


@dataclass(frozen=True)
class CreateProfileCommand:
    space_id: SpaceId
    external_ref: str
    name: str


@dataclass(frozen=True)
class SpaceResult:
    space: MemorySpace
    created: bool = True


@dataclass(frozen=True)
class ProfileResult:
    profile: MemoryProfile
    created: bool = True


@dataclass(frozen=True)
class RememberFactCommand:
    space_id: SpaceId
    profile_id: ProfileId
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
    profile_id: ProfileId
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
    profile_external_ref: str
    thread_external_ref: str | None = None


@dataclass(frozen=True)
class ScopeResult:
    space_id: SpaceId
    profile_id: ProfileId
    thread_id: ThreadId | None = None


@dataclass(frozen=True)
class IngestEpisodeCommand:
    space_id: SpaceId
    profile_id: ProfileId
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
    profile_id: ProfileId
    title: str
    text: str
    source_type: str
    source_external_id: str
    thread_id: ThreadId | None = None
    idempotency_key: str | None = None
    classification: str = "unknown"


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
    profile_id: ProfileId
    thread_id: ThreadId | None
    include_deleted: bool
    include_restricted: bool
    max_facts: int
    max_documents: int
    max_chunks: int


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


@dataclass(frozen=True)
class ContextItem:
    item_id: str
    item_type: str
    text: str
    score: float
    source_refs: tuple[SourceRef, ...]
    is_instruction: bool = False
    diagnostics: dict[str, object] | None = None


@dataclass(frozen=True)
class ContextBundle:
    bundle_id: str
    rendered_text: str
    items: tuple[ContextItem, ...]
    token_estimate: int
    diagnostics: dict[str, object]


@dataclass(frozen=True)
class BuildContextQuery:
    space_id: SpaceId
    profile_ids: tuple[ProfileId, ...]
    query: str
    thread_id: ThreadId | None = None
    consistency_mode: ConsistencyMode = ConsistencyMode.BEST_EFFORT
    token_budget: int = 1800
    max_rendered_chars: int = 18000
    max_facts: int = 20
    max_chunks: int = 30
    include_graph: bool = True
    category: str | None = None
    tags_any: tuple[str, ...] = ()
    tags_all: tuple[str, ...] = ()
    tags_none: tuple[str, ...] = ()


@dataclass(frozen=True)
class BuildMemoryDigestQuery:
    space_id: SpaceId
    profile_ids: tuple[ProfileId, ...]
    topic: str
    thread_id: ThreadId | None = None
    consistency_mode: ConsistencyMode = ConsistencyMode.BEST_EFFORT
    token_budget: int = 2400
    max_rendered_chars: int = 24000
    max_facts: int = 20
    max_chunks: int = 20
    max_suggestions: int = 10
    include_pending_suggestions: bool = True
    include_superseded: bool = False
    include_related: bool = True


@dataclass(frozen=True)
class MemoryDigestSection:
    title: str
    items: tuple[ContextItem, ...]
    truncated: bool = False


@dataclass(frozen=True)
class MemoryDigest:
    digest_id: str
    topic: str
    rendered_markdown: str
    sections: tuple[MemoryDigestSection, ...]
    source_refs: tuple[SourceRef, ...]
    token_estimate: int
    diagnostics: dict[str, object]


@dataclass(frozen=True)
class BuildMemoryInsightsQuery:
    space_id: SpaceId
    profile_ids: tuple[ProfileId, ...]
    thread_id: ThreadId | None = None
    max_facts: int = 200
    max_documents: int = 100
    max_suggestions: int = 100
    max_captures: int = 100
    max_activity: int = 50


@dataclass(frozen=True)
class MemoryInsightActionItem:
    id: str
    severity: str
    action: str
    target_type: str
    target_id: str | None
    profile_id: str
    reason: str
    preview: str | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class MemoryActivityItem:
    id: str
    occurred_at: datetime
    event_type: str
    entity_type: str
    entity_id: str
    profile_id: str
    thread_id: str | None
    status: str
    preview: str | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class MemoryConsolidationPlanItem:
    id: str
    plan_type: str
    profile_id: str
    confidence: str
    canonical_candidate_id: str
    candidate_fact_ids: tuple[str, ...]
    recommended_steps: tuple[str, ...]
    reason: str
    preview: str | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class MemoryInsightsResult:
    insights_id: str
    generated_at: datetime
    scope: dict[str, object]
    health_score: float
    metrics: dict[str, object]
    taxonomy: dict[str, object]
    action_items: tuple[MemoryInsightActionItem, ...]
    recent_activity: tuple[MemoryActivityItem, ...]
    consolidation_plan: tuple[MemoryConsolidationPlanItem, ...]
    diagnostics: dict[str, object]


@dataclass(frozen=True)
class DeleteThreadMemoryCommand:
    space_id: SpaceId
    profile_id: ProfileId
    thread_id: ThreadId


@dataclass(frozen=True)
class DeleteThreadMemoryResult:
    deleted_chunks: int
    deleted_facts: int
    deleted_jobs: int


@dataclass(frozen=True)
class GetSessionStatusQuery:
    space_id: SpaceId
    profile_id: ProfileId
    thread_id: ThreadId


@dataclass(frozen=True)
class SessionStatusResult:
    chunks: int
    facts: int
    jobs: int
    pending_jobs: int


@dataclass(frozen=True)
class CreateSuggestionCommand:
    space_id: SpaceId
    profile_id: ProfileId
    candidate_text: str
    kind: MemoryKind
    source_refs: tuple[SourceRef, ...]
    safe_reason: str
    confidence: str = "medium"
    trust_level: str = "medium"
    target_fact_id: str | None = None
    target_fact_version: int | None = None
    operation: str = "add"
    category: str | None = None
    tags: tuple[str, ...] = ()
    ttl_policy: str | None = None
    expires_at: datetime | None = None
    expiry_reason: str | None = None
    created_from_capture_id: str | None = None
    candidate_fingerprint: str | None = None
    review_payload: dict[str, object] | None = None
    auto_approve: bool = False


@dataclass(frozen=True)
class CreateSuggestionsBatchCommand:
    items: tuple[CreateSuggestionCommand, ...]
    continue_on_error: bool = False


@dataclass(frozen=True)
class SuggestionResult:
    suggestion: MemorySuggestion
    fact: MemoryFact | None = None
    indexing_status: str | None = None


@dataclass(frozen=True)
class CreateSuggestionBatchItemResult:
    index: int
    status: str
    result: SuggestionResult | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class CreateSuggestionsBatchResult:
    created: int
    failed: int
    stopped: bool
    results: tuple[CreateSuggestionBatchItemResult, ...]


@dataclass(frozen=True)
class ListSuggestionsQuery:
    space_id: SpaceId
    profile_id: ProfileId
    status: str | None = None
    operation: str | None = None
    category: str | None = None
    tag: str | None = None
    limit: int = 100


@dataclass(frozen=True)
class ApproveSuggestionCommand:
    suggestion_id: str
    reason: str | None = None
    force: bool = False


@dataclass(frozen=True)
class RejectSuggestionCommand:
    suggestion_id: str
    reason: str | None = None


@dataclass(frozen=True)
class ExpireSuggestionCommand:
    suggestion_id: str
    reason: str | None = None


@dataclass(frozen=True)
class ReviewSuggestionBatchItemCommand:
    suggestion_id: str
    action: str
    reason: str | None = None
    force: bool = False


@dataclass(frozen=True)
class ReviewSuggestionsBatchCommand:
    items: tuple[ReviewSuggestionBatchItemCommand, ...]
    continue_on_error: bool = False


@dataclass(frozen=True)
class ReviewSuggestionBatchItemResult:
    suggestion_id: str
    action: str
    status: str
    result: SuggestionResult | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class ReviewSuggestionsBatchResult:
    applied: int
    failed: int
    stopped: bool
    results: tuple[ReviewSuggestionBatchItemResult, ...]


@dataclass(frozen=True)
class ReceiveCaptureCommand:
    space_id: SpaceId
    profile_id: ProfileId
    text: str
    source_agent: str
    source_kind: str
    event_type: str
    actor_role: str = "unknown"
    thread_id: ThreadId | None = None
    evidence_refs: tuple[SourceRef, ...] = ()
    trust_level: str = "medium"
    source_authority: str = "unknown"
    sensitivity: str = "medium"
    data_classification: str = "internal"
    occurred_at: datetime | None = None
    metadata: dict[str, object] | None = None
    source_event_id: str | None = None
    source_actor_external_ref: str | None = None
    client_instance_id: str | None = None
    agent_session_external_ref: str | None = None
    turn_external_ref: str | None = None
    parent_capture_id: str | None = None
    sequence_index: int | None = None
    trace_id: str | None = None
    idempotency_key: str | None = None
    consolidate: bool = True


@dataclass(frozen=True)
class CaptureResult:
    capture: CanonicalCapture
    duplicate: bool = False
    created_suggestions: int = 0
    suggestion_ids: tuple[str, ...] = ()
    auto_applied_facts: int = 0
    auto_applied_fact_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ListCapturesQuery:
    space_id: SpaceId
    profile_id: ProfileId
    status: str | None = None
    consolidation_status: str | None = None
    limit: int = 50
    cursor_created_at: datetime | None = None
    cursor_id: str | None = None


@dataclass(frozen=True)
class GetCaptureQuery:
    capture_id: str


@dataclass(frozen=True)
class PurgeCaptureCommand:
    capture_id: str
    reason: str = "privacy_purge"


@dataclass(frozen=True)
class ConsolidateCaptureCommand:
    capture_id: str
    force: bool = False
