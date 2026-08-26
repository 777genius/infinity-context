"""Durable reconciliation state for both vector projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infinity_context_adapters.postgres.models import MemoryLocatorProjectionTombstoneRow


@dataclass(frozen=True, slots=True)
class PostgresLocatorProjectionMaintenance:
    sessions: async_sessionmaker[AsyncSession]

    async def pending(self, lane: str, *, limit: int = 100) -> tuple[str, ...]:
        column = _lane_column(lane)
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(MemoryLocatorProjectionTombstoneRow.chunk_id)
                    .where(column.is_(None))
                    .order_by(
                        MemoryLocatorProjectionTombstoneRow.updated_at,
                        MemoryLocatorProjectionTombstoneRow.chunk_id,
                    )
                    .limit(limit)
                )
            ).scalars()
            return tuple(rows)

    async def pending_deletes(self, lane: str, *, limit: int = 100) -> tuple[tuple[str, int], ...]:
        """Return tombstones with the version that must still be current."""

        column = _lane_column(lane)
        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(
                        MemoryLocatorProjectionTombstoneRow.chunk_id,
                        MemoryLocatorProjectionTombstoneRow.canonical_version,
                    )
                    .where(column.is_(None))
                    .order_by(
                        MemoryLocatorProjectionTombstoneRow.updated_at,
                        MemoryLocatorProjectionTombstoneRow.chunk_id,
                    )
                    .limit(limit)
                )
            ).all()
            return tuple((str(chunk_id), int(version)) for chunk_id, version in rows)

    async def current_delete_ids(
        self,
        chunk_ids: tuple[str, ...],
        *,
        canonical_version: int,
    ) -> tuple[str, ...]:
        """Authorize only an exact current tombstone/inactive-row delete."""

        if not chunk_ids:
            return ()
        # Import through models so this adapter keeps one SQLAlchemy metadata graph.
        from infinity_context_adapters.postgres.models import MemoryChunkRow

        async with self.sessions() as session:
            rows = (
                await session.execute(
                    select(MemoryLocatorProjectionTombstoneRow.chunk_id)
                    .outerjoin(
                        MemoryChunkRow,
                        MemoryChunkRow.id == MemoryLocatorProjectionTombstoneRow.chunk_id,
                    )
                    .where(
                        MemoryLocatorProjectionTombstoneRow.chunk_id.in_(chunk_ids),
                        MemoryLocatorProjectionTombstoneRow.canonical_version == canonical_version,
                        or_(
                            MemoryChunkRow.id.is_(None),
                            and_(
                                MemoryChunkRow.retrieval_version == canonical_version,
                                or_(
                                    MemoryChunkRow.status != "active",
                                    ~MemoryChunkRow.classification.in_(("public", "internal")),
                                ),
                            ),
                        ),
                    )
                )
            ).scalars()
            authorized = set(rows)
        return tuple(chunk_id for chunk_id in chunk_ids if chunk_id in authorized)

    async def mark_deleted(
        self,
        lane: str,
        chunk_ids: tuple[str, ...],
        *,
        completed_at: datetime,
        canonical_version: int | None = None,
    ) -> None:
        if not chunk_ids:
            return
        column = _lane_column(lane)
        async with self.sessions() as session, session.begin():
            conditions = [MemoryLocatorProjectionTombstoneRow.chunk_id.in_(chunk_ids)]
            if canonical_version is not None:
                conditions.append(
                    MemoryLocatorProjectionTombstoneRow.canonical_version == canonical_version
                )
            rows = (
                await session.execute(
                    select(MemoryLocatorProjectionTombstoneRow).where(*conditions)
                )
            ).scalars()
            for row in rows:
                setattr(row, column.key, completed_at)
                row.updated_at = completed_at

    async def tracks(self, chunk_ids: tuple[str, ...]) -> bool:
        if not chunk_ids:
            return False
        async with self.sessions() as session:
            tracked = set(
                (
                    await session.execute(
                        select(MemoryLocatorProjectionTombstoneRow.chunk_id).where(
                            MemoryLocatorProjectionTombstoneRow.chunk_id.in_(chunk_ids)
                        )
                    )
                ).scalars()
            )
        return tracked == set(chunk_ids)


def _lane_column(lane: str):
    if lane == "legacy":
        return MemoryLocatorProjectionTombstoneRow.legacy_deleted_at
    if lane == "locator":
        return MemoryLocatorProjectionTombstoneRow.locator_deleted_at
    raise ValueError("unknown locator projection tombstone lane")


__all__ = ("PostgresLocatorProjectionMaintenance",)
