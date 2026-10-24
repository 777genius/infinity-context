"""Canonical semantic anchor persistence."""

from __future__ import annotations

from infinity_context_core.domain.entities import (
    MemoryAnchor,
)
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.ports.repositories import (
    ActiveAnchorKey,
    AnchorRepositoryPort,
    AnchorScopeQuery,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.canonical_retrieval_batching import (
    find_active_anchor_keys,
    get_anchor_ids,
    list_anchor_scopes,
)
from infinity_context_adapters.postgres.mappers import (
    anchor_row_to_domain,
    anchor_to_row,
    apply_anchor_to_row,
)
from infinity_context_adapters.postgres.models import (
    MemoryAnchorRow,
)


class PostgresAnchorRepository(AnchorRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, anchor: MemoryAnchor) -> MemoryAnchor:
        self._session.add(anchor_to_row(anchor))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise MemoryConflictError("Semantic anchor conflicted with existing data") from exc
        return anchor

    async def get_by_id(self, anchor_id: str) -> MemoryAnchor | None:
        row = await self._session.get(MemoryAnchorRow, anchor_id)
        return anchor_row_to_domain(row) if row is not None else None

    async def get_by_ids(self, anchor_ids: tuple[str, ...]) -> list[MemoryAnchor]:
        return await get_anchor_ids(self._session, anchor_ids)

    async def find_active_by_key(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        kind: str,
        normalized_key: str,
    ) -> MemoryAnchor | None:
        row = (
            await self._session.execute(
                select(MemoryAnchorRow)
                .where(
                    MemoryAnchorRow.space_id == space_id,
                    MemoryAnchorRow.memory_scope_id == memory_scope_id,
                    MemoryAnchorRow.kind == kind,
                    MemoryAnchorRow.normalized_key == normalized_key,
                    MemoryAnchorRow.status == "active",
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return anchor_row_to_domain(row) if row is not None else None

    async def find_active_by_keys(
        self,
        requests: tuple[ActiveAnchorKey, ...],
    ) -> list[MemoryAnchor | None]:
        return await find_active_anchor_keys(self._session, requests)

    async def list_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        kind: str | None,
        status: str | None,
        limit: int,
    ) -> list[MemoryAnchor]:
        conditions = [
            MemoryAnchorRow.space_id == space_id,
            MemoryAnchorRow.memory_scope_id == memory_scope_id,
        ]
        if kind:
            conditions.append(MemoryAnchorRow.kind == kind)
        if status:
            conditions.append(MemoryAnchorRow.status == status)
        statement = (
            select(MemoryAnchorRow)
            .where(*conditions)
            .order_by(MemoryAnchorRow.updated_at.desc(), MemoryAnchorRow.id.desc())
        )
        if limit >= 0:
            statement = statement.limit(limit)
        rows = (await self._session.execute(statement)).scalars()
        return [anchor_row_to_domain(row) for row in rows]

    async def list_for_scopes(
        self,
        requests: tuple[AnchorScopeQuery, ...],
    ) -> list[list[MemoryAnchor]]:
        return await list_anchor_scopes(self._session, requests)

    async def save(self, anchor: MemoryAnchor) -> MemoryAnchor:
        row = await self._session.get(MemoryAnchorRow, str(anchor.id))
        if row is None:
            raise MemoryConflictError("Semantic anchor was deleted before save")
        apply_anchor_to_row(anchor, row)
        await self._session.flush()
        return anchor
