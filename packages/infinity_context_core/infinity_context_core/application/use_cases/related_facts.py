"""Read-side related fact use case."""

from __future__ import annotations

from infinity_context_core.application.dto import RelatedFactsQuery, RelatedFactsResult
from infinity_context_core.application.related_facts import rank_related_facts
from infinity_context_core.domain.errors import MemoryNotFoundError, MemoryValidationError
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort


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
                memory_scope_id=str(target.memory_scope_id),
                thread_id=None,
                status="active",
                limit=_candidate_limit(query.limit),
                enforce_code_scope=query.enforce_code_scope,
                repository_id=query.repository_id,
                code_scope_id=query.code_scope_id,
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
