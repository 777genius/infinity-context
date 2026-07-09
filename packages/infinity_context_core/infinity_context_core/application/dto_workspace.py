"""Dto Workspace DTOs."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.domain.entities import (
    MemoryScope,
    MemoryScopeId,
    MemorySpace,
    SpaceId,
    SpaceMembership,
    User,
)
from infinity_context_core.ports.capabilities import ConsistencyMode as ConsistencyMode


@dataclass(frozen=True)
class CreateSpaceCommand:
    slug: str
    name: str

@dataclass(frozen=True)
class CreateMemoryScopeCommand:
    space_id: SpaceId
    external_ref: str
    name: str

@dataclass(frozen=True)
class UpdateMemoryScopeCommand:
    memory_scope_id: MemoryScopeId
    external_ref: str | None = None
    name: str | None = None

@dataclass(frozen=True)
class DeleteMemoryScopeCommand:
    memory_scope_id: MemoryScopeId

@dataclass(frozen=True)
class SpaceResult:
    space: MemorySpace
    created: bool = True

@dataclass(frozen=True)
class MemoryScopeResult:
    memory_scope: MemoryScope
    created: bool = True

@dataclass(frozen=True)
class CreateUserCommand:
    external_ref: str
    display_name: str
    email: str | None = None
    metadata: dict[str, object] | None = None

@dataclass(frozen=True)
class ListUsersQuery:
    status: str | None = "active"
    limit: int = 100

@dataclass(frozen=True)
class UserResult:
    user: User
    created: bool = True

@dataclass(frozen=True)
class UsersResult:
    users: tuple[User, ...]

@dataclass(frozen=True)
class CreateSpaceMembershipCommand:
    space_id: SpaceId
    user_id: str
    role: str

@dataclass(frozen=True)
class ListSpaceMembershipsQuery:
    space_id: SpaceId
    status: str | None = "active"
    limit: int = 100

@dataclass(frozen=True)
class CheckSpaceAccessQuery:
    space_id: SpaceId
    user_id: str
    required_role: str = "viewer"

@dataclass(frozen=True)
class SpaceMembershipResult:
    membership: SpaceMembership
    created: bool = True

@dataclass(frozen=True)
class SpaceMembershipsResult:
    memberships: tuple[SpaceMembership, ...]

@dataclass(frozen=True)
class SpaceAccessResult:
    allowed: bool
    membership: SpaceMembership | None
    required_role: str
