"""Canonical typed fact relation use cases."""

from __future__ import annotations

from memo_stack_core.application.dto import (
    FactRelationItem,
    FactRelationResult,
    FactRelationsResult,
    LinkFactsCommand,
    ListFactRelationsQuery,
    UnlinkFactRelationCommand,
)
from memo_stack_core.domain.entities import (
    FactRelationType,
    FactStatus,
    MemoryFactId,
    MemoryFactRelation,
    MemoryFactRelationId,
)
from memo_stack_core.domain.errors import (
    MemoryConflictError,
    MemoryNotFoundError,
    MemoryValidationError,
)
from memo_stack_core.ports.clock import ClockPort
from memo_stack_core.ports.ids import IdGeneratorPort
from memo_stack_core.ports.unit_of_work import UnitOfWorkFactoryPort


class LinkFactsUseCase:
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

    async def execute(self, command: LinkFactsCommand) -> FactRelationResult:
        try:
            relation_type = FactRelationType(command.relation_type)
        except ValueError as exc:
            raise MemoryValidationError("Unknown fact relation type") from exc
        async with self._uow_factory() as uow:
            source = await uow.facts.get_by_id(command.source_fact_id)
            target = await uow.facts.get_by_id(command.target_fact_id)
            if source is None or target is None:
                raise MemoryNotFoundError("Fact not found")
            _ensure_linkable(source=source, target=target)
            existing = await uow.fact_relations.find_active(
                source_fact_id=command.source_fact_id,
                target_fact_id=command.target_fact_id,
                relation_type=relation_type.value,
            )
            if existing is not None:
                if (
                    relation_type == FactRelationType.CONTRADICTS
                    and target.status == FactStatus.ACTIVE
                ):
                    await uow.facts.save(target.mark_disputed(now=self._clock.now()))
                    await uow.commit()
                return FactRelationResult(relation=existing)
            now = self._clock.now()
            relation = MemoryFactRelation.create(
                relation_id=MemoryFactRelationId(self._ids.new_id("relation")),
                space_id=source.space_id,
                memory_scope_id=source.memory_scope_id,
                source_fact_id=MemoryFactId(command.source_fact_id),
                target_fact_id=MemoryFactId(command.target_fact_id),
                relation_type=relation_type,
                reason=command.reason,
                now=now,
                observed_at=command.observed_at,
                valid_from=command.valid_from,
                valid_to=command.valid_to,
            )
            saved = await uow.fact_relations.create(relation)
            if relation_type == FactRelationType.CONTRADICTS and target.status == FactStatus.ACTIVE:
                await uow.facts.save(target.mark_disputed(now=now))
            await uow.commit()
            return FactRelationResult(relation=saved)


class ListFactRelationsUseCase:
    def __init__(self, *, uow_factory: UnitOfWorkFactoryPort) -> None:
        self._uow_factory = uow_factory

    async def execute(self, query: ListFactRelationsQuery) -> FactRelationsResult:
        if query.limit < 1 or query.limit > 100:
            raise MemoryValidationError("Fact relation limit must be between 1 and 100")
        async with self._uow_factory() as uow:
            target = await uow.facts.get_by_id(query.fact_id)
            if target is None:
                raise MemoryNotFoundError("Fact not found")
            relations = await uow.fact_relations.list_for_fact(
                fact_id=query.fact_id,
                status=query.status,
                limit=query.limit,
            )
            items: list[FactRelationItem] = []
            for relation in relations:
                other_id = (
                    relation.target_fact_id
                    if str(relation.source_fact_id) == query.fact_id
                    else relation.source_fact_id
                )
                other = await uow.facts.get_by_id(str(other_id))
                if other is None or other.status == FactStatus.DELETED:
                    continue
                if other.classification == "restricted":
                    continue
                items.append(
                    FactRelationItem(
                        relation=relation,
                        related_fact=other,
                        direction="outgoing"
                        if str(relation.source_fact_id) == query.fact_id
                        else "incoming",
                    )
                )
            return FactRelationsResult(target=target, items=tuple(items))


class UnlinkFactRelationUseCase:
    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactoryPort,
        clock: ClockPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    async def execute(self, command: UnlinkFactRelationCommand) -> FactRelationResult:
        async with self._uow_factory() as uow:
            relation = await uow.fact_relations.get_by_id(command.relation_id)
            if relation is None:
                raise MemoryNotFoundError("Fact relation not found")
            deleted = relation.delete(now=self._clock.now())
            saved = await uow.fact_relations.save(deleted)
            await uow.commit()
            return FactRelationResult(relation=saved)


def _ensure_linkable(*, source, target) -> None:
    if source.space_id != target.space_id or source.memory_scope_id != target.memory_scope_id:
        raise MemoryConflictError("Fact relations cannot cross memory_scope boundaries")
    if source.status == FactStatus.DELETED or target.status == FactStatus.DELETED:
        raise MemoryConflictError("Deleted facts cannot be linked")
    if source.classification == "restricted" or target.classification == "restricted":
        raise MemoryConflictError("Restricted facts cannot be linked")
