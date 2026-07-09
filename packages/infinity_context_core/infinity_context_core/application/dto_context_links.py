"""Dto Context Links DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field

from infinity_context_core.domain.assets import (
    MemoryContextLink,
    MemoryContextLinkSuggestion,
)
from infinity_context_core.domain.entities import (
    MemoryScopeId,
    SpaceId,
    ThreadId,
)
from infinity_context_core.ports.capabilities import ConsistencyMode as ConsistencyMode


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
