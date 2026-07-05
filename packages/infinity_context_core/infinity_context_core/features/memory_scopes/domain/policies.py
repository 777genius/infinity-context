"""Policies for canonical memory scopes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from infinity_context_core.features.memory_scopes.domain.errors import (
    MemoryScopeLifecycleError,
    MemoryScopeOwnershipError,
)
from infinity_context_core.features.memory_scopes.domain.scope import (
    MemoryScopeActor,
    MemoryScopeOwner,
    MemoryScopeSnapshot,
)

MEMORY_SCOPE_TRANSFER_CAPABILITY: Final = "memory_scope:transfer"
MEMORY_SCOPE_ADMIN_CAPABILITY: Final = "memory_scope:admin"
MEMORY_SCOPE_LIFECYCLE_CAPABILITY: Final = "memory_scope:lifecycle"


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


@dataclass(frozen=True, slots=True)
class MemoryScopeLifecycleDecision:
    """Decision returned by lifecycle policy checks."""

    allowed: bool
    reason: str | None = None

    @classmethod
    def allow(cls) -> MemoryScopeLifecycleDecision:
        return cls(allowed=True)

    @classmethod
    def deny(cls, reason: str) -> MemoryScopeLifecycleDecision:
        return cls(allowed=False, reason=reason)

    def require_allowed(self) -> None:
        """Raise a feature-owned error when this decision denies an operation."""

        if not self.allowed:
            raise MemoryScopeLifecycleError(
                self.reason or "memory_scope_lifecycle_denied"
            )


@dataclass(frozen=True, slots=True)
class MemoryScopeLifecyclePolicy:
    """Business rules for archiving and restoring a memory scope."""

    def decide_archive(
        self,
        scope: MemoryScopeSnapshot,
        *,
        initiated_by: MemoryScopeActor,
    ) -> MemoryScopeLifecycleDecision:
        """Return whether a scope may be archived."""

        if scope.is_archived():
            return MemoryScopeLifecycleDecision.deny("memory_scope_already_archived")
        if scope.is_deleted():
            return MemoryScopeLifecycleDecision.deny("memory_scope_deleted")
        return self._decide_lifecycle_access(scope, initiated_by=initiated_by)

    def assert_can_archive(
        self,
        scope: MemoryScopeSnapshot,
        *,
        initiated_by: MemoryScopeActor,
    ) -> MemoryScopeLifecycleDecision:
        """Raise if lifecycle policy denies archiving."""

        decision = self.decide_archive(scope, initiated_by=initiated_by)
        decision.require_allowed()
        return decision

    def decide_restore(
        self,
        scope: MemoryScopeSnapshot,
        *,
        initiated_by: MemoryScopeActor,
    ) -> MemoryScopeLifecycleDecision:
        """Return whether an archived scope may be restored."""

        if scope.is_active():
            return MemoryScopeLifecycleDecision.deny("memory_scope_already_active")
        if scope.is_deleted():
            return MemoryScopeLifecycleDecision.deny("memory_scope_deleted")
        return self._decide_lifecycle_access(scope, initiated_by=initiated_by)

    def assert_can_restore(
        self,
        scope: MemoryScopeSnapshot,
        *,
        initiated_by: MemoryScopeActor,
    ) -> MemoryScopeLifecycleDecision:
        """Raise if lifecycle policy denies restoration."""

        decision = self.decide_restore(scope, initiated_by=initiated_by)
        decision.require_allowed()
        return decision

    def _decide_lifecycle_access(
        self,
        scope: MemoryScopeSnapshot,
        *,
        initiated_by: MemoryScopeActor,
    ) -> MemoryScopeLifecycleDecision:
        if initiated_by.same_principal_as(scope.owner):
            return MemoryScopeLifecycleDecision.allow()
        if initiated_by.has_capability(MEMORY_SCOPE_LIFECYCLE_CAPABILITY):
            return MemoryScopeLifecycleDecision.allow()
        if initiated_by.has_capability(MEMORY_SCOPE_ADMIN_CAPABILITY):
            return MemoryScopeLifecycleDecision.allow()
        return MemoryScopeLifecycleDecision.deny(
            "actor_cannot_manage_memory_scope_lifecycle"
        )


__all__ = (
    "MEMORY_SCOPE_ADMIN_CAPABILITY",
    "MEMORY_SCOPE_LIFECYCLE_CAPABILITY",
    "MEMORY_SCOPE_TRANSFER_CAPABILITY",
    "MemoryScopeLifecycleDecision",
    "MemoryScopeLifecyclePolicy",
    "MemoryScopeOwnershipDecision",
    "MemoryScopeOwnershipPolicy",
)
