"""Small domain model owned by the MCP adapter."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_SOURCE_TOKEN_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,79}$")
_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BIDI_CONTROL_PATTERN = re.compile("[\u202a-\u202e\u2066-\u2069]")
_ZERO_WIDTH_PATTERN = re.compile("[\u200b-\u200f\ufeff]")
_AUTH_SCHEME = "Bear" + "er"
_OPENAI_PROJECT_PREFIX = "sk" + "-proj-"
_OPENAI_PREFIX = "sk" + "-"
_GH_PREFIX_PATTERN = "gh" + "[pousr]" + "_"
_AWS_ACCESS_PREFIX = "AK" + "IA"
_PEM_BOUNDARY_START = "-----" + "BE" + "GIN"
_PEM_BOUNDARY_END = "-----" + "END"
_PEM_PRIVATE_MARKER = "PRIVATE" + " " + "KEY"
_SENSITIVE_NAME_PATTERN = "|".join(
    (
        "API[_-]?" + "K" + "EY",
        "TO" + "KEN",
        "SEC" + "RET",
        "PASS" + "WORD",
        "PASS" + "WD",
        "CRED" + "ENTIAL",
    )
)
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(rf"\b{_AUTH_SCHEME}\s+[A-Za-z0-9._~+/=-]{{8,}}\b", re.IGNORECASE),
    re.compile(rf"\b{_OPENAI_PROJECT_PREFIX}[A-Za-z0-9_-]{{12,}}\b"),
    re.compile(rf"\b{_OPENAI_PREFIX}[A-Za-z0-9_-]{{12,}}\b"),
    re.compile(rf"\b{_GH_PREFIX_PATTERN}[A-Za-z0-9_]{{12,}}\b"),
    re.compile(rf"\b{_AWS_ACCESS_PREFIX}[0-9A-Z]{{12,}}\b"),
    re.compile(
        rf"{_PEM_BOUNDARY_START} [A-Z ]*{_PEM_PRIVATE_MARKER}-----.*?"
        rf"{_PEM_BOUNDARY_END} [A-Z ]*{_PEM_PRIVATE_MARKER}-----",
        re.DOTALL,
    ),
    re.compile(rf"{_PEM_BOUNDARY_START} [A-Z ]*{_PEM_PRIVATE_MARKER}-----"),
    re.compile(
        rf"\b[A-Za-z0-9_]*(?:{_SENSITIVE_NAME_PATTERN})"
        r'\s*[:=]\s*[\'"]?(?![$<{]|\[redacted[^\]]*\])[^\'"\s]{12,}',
        re.IGNORECASE,
    ),
)
_USERINFO_PATTERN = re.compile(r"(https?://)[^/@\s]+@")
JsonScalar = str | int | float | bool | None


class McpPublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class McpToolError(McpPublicModel):
    status_code: int | None = None
    code: str
    message: str
    safe_message: str
    retryable: bool
    unknown_commit_state: bool = False


class McpDiagnostics(McpPublicModel):
    schema_version: Literal["mcp.infinity_context.v1"] = "mcp.infinity_context.v1"
    trace_id: str
    scope: dict[str, Any] | None = None
    policy: dict[str, Any] = Field(default_factory=dict)
    side_effects: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    degraded: bool = False
    backend: dict[str, Any] = Field(default_factory=dict)


class McpDataModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class MemoryScopeData(McpDataModel):
    space_slug: str | None = None
    memory_scope_external_ref: str | None = None
    memory_scope_external_refs: list[str] = Field(default_factory=list)
    thread_external_ref: str | None = None


class MemoryReadinessData(McpDataModel):
    api_reachable: bool | None = None
    read_ready: bool | None = None
    write_ready: bool | None = None
    delete_ready: bool | None = None
    projection_ready: bool | None = None
    degraded: bool | None = None
    degraded_reasons: list[str] = Field(default_factory=list)
    checked_endpoints: list[str] = Field(default_factory=list)


class MemoryHealthData(McpDataModel):
    status: str | None = None
    ok: bool | None = None


class MemoryCapabilityData(McpDataModel):
    adapter_name: str | None = None
    capability: str | None = None
    enabled: bool | None = None
    healthy: bool | None = None
    status: str | None = None
    degraded_reason: str | None = None


class MemoryCapabilitiesData(McpDataModel):
    policy_mode: str | None = None
    capabilities: list[MemoryCapabilityData] = Field(default_factory=list)


class MemorySourceRefData(McpDataModel):
    source_type: str | None = None
    source_id: str | None = None
    chunk_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote_preview: str | None = None


class MemoryRecordData(McpDataModel):
    id: str | None = None
    item_id: str | None = None
    item_type: str | None = None
    fact_id: str | None = None
    capture_id: str | None = None
    suggestion_id: str | None = None
    document_id: str | None = None
    version: int | None = None
    status: str | None = None
    text: str | None = None
    candidate_text: str | None = None
    text_preview: str | None = None
    kind: str | None = None
    operation: str | None = None
    consolidation_status: str | None = None
    source_agent: str | None = None
    source_kind: str | None = None
    event_type: str | None = None
    actor_role: str | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)
    ttl_policy: str | None = None
    expires_at: str | None = None
    classification: str | None = None
    confidence: str | None = None
    trust_level: str | None = None
    safe_reason: str | None = None
    reason: str | None = None
    source_refs: list[MemorySourceRefData] = Field(default_factory=list)
    resource_uri: str | None = None
    indexing_status: str | None = None
    relation_reasons: list[str] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    deleted_at: str | None = None
    score: float | None = None


class MemorySearchItemData(MemoryRecordData):
    item_type: Literal["fact", "chunk", "suggestion", "document", "unknown"] | None = None


class MemoryStatusData(McpDataModel):
    api_url: str | None = None
    auth_configured: bool | None = None
    default_scope: MemoryScopeData | None = None
    health: MemoryHealthData | None = None
    capabilities: MemoryCapabilitiesData | None = None
    capability_diagnostics: list[MemoryCapabilityData] = Field(default_factory=list)
    readiness: MemoryReadinessData | None = None
    writes_enabled: bool | None = None
    deletes_enabled: bool | None = None
    ingest_enabled: bool | None = None
    write_mode: str | None = None
    delete_mode: str | None = None
    ingest_mode: str | None = None
    usage_guide: str | None = None


class MemorySearchDiagnosticsData(McpDataModel):
    evidence_only: bool | None = None
    consistency_mode: str | None = None
    retrieval_disabled: bool | None = None
    scope_not_found: bool | None = None
    facts_considered: int | None = None
    keyword_chunks_considered: int | None = None
    vector_status: str | None = None
    vector_degraded_reason: str | None = None
    vector_candidate_count: int | None = None
    vector_hydrated_count: int | None = None
    graph_status: str | None = None
    graph_degraded_reason: str | None = None
    graph_candidate_count: int | None = None
    graph_hydrated_count: int | None = None
    rag_status: str | None = None
    rag_degraded_reason: str | None = None
    stale_vector_drop_count: int | None = None
    stale_graph_drop_count: int | None = None
    stale_rag_drop_count: int | None = None
    context_items_used: int | None = None
    pending_suggestions_considered: int | None = None
    superseded_facts_considered: int | None = None
    dropped_by_char_cap: int | None = None
    truncated: bool | None = None


class MemorySearchData(McpDataModel):
    rendered_text: str | None = None
    rendered_text_truncated: bool | None = None
    rendered_text_original_chars: int | None = None
    diagnostics: MemorySearchDiagnosticsData | None = None
    items: list[MemorySearchItemData] = Field(default_factory=list)
    facts: list[MemorySearchItemData] = Field(default_factory=list)
    chunks: list[MemorySearchItemData] = Field(default_factory=list)
    resource_uris: list[str] = Field(default_factory=list)
    requested_memory_scope_external_refs: list[str] = Field(default_factory=list)
    requested_token_budget: int | None = None
    effective_token_budget: int | None = None
    budget_clamped: bool | None = None
    requested_max_facts: int | None = None
    effective_max_facts: int | None = None
    requested_max_chunks: int | None = None
    effective_max_chunks: int | None = None


class MemoryDigestSectionData(McpDataModel):
    title: str | None = None
    items: list[MemorySearchItemData] = Field(default_factory=list)
    truncated: bool | None = None


class MemoryDigestData(McpDataModel):
    digest_id: str | None = None
    topic: str | None = None
    rendered_markdown: str | None = None
    rendered_markdown_truncated: bool | None = None
    rendered_markdown_original_chars: int | None = None
    diagnostics: MemorySearchDiagnosticsData | None = None
    sections: list[MemoryDigestSectionData] = Field(default_factory=list)
    source_refs: list[MemorySourceRefData] = Field(default_factory=list)
    token_estimate: int | None = None
    requested_memory_scope_external_refs: list[str] = Field(default_factory=list)
    requested_token_budget: int | None = None
    effective_token_budget: int | None = None
    budget_clamped: bool | None = None
    requested_max_facts: int | None = None
    effective_max_facts: int | None = None
    requested_max_chunks: int | None = None
    effective_max_chunks: int | None = None
    requested_max_suggestions: int | None = None
    effective_max_suggestions: int | None = None


class MemoryInsightActionItemData(McpDataModel):
    id: str | None = None
    severity: Literal["critical", "warning", "info"] | str | None = None
    action: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    memory_scope_id: str | None = None
    reason: str | None = None
    preview: str | None = None
    metadata: dict[str, JsonScalar | list[JsonScalar]] = Field(default_factory=dict)


class MemoryActivityItemData(McpDataModel):
    id: str | None = None
    occurred_at: str | None = None
    event_type: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    memory_scope_id: str | None = None
    thread_id: str | None = None
    status: str | None = None
    preview: str | None = None
    metadata: dict[str, JsonScalar | list[JsonScalar]] = Field(default_factory=dict)


class MemoryConsolidationPlanItemData(McpDataModel):
    id: str | None = None
    plan_type: str | None = None
    memory_scope_id: str | None = None
    confidence: Literal["low", "medium", "high"] | str | None = None
    canonical_candidate_id: str | None = None
    candidate_fact_ids: list[str] = Field(default_factory=list)
    recommended_steps: list[str] = Field(default_factory=list)
    reason: str | None = None
    preview: str | None = None
    metadata: dict[str, JsonScalar | list[JsonScalar]] = Field(default_factory=dict)


class MemoryInsightCountData(McpDataModel):
    value: str | None = None
    count: int | None = None


class InsightFactsMetricsData(McpDataModel):
    total_sampled: int | None = None
    active: int | None = None
    expired_active: int | None = None
    uncategorized_active: int | None = None
    untagged_active: int | None = None
    by_status: dict[str, int] = Field(default_factory=dict)


class InsightDocumentMetricsData(McpDataModel):
    active: int | None = None
    chunks_sampled: int | None = None
    without_chunks: int | None = None


class InsightEpisodeMetricsData(McpDataModel):
    active: int | None = None
    chunks_sampled: int | None = None
    without_chunks: int | None = None
    by_status: dict[str, int] = Field(default_factory=dict)


class InsightSuggestionMetricsData(McpDataModel):
    total_sampled: int | None = None
    pending: int | None = None
    by_status: dict[str, int] = Field(default_factory=dict)
    by_operation: dict[str, int] = Field(default_factory=dict)


class InsightCaptureMetricsData(McpDataModel):
    attention_needed: int | None = None
    by_consolidation_status: dict[str, int] = Field(default_factory=dict)


class MemoryInsightsMetricsData(McpDataModel):
    memory_scopes: int | None = None
    facts: InsightFactsMetricsData = Field(default_factory=InsightFactsMetricsData)
    documents: InsightDocumentMetricsData = Field(default_factory=InsightDocumentMetricsData)
    episodes: InsightEpisodeMetricsData = Field(default_factory=InsightEpisodeMetricsData)
    chunks: dict[str, int] = Field(default_factory=dict)
    suggestions: InsightSuggestionMetricsData = Field(default_factory=InsightSuggestionMetricsData)
    captures: InsightCaptureMetricsData = Field(default_factory=InsightCaptureMetricsData)


class MemoryInsightsTaxonomyData(McpDataModel):
    top_categories: list[MemoryInsightCountData] = Field(default_factory=list)
    top_tags: list[MemoryInsightCountData] = Field(default_factory=list)
    ttl_policies: list[MemoryInsightCountData] = Field(default_factory=list)


class InsightsDiagnosticsData(McpDataModel):
    evidence_only: bool | None = None
    read_only: bool | None = None
    sample_limited: bool | None = None
    retrieval_disabled: bool | None = None
    scope_not_found: bool | None = None
    policy_mode: str | None = None
    max_facts_per_memory_scope: int | None = None
    max_documents_per_memory_scope: int | None = None
    max_episodes_per_memory_scope: int | None = None
    max_suggestions_per_memory_scope: int | None = None
    max_captures_per_memory_scope: int | None = None
    max_activity: int | None = None
    memory_scopes_sampled: int | None = None


class MemoryInsightsData(McpDataModel):
    insights_id: str | None = None
    generated_at: str | None = None
    scope: dict[str, JsonScalar | list[str]] = Field(default_factory=dict)
    health_score: float | None = None
    metrics: MemoryInsightsMetricsData = Field(default_factory=MemoryInsightsMetricsData)
    taxonomy: MemoryInsightsTaxonomyData = Field(default_factory=MemoryInsightsTaxonomyData)
    action_items: list[MemoryInsightActionItemData] = Field(default_factory=list)
    recent_activity: list[MemoryActivityItemData] = Field(default_factory=list)
    consolidation_plan: list[MemoryConsolidationPlanItemData] = Field(default_factory=list)
    diagnostics: InsightsDiagnosticsData = Field(default_factory=InsightsDiagnosticsData)
    requested_memory_scope_external_refs: list[str] = Field(default_factory=list)
    requested_max_facts: int | None = None
    effective_max_facts: int | None = None
    requested_max_documents: int | None = None
    effective_max_documents: int | None = None
    requested_max_episodes: int | None = None
    effective_max_episodes: int | None = None
    requested_max_suggestions: int | None = None
    effective_max_suggestions: int | None = None
    requested_max_captures: int | None = None
    effective_max_captures: int | None = None


class MemoryGraphNodeData(McpDataModel):
    id: str
    type: str
    label: str
    data: dict[str, JsonScalar] = Field(default_factory=dict)


class MemoryGraphEdgeData(McpDataModel):
    id: str
    type: str
    source: str
    target: str
    label: str
    data: dict[str, JsonScalar] = Field(default_factory=dict)


class MemoryGraphExportData(McpDataModel):
    schema_version: str | None = None
    scope: dict[str, JsonScalar] = Field(default_factory=dict)
    nodes: list[MemoryGraphNodeData] = Field(default_factory=list)
    edges: list[MemoryGraphEdgeData] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)
    truncated: bool | None = None
    warnings: list[str] = Field(default_factory=list)


class MemoryScopeSnapshotDocumentData(McpDataModel):
    id: str | None = None
    thread_id: str | None = None
    title: str | None = None
    source_type: str | None = None
    source_external_id: str | None = None
    content_hash: str | None = None
    classification: str | None = None
    status: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MemoryScopeSnapshotChunkData(McpDataModel):
    id: str | None = None
    thread_id: str | None = None
    document_id: str | None = None
    episode_id: str | None = None
    source_type: str | None = None
    source_external_id: str | None = None
    source_hash: str | None = None
    kind: str | None = None
    text: str | None = None
    normalized_text: str | None = None
    status: str | None = None
    sequence: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    token_estimate: int | None = None
    classification: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    metadata_json: dict[str, JsonScalar] = Field(default_factory=dict)


class MemoryScopeSnapshotSourceRefData(MemorySourceRefData):
    fact_id: str | None = None
    fact_version: int | None = None


class MemoryScopeSnapshotData(McpDataModel):
    schema_version: int | None = None
    space: dict[str, JsonScalar] = Field(default_factory=dict)
    memory_scope: dict[str, JsonScalar] = Field(default_factory=dict)
    facts: list[MemoryRecordData] = Field(default_factory=list)
    documents: list[MemoryScopeSnapshotDocumentData] = Field(default_factory=list)
    chunks: list[MemoryScopeSnapshotChunkData] = Field(default_factory=list)
    relations: list[dict[str, JsonScalar]] = Field(default_factory=list)
    source_refs: list[MemoryScopeSnapshotSourceRefData] = Field(default_factory=list)
    exported_at: str | None = None
    redacted: bool | None = None


class MemoryScopeSnapshotManifestCountsData(McpDataModel):
    facts: int | None = None
    documents: int | None = None
    chunks: int | None = None
    relations: int | None = None
    source_refs: int | None = None


class MemoryScopeSnapshotManifestData(McpDataModel):
    schema_version: str | None = None
    created_at: str | None = None
    snapshot_file: str | None = None
    snapshot_sha256: str | None = None
    snapshot_bytes: int | None = None
    space_slug: str | None = None
    memory_scope_external_ref: str | None = None
    redacted: bool | None = None
    snapshot_schema_version: int | str | None = None
    counts: MemoryScopeSnapshotManifestCountsData = Field(
        default_factory=MemoryScopeSnapshotManifestCountsData
    )


class MemoryScopeSnapshotImportConflictsData(McpDataModel):
    facts: list[str] = Field(default_factory=list)
    documents: list[str] = Field(default_factory=list)
    chunks: list[str] = Field(default_factory=list)
    relations: list[str] = Field(default_factory=list)
    unknown: list[str] = Field(default_factory=list)


class MemoryScopeSnapshotImportSupersedeData(McpDataModel):
    facts: int | None = None
    fact_ids: list[str] = Field(default_factory=list)


class MemoryScopeSnapshotImportPreviewData(McpDataModel):
    snapshot_counts: MemoryScopeSnapshotManifestCountsData = Field(
        default_factory=MemoryScopeSnapshotManifestCountsData
    )
    conflict_count: int | None = None
    conflicts: MemoryScopeSnapshotImportConflictsData = Field(
        default_factory=MemoryScopeSnapshotImportConflictsData
    )
    would_import: MemoryScopeSnapshotManifestCountsData = Field(
        default_factory=MemoryScopeSnapshotManifestCountsData
    )
    would_skip: MemoryScopeSnapshotManifestCountsData = Field(
        default_factory=MemoryScopeSnapshotManifestCountsData
    )
    would_supersede: MemoryScopeSnapshotImportSupersedeData = Field(
        default_factory=MemoryScopeSnapshotImportSupersedeData
    )
    warnings: list[str] = Field(default_factory=list)
    would_create_memory_scope: bool | None = None


class MemoryScopeSnapshotExportData(McpDataModel):
    status: str | None = None
    snapshot: MemoryScopeSnapshotData = Field(default_factory=MemoryScopeSnapshotData)
    counts: dict[str, int] = Field(default_factory=dict)
    redacted: bool | None = None
    manifest: MemoryScopeSnapshotManifestData = Field(
        default_factory=MemoryScopeSnapshotManifestData
    )


class MemoryScopeSnapshotImportData(McpDataModel):
    status: str | None = None
    dry_run: bool | None = None
    merge_strategy: str | None = None
    would_import: dict[str, int] | None = None
    imported: dict[str, int] | None = None
    conflict_count: int | None = None
    conflict_ids: list[str] = Field(default_factory=list)
    created_memory_scope: dict[str, str] | None = None
    preview: MemoryScopeSnapshotImportPreviewData | None = None
    reason: str | None = None


class MemoryFactListData(McpDataModel):
    items: list[MemoryRecordData] = Field(default_factory=list)
    next_cursor: str | None = None
    total_count: int | None = None
    truncated: bool | None = None


class MemoryRelatedFactsData(McpDataModel):
    target: MemoryRecordData | None = None
    items: list[MemoryRecordData] = Field(default_factory=list)
    diagnostics: dict[str, JsonScalar] = Field(default_factory=dict)


class MemoryFactRelationData(McpDataModel):
    id: str | None = None
    space_id: str | None = None
    memory_scope_id: str | None = None
    source_fact_id: str | None = None
    target_fact_id: str | None = None
    relation_type: str | None = None
    reason: str | None = None
    status: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MemoryFactRelationItemData(McpDataModel):
    relation: MemoryFactRelationData | None = None
    related_fact: MemoryRecordData | None = None
    direction: Literal["incoming", "outgoing"] | str | None = None


class MemoryFactRelationsData(McpDataModel):
    target: MemoryRecordData | None = None
    items: list[MemoryFactRelationItemData] = Field(default_factory=list)


class MemoryFactMutationData(MemoryRecordData):
    fact: MemoryRecordData | None = None
    suggestion: MemoryRecordData | None = None
    chunks: int | list[MemoryRecordData] | None = None


class MemorySuggestionListData(McpDataModel):
    items: list[MemoryRecordData] = Field(default_factory=list)
    next_cursor: str | None = None
    total_count: int | None = None
    truncated: bool | None = None


class MemoryCaptureListData(McpDataModel):
    items: list[MemoryRecordData] = Field(default_factory=list)
    next_cursor: str | None = None
    total_count: int | None = None
    truncated: bool | None = None


class MemoryCaptureMutationData(McpDataModel):
    capture: MemoryRecordData | None = None
    created_suggestions: int | None = None
    suggestion_ids: list[str] = Field(default_factory=list)
    auto_applied_facts: int | None = None
    auto_applied_fact_ids: list[str] = Field(default_factory=list)


class MemoryProposalItemData(McpDataModel):
    candidate_index: int
    status: str
    decision_code: str
    text: str | None = None
    fact_id: str | None = None
    suggestion_id: str | None = None
    duplicate_id: str | None = None
    target_fact_id: str | None = None
    resource_uri: str | None = None
    retryable: bool = False
    message: str | None = None


class MemoryProposalBatchData(McpDataModel):
    accepted_suggestions: list[MemoryProposalItemData] = Field(default_factory=list)
    direct_writes: list[MemoryProposalItemData] = Field(default_factory=list)
    duplicates: list[MemoryProposalItemData] = Field(default_factory=list)
    conflicts: list[MemoryProposalItemData] = Field(default_factory=list)
    unsafe_rejected: list[MemoryProposalItemData] = Field(default_factory=list)
    needs_review: list[MemoryProposalItemData] = Field(default_factory=list)


class MemorySuggestBatchItemData(McpDataModel):
    index: int | None = None
    status: str | None = None
    suggestion: MemoryRecordData | None = None
    error_code: str | None = None
    error_message: str | None = None


class MemorySuggestBatchData(McpDataModel):
    created: int | None = None
    failed: int | None = None
    stopped: bool | None = None
    results: list[MemorySuggestBatchItemData] = Field(default_factory=list)


class MemoryReviewSuggestionData(MemoryFactMutationData):
    pass


class MemoryReviewBatchItemData(McpDataModel):
    suggestion_id: str | None = None
    action: str | None = None
    status: str | None = None
    suggestion: MemoryRecordData | None = None
    fact: MemoryRecordData | None = None
    error_code: str | None = None
    error_message: str | None = None


class MemoryReviewSuggestionsBatchData(McpDataModel):
    applied: int | None = None
    failed: int | None = None
    stopped: bool | None = None
    results: list[MemoryReviewBatchItemData] = Field(default_factory=list)


class MemoryDocumentFragmentSummaryData(McpDataModel):
    fragment_count: int | None = None
    node_counts: dict[str, int] = Field(default_factory=dict)
    node_map: dict[str, list[int]] = Field(default_factory=dict)


class MemoryDocumentIngestData(MemoryFactMutationData):
    chunks: int | None = None
    fragment_summary: MemoryDocumentFragmentSummaryData = Field(
        default_factory=MemoryDocumentFragmentSummaryData
    )


class MemoryToolData(
    MemoryStatusData,
    MemorySearchData,
    MemoryDigestData,
    MemoryInsightsData,
    MemoryFactListData,
    MemoryFactMutationData,
    MemorySuggestionListData,
    MemoryCaptureListData,
    MemoryCaptureMutationData,
    MemoryProposalBatchData,
    MemorySuggestBatchData,
    MemoryReviewSuggestionsBatchData,
):
    chunks: int | list[MemorySearchItemData] | list[MemoryRecordData] | None = None
    pass


class McpToolResponse(McpPublicModel):
    ok: bool
    message: str
    data: MemoryToolData | None = None
    error: McpToolError | None = None
    diagnostics: McpDiagnostics

    @model_validator(mode="before")
    @classmethod
    def _wrap_list_data(cls, values: Any) -> Any:
        if isinstance(values, dict) and isinstance(values.get("data"), list):
            return {**values, "data": {"items": values["data"]}}
        return values


class MemoryStatusResponse(McpToolResponse):
    data: MemoryStatusData | None = None


class MemorySearchResponse(McpToolResponse):
    data: MemorySearchData | None = None


class MemoryDigestResponse(McpToolResponse):
    data: MemoryDigestData | None = None


class MemoryInsightsResponse(McpToolResponse):
    data: MemoryInsightsData | None = None


class MemoryFactResponse(McpToolResponse):
    data: MemoryRecordData | None = None


class MemoryFactListResponse(McpToolResponse):
    data: MemoryFactListData | None = None


class MemoryRelatedFactsResponse(McpToolResponse):
    data: MemoryRelatedFactsData | None = None


class MemoryFactRelationResponse(McpToolResponse):
    data: MemoryFactRelationData | None = None


class MemoryFactRelationsResponse(McpToolResponse):
    data: MemoryFactRelationsData | None = None


class MemoryFactMutationResponse(McpToolResponse):
    data: MemoryFactMutationData | None = None


class MemorySuggestionListResponse(McpToolResponse):
    data: MemorySuggestionListData | None = None


class MemoryCaptureListResponse(McpToolResponse):
    data: MemoryCaptureListData | None = None


class MemoryCaptureMutationResponse(McpToolResponse):
    data: MemoryCaptureMutationData | None = None


class MemoryProposalResponse(McpToolResponse):
    data: MemoryProposalBatchData | None = None


class MemorySuggestBatchResponse(McpToolResponse):
    data: MemorySuggestBatchData | None = None


class MemoryReviewSuggestionResponse(McpToolResponse):
    data: MemoryReviewSuggestionData | None = None


class MemoryReviewSuggestionsBatchResponse(McpToolResponse):
    data: MemoryReviewSuggestionsBatchData | None = None


class MemoryDocumentIngestResponse(McpToolResponse):
    data: MemoryDocumentIngestData | None = None


class MemoryGraphExportResponse(McpToolResponse):
    data: MemoryGraphExportData | None = None


class MemoryScopeSnapshotExportResponse(McpToolResponse):
    data: MemoryScopeSnapshotExportData | None = None


class MemoryScopeSnapshotImportResponse(McpToolResponse):
    data: MemoryScopeSnapshotImportData | None = None


class MemoryCandidateOperation(StrEnum):
    REMEMBER = "remember"
    UPDATE = "update"
    FORGET = "forget"
    UNKNOWN = "unknown"


class MemoryUpdateCandidateInput(McpPublicModel):
    text: str = Field(min_length=0, max_length=4000)
    kind: Literal["note", "architecture_decision", "constraint", "user_preference"] = "note"
    operation: MemoryCandidateOperation = MemoryCandidateOperation.UNKNOWN
    target_fact_id: str | None = Field(default=None, min_length=1, max_length=160)
    expected_version: int | None = Field(default=None, ge=1)
    confidence: Literal["low", "medium", "high"] = "medium"
    reason: str = Field(default="", max_length=320)
    evidence_quote: str | None = Field(default=None, max_length=500)
    labels: list[Annotated[str, Field(max_length=80)]] = Field(default_factory=list, max_length=12)


class MemorySuggestBatchItemInput(McpPublicModel):
    candidate_text: str = Field(min_length=1, max_length=4000)
    kind: Literal["note", "architecture_decision", "constraint", "user_preference"] = "note"
    confidence: Literal["low", "medium", "high"] = "medium"
    trust_level: Literal["low", "medium", "high"] = "medium"
    safe_reason: str = Field(default="mcp_agent_suggestion_requires_review", max_length=320)
    quote_preview: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default=None, max_length=80)
    tags: list[Annotated[str, Field(max_length=80)]] = Field(default_factory=list, max_length=10)
    ttl_policy: str | None = Field(default=None, max_length=80)


class MemoryReviewSuggestionBatchItemInput(McpPublicModel):
    suggestion_id: str = Field(min_length=1, max_length=160)
    action: Literal["approve", "reject", "expire"]
    reason: str | None = Field(default=None, max_length=320)
    force: bool = False


@dataclass(frozen=True)
class MemoryScope:
    space_slug: str
    memory_scope_external_ref: str
    thread_external_ref: str | None = None

    def to_read_scope(self) -> MemoryReadScope:
        return MemoryReadScope(
            space_slug=self.space_slug,
            memory_scope_external_refs=(self.memory_scope_external_ref,),
            thread_external_ref=self.thread_external_ref,
        )


@dataclass(frozen=True)
class MemoryReadScope:
    space_slug: str
    memory_scope_external_refs: tuple[str, ...]
    thread_external_ref: str | None = None

    def __post_init__(self) -> None:
        normalized_space = self.space_slug.strip()
        normalized_memory_scopes = tuple(ref.strip() for ref in self.memory_scope_external_refs)
        if not normalized_space:
            raise ValueError("MemoryReadScope.space_slug is required")
        if not normalized_memory_scopes:
            raise ValueError("MemoryReadScope.memory_scope_external_refs is required")
        if any(not ref for ref in normalized_memory_scopes):
            raise ValueError("MemoryReadScope.memory_scope_external_refs cannot contain blanks")
        if len(set(normalized_memory_scopes)) != len(normalized_memory_scopes):
            raise ValueError("MemoryReadScope.memory_scope_external_refs must be unique")
        normalized_thread = self.thread_external_ref.strip() if self.thread_external_ref else None
        if self.thread_external_ref is not None and not normalized_thread:
            raise ValueError("MemoryReadScope.thread_external_ref cannot be blank")
        if normalized_thread is not None and len(normalized_memory_scopes) > 1:
            raise ValueError("MemoryReadScope thread scope supports one memory_scope")
        object.__setattr__(self, "space_slug", normalized_space)
        object.__setattr__(self, "memory_scope_external_refs", normalized_memory_scopes)
        object.__setattr__(self, "thread_external_ref", normalized_thread)


@dataclass(frozen=True)
class SourceRef:
    source_type: str
    source_id: str
    chunk_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote_preview: str | None = None

    def __post_init__(self) -> None:
        source_type = self.source_type.strip()
        source_id = self.source_id.strip()
        chunk_id = self.chunk_id.strip() if self.chunk_id else None
        quote_preview = self.quote_preview.strip() if self.quote_preview else None
        if not source_type:
            raise ValueError("SourceRef.source_type is required")
        if not _SOURCE_TOKEN_PATTERN.fullmatch(source_type):
            raise ValueError("SourceRef.source_type is invalid")
        if not source_id:
            raise ValueError("SourceRef.source_id is required")
        _raise_on_control_chars(source_id, "SourceRef.source_id")
        if chunk_id is not None:
            _raise_on_control_chars(chunk_id, "SourceRef.chunk_id")
        if quote_preview is not None:
            _raise_on_control_chars(quote_preview, "SourceRef.quote_preview")
        if self.char_start is not None and self.char_start < 0:
            raise ValueError("SourceRef.char_start must be non-negative")
        if self.char_end is not None and self.char_end < 0:
            raise ValueError("SourceRef.char_end must be non-negative")
        if (
            self.char_start is not None
            and self.char_end is not None
            and self.char_end < self.char_start
        ):
            raise ValueError("SourceRef.char_end must be >= char_start")
        object.__setattr__(self, "source_type", source_type)
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "chunk_id", chunk_id)
        object.__setattr__(self, "quote_preview", quote_preview)

    def to_payload(self) -> dict[str, Any]:
        return _without_none(
            {
                "source_type": self.source_type,
                "source_id": self.source_id,
                "chunk_id": self.chunk_id,
                "char_start": self.char_start,
                "char_end": self.char_end,
                "quote_preview": self.quote_preview,
            }
        )


@dataclass(frozen=True)
class MemoryGatewayError(RuntimeError):
    status_code: int
    code: str
    message: str
    retryable: bool
    unknown_commit_state: bool = False

    def __str__(self) -> str:
        return self.message


def public_error_code(code: str, *, status_code: int = 0) -> str:
    normalized = code.strip() or "infinity_context_mcp.internal.unexpected"
    if normalized.startswith(
        (
            "infinity_context_mcp.validation.",
            "infinity_context_mcp.policy.",
            "infinity_context_mcp.gateway.",
            "infinity_context_mcp.conflict.",
            "infinity_context_mcp.degraded.",
            "infinity_context_mcp.internal.",
        )
    ):
        return normalized
    if normalized in {"infinity_context_mcp.network_error", "network_error"}:
        return "infinity_context_mcp.gateway.network_error"
    if normalized in {"infinity_context_mcp.invalid_json", "invalid_json"}:
        return "infinity_context_mcp.gateway.invalid_json"
    if normalized in {"infinity_context_mcp.invalid_scope", "invalid_scope"}:
        return "infinity_context_mcp.validation.invalid_scope"
    if normalized in {"infinity_context_mcp.writes_disabled", "writes_disabled"}:
        return "infinity_context_mcp.policy.write_mode_off"
    if normalized in {"infinity_context_mcp.deletes_disabled", "deletes_disabled"}:
        return "infinity_context_mcp.policy.delete_mode_off"
    lowered = normalized.lower()
    if "backpressure" in lowered or status_code == 429:
        return "infinity_context_mcp.degraded.backpressure"
    if "idempotency" in lowered:
        return "infinity_context_mcp.conflict.idempotency_mismatch"
    if "version" in lowered or status_code == 409:
        return "infinity_context_mcp.conflict.version_stale"
    if status_code in {401, 403}:
        return "infinity_context_mcp.gateway.auth_failed"
    if status_code in {400, 422}:
        return "infinity_context_mcp.validation.backend_rejected"
    if status_code >= 500:
        return "infinity_context_mcp.gateway.backend_error"
    return "infinity_context_mcp.internal.unexpected"


def safe_message(value: str) -> str:
    redacted = redact_sensitive_text(value)
    redacted = redacted.replace("\x00", "")
    if len(redacted) > 500:
        redacted = redacted[:500] + "...[truncated]"
    return redacted


def redact_sensitive_text(value: str) -> str:
    redacted = _USERINFO_PATTERN.sub(r"\1[redacted]@", value)
    for pattern in _SENSITIVE_VALUE_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return redacted


def contains_sensitive_value(value: str | None) -> bool:
    if not value:
        return False
    return redact_sensitive_text(value) != value


def has_control_characters(value: str | None) -> bool:
    if not value:
        return False
    return (
        _CONTROL_PATTERN.search(value) is not None
        or _BIDI_CONTROL_PATTERN.search(value) is not None
    )


def has_zero_width_characters(value: str | None) -> bool:
    if not value:
        return False
    return _ZERO_WIDTH_PATTERN.search(value) is not None


def _raise_on_control_chars(value: str, field_name: str) -> None:
    if has_control_characters(value) or has_zero_width_characters(value):
        raise ValueError(f"{field_name} contains control characters")


def _without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}
