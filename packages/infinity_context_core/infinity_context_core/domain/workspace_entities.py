"""Workspace, user and scope domain entities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime

from infinity_context_core.domain.entity_policies import _optional_str
from infinity_context_core.domain.entity_types import (
    LifecycleStatus,
    MemoryScopeId,
    SpaceId,
    SpaceMembershipId,
    SpaceMembershipRole,
    ThreadId,
    UserId,
    UserStatus,
)
from infinity_context_core.domain.errors import MemoryConflictError, MemoryValidationError


@dataclass(frozen=True)
class MemorySpace:
    id: SpaceId
    slug: str
    name: str
    status: LifecycleStatus
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        space_id: SpaceId,
        slug: str,
        name: str,
        now: datetime,
    ) -> MemorySpace:
        if not slug.strip():
            raise MemoryValidationError("Space slug is required")
        if not name.strip():
            raise MemoryValidationError("Space name is required")
        return cls(
            id=space_id,
            slug=slug.strip(),
            name=name.strip(),
            status=LifecycleStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )

@dataclass(frozen=True)
class User:
    id: UserId
    external_ref: str
    display_name: str
    email: str | None
    status: UserStatus
    metadata: Mapping[str, object]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        user_id: UserId,
        external_ref: str,
        display_name: str,
        now: datetime,
        email: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> User:
        safe_ref = external_ref.strip()
        safe_name = display_name.strip()
        if not safe_ref:
            raise MemoryValidationError("User external_ref is required")
        if not safe_name:
            raise MemoryValidationError("User display_name is required")
        return cls(
            id=user_id,
            external_ref=safe_ref[:200],
            display_name=safe_name[:240],
            email=_optional_str(email),
            status=UserStatus.ACTIVE,
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
        )

    def update_details(
        self,
        *,
        display_name: str | None = None,
        email: str | None = None,
        metadata: Mapping[str, object] | None = None,
        now: datetime,
    ) -> User:
        if self.status == UserStatus.DELETED:
            raise MemoryConflictError("Deleted user cannot be updated")
        next_name = self.display_name if display_name is None else display_name.strip()
        if not next_name:
            raise MemoryValidationError("User display_name is required")
        return replace(
            self,
            display_name=next_name[:240],
            email=self.email if email is None else _optional_str(email),
            metadata={**dict(self.metadata), **dict(metadata or {})},
            updated_at=now,
        )

    def disable(self, *, now: datetime) -> User:
        if self.status == UserStatus.DISABLED:
            return self
        return replace(self, status=UserStatus.DISABLED, updated_at=now)

    def delete(self, *, now: datetime) -> User:
        if self.status == UserStatus.DELETED:
            return self
        return replace(self, status=UserStatus.DELETED, updated_at=now)

@dataclass(frozen=True)
class SpaceMembership:
    id: SpaceMembershipId
    space_id: SpaceId
    user_id: UserId
    role: SpaceMembershipRole
    status: LifecycleStatus
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        membership_id: SpaceMembershipId,
        space_id: SpaceId,
        user_id: UserId,
        role: SpaceMembershipRole,
        now: datetime,
    ) -> SpaceMembership:
        return cls(
            id=membership_id,
            space_id=space_id,
            user_id=user_id,
            role=role,
            status=LifecycleStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )

    def update_role(self, *, role: SpaceMembershipRole, now: datetime) -> SpaceMembership:
        if self.status == LifecycleStatus.DELETED:
            raise MemoryConflictError("Deleted space membership cannot be updated")
        if self.role == role:
            return self
        return replace(self, role=role, updated_at=now)

    def delete(self, *, now: datetime) -> SpaceMembership:
        if self.status == LifecycleStatus.DELETED:
            return self
        return replace(self, status=LifecycleStatus.DELETED, updated_at=now)

    def allows(self, required_role: SpaceMembershipRole) -> bool:
        role_rank = {
            SpaceMembershipRole.VIEWER: 1,
            SpaceMembershipRole.MEMBER: 2,
            SpaceMembershipRole.ADMIN: 3,
            SpaceMembershipRole.OWNER: 4,
        }
        return (
            self.status == LifecycleStatus.ACTIVE
            and role_rank[self.role] >= role_rank[required_role]
        )

@dataclass(frozen=True)
class MemoryScope:
    id: MemoryScopeId
    space_id: SpaceId
    external_ref: str
    name: str
    status: LifecycleStatus
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        memory_scope_id: MemoryScopeId,
        space_id: SpaceId,
        external_ref: str,
        name: str,
        now: datetime,
    ) -> MemoryScope:
        if not external_ref.strip():
            raise MemoryValidationError("MemoryScope external_ref is required")
        if not name.strip():
            raise MemoryValidationError("MemoryScope name is required")
        return cls(
            id=memory_scope_id,
            space_id=space_id,
            external_ref=external_ref.strip(),
            name=name.strip(),
            status=LifecycleStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )

    def update_details(
        self,
        *,
        external_ref: str | None = None,
        name: str | None = None,
        now: datetime,
    ) -> MemoryScope:
        if self.status == LifecycleStatus.DELETED:
            raise MemoryConflictError("Deleted memory_scope cannot be updated")
        next_external_ref = self.external_ref if external_ref is None else external_ref.strip()
        next_name = self.name if name is None else name.strip()
        if not next_external_ref:
            raise MemoryValidationError("MemoryScope external_ref is required")
        if not next_name:
            raise MemoryValidationError("MemoryScope name is required")
        return replace(
            self,
            external_ref=next_external_ref,
            name=next_name,
            updated_at=now,
        )

    def delete(self, *, now: datetime) -> MemoryScope:
        if self.status == LifecycleStatus.DELETED:
            return self
        return replace(self, status=LifecycleStatus.DELETED, updated_at=now)

@dataclass(frozen=True)
class MemoryThread:
    id: ThreadId
    space_id: SpaceId
    memory_scope_id: MemoryScopeId
    external_ref: str
    status: LifecycleStatus
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        thread_id: ThreadId,
        space_id: SpaceId,
        memory_scope_id: MemoryScopeId,
        external_ref: str,
        now: datetime,
    ) -> MemoryThread:
        if not external_ref.strip():
            raise MemoryValidationError("Thread external_ref is required")
        return cls(
            id=thread_id,
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            external_ref=external_ref.strip(),
            status=LifecycleStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
