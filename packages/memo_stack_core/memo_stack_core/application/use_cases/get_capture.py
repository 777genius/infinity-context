"""Load one capture through the application boundary."""

from __future__ import annotations

from memo_stack_core.application.dto import GetCaptureQuery
from memo_stack_core.domain.capture import CanonicalCapture
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort


class GetCaptureUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: GetCaptureQuery) -> CanonicalCapture | None:
        async with self._uow_factory() as uow:
            return await uow.captures.get_by_id(query.capture_id)
