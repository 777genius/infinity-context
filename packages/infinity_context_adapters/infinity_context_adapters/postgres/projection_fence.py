"""Postgres lifecycle fence for external derived projection writes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from infinity_context_core.ports.projection_fence import (
    ProjectionFencePermit,
    ProjectionFencePort,
)
from sqlalchemy import Select, and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infinity_context_adapters.postgres.models import MemoryComparisonBenchmarkRunRow


class PostgresProjectionFence(ProjectionFencePort):
    """Hold a shared registry-row lock while an active run is projected."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        max_active_holds: int = 1,
    ) -> None:
        if type(max_active_holds) is not int or max_active_holds < 1:
            raise ValueError("max_active_holds must be a positive int")
        self._session_factory = session_factory
        self._active_holds = asyncio.Semaphore(max_active_holds)

    @asynccontextmanager
    async def hold(self, space_id: str) -> AsyncIterator[ProjectionFencePermit]:
        authorized = await self._read_authorization(space_id)
        if authorized is None:
            yield ProjectionFencePermit(allow_upsert=True)
            return
        if authorized is not True:
            yield ProjectionFencePermit(allow_upsert=False)
            return

        # Do not open the lock-holding session until capacity is reserved. The
        # handler needs a second connection for its authoritative canonical read.
        async with self._active_holds:
            session = self._session_factory()
            try:
                async with session.begin():
                    locked_authorized = await session.scalar(_projection_fence_query(space_id))
                    if locked_authorized is True:
                        yield ProjectionFencePermit(allow_upsert=True)
                        return
            finally:
                await session.close()

        yield ProjectionFencePermit(allow_upsert=False)

    async def _read_authorization(self, space_id: str) -> bool | None:
        session = self._session_factory()
        try:
            async with session.begin():
                return await session.scalar(_projection_state_query(space_id))
        finally:
            await session.close()


def _projection_state_query(space_id: str) -> Select[tuple[bool]]:
    return select(
        and_(
            MemoryComparisonBenchmarkRunRow.state == "active",
            MemoryComparisonBenchmarkRunRow.projection_cleanup_state == "unsealed",
            MemoryComparisonBenchmarkRunRow.cleanup_plan_state == "sealed",
            MemoryComparisonBenchmarkRunRow.cleanup_plan_json.is_not(None),
            MemoryComparisonBenchmarkRunRow.cleanup_plan_sha256.is_not(None),
        )
    ).where(MemoryComparisonBenchmarkRunRow.space_id == space_id)


def _projection_fence_query(space_id: str) -> Select[tuple[bool]]:
    return _projection_state_query(space_id).with_for_update(read=True)


__all__ = ("PostgresProjectionFence",)
