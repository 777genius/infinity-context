"""Dto Assets DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from infinity_context_core.domain.assets import (
    MemoryAsset,
    MemoryContextLink,
    MemoryContextLinkSuggestion,
)
from infinity_context_core.domain.capture import CanonicalCapture
from infinity_context_core.domain.entities import (
    MemoryAnchor,
    MemoryChunk,
    MemoryDocument,
    MemoryEpisode,
    MemoryFact,
    MemoryScope,
    MemoryScopeId,
    MemoryThread,
    SpaceId,
    ThreadId,
)
from infinity_context_core.domain.extraction import AssetExtractionJob, ExtractionArtifact
from infinity_context_core.domain.usage import ProductPlan, UsageQuotaSnapshot
from infinity_context_core.ports.capabilities import ConsistencyMode as ConsistencyMode


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
class DeduplicationInfo:
    duplicate: bool
    status: str
    reason_code: str
    scope: str = "none"
    match_type: str | None = None
    reason_codes: tuple[str, ...] = ()
    recommended_action: str | None = None
    source_label: str | None = None
    target_label: str | None = None
    duplicate_of_asset_id: str | None = None
    duplicate_of_job_id: str | None = None
    suggestion_id: str | None = None
    suggestion_status: str | None = None
    storage_key_reused: bool | None = None
    blob_written: bool | None = None
    temporary_blob_cleaned_up: bool | None = None
    artifact_count: int | None = None

@dataclass(frozen=True)
class AssetResult:
    asset: MemoryAsset
    duplicate: bool = False
    deduplication: DeduplicationInfo | None = None

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
    deduplication: DeduplicationInfo | None = None

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
    visual_summary: dict[str, object]
    quick_actions: tuple[dict[str, object], ...]
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
