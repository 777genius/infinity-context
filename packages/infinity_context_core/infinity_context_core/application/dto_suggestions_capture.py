"""Dto Suggestions Capture DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from infinity_context_core.domain.capture import CanonicalCapture
from infinity_context_core.domain.entities import (
    MemoryFact,
    MemoryKind,
    MemoryScopeId,
    MemorySuggestion,
    SourceRef,
    SpaceId,
    ThreadId,
)
from infinity_context_core.ports.capabilities import ConsistencyMode as ConsistencyMode


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
class ResolveSuggestionConflictCommand:
    suggestion_id: str
    action: str
    reason: str | None = None
    force: bool = False

@dataclass(frozen=True)
class ResolveDuplicateMergeCommand:
    suggestion_id: str
    action: str
    reason: str | None = None
    force: bool = False

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
