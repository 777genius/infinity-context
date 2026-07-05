"""Feature-owned memory fact domain model skeleton."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TypeAlias


MemoryFactKind: TypeAlias = str
MemoryFactStatus: TypeAlias = str
MemoryFactConfidence: TypeAlias = str
MemoryFactTrustLevel: TypeAlias = str
MemoryFactClassification: TypeAlias = str


@dataclass(frozen=True, slots=True)
class MemoryFactScope:
    """Canonical scope ownership for a fact without storage concerns."""

    space_id: str
    memory_scope_id: str
    thread_id: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryFactIdentity:
    """Stable fact identity plus the scope that owns it."""

    fact_id: str
    scope: MemoryFactScope


@dataclass(frozen=True, slots=True)
class MemoryFactSourceRef:
    """Pointer to the source evidence that supports a fact."""

    source_type: str
    source_id: str
    chunk_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote_preview: str | None = None
    page_number: int | None = None
    time_start_ms: int | None = None
    time_end_ms: int | None = None
    bbox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True, slots=True)
class MemoryFactEvidenceRef:
    """Named evidence handle that points back to a source reference."""

    source_ref: MemoryFactSourceRef
    evidence_id: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryFactVisibility:
    """Lifecycle fields that determine whether a fact may be shown."""

    status: MemoryFactStatus = "active"
    version: int = 1
    confidence: MemoryFactConfidence = "medium"
    trust_level: MemoryFactTrustLevel = "medium"
    classification: MemoryFactClassification = "internal"
    ttl_policy: str | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class MemoryFactSnapshot:
    """Immutable read model for a canonical memory fact."""

    identity: MemoryFactIdentity
    text: str
    source_refs: tuple[MemoryFactSourceRef, ...]
    visibility: MemoryFactVisibility = field(default_factory=MemoryFactVisibility)
    kind: MemoryFactKind = "note"
    evidence_refs: tuple[MemoryFactEvidenceRef, ...] = ()
    category: str | None = None
    tags: tuple[str, ...] = ()
    created_at: datetime | None = None
    updated_at: datetime | None = None


__all__ = (
    "MemoryFactClassification",
    "MemoryFactConfidence",
    "MemoryFactEvidenceRef",
    "MemoryFactIdentity",
    "MemoryFactKind",
    "MemoryFactScope",
    "MemoryFactSnapshot",
    "MemoryFactSourceRef",
    "MemoryFactStatus",
    "MemoryFactTrustLevel",
    "MemoryFactVisibility",
)
