"""Public contract DTOs for the memory_scopes feature."""

from __future__ import annotations

from collections.abc import Mapping
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
class MemoryScopeDescriptorDto:
    """Stable descriptor for a memory scope."""

    identity: ScopeIdentityDto
    name: str
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


__all__ = [
    "FEATURE_ID",
    "CreateMemoryScopeRequestDto",
    "CreateMemoryScopeResultDto",
    "MemoryScopeDescriptorDto",
    "ScopeIdentityDto",
    "TransferMemoryScopeRequestDto",
    "TransferMemoryScopeResultDto",
]
