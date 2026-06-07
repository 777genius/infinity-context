"""Read-side related fact use case."""

from __future__ import annotations

from memo_stack_core.application.dto import RelatedFactsQuery, RelatedFactsResult
from memo_stack_core.application.related_facts import rank_related_facts
from memo_stack_core.domain.errors import MemoryNotFoundError, MemoryValidationError
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort


class RelatedFactsUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: RelatedFactsQuery) -> RelatedFactsResult:
        if query.limit < 1 or query.limit > 50:
            raise MemoryValidationError("Related facts limit must be between 1 and 50")
        async with self._uow_factory() as uow:
            target = await uow.facts.get_by_id(query.fact_id)
            if target is None:
                raise MemoryNotFoundError("Fact not found")
            candidates = await uow.facts.list_for_scope(
                space_id=str(target.space_id),
                profile_id=str(target.profile_id),
                thread_id=None,
                status="active",
                limit=_candidate_limit(query.limit),
            )
        items = rank_related_facts(
            target=target,
            candidates=tuple(candidates),
            limit=query.limit,
            include_other_threads=query.include_other_threads,
        )
        return RelatedFactsResult(
            target=target,
            items=items,
            diagnostics={
                "candidate_count": len(candidates),
                "returned_count": len(items),
                "include_other_threads": query.include_other_threads,
            },
        )


def _candidate_limit(limit: int) -> int:
    return min(500, max(100, limit * 25))
