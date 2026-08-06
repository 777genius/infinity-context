"""Immutable authorization context supplied to agent-facing application flows."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AgentAccessPolicy(StrEnum):
    SCOPED = "scoped"
    LOCKED_PROJECT = "locked_project"


class AgentScopeResolutionMethod(StrEnum):
    EXPLICIT = "explicit"
    TRUSTED_BINDING = "trusted_binding"
    SERVER_TOKEN = "server_token"


@dataclass(frozen=True, slots=True)
class AgentScopeResolutionEvidence:
    method: AgentScopeResolutionMethod
    binding_id: str | None = None
    binding_version: int | None = None
    drift_status: str = "stable"

    def __post_init__(self) -> None:
        object.__setattr__(self, "method", AgentScopeResolutionMethod(self.method))
        if self.binding_id is not None:
            _require_opaque("binding_id", self.binding_id)
        if self.binding_version is not None and self.binding_version < 1:
            raise ValueError("binding_version must be positive")
        _require_non_blank("drift_status", self.drift_status)


@dataclass(frozen=True, slots=True)
class AuthorizedAgentRequest:
    actor_id: str
    space_id: str
    memory_scope_ids: tuple[str, ...]
    repository_id: str | None
    code_scope_id: str | None
    permissions: frozenset[str]


@dataclass(frozen=True, slots=True)
class AuthorizedAgentContext:
    """Canonical access boundary; prompts cannot widen it with request parameters."""

    actor_id: str
    space_id: str
    memory_scope_ids: tuple[str, ...]
    permissions: frozenset[str]
    access_policy: AgentAccessPolicy
    resolution: AgentScopeResolutionEvidence
    repository_id: str | None = None
    code_scope_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "access_policy", AgentAccessPolicy(self.access_policy))
        object.__setattr__(self, "permissions", frozenset(self.permissions))
        _require_non_blank("actor_id", self.actor_id)
        _require_non_blank("space_id", self.space_id)
        if not self.memory_scope_ids:
            raise ValueError("Authorized agent requires memory_scope_ids")
        if any(not value.strip() for value in self.memory_scope_ids):
            raise ValueError("Authorized agent memory_scope_ids cannot contain blanks")
        if len(set(self.memory_scope_ids)) != len(self.memory_scope_ids):
            raise ValueError("Authorized agent memory_scope_ids must be unique")
        if not self.permissions or any(not value.strip() for value in self.permissions):
            raise ValueError("Authorized agent requires non-blank permissions")
        if self.repository_id is not None:
            _require_opaque("repository_id", self.repository_id)
        if self.code_scope_id is not None:
            _require_opaque("code_scope_id", self.code_scope_id)
            if self.repository_id is None:
                raise ValueError("code_scope_id requires repository_id")
        if self.access_policy is AgentAccessPolicy.LOCKED_PROJECT and self.repository_id is None:
            raise ValueError("locked_project policy requires repository_id")

    def authorize(
        self,
        *,
        requested_space_id: str,
        requested_memory_scope_ids: tuple[str, ...],
        required_permission: str,
        requested_repository_id: str | None = None,
        requested_code_scope_id: str | None = None,
    ) -> AuthorizedAgentRequest:
        if requested_space_id != self.space_id:
            raise PermissionError("Agent cannot override locked MemorySpace")
        if not requested_memory_scope_ids:
            raise PermissionError("Agent request requires MemoryScope")
        if not set(requested_memory_scope_ids) <= set(self.memory_scope_ids):
            raise PermissionError("Agent cannot access requested MemoryScope")
        if required_permission not in self.permissions:
            raise PermissionError("Agent lacks required permission")
        if requested_repository_id is not None and self.repository_id is None:
            raise PermissionError("Agent is not authorized for a CodeRepository")
        repository_id = requested_repository_id or self.repository_id
        if self.repository_id is not None and repository_id != self.repository_id:
            raise PermissionError("Agent cannot override locked CodeRepository")
        if self.access_policy is AgentAccessPolicy.LOCKED_PROJECT and repository_id is None:
            raise PermissionError("Locked project request requires CodeRepository")
        code_scope_id = requested_code_scope_id or self.code_scope_id
        if (
            self.access_policy is AgentAccessPolicy.LOCKED_PROJECT
            and requested_code_scope_id is not None
            and self.code_scope_id is None
        ):
            raise PermissionError("Project token is not bound to a CodeScope")
        if self.code_scope_id is not None and code_scope_id != self.code_scope_id:
            raise PermissionError("Agent cannot override locked CodeScope")
        if code_scope_id is not None and repository_id is None:
            raise PermissionError("CodeScope requires CodeRepository")
        return AuthorizedAgentRequest(
            actor_id=self.actor_id,
            space_id=self.space_id,
            memory_scope_ids=requested_memory_scope_ids,
            repository_id=repository_id,
            code_scope_id=code_scope_id,
            permissions=self.permissions,
        )


def _require_non_blank(field_name: str, value: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")


def _require_opaque(field_name: str, value: str) -> None:
    _require_non_blank(field_name, value)
    if "/" in value or "\\" in value or "://" in value or "@" in value:
        raise ValueError(f"{field_name} must be an opaque identifier")


__all__ = (
    "AgentAccessPolicy",
    "AgentScopeResolutionEvidence",
    "AgentScopeResolutionMethod",
    "AuthorizedAgentContext",
    "AuthorizedAgentRequest",
)
