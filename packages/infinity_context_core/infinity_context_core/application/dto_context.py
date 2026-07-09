"""Dto Context DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from infinity_context_core.domain.entities import (
    MemoryScopeId,
    SourceRef,
    SpaceId,
    ThreadId,
)
from infinity_context_core.ports.capabilities import ConsistencyMode as ConsistencyMode


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
    max_evidence_items: int = 12
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
