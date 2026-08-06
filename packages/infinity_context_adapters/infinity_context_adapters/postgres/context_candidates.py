"""SQLAlchemy read adapter for canonical context candidate pointers."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.features.context_building.public import (
    ContextCandidateRequest,
    ContextClockPort,
)
from infinity_context_core.features.memory_facts.public import (
    FactSupersessionRelation,
    MemoryFactScope,
    MemoryFactSelectionPort,
    MemoryFactSelectionQuery,
    MemoryFactSnapshot,
)
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infinity_context_adapters.features.context_building.postgres_candidate_provider import (
    PostgresCandidatePointer,
)
from infinity_context_adapters.features.memory_facts.postgres_fact_store import (
    PostgresMemoryFactStore,
)
from infinity_context_adapters.features.memory_facts.postgres_temporal_decision_store import (
    PostgresFactSupersessionRepository,
)
from infinity_context_adapters.postgres.fact_selection_conditions import (
    memory_fact_code_scope_conditions,
    memory_fact_selection_conditions,
)
from infinity_context_adapters.postgres.models import MemoryFactRow


@dataclass(frozen=True, slots=True)
class PostgresMemoryFactCandidateLookup:
    """Rank eligible fact identities without owning prompt text or truth decisions."""

    sessions: async_sessionmaker[AsyncSession]
    clock: ContextClockPort

    async def find_candidate_pointers(
        self,
        request: ContextCandidateRequest,
    ) -> tuple[PostgresCandidatePointer, ...]:
        query = request.query
        reference_time = query.as_of or self.clock.now()
        temporal_mode = "as_of" if query.as_of is not None else "current"
        conditions = list(
            memory_fact_selection_conditions(
                space_id=query.scope.space_id,
                memory_scope_ids=(query.scope.memory_scope_id,),
                thread_id=query.scope.thread_id,
                repository_id=query.repository_id,
                code_scope_id=query.code_scope_id,
                temporal_mode=temporal_mode,
                reference_time=reference_time,
            )
        )
        terms = request.query_plan.terms if request.query_plan is not None else ()
        matches = tuple(
            func.lower(MemoryFactRow.text).contains(term.casefold(), autoescape=True)
            for term in terms
            if term.strip()
        )
        effective_confirmation = case(
            (
                MemoryFactRow.last_confirmed_at <= reference_time,
                MemoryFactRow.last_confirmed_at,
            ),
            else_=None,
        )
        if matches:
            conditions.append(or_(*matches))
            relevance = sum(case((match, 1), else_=0) for match in matches)
            ordering = (
                relevance.desc(),
                case((effective_confirmation.is_(None), 1), else_=0),
                effective_confirmation.desc(),
                MemoryFactRow.observed_at.desc(),
                MemoryFactRow.id,
            )
        else:
            ordering = (
                case((effective_confirmation.is_(None), 1), else_=0),
                effective_confirmation.desc(),
                MemoryFactRow.observed_at.desc(),
                MemoryFactRow.id,
            )

        async with self.sessions() as session:
            rows = tuple(
                (
                    await session.execute(
                        select(MemoryFactRow.id, MemoryFactRow.version)
                        .where(*conditions)
                        .order_by(*ordering)
                        .offset(request.offset)
                        .limit(request.limit)
                    )
                ).all()
            )
        return tuple(
            PostgresCandidatePointer(
                canonical_id=row.id,
                canonical_version=row.version,
                rank=request.offset + index,
            )
            for index, row in enumerate(rows, start=1)
        )


@dataclass(frozen=True, slots=True)
class PostgresMemoryFactSelection:
    """Short-lived-session adapter for canonical hydration reads."""

    sessions: async_sessionmaker[AsyncSession]

    async def find_eligible(
        self,
        query: MemoryFactSelectionQuery,
    ) -> tuple[MemoryFactSnapshot, ...]:
        async with self.sessions() as session:
            return await PostgresMemoryFactStore(session).find_eligible(query)

    async def find_current_supersessions(
        self,
        query: MemoryFactSelectionQuery,
    ) -> tuple[FactSupersessionRelation, ...]:
        predecessor_ids = tuple(dict.fromkeys(query.fact_ids))
        if not predecessor_ids:
            return ()
        conditions: list[object] = [
            MemoryFactRow.id.in_(predecessor_ids),
            MemoryFactRow.space_id == query.space_id,
            MemoryFactRow.memory_scope_id.in_(query.memory_scope_ids),
            MemoryFactRow.classification.in_(("public", "internal")),
        ]
        if query.thread_id is None:
            conditions.append(MemoryFactRow.thread_id.is_(None))
        else:
            conditions.append(
                or_(MemoryFactRow.thread_id.is_(None), MemoryFactRow.thread_id == query.thread_id)
            )
        conditions.extend(
            memory_fact_code_scope_conditions(
                MemoryFactRow,
                repository_id=query.repository_id,
                code_scope_id=query.code_scope_id,
            )
        )
        async with self.sessions() as session:
            rows = tuple(
                (
                    await session.execute(
                        select(
                            MemoryFactRow.id,
                            MemoryFactRow.space_id,
                            MemoryFactRow.memory_scope_id,
                            MemoryFactRow.thread_id,
                        ).where(*conditions)
                    )
                ).all()
            )
            repository = PostgresFactSupersessionRepository(session)
            relations: list[FactSupersessionRelation] = []
            for row in rows:
                try:
                    relation = await repository.find_active_successor(
                        scope=MemoryFactScope(
                            space_id=row.space_id,
                            memory_scope_id=row.memory_scope_id,
                            thread_id=row.thread_id,
                        ),
                        predecessor_fact_id=row.id,
                    )
                except ValueError:
                    continue
                if relation is not None and relation.effective_at <= query.reference_time:
                    relations.append(relation)
        relations.sort(key=lambda relation: (relation.predecessor_fact_id, relation.relation_id))
        return tuple(relations)


def create_postgres_memory_fact_selection(
    sessions: async_sessionmaker[AsyncSession],
) -> MemoryFactSelectionPort:
    return PostgresMemoryFactSelection(sessions=sessions)


__all__ = (
    "PostgresMemoryFactCandidateLookup",
    "PostgresMemoryFactSelection",
    "create_postgres_memory_fact_selection",
)
