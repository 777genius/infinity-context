"""Authentication and authorization scope ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from memo_stack_core.domain.errors import MemoryValidationError


@dataclass(frozen=True)
class MemoryPrincipal:
    id: str
    type: str
    permissions: tuple[str, ...]
    space_ids: tuple[str, ...]
    profile_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemoryScope:
    space_id: str
    profile_id: str
    thread_id: str | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None

    def __post_init__(self) -> None:
        if not self.space_id.strip():
            raise MemoryValidationError("MemoryScope.space_id is required")
        if not self.profile_id.strip():
            raise MemoryValidationError("MemoryScope.profile_id is required")
        if self.thread_id is not None and not self.thread_id.strip():
            raise MemoryValidationError("MemoryScope.thread_id cannot be blank")
        if self.tenant_id is not None and not self.tenant_id.strip():
            raise MemoryValidationError("MemoryScope.tenant_id cannot be blank")
        if self.workspace_id is not None and not self.workspace_id.strip():
            raise MemoryValidationError("MemoryScope.workspace_id cannot be blank")


@dataclass(frozen=True)
class ReadScope:
    space_id: str
    profile_ids: tuple[str, ...]
    thread_id: str | None = None
    tenant_id: str | None = None
    workspace_id: str | None = None

    def __post_init__(self) -> None:
        if not self.space_id.strip():
            raise MemoryValidationError("ReadScope.space_id is required")
        if not self.profile_ids:
            raise MemoryValidationError("ReadScope.profile_ids is required")
        if any(not profile_id.strip() for profile_id in self.profile_ids):
            raise MemoryValidationError("ReadScope.profile_ids cannot contain blanks")
        if len(set(self.profile_ids)) != len(self.profile_ids):
            raise MemoryValidationError("ReadScope.profile_ids cannot contain duplicates")
        if self.thread_id is not None and not self.thread_id.strip():
            raise MemoryValidationError("ReadScope.thread_id cannot be blank")
        if self.tenant_id is not None and not self.tenant_id.strip():
            raise MemoryValidationError("ReadScope.tenant_id cannot be blank")
        if self.workspace_id is not None and not self.workspace_id.strip():
            raise MemoryValidationError("ReadScope.workspace_id cannot be blank")


class AuthPort(Protocol):
    async def authenticate(self, token: str | None) -> MemoryPrincipal:
        """Authenticate a request token."""
