"""Postgres adapters for append-only fact decisions and supersession edges."""

from __future__ import annotations

from datetime import UTC, datetime

from infinity_context_core.features.memory_facts.public import (
    FactSupersessionRelation,
    FactTemporalDecision,
    FactTemporalDecisionType,
    MemoryFactScope,
)
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.features.memory_facts.postgres_fact_mapping import (
    memory_fact_evidence_refs_from_json,
    memory_fact_evidence_refs_to_json,
)
from infinity_context_adapters.postgres.models import (
    MemoryFactRelationRow,
    MemoryFactTemporalDecisionRow,
)


class PostgresFactTemporalDecisionRepository:
    """Append-only decision repository inside the fact unit of work."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, decision: FactTemporalDecision) -> FactTemporalDecision:
        existing = await self.get(decision.decision_id)
        if existing is not None:
            if existing == decision:
                return decision
            raise ValueError("Temporal decision is append-only")
        self._session.add(_decision_to_row(decision))
        return decision

    async def get(self, decision_id: str) -> FactTemporalDecision | None:
        row = await self._session.get(MemoryFactTemporalDecisionRow, decision_id)
        return _decision_from_row(row) if row is not None else None

    async def get_by_idempotency_key(
        self,
        *,
        scope: MemoryFactScope,
        decision_type: FactTemporalDecisionType,
        idempotency_key: str,
    ) -> FactTemporalDecision | None:
        thread_condition = (
            MemoryFactTemporalDecisionRow.thread_id.is_(None)
            if scope.thread_id is None
            else MemoryFactTemporalDecisionRow.thread_id == scope.thread_id
        )
        row = (
            await self._session.execute(
                select(MemoryFactTemporalDecisionRow).where(
                    MemoryFactTemporalDecisionRow.space_id == scope.space_id,
                    MemoryFactTemporalDecisionRow.memory_scope_id == scope.memory_scope_id,
                    MemoryFactTemporalDecisionRow.thread_scope_key
                    == _thread_scope_key(scope.thread_id),
                    thread_condition,
                    MemoryFactTemporalDecisionRow.decision_type
                    == FactTemporalDecisionType(decision_type).value,
                    MemoryFactTemporalDecisionRow.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        return _decision_from_row(row) if row is not None else None

    async def find_compensation(
        self,
        decision_id: str,
    ) -> FactTemporalDecision | None:
        row = (
            await self._session.execute(
                select(MemoryFactTemporalDecisionRow).where(
                    MemoryFactTemporalDecisionRow.compensates_decision_id == decision_id
                )
            )
        ).scalar_one_or_none()
        return _decision_from_row(row) if row is not None else None


class PostgresFactSupersessionRepository:
    """Immutable supersession relations backed by canonical relation rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        relation: FactSupersessionRelation,
    ) -> FactSupersessionRelation:
        row = await self._session.get(MemoryFactRelationRow, relation.relation_id)
        if row is not None:
            decision = (
                await self._session.get(
                    MemoryFactTemporalDecisionRow,
                    row.temporal_decision_id,
                )
                if row.temporal_decision_id is not None
                else None
            )
            existing = _audited_supersession_from_rows(row, decision)
            if existing == relation:
                return relation
            raise ValueError("Supersession relation is append-only")
        self._session.add(_supersession_to_row(relation))
        return relation

    async def find_active_successor(
        self,
        *,
        scope: MemoryFactScope,
        predecessor_fact_id: str,
    ) -> FactSupersessionRelation | None:
        rows = tuple(
            (
                await self._session.execute(
                    _audited_supersession_select().where(
                        *_scope_conditions(scope),
                        MemoryFactRelationRow.target_fact_id == predecessor_fact_id,
                        MemoryFactRelationRow.relation_type == "supersedes",
                        MemoryFactRelationRow.status == "active",
                    )
                )
            ).all()
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise ValueError("Multiple feature-owned supersession successors found")
        return _audited_supersession_from_rows(*rows[0])

    async def find_active_predecessor(
        self,
        *,
        scope: MemoryFactScope,
        successor_fact_id: str,
    ) -> FactSupersessionRelation | None:
        rows = tuple(
            (
                await self._session.execute(
                    _audited_supersession_select().where(
                        *_scope_conditions(scope),
                        MemoryFactRelationRow.source_fact_id == successor_fact_id,
                        MemoryFactRelationRow.relation_type == "supersedes",
                        MemoryFactRelationRow.status == "active",
                    )
                )
            ).all()
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise ValueError("Supersession successor replaces multiple predecessors")
        return _audited_supersession_from_rows(*rows[0])

    async def find_by_decision(
        self,
        decision_id: str,
    ) -> FactSupersessionRelation | None:
        rows = tuple(
            (
                await self._session.execute(
                    _audited_supersession_select().where(
                        MemoryFactRelationRow.temporal_decision_id == decision_id,
                        MemoryFactRelationRow.relation_type == "supersedes",
                    )
                )
            ).all()
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise ValueError("Temporal decision has multiple supersession relations")
        return _audited_supersession_from_rows(*rows[0])

    async def list_active(
        self,
        *,
        scope: MemoryFactScope,
    ) -> tuple[FactSupersessionRelation, ...]:
        rows = tuple(
            (
                await self._session.execute(
                    _audited_supersession_select()
                    .where(
                        *_scope_conditions(scope),
                        MemoryFactRelationRow.relation_type == "supersedes",
                        MemoryFactRelationRow.status == "active",
                    )
                    .order_by(MemoryFactRelationRow.id)
                )
            ).all()
        )
        return tuple(_audited_supersession_from_rows(*row) for row in rows)


def _decision_to_row(decision: FactTemporalDecision) -> MemoryFactTemporalDecisionRow:
    scope = decision.scope
    return MemoryFactTemporalDecisionRow(
        id=decision.decision_id,
        decision_type=decision.decision_type.value,
        space_id=scope.space_id,
        memory_scope_id=scope.memory_scope_id,
        thread_id=scope.thread_id,
        thread_scope_key=_thread_scope_key(scope.thread_id),
        source_fact_id=decision.source_fact_id,
        source_fact_version=decision.source_fact_version,
        target_fact_id=decision.target_fact_id,
        target_fact_version=decision.target_fact_version,
        effective_at=decision.effective_at,
        evidence_refs_json=memory_fact_evidence_refs_to_json(decision.evidence_refs),
        actor_id=decision.actor_id,
        policy_version=decision.policy_version,
        reason_code=decision.reason_code,
        applied_at=decision.applied_at,
        idempotency_key=decision.idempotency_key,
        compensates_decision_id=decision.compensates_decision_id,
        outbox_message_ids_json=list(decision.outbox_message_ids),
    )


def _decision_from_row(row: MemoryFactTemporalDecisionRow) -> FactTemporalDecision:
    return FactTemporalDecision(
        decision_id=row.id,
        decision_type=FactTemporalDecisionType(row.decision_type),
        scope=MemoryFactScope(
            space_id=row.space_id,
            memory_scope_id=row.memory_scope_id,
            thread_id=row.thread_id,
        ),
        source_fact_id=row.source_fact_id,
        source_fact_version=row.source_fact_version,
        target_fact_id=row.target_fact_id,
        target_fact_version=row.target_fact_version,
        effective_at=_aware(row.effective_at),
        evidence_refs=memory_fact_evidence_refs_from_json(row.evidence_refs_json),
        actor_id=row.actor_id,
        policy_version=row.policy_version,
        reason_code=row.reason_code,
        applied_at=_aware(row.applied_at),
        idempotency_key=row.idempotency_key,
        compensates_decision_id=row.compensates_decision_id,
        outbox_message_ids=tuple(row.outbox_message_ids_json),
    )


def _thread_scope_key(thread_id: str | None) -> str:
    return "global" if thread_id is None else f"thread:{thread_id}"


def _supersession_to_row(relation: FactSupersessionRelation) -> MemoryFactRelationRow:
    scope = relation.scope
    return MemoryFactRelationRow(
        id=relation.relation_id,
        space_id=scope.space_id,
        memory_scope_id=scope.memory_scope_id,
        thread_id=scope.thread_id,
        source_fact_id=relation.successor_fact_id,
        source_fact_version=relation.successor_fact_version,
        target_fact_id=relation.predecessor_fact_id,
        target_fact_version=relation.predecessor_fact_version,
        relation_type="supersedes",
        reason=f"temporal_decision:{relation.decision_id}",
        status="active",
        observed_at=relation.created_at,
        valid_from=relation.effective_at,
        valid_to=None,
        temporal_decision_id=relation.decision_id,
        created_at=relation.created_at,
        updated_at=relation.created_at,
    )


def _audited_supersession_select() -> Select[
    tuple[MemoryFactRelationRow, MemoryFactTemporalDecisionRow]
]:
    return select(MemoryFactRelationRow, MemoryFactTemporalDecisionRow).outerjoin(
        MemoryFactTemporalDecisionRow,
        MemoryFactTemporalDecisionRow.id == MemoryFactRelationRow.temporal_decision_id,
    )


def _audited_supersession_from_rows(
    row: MemoryFactRelationRow,
    decision: MemoryFactTemporalDecisionRow | None,
) -> FactSupersessionRelation:
    if (
        row.relation_type != "supersedes"
        or row.source_fact_version is None
        or row.target_fact_version is None
        or row.temporal_decision_id is None
        or row.valid_from is None
    ):
        raise ValueError("Legacy relation is not a feature-owned supersession")
    if decision is None or not _relation_matches_temporal_decision(row, decision):
        raise ValueError("Supersession relation does not match its temporal decision")
    return FactSupersessionRelation(
        relation_id=row.id,
        scope=MemoryFactScope(
            space_id=row.space_id,
            memory_scope_id=row.memory_scope_id,
            thread_id=row.thread_id,
        ),
        successor_fact_id=row.source_fact_id,
        successor_fact_version=row.source_fact_version,
        predecessor_fact_id=row.target_fact_id,
        predecessor_fact_version=row.target_fact_version,
        effective_at=_aware(row.valid_from),
        decision_id=row.temporal_decision_id,
        created_at=_aware(row.created_at),
    )


def _relation_matches_temporal_decision(
    relation: MemoryFactRelationRow,
    decision: MemoryFactTemporalDecisionRow,
) -> bool:
    return (
        decision.decision_type == FactTemporalDecisionType.SUPERSEDE.value
        and decision.id == relation.temporal_decision_id
        and decision.space_id == relation.space_id
        and decision.memory_scope_id == relation.memory_scope_id
        and decision.thread_id == relation.thread_id
        and decision.source_fact_id == relation.source_fact_id
        and decision.source_fact_version == relation.source_fact_version
        and decision.target_fact_id == relation.target_fact_id
        and decision.target_fact_version == relation.target_fact_version
        and _aware(decision.effective_at) == _aware(relation.valid_from)
    )


def _scope_conditions(scope: MemoryFactScope) -> tuple[object, ...]:
    thread_condition = (
        MemoryFactRelationRow.thread_id.is_(None)
        if scope.thread_id is None
        else MemoryFactRelationRow.thread_id == scope.thread_id
    )
    return (
        MemoryFactRelationRow.space_id == scope.space_id,
        MemoryFactRelationRow.memory_scope_id == scope.memory_scope_id,
        thread_condition,
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value


__all__ = (
    "PostgresFactSupersessionRepository",
    "PostgresFactTemporalDecisionRepository",
)
