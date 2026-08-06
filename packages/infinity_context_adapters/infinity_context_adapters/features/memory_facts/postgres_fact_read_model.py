"""Postgres read model for complete canonical fact snapshots."""

from __future__ import annotations

from infinity_context_core.features.memory_facts.public import (
    MemoryFactListSpec,
    MemoryFactReadModelPort,
    MemoryFactSnapshot,
)
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infinity_context_adapters.features.memory_facts.postgres_fact_mapping import (
    memory_fact_row_to_snapshot,
)
from infinity_context_adapters.features.memory_facts.postgres_fact_store import (
    PostgresMemoryFactStore,
)
from infinity_context_adapters.postgres.models import MemoryFactRow, MemorySourceRefRow


class PostgresMemoryFactReadModel:
    """Administrative reads; prompt disclosure remains owned by selection policy."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get_by_id(self, fact_id: str) -> MemoryFactSnapshot | None:
        async with self._sessions() as session:
            row = await session.get(MemoryFactRow, fact_id)
            if row is None:
                return None
            refs = await _source_refs(session, ((row.id, row.version),))
            return memory_fact_row_to_snapshot(row, refs.get((row.id, row.version), []))

    async def get_many_by_ids(
        self,
        fact_ids: tuple[str, ...],
    ) -> tuple[MemoryFactSnapshot, ...]:
        unique_ids = tuple(dict.fromkeys(fact_id for fact_id in fact_ids if fact_id.strip()))
        if not unique_ids:
            return ()
        async with self._sessions() as session:
            rows = tuple(
                (
                    await session.execute(
                        select(MemoryFactRow).where(MemoryFactRow.id.in_(unique_ids))
                    )
                ).scalars()
            )
            by_id = {row.id: row for row in rows}
            refs = await _source_refs(
                session,
                tuple((row.id, row.version) for row in rows),
            )
            return tuple(
                memory_fact_row_to_snapshot(
                    row,
                    refs.get((row.id, row.version), []),
                )
                for fact_id in unique_ids
                if (row := by_id.get(fact_id)) is not None
            )

    async def list_for_scope(
        self,
        spec: MemoryFactListSpec,
    ) -> tuple[MemoryFactSnapshot, ...]:
        conditions = [
            MemoryFactRow.space_id == spec.space_id,
            MemoryFactRow.memory_scope_id == spec.memory_scope_id,
        ]
        if spec.status is not None:
            conditions.append(MemoryFactRow.status == spec.status)
        if spec.category is not None:
            conditions.append(MemoryFactRow.category == spec.category)
        if spec.thread_id is not None:
            conditions.append(
                or_(MemoryFactRow.thread_id == spec.thread_id, MemoryFactRow.thread_id.is_(None))
            )
        if spec.restrict_to_repository_visibility:
            if spec.repository_id is None:
                conditions.append(MemoryFactRow.repository_id.is_(None))
            else:
                code_visibility = MemoryFactRow.code_scope_id.is_(None)
                if spec.code_scope_id is not None:
                    code_visibility = or_(
                        code_visibility,
                        MemoryFactRow.code_scope_id == spec.code_scope_id,
                    )
                conditions.append(
                    or_(
                        MemoryFactRow.repository_id.is_(None),
                        (MemoryFactRow.repository_id == spec.repository_id) & code_visibility,
                    )
                )
        if spec.cursor_updated_at is not None and spec.cursor_id is not None:
            conditions.append(
                or_(
                    MemoryFactRow.updated_at < spec.cursor_updated_at,
                    (MemoryFactRow.updated_at == spec.cursor_updated_at)
                    & (MemoryFactRow.id < spec.cursor_id),
                )
            )
        fetch_limit = spec.limit if spec.tag is None else min(spec.limit * 5, 2500)
        async with self._sessions() as session:
            rows = tuple(
                (
                    await session.execute(
                        select(MemoryFactRow)
                        .where(*conditions)
                        .order_by(MemoryFactRow.updated_at.desc(), MemoryFactRow.id.desc())
                        .limit(fetch_limit)
                    )
                ).scalars()
            )
            refs = await _source_refs(
                session,
                tuple((row.id, row.version) for row in rows),
            )
            snapshots = (
                memory_fact_row_to_snapshot(row, refs.get((row.id, row.version), []))
                for row in rows
            )
            return tuple(
                snapshot for snapshot in snapshots if spec.tag is None or spec.tag in snapshot.tags
            )[: spec.limit]

    async def list_versions_by_id(
        self,
        fact_id: str,
    ) -> tuple[MemoryFactSnapshot, ...]:
        current = await self.get_by_id(fact_id)
        if current is None:
            return ()
        async with self._sessions() as session:
            return await PostgresMemoryFactStore(session).list_versions(current.identity)


async def _source_refs(
    session: AsyncSession,
    identities: tuple[tuple[str, int], ...],
) -> dict[tuple[str, int], list[MemorySourceRefRow]]:
    if not identities:
        return {}
    fact_ids = tuple(dict.fromkeys(fact_id for fact_id, _ in identities))
    rows = tuple(
        (
            await session.execute(
                select(MemorySourceRefRow)
                .where(MemorySourceRefRow.fact_id.in_(fact_ids))
                .order_by(
                    MemorySourceRefRow.fact_id,
                    MemorySourceRefRow.fact_version,
                    MemorySourceRefRow.id,
                )
            )
        ).scalars()
    )
    requested = set(identities)
    grouped: dict[tuple[str, int], list[MemorySourceRefRow]] = {}
    for row in rows:
        key = (row.fact_id, row.fact_version)
        if key in requested:
            grouped.setdefault(key, []).append(row)
    return grouped


def create_postgres_memory_fact_read_model(
    sessions: async_sessionmaker[AsyncSession],
) -> MemoryFactReadModelPort:
    return PostgresMemoryFactReadModel(sessions)


__all__ = (
    "PostgresMemoryFactReadModel",
    "create_postgres_memory_fact_read_model",
)
