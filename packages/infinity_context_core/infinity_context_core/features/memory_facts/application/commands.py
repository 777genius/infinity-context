"""Application command/result contracts for memory fact lifecycle use cases."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.features.memory_facts.domain import (
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
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class RememberFactResult:
    """Result returned after a remember request reaches the application boundary."""

    fact: MemoryFactSnapshot
    outbox_message_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class UpdateFactCommand:
    """Request to replace the current version of a canonical fact."""

    identity: MemoryFactIdentity
    expected_version: int
    text: str
    source_refs: tuple[MemoryFactSourceRef, ...]
    kind: MemoryFactKind = "note"
    evidence_refs: tuple[MemoryFactEvidenceRef, ...] = ()
    category: str | None = None
    tags: tuple[str, ...] = ()
    reason: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class UpdateFactResult:
    """Result returned after an update request reaches the application boundary."""

    fact: MemoryFactSnapshot
    outbox_message_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ForgetFactCommand:
    """Request to tombstone a canonical fact without deleting its history."""

    identity: MemoryFactIdentity
    expected_version: int | None = None
    reason: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class ForgetFactResult:
    """Result returned after a forget request reaches the application boundary."""

    fact: MemoryFactSnapshot
    tombstone_id: str | None = None
    outbox_message_ids: tuple[str, ...] = ()


__all__ = (
    "ForgetFactCommand",
    "ForgetFactResult",
    "RememberFactCommand",
    "RememberFactResult",
    "UpdateFactCommand",
    "UpdateFactResult",
)
