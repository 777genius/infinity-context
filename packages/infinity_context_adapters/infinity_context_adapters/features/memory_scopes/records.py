"""Provider-neutral read records for memory_scopes adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar

from infinity_context_core.features.memory_scopes.public import (
    FEATURE_ID,
    MEMORY_SCOPE_STATUS_ACTIVE,
    MemoryScopeIdentity,
    MemoryScopeOwner,
    MemoryScopeSnapshot,
    MemoryScopeStatus,
)


@dataclass(frozen=True, slots=True)
class MemoryScopeRecord:
    """Feature-owned scalar record that hydrates a MemoryScopeSnapshot."""

    feature_id: ClassVar[str] = FEATURE_ID

    space_id: str
    memory_scope_id: str
    name: str
    owner_principal_id: str
    owner_principal_kind: str = "user"
    external_ref: str | None = None
    description: str | None = None
    status: MemoryScopeStatus = MEMORY_SCOPE_STATUS_ACTIVE
    created_at: datetime | None = None
    updated_at: datetime | None = None
    archived_at: datetime | None = None

    @classmethod
    def from_snapshot(cls, scope: MemoryScopeSnapshot) -> MemoryScopeRecord:
        """Flatten the public memory scope snapshot for adapter persistence."""

        return cls(
            space_id=scope.identity.space_id,
            memory_scope_id=scope.identity.memory_scope_id,
            name=scope.name,
            owner_principal_id=scope.owner.principal_id,
            owner_principal_kind=scope.owner.principal_kind,
            external_ref=scope.external_ref,
            description=scope.description,
            status=scope.status,
            created_at=scope.created_at,
            updated_at=scope.updated_at,
            archived_at=scope.archived_at,
        )

    def to_snapshot(self) -> MemoryScopeSnapshot:
        """Hydrate the memory_scopes public snapshot from adapter scalars."""

        return MemoryScopeSnapshot(
            identity=MemoryScopeIdentity(
                space_id=self.space_id,
                memory_scope_id=self.memory_scope_id,
            ),
            name=self.name,
            owner=MemoryScopeOwner(
                principal_id=self.owner_principal_id,
                principal_kind=self.owner_principal_kind,
            ),
            external_ref=self.external_ref,
            description=self.description,
            status=self.status,
            created_at=self.created_at,
            updated_at=self.updated_at,
            archived_at=self.archived_at,
        )


def memory_scope_record_from_snapshot(scope: MemoryScopeSnapshot) -> MemoryScopeRecord:
    """Create a provider-neutral memory scope record from a public snapshot."""

    return MemoryScopeRecord.from_snapshot(scope)


__all__ = (
    "MemoryScopeRecord",
    "memory_scope_record_from_snapshot",
)
