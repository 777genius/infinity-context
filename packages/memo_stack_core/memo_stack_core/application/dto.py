"""Application command/result DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from memo_stack_core.domain.assets import (
    MemoryAsset,
    MemoryContextLink,
    MemoryContextLinkSuggestion,
)
from memo_stack_core.domain.capture import CanonicalCapture
from memo_stack_core.domain.entities import (
    MemoryAnchor,
    MemoryChunk,
    MemoryChunkKind,
    MemoryDocument,
    MemoryEpisode,
    MemoryFact,
    MemoryFactRelation,
    MemoryKind,
    MemoryScope,
    MemoryScopeId,
    MemorySpace,
    MemorySuggestion,
    MemoryThread,
    SourceRef,
    SpaceId,
    SpaceMembership,
    SpeakerRole,
    ThreadId,
    TrustLevel,
    User,
)
from memo_stack_core.domain.extraction import AssetExtractionJob, ExtractionArtifact
from memo_stack_core.domain.usage import ProductPlan, UsageQuotaSnapshot
from memo_stack_core.ports.capabilities import ConsistencyMode as ConsistencyMode


@dataclass(frozen=True)
class CreateSpaceCommand:
    slug: str
    name: str


@dataclass(frozen=True)
class CreateMemoryScopeCommand:
    space_id: SpaceId
    external_ref: str
    name: str


@dataclass(frozen=True)
class UpdateMemoryScopeCommand:
    memory_scope_id: MemoryScopeId
    external_ref: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class DeleteMemoryScopeCommand:
    memory_scope_id: MemoryScopeId


@dataclass(frozen=True)
class SpaceResult:
    space: MemorySpace
    created: bool = True


@dataclass(frozen=True)
class MemoryScopeResult:
    memory_scope: MemoryScope
    created: bool = True


@dataclass(frozen=True)
class CreateUserCommand:
    external_ref: str
    display_name: str
    email: str | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class ListUsersQuery:
    status: str | None = "active"
    limit: int = 100


@dataclass(frozen=True)
class UserResult:
    user: User
    created: bool = True


@dataclass(frozen=True)
class UsersResult:
    users: tuple[User, ...]


@dataclass(frozen=True)
class CreateSpaceMembershipCommand:
    space_id: SpaceId
    user_id: str
    role: str


@dataclass(frozen=True)
class ListSpaceMembershipsQuery:
    space_id: SpaceId
    status: str | None = "active"
    limit: int = 100


@dataclass(frozen=True)
class CheckSpaceAccessQuery:
    space_id: SpaceId
    user_id: str
    required_role: str = "viewer"


@dataclass(frozen=True)
class SpaceMembershipResult:
    membership: SpaceMembership
    created: bool = True


@dataclass(frozen=True)
class SpaceMembershipsResult:
    memberships: tuple[SpaceMembership, ...]


@dataclass(frozen=True)
class SpaceAccessResult:
    allowed: bool
    membership: SpaceMembership | None
    required_role: str


@dataclass(frozen=True)
class CreateAssetCommand:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    filename: str
    content_type: str
    content: bytes
    thread_id: ThreadId | None = None
    classification: str = "unknown"
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class DeleteAssetCommand:
    asset_id: str


@dataclass(frozen=True)
class AssetResult:
    asset: MemoryAsset
    duplicate: bool = False


@dataclass(frozen=True)
class GetAssetQuery:
    asset_id: str


@dataclass(frozen=True)
class ListAssetsQuery:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    thread_id: ThreadId | None
    status: str | None
    limit: int
    cursor_created_at: datetime | None = None
    cursor_id: str | None = None


@dataclass(frozen=True)
class RequestAssetExtractionCommand:
    asset_id: str
    parser_profile: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True)
class RunAssetExtractionCommand:
    job_id: str
    force: bool = False
    worker_id: str | None = None


@dataclass(frozen=True)
class GetAssetExtractionQuery:
    job_id: str


@dataclass(frozen=True)
class ListAssetExtractionsQuery:
    asset_id: str | None = None
    space_id: SpaceId | None = None
    memory_scope_id: MemoryScopeId | None = None
    thread_id: ThreadId | None = None
    status: str | None = None
    limit: int = 50
    cursor_created_at: datetime | None = None
    cursor_id: str | None = None


@dataclass(frozen=True)
class GetExtractionArtifactQuery:
    artifact_id: str


@dataclass(frozen=True)
class RetryAssetExtractionCommand:
    job_id: str


@dataclass(frozen=True)
class CancelAssetExtractionCommand:
    job_id: str


@dataclass(frozen=True)
class AssetExtractionResult:
    job: AssetExtractionJob
    artifacts: tuple[ExtractionArtifact, ...] = ()
    duplicate: bool = False
    indexing_status: str = "pending"


@dataclass(frozen=True)
class AssetExtractionsResult:
    jobs: tuple[AssetExtractionJob, ...]


@dataclass(frozen=True)
class MemoryOperationsConsoleQuery:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    thread_id: ThreadId | None = None
    limit: int = 50


@dataclass(frozen=True)
class MemoryOperationsConsoleResult:
    generated_at: datetime
    scope: dict[str, object]
    extraction_status_counts: dict[str, int]
    link_suggestion_status_counts: dict[str, int]
    extraction_jobs: tuple[AssetExtractionJob, ...]
    context_link_suggestions: tuple[MemoryContextLinkSuggestion, ...]
    diagnostics: dict[str, object]


@dataclass(frozen=True)
class MemoryBrowserQuery:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    limit: int = 50
    fact_status: str | None = "active"
    episode_status: str | None = "active"
    document_status: str | None = "active"
    chunk_status: str | None = "active"
    extraction_status: str | None = None
    thread_status: str | None = "active"
    capture_status: str | None = None
    asset_status: str | None = "stored"
    anchor_status: str | None = "active"
    link_status: str | None = None
    suggestion_status: str | None = None


@dataclass(frozen=True)
class MemoryBrowserResult:
    generated_at: datetime
    memory_scope: MemoryScope
    facts: tuple[MemoryFact, ...]
    episodes: tuple[MemoryEpisode, ...]
    documents: tuple[MemoryDocument, ...]
    chunks: tuple[MemoryChunk, ...]
    extraction_jobs: tuple[AssetExtractionJob, ...]
    threads: tuple[MemoryThread, ...]
    captures: tuple[CanonicalCapture, ...]
    assets: tuple[MemoryAsset, ...]
    anchors: tuple[MemoryAnchor, ...]
    context_links: tuple[MemoryContextLink, ...]
    context_link_suggestions: tuple[MemoryContextLinkSuggestion, ...]
    stats: dict[str, int]
    diagnostics: dict[str, object]


@dataclass(frozen=True)
class ExtractionArtifactBytesResult:
    artifact: ExtractionArtifact
    content: bytes


@dataclass(frozen=True)
class UsageSummaryQuery:
    space_id: SpaceId


@dataclass(frozen=True)
class UsageResourceSummary:
    resource: str
    limit: int
    used: int
    remaining: int
    window_start: datetime
    window_end: datetime


@dataclass(frozen=True)
class UsageSummaryResult:
    plan: ProductPlan
    resources: tuple[UsageResourceSummary, ...]

    @classmethod
    def from_snapshots(
        cls,
        *,
        plan: ProductPlan,
        snapshots: tuple[UsageQuotaSnapshot, ...],
    ) -> UsageSummaryResult:
        return cls(
            plan=plan,
            resources=tuple(
                UsageResourceSummary(
                    resource=snapshot.resource.value,
                    limit=snapshot.limit,
                    used=snapshot.used,
                    remaining=snapshot.remaining,
                    window_start=snapshot.window.start,
                    window_end=snapshot.window.end,
                )
                for snapshot in snapshots
            ),
        )


@dataclass(frozen=True)
class ListAnchorsQuery:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    kind: str | None = None
    status: str | None = "active"
    limit: int = 100


@dataclass(frozen=True)
class CreateAnchorCommand:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    kind: str
    label: str
    aliases: tuple[str, ...] = ()
    description: str | None = None
    confidence: str | None = None
    evidence_refs: tuple[SourceRef, ...] = ()
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class UpdateAnchorCommand:
    anchor_id: str
    label: str | None = None
    aliases: tuple[str, ...] = ()
    description: str | None = None
    confidence: str | None = None
    evidence_refs: tuple[SourceRef, ...] = ()
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class DeleteAnchorCommand:
    anchor_id: str
    reason: str = "manual delete"


@dataclass(frozen=True)
class AnchorResult:
    anchor: MemoryAnchor


@dataclass(frozen=True)
class AnchorsResult:
    anchors: tuple[MemoryAnchor, ...]


@dataclass(frozen=True)
class AnchorMergeCandidate:
    source_anchor: MemoryAnchor
    target_anchor: MemoryAnchor
    confidence: str
    score: float
    reasons: tuple[str, ...]
    metadata: dict[str, object]


@dataclass(frozen=True)
class AnchorMergeSuggestionsQuery:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    kind: str | None = None
    limit: int = 50


@dataclass(frozen=True)
class AnchorMergeSuggestionsResult:
    candidates: tuple[AnchorMergeCandidate, ...]
    diagnostics: dict[str, object]


@dataclass(frozen=True)
class MergeAnchorsCommand:
    source_anchor_id: str
    target_anchor_id: str
    reason: str


@dataclass(frozen=True)
class SplitAnchorCommand:
    anchor_id: str
    alias: str
    new_label: str | None = None
    reason: str = "manual split"


@dataclass(frozen=True)
class BackfillAnchorsCommand:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    limit_per_source: int = 100


@dataclass(frozen=True)
class AnchorBackfillSourceSummary:
    source_type: str
    scanned: int
    observed: int
    skipped_conflicts: int = 0


@dataclass(frozen=True)
class BackfillAnchorsResult:
    anchors: tuple[MemoryAnchor, ...]
    created: int
    updated: int
    sources: tuple[AnchorBackfillSourceSummary, ...]
    diagnostics: dict[str, object]


@dataclass(frozen=True)
class CreateContextLinkCommand:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    relation_type: str
    reason: str
    confidence: str = "medium"
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class DeleteContextLinkCommand:
    context_link_id: str


@dataclass(frozen=True)
class UpdateContextLinkCommand:
    context_link_id: str
    source_type: str | None = None
    source_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    relation_type: str | None = None
    confidence: str | None = None
    reason: str | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class ContextLinkResult:
    link: MemoryContextLink
    duplicate: bool = False


@dataclass(frozen=True)
class ContextLinkSuggestionResult:
    suggestion: MemoryContextLinkSuggestion
    link: MemoryContextLink | None = None
    duplicate_link: bool = False


@dataclass(frozen=True)
class ListContextLinksQuery:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    status: str | None
    limit: int
    source_type: str | None = None
    source_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    relation_type: str | None = None
    statuses: tuple[str, ...] | None = None


@dataclass(frozen=True)
class SuggestContextLinksCommand:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    text: str
    source_type: str | None = None
    source_id: str | None = None
    thread_id: ThreadId | None = None
    limit: int = 10
    persist: bool = False


@dataclass(frozen=True)
class ContextLinkCandidate:
    target_type: str
    target_id: str
    label: str
    preview: str
    score: float
    tier: str
    reasons: tuple[str, ...]
    suggestion_id: str | None = None
    status: str | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class ContextLinkSuggestionsResult:
    candidates: tuple[ContextLinkCandidate, ...]
    diagnostics: dict[str, object]


@dataclass(frozen=True)
class ListContextLinkSuggestionsQuery:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    status: str | None
    limit: int
    source_type: str | None = None
    source_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    relation_type: str | None = None
    statuses: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ReviewContextLinkSuggestionCommand:
    suggestion_id: str
    action: str
    reason: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    relation_type: str | None = None
    confidence: str | None = None
    link_reason: str | None = None


@dataclass(frozen=True)
class ReviewContextLinkSuggestionBatchItemCommand:
    suggestion_id: str
    action: str
    reason: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    relation_type: str | None = None
    confidence: str | None = None
    link_reason: str | None = None


@dataclass(frozen=True)
class ContextLinkSuggestionVisibleFilter:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    status: str | None
    limit: int
    source_type: str | None = None
    source_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    relation_type: str | None = None
    statuses: tuple[str, ...] | None = None


@dataclass(frozen=True)
class ReviewContextLinkSuggestionsBatchCommand:
    items: tuple[ReviewContextLinkSuggestionBatchItemCommand, ...]
    continue_on_error: bool = False
    visible_filter: ContextLinkSuggestionVisibleFilter | None = None


@dataclass(frozen=True)
class ReviewContextLinkSuggestionBatchItemResult:
    suggestion_id: str
    action: str
    status: str
    result: ContextLinkSuggestionResult | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class ReviewContextLinkSuggestionsBatchResult:
    applied: int
    failed: int
    stopped: bool
    results: tuple[ReviewContextLinkSuggestionBatchItemResult, ...]
    diagnostics: dict[str, object] = field(default_factory=dict)


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
    memory_scope_ids: tuple[MemoryScopeId, ...]
    query: str
    thread_id: ThreadId | None = None
    consistency_mode: ConsistencyMode = ConsistencyMode.BEST_EFFORT
    token_budget: int = 1800
    max_rendered_chars: int = 18000
    max_facts: int = 20
    max_chunks: int = 30
    max_conflicting_suggestions: int = 5
    include_graph: bool = True
    include_superseded: bool = False
    include_stale: bool = False
    category: str | None = None
    tags_any: tuple[str, ...] = ()
    tags_all: tuple[str, ...] = ()
    tags_none: tuple[str, ...] = ()


@dataclass(frozen=True)
class BuildMemoryDigestQuery:
    space_id: SpaceId
    memory_scope_ids: tuple[MemoryScopeId, ...]
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
    memory_scope_ids: tuple[MemoryScopeId, ...]
    thread_id: ThreadId | None = None
    max_facts: int = 200
    max_documents: int = 100
    max_episodes: int = 100
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
    memory_scope_id: str
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
    memory_scope_id: str
    thread_id: str | None
    status: str
    preview: str | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class MemoryConsolidationPlanItem:
    id: str
    plan_type: str
    memory_scope_id: str
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
    memory_scope_id: MemoryScopeId
    thread_id: ThreadId


@dataclass(frozen=True)
class DeleteThreadMemoryResult:
    deleted_chunks: int
    deleted_facts: int
    deleted_jobs: int


@dataclass(frozen=True)
class GetSessionStatusQuery:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
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
    memory_scope_id: MemoryScopeId
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
    created: bool = True


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
    existing: int
    failed: int
    stopped: bool
    results: tuple[CreateSuggestionBatchItemResult, ...]


@dataclass(frozen=True)
class ListSuggestionsQuery:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
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
    memory_scope_id: MemoryScopeId
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
    memory_scope_id: MemoryScopeId
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
