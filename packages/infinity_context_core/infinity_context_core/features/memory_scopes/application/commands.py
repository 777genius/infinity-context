"""Application command/result contracts for memory scope lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.features.memory_scopes.domain import (
    MemoryScopeActor,
    MemoryScopeIdentity,
    MemoryScopeOwner,
    MemoryScopeSnapshot,
    MemoryScopeStatus,
)


@dataclass(frozen=True, slots=True)
class CreateMemoryScopeCommand:
    """Request to create a canonical memory scope inside one space."""

    space_id: str
    name: str
    owner: MemoryScopeOwner
    external_ref: str | None = None
    description: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class CreateMemoryScopeResult:
    """Result returned after a memory scope is created."""

    scope: MemoryScopeSnapshot


@dataclass(frozen=True, slots=True)
class TransferMemoryScopeOwnershipCommand:
    """Request to transfer a memory scope to a new owner."""

    identity: MemoryScopeIdentity
    new_owner: MemoryScopeOwner
    initiated_by: MemoryScopeActor
    expected_current_owner: MemoryScopeOwner | None = None
    reason: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class TransferMemoryScopeOwnershipResult:
    """Result returned after ownership transfer reaches the application boundary."""

    scope: MemoryScopeSnapshot
    previous_owner: MemoryScopeOwner


@dataclass(frozen=True, slots=True)
class ArchiveMemoryScopeCommand:
    """Request to archive a scope without hard-deleting canonical memory."""

    identity: MemoryScopeIdentity
    initiated_by: MemoryScopeActor
    expected_status: MemoryScopeStatus | None = None
    reason: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class ArchiveMemoryScopeResult:
    """Result returned after a memory scope is archived."""

    scope: MemoryScopeSnapshot
    previous_status: MemoryScopeStatus


@dataclass(frozen=True, slots=True)
class RestoreMemoryScopeCommand:
    """Request to restore an archived memory scope to active use."""

    identity: MemoryScopeIdentity
    initiated_by: MemoryScopeActor
    expected_status: MemoryScopeStatus | None = None
    reason: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class RestoreMemoryScopeResult:
    """Result returned after a memory scope is restored."""

    scope: MemoryScopeSnapshot
    previous_status: MemoryScopeStatus


__all__ = (
    "ArchiveMemoryScopeCommand",
    "ArchiveMemoryScopeResult",
    "CreateMemoryScopeCommand",
    "CreateMemoryScopeResult",
    "RestoreMemoryScopeCommand",
    "RestoreMemoryScopeResult",
    "TransferMemoryScopeOwnershipCommand",
    "TransferMemoryScopeOwnershipResult",
)
