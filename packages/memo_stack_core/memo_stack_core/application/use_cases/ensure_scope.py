"""Resolve or create canonical memory scope."""

from __future__ import annotations

from memo_stack_core.application.dto import EnsureScopeCommand, ScopeResult
from memo_stack_core.domain.entities import ProfileId, SpaceId, ThreadId
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort


class EnsureScopeUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort, clock: ClockPort) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: EnsureScopeCommand) -> ScopeResult:
        async with self._uow_factory() as uow:
            scope = await uow.scope.ensure_scope(
                space_slug=command.space_slug,
                profile_external_ref=command.profile_external_ref,
                thread_external_ref=command.thread_external_ref,
                now=self._clock.now(),
            )
            await uow.commit()
        return ScopeResult(
            space_id=SpaceId(scope.space_id),
            profile_id=ProfileId(scope.profile_id),
            thread_id=ThreadId(scope.thread_id) if scope.thread_id else None,
        )
