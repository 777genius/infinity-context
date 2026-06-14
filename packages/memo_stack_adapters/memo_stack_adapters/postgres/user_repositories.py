"""Postgres repositories for canonical users and ACL memberships."""

from __future__ import annotations

from memo_stack_core.domain.entities import SpaceMembership, User
from memo_stack_core.domain.errors import MemoryConflictError, MemoryNotFoundError
from memo_stack_core.ports.repositories import UserRepositoryPort
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from memo_stack_adapters.postgres.mappers import (
    apply_space_membership_to_row,
    apply_user_to_row,
    space_membership_row_to_domain,
    space_membership_to_row,
    user_row_to_domain,
    user_to_row,
)
from memo_stack_adapters.postgres.models import (
    MemorySpaceMembershipRow,
    MemorySpaceRow,
    MemoryUserRow,
)


class PostgresUserRepository(UserRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_user(self, user: User) -> User:
        existing = (
            await self._session.execute(
                select(MemoryUserRow).where(MemoryUserRow.external_ref == user.external_ref)
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.status == "deleted":
                apply_user_to_row(user, existing)
                await self._session.flush()
            return user_row_to_domain(existing)
        self._session.add(user_to_row(user))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise MemoryConflictError("User conflicted with existing data") from exc
        return user

    async def get_user(self, user_id: str) -> User | None:
        row = await self._session.get(MemoryUserRow, user_id)
        return user_row_to_domain(row) if row is not None else None

    async def list_users(self, *, status: str | None, limit: int) -> list[User]:
        stmt = select(MemoryUserRow)
        if status is not None:
            stmt = stmt.where(MemoryUserRow.status == status)
        rows = (
            await self._session.execute(
                stmt.order_by(MemoryUserRow.updated_at.desc(), MemoryUserRow.id.desc()).limit(
                    limit
                )
            )
        ).scalars()
        return [user_row_to_domain(row) for row in rows]

    async def create_space_membership(
        self,
        membership: SpaceMembership,
    ) -> SpaceMembership:
        await self._assert_active_user_and_space(
            user_id=str(membership.user_id),
            space_id=str(membership.space_id),
        )
        existing = await self._get_membership_row(
            space_id=str(membership.space_id),
            user_id=str(membership.user_id),
        )
        if existing is not None:
            if existing.status == "deleted":
                apply_space_membership_to_row(membership, existing)
                await self._session.flush()
            return space_membership_row_to_domain(existing)
        self._session.add(space_membership_to_row(membership))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise MemoryConflictError("Space membership conflicted with existing data") from exc
        return membership

    async def get_space_membership(
        self,
        *,
        space_id: str,
        user_id: str,
        status: str | None,
    ) -> SpaceMembership | None:
        row = await self._get_membership_row(space_id=space_id, user_id=user_id)
        if row is None:
            return None
        if status is not None and row.status != status:
            return None
        return space_membership_row_to_domain(row)

    async def list_space_memberships(
        self,
        *,
        space_id: str,
        status: str | None,
        limit: int,
    ) -> list[SpaceMembership]:
        conditions = [MemorySpaceMembershipRow.space_id == space_id]
        if status is not None:
            conditions.append(MemorySpaceMembershipRow.status == status)
        rows = (
            await self._session.execute(
                select(MemorySpaceMembershipRow)
                .where(*conditions)
                .order_by(
                    MemorySpaceMembershipRow.updated_at.desc(),
                    MemorySpaceMembershipRow.id.desc(),
                )
                .limit(limit)
            )
        ).scalars()
        return [space_membership_row_to_domain(row) for row in rows]

    async def save_space_membership(
        self,
        membership: SpaceMembership,
    ) -> SpaceMembership:
        row = await self._session.get(MemorySpaceMembershipRow, str(membership.id))
        if row is None:
            raise MemoryNotFoundError("Space membership not found")
        apply_space_membership_to_row(membership, row)
        await self._session.flush()
        return membership

    async def _get_membership_row(
        self,
        *,
        space_id: str,
        user_id: str,
    ) -> MemorySpaceMembershipRow | None:
        return (
            await self._session.execute(
                select(MemorySpaceMembershipRow)
                .where(
                    MemorySpaceMembershipRow.space_id == space_id,
                    MemorySpaceMembershipRow.user_id == user_id,
                )
                .order_by(MemorySpaceMembershipRow.updated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _assert_active_user_and_space(self, *, user_id: str, space_id: str) -> None:
        user = await self._session.get(MemoryUserRow, user_id)
        if user is None or user.status != "active":
            raise MemoryNotFoundError("User not found")
        space = await self._session.get(MemorySpaceRow, space_id)
        if space is None or space.status != "active":
            raise MemoryNotFoundError("Space not found")
