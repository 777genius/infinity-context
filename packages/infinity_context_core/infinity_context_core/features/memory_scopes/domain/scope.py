"""Feature-owned memory scope identity and lifecycle model."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final, TypeAlias

from infinity_context_core.features.memory_scopes.domain.errors import (
    MemoryScopeDomainError,
)

MemoryScopeStatus: TypeAlias = str
MemoryScopePrincipalKind: TypeAlias = str
MemoryScopeCapability: TypeAlias = str

MEMORY_SCOPE_STATUS_ACTIVE: Final[MemoryScopeStatus] = "active"
MEMORY_SCOPE_STATUS_ARCHIVED: Final[MemoryScopeStatus] = "archived"
MEMORY_SCOPE_STATUS_DELETED: Final[MemoryScopeStatus] = "deleted"
VALID_MEMORY_SCOPE_STATUSES: Final[tuple[MemoryScopeStatus, ...]] = (
    MEMORY_SCOPE_STATUS_ACTIVE,
    MEMORY_SCOPE_STATUS_ARCHIVED,
    MEMORY_SCOPE_STATUS_DELETED,
)


@dataclass(frozen=True, slots=True)
class MemoryScopeIdentity:
    """Canonical scope identity used by all scope-owned memory operations."""

    space_id: str
    memory_scope_id: str

    def __post_init__(self) -> None:
        _require_non_blank(self.space_id, "space_id")
        _require_non_blank(self.memory_scope_id, "memory_scope_id")


@dataclass(frozen=True, slots=True)
class MemoryScopeOwner:
    """Principal that owns a memory scope."""

    principal_id: str
    principal_kind: MemoryScopePrincipalKind = "user"

    def __post_init__(self) -> None:
        _require_non_blank(self.principal_id, "principal_id")
        _require_non_blank(self.principal_kind, "principal_kind")


@dataclass(frozen=True, slots=True)
class MemoryScopeActor:
    """Principal attempting a memory scope ownership operation."""

    principal_id: str
    principal_kind: MemoryScopePrincipalKind = "user"
    capabilities: tuple[MemoryScopeCapability, ...] = ()

    def __post_init__(self) -> None:
        _require_non_blank(self.principal_id, "principal_id")
        _require_non_blank(self.principal_kind, "principal_kind")
        for capability in self.capabilities:
            _require_non_blank(capability, "capability")

    def same_principal_as(self, owner: MemoryScopeOwner) -> bool:
        """Return whether this actor is the same principal as an owner."""

        return (
            self.principal_id == owner.principal_id
            and self.principal_kind == owner.principal_kind
        )

    def has_capability(self, capability: MemoryScopeCapability) -> bool:
        """Return whether this actor carries a scope-management capability."""

        return capability in self.capabilities


@dataclass(frozen=True, slots=True)
class MemoryScopeSnapshot:
    """Immutable read/write model for one canonical memory scope."""

    identity: MemoryScopeIdentity
    name: str
    owner: MemoryScopeOwner
    external_ref: str | None = None
    description: str | None = None
    status: MemoryScopeStatus = MEMORY_SCOPE_STATUS_ACTIVE
    created_at: datetime | None = None
    updated_at: datetime | None = None
    archived_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.name, "name")
        _require_optional_non_blank(self.external_ref, "external_ref")
        if self.status not in VALID_MEMORY_SCOPE_STATUSES:
            raise MemoryScopeDomainError(
                f"status must be one of {VALID_MEMORY_SCOPE_STATUSES}"
            )

    def is_active(self) -> bool:
        """Return whether this scope may participate in default memory reads/writes."""

        return self.status == MEMORY_SCOPE_STATUS_ACTIVE

    def transfer_ownership(
        self,
        new_owner: MemoryScopeOwner,
        *,
        transferred_at: datetime | None = None,
    ) -> MemoryScopeSnapshot:
        """Return a copy of this scope owned by a new principal."""

        return replace(self, owner=new_owner, updated_at=transferred_at)

    def archive(self, *, archived_at: datetime | None = None) -> MemoryScopeSnapshot:
        """Return a copy archived without hard-deleting canonical memory."""

        return replace(
            self,
            status=MEMORY_SCOPE_STATUS_ARCHIVED,
            updated_at=archived_at,
            archived_at=archived_at,
        )


def _require_non_blank(value: str, field_name: str) -> None:
    if value.strip() == "":
        raise MemoryScopeDomainError(f"{field_name} cannot be blank")


def _require_optional_non_blank(value: str | None, field_name: str) -> None:
    if value is not None:
        _require_non_blank(value, field_name)


__all__ = (
    "MEMORY_SCOPE_STATUS_ACTIVE",
    "MEMORY_SCOPE_STATUS_ARCHIVED",
    "MEMORY_SCOPE_STATUS_DELETED",
    "MemoryScopeActor",
    "MemoryScopeCapability",
    "MemoryScopeIdentity",
    "MemoryScopeOwner",
    "MemoryScopePrincipalKind",
    "MemoryScopeSnapshot",
    "MemoryScopeStatus",
    "VALID_MEMORY_SCOPE_STATUSES",
)
