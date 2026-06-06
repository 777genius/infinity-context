"""Space and profile management use cases."""

from __future__ import annotations

from memo_stack_core.application.dto import (
    CreateProfileCommand,
    CreateSpaceCommand,
    ProfileResult,
    SpaceResult,
)
from memo_stack_core.domain.entities import MemoryProfile, MemorySpace, ProfileId, SpaceId
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.ids import IdGeneratorPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort


class CreateSpaceUseCase:
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

    async def execute(self, command: CreateSpaceCommand) -> SpaceResult:
        now = self._clock.now()
        space = MemorySpace.create(
            space_id=SpaceId(self._ids.new_id("space")),
            slug=command.slug,
            name=command.name,
            now=now,
        )
        async with self._uow_factory() as uow:
            saved = await uow.scope.create_space(space)
            await uow.commit()
        return SpaceResult(space=saved, created=saved.id == space.id)


class ListSpacesUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, *, limit: int = 100) -> list[MemorySpace]:
        async with self._uow_factory() as uow:
            return await uow.scope.list_spaces(limit=limit)


class CreateProfileUseCase:
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

    async def execute(self, command: CreateProfileCommand) -> ProfileResult:
        now = self._clock.now()
        profile = MemoryProfile.create(
            profile_id=ProfileId(self._ids.new_id("profile")),
            space_id=command.space_id,
            external_ref=command.external_ref,
            name=command.name,
            now=now,
        )
        async with self._uow_factory() as uow:
            saved = await uow.scope.create_profile(profile)
            await uow.commit()
        return ProfileResult(profile=saved, created=saved.id == profile.id)


class ListProfilesUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, *, space_id: SpaceId, limit: int = 100) -> list[MemoryProfile]:
        async with self._uow_factory() as uow:
            return await uow.scope.list_profiles(space_id=str(space_id), limit=limit)
