"""Canonical user and space ACL use cases."""

from __future__ import annotations

from memo_stack_core.application.dto import (
    CheckSpaceAccessQuery,
    CreateSpaceMembershipCommand,
    CreateUserCommand,
    ListSpaceMembershipsQuery,
    ListUsersQuery,
    SpaceAccessResult,
    SpaceMembershipResult,
    SpaceMembershipsResult,
    UserResult,
    UsersResult,
)
from memo_stack_core.domain.entities import (
    SpaceMembership,
    SpaceMembershipId,
    SpaceMembershipRole,
    User,
    UserId,
)
from memo_stack_core.domain.errors import MemoryNotFoundError, MemoryValidationError
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.ids import IdGeneratorPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort


class CreateUserUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids

    async def execute(self, command: CreateUserCommand) -> UserResult:
        now = self._clock.now()
        user = User.create(
            user_id=UserId(self._ids.new_id("user")),
            external_ref=command.external_ref,
            display_name=command.display_name,
            email=command.email,
            metadata=command.metadata,
            now=now,
        )
        async with self._uow_factory() as uow:
            saved = await uow.users.create_user(user)
            await uow.commit()
        return UserResult(user=saved, created=saved.id == user.id)


class ListUsersUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: ListUsersQuery) -> UsersResult:
        async with self._uow_factory() as uow:
            users = await uow.users.list_users(status=query.status, limit=query.limit)
        return UsersResult(users=tuple(users))


class CreateSpaceMembershipUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids

    async def execute(self, command: CreateSpaceMembershipCommand) -> SpaceMembershipResult:
        role = _membership_role(command.role)
        now = self._clock.now()
        membership = SpaceMembership.create(
            membership_id=SpaceMembershipId(self._ids.new_id("membership")),
            space_id=command.space_id,
            user_id=UserId(command.user_id),
            role=role,
            now=now,
        )
        async with self._uow_factory() as uow:
            saved = await uow.users.create_space_membership(membership)
            if saved.id != membership.id and saved.role != role:
                saved = await uow.users.save_space_membership(saved.update_role(role=role, now=now))
            await uow.commit()
        return SpaceMembershipResult(membership=saved, created=saved.id == membership.id)


class ListSpaceMembershipsUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: ListSpaceMembershipsQuery) -> SpaceMembershipsResult:
        async with self._uow_factory() as uow:
            memberships = await uow.users.list_space_memberships(
                space_id=str(query.space_id),
                status=query.status,
                limit=query.limit,
            )
        return SpaceMembershipsResult(memberships=tuple(memberships))


class CheckSpaceAccessUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: CheckSpaceAccessQuery) -> SpaceAccessResult:
        required_role = _membership_role(query.required_role)
        async with self._uow_factory() as uow:
            user = await uow.users.get_user(query.user_id)
            if user is None:
                raise MemoryNotFoundError("User not found")
            membership = await uow.users.get_space_membership(
                space_id=str(query.space_id),
                user_id=query.user_id,
                status="active",
            )
        return SpaceAccessResult(
            allowed=membership.allows(required_role) if membership is not None else False,
            membership=membership,
            required_role=required_role.value,
        )


def _membership_role(value: str) -> SpaceMembershipRole:
    try:
        return SpaceMembershipRole(value.strip().lower())
    except ValueError as exc:
        raise MemoryValidationError(f"Unknown space membership role: {value}") from exc
