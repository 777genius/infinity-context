"""Read-side fact use cases."""

from __future__ import annotations

from memo_stack_core.application.dto import (
    FactQueryResult,
    FactsQueryResult,
    FactVersionsQuery,
    GetFactQuery,
    ListFactsQuery,
)
from memo_stack_core.domain.errors import MemoryNotFoundError
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort


class ListFactsUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: ListFactsQuery) -> FactsQueryResult:
        async with self._uow_factory() as uow:
            facts = await uow.facts.list_for_scope(
                space_id=str(query.space_id),
                profile_id=str(query.profile_id),
                thread_id=str(query.thread_id) if query.thread_id else None,
                status=query.status,
                limit=query.limit,
                cursor_updated_at=query.cursor_updated_at,
                cursor_id=query.cursor_id,
            )
        return FactsQueryResult(facts=tuple(facts))


class GetFactUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: GetFactQuery) -> FactQueryResult:
        async with self._uow_factory() as uow:
            fact = await uow.facts.get_by_id(query.fact_id)
        if fact is None:
            raise MemoryNotFoundError("Fact not found")
        return FactQueryResult(fact=fact)


class ListFactVersionsUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: FactVersionsQuery) -> FactsQueryResult:
        async with self._uow_factory() as uow:
            versions = await uow.facts.list_versions(query.fact_id)
        if not versions:
            raise MemoryNotFoundError("Fact not found")
        return FactsQueryResult(facts=tuple(versions))
