"""Canonical episode source persistence."""

from __future__ import annotations

from infinity_context_core.domain.entities import (
    MemoryEpisode,
)
from infinity_context_core.ports.repositories import (
    EpisodeRepositoryPort,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.mappers import (
    episode_row_to_domain,
    episode_to_row,
)
from infinity_context_adapters.postgres.models import (
    MemoryEpisodeRow,
)


class PostgresEpisodeRepository(EpisodeRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, episode: MemoryEpisode) -> MemoryEpisode:
        self._session.add(episode_to_row(episode))
        return episode

    async def get_by_id(self, episode_id: str) -> MemoryEpisode | None:
        row = await self._session.get(MemoryEpisodeRow, episode_id)
        return episode_row_to_domain(row) if row is not None else None

    async def list_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
        status: str | None,
        limit: int,
    ) -> list[MemoryEpisode]:
        conditions = [
            MemoryEpisodeRow.space_id == space_id,
            MemoryEpisodeRow.memory_scope_id == memory_scope_id,
        ]
        if thread_id is not None:
            conditions.append(MemoryEpisodeRow.thread_id == thread_id)
        if status is not None:
            conditions.append(MemoryEpisodeRow.status == status)
        rows = (
            await self._session.execute(
                select(MemoryEpisodeRow)
                .where(*conditions)
                .order_by(MemoryEpisodeRow.occurred_at.desc(), MemoryEpisodeRow.id.desc())
                .limit(limit)
            )
        ).scalars()
        return [episode_row_to_domain(row) for row in rows]
