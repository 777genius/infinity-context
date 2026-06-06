"""Capture diagnostic listing use case."""

from __future__ import annotations

from memo_stack_core.application.dto import ListCapturesQuery
from memo_stack_core.domain.capture import CanonicalCapture
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort


class ListCapturesUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: ListCapturesQuery) -> tuple[CanonicalCapture, ...]:
        async with self._uow_factory() as uow:
            captures = await uow.captures.list_for_scope(
                space_id=str(query.space_id),
                profile_id=str(query.profile_id),
                status=query.status,
                consolidation_status=query.consolidation_status,
                limit=query.limit,
                cursor_created_at=query.cursor_created_at,
                cursor_id=query.cursor_id,
            )
        return tuple(captures)
