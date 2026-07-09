"""Public contract DTOs for the memory_scopes feature."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .._json import JsonObject, JsonValue, json_compatible

FEATURE_ID = "memory_scopes"


@dataclass(frozen=True, slots=True)
class ScopeIdentityDto:
    """Stable public identity fields for a memory scope."""

    id: str
    space_id: str
    external_ref: str

    def to_dict(self) -> JsonObject:
        return {
            "id": self.id,
            "space_id": self.space_id,
            "external_ref": self.external_ref,
        }


@dataclass(frozen=True, slots=True)
class MemoryScopeOwnerDto:
    """Stable owner principal shape for memory scope write contracts."""

    principal_id: str
    principal_kind: str = "user"

    def to_dict(self) -> JsonObject:
        return {
            "principal_id": self.principal_id,
            "principal_kind": self.principal_kind,
        }


@dataclass(frozen=True, slots=True)
class MemoryScopeActorDto:
    """Stable actor principal shape for memory scope lifecycle commands."""

    principal_id: str
    principal_kind: str = "user"
    capabilities: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> JsonObject:
        return {
            "principal_id": self.principal_id,
            "principal_kind": self.principal_kind,
            "capabilities": json_compatible(self.capabilities),
        }


@dataclass(frozen=True, slots=True)
class MemoryScopeDescriptorDto:
    """Stable descriptor for a memory scope."""

    identity: ScopeIdentityDto
    name: str
    owner: MemoryScopeOwnerDto | Mapping[str, JsonValue] | None = None
    description: str | None = None
    status: str = "active"
    policy_mode: str = "manual_only"
    created_at: str | None = None
    updated_at: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        return {
            **self.identity.to_dict(),
            "name": self.name,
            "owner": json_compatible(_owner_from_fields(self.owner, self.metadata)),
            "description": self.description,
            "status": self.status,
            "policy_mode": self.policy_mode,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": json_compatible(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class CreateMemoryScopeRequestDto:
    """Stable request shape for creating or ensuring a memory scope."""

    external_ref: str
    name: str
    owner: MemoryScopeOwnerDto | Mapping[str, JsonValue] | None = None
    space_id: str | None = None
    space_slug: str | None = None
    description: str | None = None
    policy_mode: str = "manual_only"
    idempotency_key: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        return {
            "space_id": self.space_id,
            "space_slug": self.space_slug,
            "external_ref": self.external_ref,
            "name": self.name,
            "owner": json_compatible(self.owner),
            "description": self.description,
            "policy_mode": self.policy_mode,
            "idempotency_key": self.idempotency_key,
            "metadata": json_compatible(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class CreateMemoryScopeResultDto:
    """Stable result wrapper for scope creation."""

    scope: MemoryScopeDescriptorDto
    created: bool = True

    def to_dict(self) -> JsonObject:
        return {
            "data": {
                "scope": self.scope.to_dict(),
                "created": self.created,
            }
        }


@dataclass(frozen=True, slots=True)
class TransferMemoryScopeRequestDto:
    """Stable request shape for transferring a scope between spaces."""

    scope_id: str
    target_space_id: str | None = None
    target_space_slug: str | None = None
    new_external_ref: str | None = None
    reason: str | None = None
    idempotency_key: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        return {
            "scope_id": self.scope_id,
            "target_space_id": self.target_space_id,
            "target_space_slug": self.target_space_slug,
            "new_external_ref": self.new_external_ref,
            "reason": self.reason,
            "idempotency_key": self.idempotency_key,
            "metadata": json_compatible(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class TransferMemoryScopeResultDto:
    """Stable result wrapper for scope transfer."""

    scope: MemoryScopeDescriptorDto
    previous_space_id: str
    transferred: bool = True

    def to_dict(self) -> JsonObject:
        return {
            "data": {
                "scope": self.scope.to_dict(),
                "previous_space_id": self.previous_space_id,
                "transferred": self.transferred,
            }
        }


@dataclass(frozen=True, slots=True)
class TransferMemoryScopeOwnershipRequestDto:
    """Stable request shape for transferring scope ownership."""

    space_id: str
    memory_scope_id: str
    new_owner: MemoryScopeOwnerDto | Mapping[str, JsonValue]
    initiated_by: MemoryScopeActorDto | Mapping[str, JsonValue]
    expected_current_owner: MemoryScopeOwnerDto | Mapping[str, JsonValue] | None = None
    reason: str | None = None
    idempotency_key: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        return {
            "space_id": self.space_id,
            "memory_scope_id": self.memory_scope_id,
            "new_owner": json_compatible(self.new_owner),
            "initiated_by": json_compatible(self.initiated_by),
            "expected_current_owner": json_compatible(self.expected_current_owner),
            "reason": self.reason,
            "idempotency_key": self.idempotency_key,
            "metadata": json_compatible(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class TransferMemoryScopeOwnershipResultDto:
    """Stable result wrapper for scope ownership transfer."""

    scope: MemoryScopeDescriptorDto
    previous_owner: MemoryScopeOwnerDto | Mapping[str, JsonValue]
    transferred: bool = True

    def to_dict(self) -> JsonObject:
        return {
            "data": {
                "scope": self.scope.to_dict(),
                "previous_owner": json_compatible(self.previous_owner),
                "transferred": self.transferred,
            }
        }


@dataclass(frozen=True, slots=True)
class ArchiveMemoryScopeRequestDto:
    """Stable request shape for archiving a memory scope."""

    space_id: str
    memory_scope_id: str
    initiated_by: MemoryScopeActorDto | Mapping[str, JsonValue] | None = None
    expected_status: str | None = None
    reason: str | None = None
    idempotency_key: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        return {
            "space_id": self.space_id,
            "memory_scope_id": self.memory_scope_id,
            "initiated_by": json_compatible(self.initiated_by),
            "expected_status": self.expected_status,
            "reason": self.reason,
            "idempotency_key": self.idempotency_key,
            "metadata": json_compatible(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class ArchiveMemoryScopeResultDto:
    """Stable result wrapper for scope archive lifecycle responses."""

    scope: MemoryScopeDescriptorDto
    previous_status: str
    archived: bool = True

    def to_dict(self) -> JsonObject:
        return {
            "data": {
                "scope": self.scope.to_dict(),
                "previous_status": self.previous_status,
                "archived": self.archived,
            }
        }


@dataclass(frozen=True, slots=True)
class RestoreMemoryScopeRequestDto:
    """Stable request shape for restoring an archived memory scope."""

    space_id: str
    memory_scope_id: str
    initiated_by: MemoryScopeActorDto | Mapping[str, JsonValue] | None = None
    expected_status: str | None = None
    reason: str | None = None
    idempotency_key: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        return {
            "space_id": self.space_id,
            "memory_scope_id": self.memory_scope_id,
            "initiated_by": json_compatible(self.initiated_by),
            "expected_status": self.expected_status,
            "reason": self.reason,
            "idempotency_key": self.idempotency_key,
            "metadata": json_compatible(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class RestoreMemoryScopeResultDto:
    """Stable result wrapper for scope restore lifecycle responses."""

    scope: MemoryScopeDescriptorDto
    previous_status: str
    restored: bool = True

    def to_dict(self) -> JsonObject:
        return {
            "data": {
                "scope": self.scope.to_dict(),
                "previous_status": self.previous_status,
                "restored": self.restored,
            }
        }


def _owner_from_fields(
    owner: MemoryScopeOwnerDto | Mapping[str, JsonValue] | None,
    metadata: Mapping[str, JsonValue],
) -> MemoryScopeOwnerDto | Mapping[str, JsonValue] | None:
    if owner is not None:
        return owner
    metadata_owner = metadata.get("owner")
    if isinstance(metadata_owner, Mapping):
        return metadata_owner
    return None


__all__ = [
    "FEATURE_ID",
    "ArchiveMemoryScopeRequestDto",
    "ArchiveMemoryScopeResultDto",
    "CreateMemoryScopeRequestDto",
    "CreateMemoryScopeResultDto",
    "MemoryScopeActorDto",
    "MemoryScopeDescriptorDto",
    "MemoryScopeOwnerDto",
    "RestoreMemoryScopeRequestDto",
    "RestoreMemoryScopeResultDto",
    "ScopeIdentityDto",
    "TransferMemoryScopeOwnershipRequestDto",
    "TransferMemoryScopeOwnershipResultDto",
    "TransferMemoryScopeRequestDto",
    "TransferMemoryScopeResultDto",
]
