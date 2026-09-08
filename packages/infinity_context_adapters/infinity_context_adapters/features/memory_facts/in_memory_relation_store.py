"""Minimal transaction-local relation adapter for focused feature tests."""

from __future__ import annotations

from collections.abc import Mapping

from infinity_context_core.features.memory_facts.public import (
    FactRelationConflict,
    FactRelationSnapshot,
    FactRelationStatus,
    FactRelationType,
    FactSupersessionRelation,
    MemoryFactScope,
    MemoryFactSnapshot,
)


class InMemoryFactRelationRepository:
    def __init__(
        self,
        relations: dict[str, FactRelationSnapshot],
        facts: Mapping[tuple[str, str, str | None, str], MemoryFactSnapshot],
        supersessions: list[FactSupersessionRelation],
    ) -> None:
        self._relations = relations
        self._facts = facts
        self._supersessions = supersessions

    def _all(self) -> tuple[FactRelationSnapshot, ...]:
        return tuple(self._relations.values()) + tuple(
            FactRelationSnapshot(
                relation_id=item.relation_id,
                space_id=item.scope.space_id,
                memory_scope_id=item.scope.memory_scope_id,
                source_fact_id=item.successor_fact_id,
                target_fact_id=item.predecessor_fact_id,
                relation_type=FactRelationType.SUPERSEDES,
                reason=f"temporal_decision:{item.decision_id}",
                status=FactRelationStatus.ACTIVE,
                observed_at=item.created_at,
                valid_from=item.effective_at,
                valid_to=None,
                created_at=item.created_at,
                updated_at=item.created_at,
            )
            for item in self._supersessions
        )

    async def get(self, relation_id: str, *, scope: MemoryFactScope) -> FactRelationSnapshot | None:
        return next(
            (
                item
                for item in self._all()
                if item.relation_id == relation_id and _in_scope(item, scope)
            ),
            None,
        )

    async def find_active(
        self, *, source_fact_id: str, target_fact_id: str, relation_type: FactRelationType
    ) -> FactRelationSnapshot | None:
        return next(
            (
                item
                for item in self._all()
                if item.source_fact_id == source_fact_id
                and item.target_fact_id == target_fact_id
                and item.relation_type == relation_type
                and item.status == FactRelationStatus.ACTIVE
            ),
            None,
        )

    async def create(self, relation: FactRelationSnapshot) -> FactRelationSnapshot:
        if any(item.relation_id == relation.relation_id for item in self._all()):
            raise FactRelationConflict("Fact relation already exists")
        if (
            await self.find_active(
                source_fact_id=relation.source_fact_id,
                target_fact_id=relation.target_fact_id,
                relation_type=relation.relation_type,
            )
            is not None
        ):
            raise FactRelationConflict("Active fact relation already exists")
        self._relations[relation.relation_id] = relation
        return relation

    async def save(self, relation: FactRelationSnapshot) -> FactRelationSnapshot:
        current = await self.get(
            relation.relation_id, scope=MemoryFactScope(relation.space_id, relation.memory_scope_id)
        )
        if current is None:
            raise LookupError("Fact relation not found")
        saved = current.delete(now=relation.updated_at)
        self._relations[relation.relation_id] = saved
        return saved

    async def get_related_fact(
        self, fact_id: str, *, scope: MemoryFactScope
    ) -> MemoryFactSnapshot | None:
        return next(
            (
                fact
                for fact in self._facts.values()
                if fact.identity.fact_id == fact_id
                and fact.identity.scope.space_id == scope.space_id
                and fact.identity.scope.memory_scope_id == scope.memory_scope_id
            ),
            None,
        )

    async def list_for_fact(
        self,
        *,
        fact_id: str,
        scope: MemoryFactScope,
        status: str | None,
        limit: int,
        enforce_code_scope: bool = False,
        repository_id: str | None = None,
        code_scope_id: str | None = None,
    ) -> tuple[FactRelationSnapshot, ...]:
        candidates = []
        for relation in self._all():
            if not _in_scope(relation, scope):
                continue
            if fact_id not in (relation.source_fact_id, relation.target_fact_id):
                continue
            if status is not None and relation.status != status:
                continue
            if enforce_code_scope:
                other_id = (
                    relation.target_fact_id
                    if relation.source_fact_id == fact_id
                    else relation.source_fact_id
                )
                other = await self.get_related_fact(other_id, scope=scope)
                if other is None or other.visibility.classification == "restricted":
                    continue
                if other.code_scope is not None and not other.code_scope.is_visible_in(
                    repository_id=repository_id, code_scope_id=code_scope_id
                ):
                    continue
            candidates.append(relation)
        return tuple(
            sorted(candidates, key=lambda item: (item.updated_at, item.relation_id), reverse=True)[
                :limit
            ]
        )


def _in_scope(relation: FactRelationSnapshot, scope: MemoryFactScope) -> bool:
    return (relation.space_id, relation.memory_scope_id) == (scope.space_id, scope.memory_scope_id)
