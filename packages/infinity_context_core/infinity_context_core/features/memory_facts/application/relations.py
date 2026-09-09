"""Bounded generic link/list/unlink; reviewed temporal mutations have separate owners."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from infinity_context_core.features.memory_facts.application.locking import (
    memory_fact_identity_lock_key,
)
from infinity_context_core.features.memory_facts.domain.fact import (
    MemoryFactIdentity,
    MemoryFactScope,
    MemoryFactSnapshot,
)
from infinity_context_core.features.memory_facts.domain.relations import (
    FactRelationSnapshot,
    require_generic_relation_type,
    require_linkable_facts,
)
from infinity_context_core.features.memory_facts.ports.clock import MemoryFactClockPort
from infinity_context_core.features.memory_facts.ports.ids import MemoryFactIdPort
from infinity_context_core.features.memory_facts.ports.unit_of_work import (
    MemoryFactTransactionPort,
    MemoryFactUnitOfWorkFactoryPort,
)


@dataclass(frozen=True, slots=True)
class LinkFactsCommand:
    source_identity: MemoryFactIdentity
    target_identity: MemoryFactIdentity
    relation_type: str
    reason: str
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


@dataclass(frozen=True, slots=True)
class ListFactRelationsQuery:
    identity: MemoryFactIdentity
    status: str | None = "active"
    limit: int = 50
    enforce_code_scope: bool = False
    repository_id: str | None = None
    code_scope_id: str | None = None


@dataclass(frozen=True, slots=True)
class UnlinkFactRelationCommand:
    relation_id: str
    scope: MemoryFactScope


@dataclass(frozen=True, slots=True)
class FactRelationResult:
    relation: FactRelationSnapshot


@dataclass(frozen=True, slots=True)
class FactRelationItem:
    relation: FactRelationSnapshot
    related_fact: MemoryFactSnapshot
    direction: Literal["outgoing", "incoming"]


@dataclass(frozen=True, slots=True)
class FactRelationsResult:
    target: MemoryFactSnapshot
    items: tuple[FactRelationItem, ...]


@dataclass(frozen=True, slots=True)
class LinkFactsHandler:
    uow_factory: MemoryFactUnitOfWorkFactoryPort
    clock: MemoryFactClockPort
    ids: MemoryFactIdPort

    async def execute(self, command: LinkFactsCommand) -> FactRelationResult:
        require_generic_relation_type(command.relation_type)
        async with self.uow_factory() as uow:
            result = await link_facts_in_transaction(
                uow, command, now=self.clock.now(), ids=self.ids
            )
            await uow.commit()
            return result


async def link_facts_in_transaction(
    transaction: MemoryFactTransactionPort,
    command: LinkFactsCommand,
    *,
    now: datetime,
    ids: MemoryFactIdPort,
) -> FactRelationResult:
    """Join a caller-owned transaction without committing or opening another UoW."""
    relation_type = require_generic_relation_type(command.relation_type)
    identities = tuple(
        sorted(
            {command.source_identity, command.target_identity}, key=memory_fact_identity_lock_key
        )
    )
    # Lock the memory-scope key, then endpoints in the stable order used by
    # audited mutations. Validate exact-thread eligibility before replay or writes.
    scopes = sorted(
        {(identity.scope.space_id, identity.scope.memory_scope_id) for identity in identities}
    )
    for space_id, memory_scope_id in scopes:
        await transaction.lock_scope(MemoryFactScope(space_id, memory_scope_id))
    locked = await transaction.facts.get_many_for_update(identities)
    by_identity = {fact.identity: fact for fact in locked}
    try:
        source = by_identity[command.source_identity]
        target = by_identity[command.target_identity]
    except KeyError as exc:
        raise LookupError("Fact not found") from exc
    require_linkable_facts(source, target)
    existing = await transaction.relations.find_active(
        source_fact_id=source.identity.fact_id,
        target_fact_id=target.identity.fact_id,
        relation_type=relation_type,
    )
    if existing is not None:
        existing.require_temporal_replay(
            observed_at=command.observed_at,
            valid_from=command.valid_from,
            valid_to=command.valid_to,
        )
        return FactRelationResult(existing)
    relation = FactRelationSnapshot.create(
        relation_id=ids.new_fact_relation_id(),
        source=source,
        target=target,
        relation_type=relation_type,
        reason=command.reason,
        now=now,
        observed_at=command.observed_at,
        valid_from=command.valid_from,
        valid_to=command.valid_to,
    )
    return FactRelationResult(await transaction.relations.create(relation))


@dataclass(frozen=True, slots=True)
class ListFactRelationsHandler:
    uow_factory: MemoryFactUnitOfWorkFactoryPort

    async def execute(self, query: ListFactRelationsQuery) -> FactRelationsResult:
        if query.limit < 1 or query.limit > 100:
            raise ValueError("Fact relation limit must be between 1 and 100")
        async with self.uow_factory() as uow:
            target = await uow.facts.get(query.identity)
            if target is None:
                raise LookupError("Fact not found")
            relations = await uow.relations.list_for_fact(
                fact_id=query.identity.fact_id,
                scope=query.identity.scope,
                status=query.status,
                limit=query.limit,
                enforce_code_scope=query.enforce_code_scope,
                repository_id=query.repository_id,
                code_scope_id=query.code_scope_id,
            )
            items: list[FactRelationItem] = []
            for relation in relations:
                outgoing = relation.source_fact_id == query.identity.fact_id
                other_id = relation.target_fact_id if outgoing else relation.source_fact_id
                other = await uow.relations.get_related_fact(other_id, scope=query.identity.scope)
                if other is None or other.visibility.status == "deleted":
                    continue
                if other.visibility.classification == "restricted":
                    continue
                items.append(
                    FactRelationItem(relation, other, "outgoing" if outgoing else "incoming")
                )
            return FactRelationsResult(target, tuple(items))


@dataclass(frozen=True, slots=True)
class UnlinkFactRelationHandler:
    uow_factory: MemoryFactUnitOfWorkFactoryPort
    clock: MemoryFactClockPort

    async def execute(self, command: UnlinkFactRelationCommand) -> FactRelationResult:
        async with self.uow_factory() as uow:
            scope = MemoryFactScope(command.scope.space_id, command.scope.memory_scope_id)
            await uow.lock_scope(scope)
            relation = await uow.relations.get(command.relation_id, scope=scope)
            if relation is None:
                raise LookupError("Fact relation not found")
            saved = await uow.relations.save(relation.delete(now=self.clock.now()))
            await uow.commit()
            return FactRelationResult(saved)
