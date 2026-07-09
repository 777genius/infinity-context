"""Dto Anchors DTOs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from infinity_context_core.domain.entities import (
    MemoryAnchor,
    MemoryScopeId,
    SourceRef,
    SpaceId,
)
from infinity_context_core.ports.capabilities import ConsistencyMode as ConsistencyMode


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
class AnchorRelationItem:
    id: str
    source_anchor: MemoryAnchor
    target_anchor: MemoryAnchor
    relation_type: str
    relation_key: str
    confidence: str
    reason: str
    metadata: dict[str, object]

@dataclass(frozen=True)
class ListAnchorRelationsQuery:
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    status: str | None = "active"
    limit: int = 100
    anchor_limit: int = 500

@dataclass(frozen=True)
class AnchorRelationsResult:
    relations: tuple[AnchorRelationItem, ...]
    diagnostics: dict[str, object]

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
