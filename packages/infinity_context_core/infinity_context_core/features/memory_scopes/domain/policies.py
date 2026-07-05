"""Ownership policies for canonical memory scopes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from infinity_context_core.features.memory_scopes.domain.errors import (
    MemoryScopeOwnershipError,
)
from infinity_context_core.features.memory_scopes.domain.scope import (
    MemoryScopeActor,
    MemoryScopeOwner,
    MemoryScopeSnapshot,
)

MEMORY_SCOPE_TRANSFER_CAPABILITY: Final = "memory_scope:transfer"
MEMORY_SCOPE_ADMIN_CAPABILITY: Final = "memory_scope:admin"


@dataclass(frozen=True, slots=True)
class MemoryScopeOwnershipDecision:
    """Decision returned by ownership policy checks."""

    allowed: bool
    reason: str | None = None

    @classmethod
    def allow(cls) -> MemoryScopeOwnershipDecision:
        return cls(allowed=True)

    @classmethod
    def deny(cls, reason: str) -> MemoryScopeOwnershipDecision:
        return cls(allowed=False, reason=reason)

    def require_allowed(self) -> None:
        """Raise a feature-owned error when this decision denies an operation."""

        if not self.allowed:
            raise MemoryScopeOwnershipError(
                self.reason or "memory_scope_ownership_denied"
            )


@dataclass(frozen=True, slots=True)
class MemoryScopeOwnershipPolicy:
    """Business rules for transferring ownership of a memory scope."""

    def decide_transfer(
        self,
        scope: MemoryScopeSnapshot,
        *,
        initiated_by: MemoryScopeActor,
        new_owner: MemoryScopeOwner,
    ) -> MemoryScopeOwnershipDecision:
        """Return whether a transfer may proceed."""

        if not scope.is_active():
            return MemoryScopeOwnershipDecision.deny("memory_scope_not_active")
        if scope.owner == new_owner:
            return MemoryScopeOwnershipDecision.deny("owner_unchanged")
        if initiated_by.same_principal_as(scope.owner):
            return MemoryScopeOwnershipDecision.allow()
        if initiated_by.has_capability(MEMORY_SCOPE_TRANSFER_CAPABILITY):
            return MemoryScopeOwnershipDecision.allow()
        if initiated_by.has_capability(MEMORY_SCOPE_ADMIN_CAPABILITY):
            return MemoryScopeOwnershipDecision.allow()
        return MemoryScopeOwnershipDecision.deny(
            "actor_cannot_transfer_memory_scope"
        )

    def assert_can_transfer(
        self,
        scope: MemoryScopeSnapshot,
        *,
        initiated_by: MemoryScopeActor,
        new_owner: MemoryScopeOwner,
    ) -> MemoryScopeOwnershipDecision:
        """Raise if transfer policy denies the ownership change."""

        decision = self.decide_transfer(
            scope,
            initiated_by=initiated_by,
            new_owner=new_owner,
        )
        decision.require_allowed()
        return decision


__all__ = (
    "MEMORY_SCOPE_ADMIN_CAPABILITY",
    "MEMORY_SCOPE_TRANSFER_CAPABILITY",
    "MemoryScopeOwnershipDecision",
    "MemoryScopeOwnershipPolicy",
)
