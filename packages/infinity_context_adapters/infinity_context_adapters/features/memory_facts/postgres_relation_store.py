"""Feature relations over existing rows and the canonical fact session."""

from __future__ import annotations

from infinity_context_core.features.memory_facts.public import (
    FactRelationSnapshot,
    FactRelationStatus,
    FactRelationType,
    MemoryFactScope,
    MemoryFactSnapshot,
)
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from infinity_context_adapters.features.memory_facts.postgres_fact_mapping import (
    memory_fact_row_to_snapshot,
)
from infinity_context_adapters.postgres.fact_selection_conditions import (
    memory_fact_code_scope_conditions,
)
from infinity_context_adapters.postgres.models import (
    MemoryFactRelationRow,
    MemoryFactRow,
    MemorySourceRefRow,
)


class PostgresFactRelationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, relation_id: str, *, scope: MemoryFactScope) -> FactRelationSnapshot | None:
        row = (
            await self._session.execute(
                select(MemoryFactRelationRow)
                .where(
                    MemoryFactRelationRow.id == relation_id,
                    MemoryFactRelationRow.space_id == scope.space_id,
                    MemoryFactRelationRow.memory_scope_id == scope.memory_scope_id,
                )
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        return relation_row_to_snapshot(row) if row is not None else None

    async def find_active(
        self, *, source_fact_id: str, target_fact_id: str, relation_type: FactRelationType
    ) -> FactRelationSnapshot | None:
        row = (
            await self._session.execute(
                select(MemoryFactRelationRow)
                .where(
                    MemoryFactRelationRow.source_fact_id == source_fact_id,
                    MemoryFactRelationRow.target_fact_id == target_fact_id,
                    MemoryFactRelationRow.relation_type == relation_type.value,
                    MemoryFactRelationRow.status == "active",
                )
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        return relation_row_to_snapshot(row) if row is not None else None

    async def create(self, relation: FactRelationSnapshot) -> FactRelationSnapshot:
        # The handler holds the scope and endpoint locks through commit. The
        # existing partial unique index also protects against non-feature writers.
        self._session.add(
            MemoryFactRelationRow(
                id=relation.relation_id,
                space_id=relation.space_id,
                memory_scope_id=relation.memory_scope_id,
                source_fact_id=relation.source_fact_id,
                target_fact_id=relation.target_fact_id,
                relation_type=relation.relation_type.value,
                reason=relation.reason,
                status=relation.status.value,
                observed_at=relation.observed_at,
                valid_from=relation.valid_from,
                valid_to=relation.valid_to,
                created_at=relation.created_at,
                updated_at=relation.updated_at,
            )
        )
        await self._session.flush()
        return relation

    async def save(self, relation: FactRelationSnapshot) -> FactRelationSnapshot:
        row = (
            await self._session.execute(
                select(MemoryFactRelationRow)
                .where(
                    MemoryFactRelationRow.id == relation.relation_id,
                    MemoryFactRelationRow.space_id == relation.space_id,
                    MemoryFactRelationRow.memory_scope_id == relation.memory_scope_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if row is None:
            raise LookupError("Fact relation not found")
        # Reapply lifecycle to the locked row, preserving immutable temporal audit
        # columns and idempotent updated_at even if a legacy unlink raced us.
        current = relation_row_to_snapshot(row)
        saved = current.delete(now=relation.updated_at)
        row.status = saved.status.value
        row.updated_at = saved.updated_at
        return saved

    async def get_related_fact(
        self, fact_id: str, *, scope: MemoryFactScope
    ) -> MemoryFactSnapshot | None:
        row = (
            await self._session.execute(
                select(MemoryFactRow).where(
                    MemoryFactRow.id == fact_id,
                    MemoryFactRow.space_id == scope.space_id,
                    MemoryFactRow.memory_scope_id == scope.memory_scope_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        refs = list(
            (
                await self._session.execute(
                    select(MemorySourceRefRow)
                    .where(
                        MemorySourceRefRow.fact_id == row.id,
                        MemorySourceRefRow.fact_version == row.version,
                    )
                    .order_by(MemorySourceRefRow.id)
                )
            ).scalars()
        )
        return memory_fact_row_to_snapshot(row, refs)

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
        conditions = [
            MemoryFactRelationRow.space_id == scope.space_id,
            MemoryFactRelationRow.memory_scope_id == scope.memory_scope_id,
            or_(
                MemoryFactRelationRow.source_fact_id == fact_id,
                MemoryFactRelationRow.target_fact_id == fact_id,
            ),
        ]
        if status is not None:
            conditions.append(MemoryFactRelationRow.status == status)
        statement = select(MemoryFactRelationRow)
        if enforce_code_scope:
            other = aliased(MemoryFactRow)
            statement = statement.join(
                other,
                or_(
                    and_(
                        MemoryFactRelationRow.source_fact_id == fact_id,
                        other.id == MemoryFactRelationRow.target_fact_id,
                    ),
                    and_(
                        MemoryFactRelationRow.target_fact_id == fact_id,
                        other.id == MemoryFactRelationRow.source_fact_id,
                    ),
                ),
            )
            conditions.extend(
                memory_fact_code_scope_conditions(
                    other,
                    repository_id=repository_id,
                    code_scope_id=code_scope_id,
                )
            )
            conditions.append(other.classification != "restricted")
        rows = (
            await self._session.execute(
                statement.where(*conditions)
                .order_by(MemoryFactRelationRow.updated_at.desc(), MemoryFactRelationRow.id.desc())
                .limit(limit)
            )
        ).scalars()
        return tuple(relation_row_to_snapshot(row) for row in rows)


def relation_row_to_snapshot(row: MemoryFactRelationRow) -> FactRelationSnapshot:
    """Translate persistence at the adapter boundary, including temporal-owned rows."""
    return FactRelationSnapshot(
        relation_id=row.id,
        space_id=row.space_id,
        memory_scope_id=row.memory_scope_id,
        source_fact_id=row.source_fact_id,
        target_fact_id=row.target_fact_id,
        relation_type=FactRelationType(row.relation_type),
        reason=row.reason,
        status=FactRelationStatus(row.status),
        observed_at=row.observed_at,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
