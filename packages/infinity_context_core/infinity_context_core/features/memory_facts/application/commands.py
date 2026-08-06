"""Application command/result contracts for memory fact lifecycle use cases."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.features.memory_facts.domain import (
    FactCodeScopeReference,
    FactEpistemicContext,
    FactFreshness,
    FactQuality,
    FactRetention,
    FactTemporalExtent,
    MemoryFactEvidenceRef,
    MemoryFactIdentity,
    MemoryFactKind,
    MemoryFactScope,
    MemoryFactSnapshot,
    MemoryFactSourceRef,
)


@dataclass(frozen=True, slots=True)
class RememberFactCommand:
    """Request to create a canonical fact inside one memory scope."""

    scope: MemoryFactScope
    text: str
    source_refs: tuple[MemoryFactSourceRef, ...]
    kind: MemoryFactKind = "note"
    evidence_refs: tuple[MemoryFactEvidenceRef, ...] = ()
    category: str | None = None
    tags: tuple[str, ...] = ()
    quality: FactQuality | None = None
    temporal_extent: FactTemporalExtent | None = None
    freshness: FactFreshness | None = None
    retention: FactRetention | None = None
    epistemic_context: FactEpistemicContext | None = None
    code_scope: FactCodeScopeReference | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class RememberFactResult:
    """Result returned after a remember request reaches the application boundary."""

    fact: MemoryFactSnapshot
    outbox_message_ids: tuple[str, ...] = ()
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class UpdateFactCommand:
    """Request to replace the current version of a canonical fact."""

    identity: MemoryFactIdentity
    expected_version: int
    text: str
    source_refs: tuple[MemoryFactSourceRef, ...]
    kind: MemoryFactKind | None = None
    evidence_refs: tuple[MemoryFactEvidenceRef, ...] | None = None
    category: str | None = None
    tags: tuple[str, ...] | None = None
    retention: FactRetention | None = None
    reason: str | None = None
    idempotency_key: str | None = None
    authorized_code_scope: FactCodeScopeReference | None = None


@dataclass(frozen=True, slots=True)
class UpdateFactResult:
    """Result returned after an update request reaches the application boundary."""

    fact: MemoryFactSnapshot
    outbox_message_ids: tuple[str, ...] = ()
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class ForgetFactCommand:
    """Request to tombstone a canonical fact without deleting its history."""

    identity: MemoryFactIdentity
    expected_version: int | None = None
    reason: str | None = None
    idempotency_key: str | None = None
    authorized_code_scope: FactCodeScopeReference | None = None


@dataclass(frozen=True, slots=True)
class ForgetFactResult:
    """Result returned after a forget request reaches the application boundary."""

    fact: MemoryFactSnapshot
    tombstone_id: str | None = None
    outbox_message_ids: tuple[str, ...] = ()
    replayed: bool = False
    already_deleted: bool = False


__all__ = (
    "ForgetFactCommand",
    "ForgetFactResult",
    "RememberFactCommand",
    "RememberFactResult",
    "UpdateFactCommand",
    "UpdateFactResult",
)
