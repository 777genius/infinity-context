"""HTTP request models for the memory_scopes server feature."""

from __future__ import annotations

from typing import Any

from infinity_context_contracts.features.memory_scopes import (
    CreateMemoryScopeRequestDto,
)
from pydantic import BaseModel, ConfigDict, Field


class MemoryScopeOwnerHttpRequest(BaseModel):
    """HTTP shape for a principal that owns a memory scope."""

    model_config = ConfigDict(extra="forbid")

    principal_id: str = Field(min_length=1, max_length=160)
    principal_kind: str = Field(default="user", min_length=1, max_length=80)


class MemoryScopeActorHttpRequest(BaseModel):
    """HTTP shape for the principal initiating a scope operation."""

    model_config = ConfigDict(extra="forbid")

    principal_id: str = Field(min_length=1, max_length=160)
    principal_kind: str = Field(default="user", min_length=1, max_length=80)
    capabilities: list[str] = Field(default_factory=list, max_length=50)


class CreateMemoryScopeHttpRequest(BaseModel):
    """HTTP request accepted by the feature-owned scope creation seam."""

    model_config = ConfigDict(extra="forbid")

    external_ref: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=240)
    owner: MemoryScopeOwnerHttpRequest
    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    policy_mode: str = Field(default="manual_only", min_length=1, max_length=80)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_contract(self) -> CreateMemoryScopeRequestDto:
        return CreateMemoryScopeRequestDto(
            external_ref=self.external_ref,
            name=self.name,
            space_id=self.space_id,
            space_slug=self.space_slug,
            description=self.description,
            policy_mode=self.policy_mode,
            idempotency_key=self.idempotency_key,
            metadata=self.metadata,
        )


class TransferMemoryScopeOwnershipHttpRequest(BaseModel):
    """HTTP request accepted by the feature-owned ownership transfer seam."""

    model_config = ConfigDict(extra="forbid")

    space_id: str = Field(min_length=1, max_length=80)
    new_owner: MemoryScopeOwnerHttpRequest
    initiated_by: MemoryScopeActorHttpRequest
    expected_current_owner: MemoryScopeOwnerHttpRequest | None = None
    reason: str | None = Field(default=None, max_length=1000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryScopeLifecycleHttpRequest(BaseModel):
    """HTTP request accepted by feature-owned archive/restore lifecycle seams."""

    model_config = ConfigDict(extra="forbid")

    space_id: str = Field(min_length=1, max_length=80)
    initiated_by: MemoryScopeActorHttpRequest
    expected_status: str | None = Field(default=None, min_length=1, max_length=80)
    reason: str | None = Field(default=None, max_length=1000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArchiveMemoryScopeHttpRequest(MemoryScopeLifecycleHttpRequest):
    """HTTP request accepted by the feature-owned scope archive seam."""


class RestoreMemoryScopeHttpRequest(MemoryScopeLifecycleHttpRequest):
    """HTTP request accepted by the feature-owned scope restore seam."""


__all__ = (
    "ArchiveMemoryScopeHttpRequest",
    "CreateMemoryScopeHttpRequest",
    "MemoryScopeActorHttpRequest",
    "MemoryScopeLifecycleHttpRequest",
    "MemoryScopeOwnerHttpRequest",
    "RestoreMemoryScopeHttpRequest",
    "TransferMemoryScopeOwnershipHttpRequest",
)
