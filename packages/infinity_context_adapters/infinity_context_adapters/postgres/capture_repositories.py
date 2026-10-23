"""Canonical capture persistence and optimistic updates."""

from __future__ import annotations

from datetime import datetime

from infinity_context_core.domain.capture import CanonicalCapture
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.ports.captures import CaptureRepositoryPort
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.mappers import (
    apply_capture_to_row,
    capture_row_to_domain,
    capture_to_row,
)
from infinity_context_adapters.postgres.models import (
    MemoryCaptureRow,
)


class PostgresCaptureRepository(CaptureRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, capture: CanonicalCapture) -> CanonicalCapture:
        self._session.add(capture_to_row(capture))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise MemoryConflictError("Canonical capture conflicted with existing data") from exc
        return capture

    async def get_by_id(self, capture_id: str) -> CanonicalCapture | None:
        row = await self._session.get(MemoryCaptureRow, capture_id)
        return capture_row_to_domain(row) if row is not None else None

    async def get_by_idempotency_key(
        self,
        *,
        space_id: str,
        idempotency_key: str,
    ) -> CanonicalCapture | None:
        row = (
            await self._session.execute(
                select(MemoryCaptureRow).where(
                    MemoryCaptureRow.space_id == space_id,
                    MemoryCaptureRow.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        return capture_row_to_domain(row) if row is not None else None

    async def get_for_update(self, capture_id: str) -> CanonicalCapture | None:
        row = (
            await self._session.execute(
                select(MemoryCaptureRow).where(MemoryCaptureRow.id == capture_id).with_for_update()
            )
        ).scalar_one_or_none()
        return capture_row_to_domain(row) if row is not None else None

    async def save(self, capture: CanonicalCapture) -> CanonicalCapture:
        row = await self._session.get(MemoryCaptureRow, str(capture.id))
        if row is None:
            msg = "Capture row missing during save"
            raise RuntimeError(msg)
        apply_capture_to_row(capture, row)
        return capture

    async def list_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        status: str | None,
        consolidation_status: str | None,
        limit: int,
        cursor_created_at: datetime | None = None,
        cursor_id: str | None = None,
    ) -> list[CanonicalCapture]:
        conditions = [
            MemoryCaptureRow.space_id == space_id,
            MemoryCaptureRow.memory_scope_id == memory_scope_id,
        ]
        if status:
            conditions.append(MemoryCaptureRow.status == status)
        if consolidation_status:
            conditions.append(MemoryCaptureRow.consolidation_status == consolidation_status)
        if cursor_created_at is not None and cursor_id is not None:
            conditions.append(
                or_(
                    MemoryCaptureRow.created_at < cursor_created_at,
                    (MemoryCaptureRow.created_at == cursor_created_at)
                    & (MemoryCaptureRow.id < cursor_id),
                )
            )
        rows = (
            await self._session.execute(
                select(MemoryCaptureRow)
                .where(*conditions)
                .order_by(MemoryCaptureRow.created_at.desc(), MemoryCaptureRow.id.desc())
                .limit(limit)
            )
        ).scalars()
        return [capture_row_to_domain(row) for row in rows]

    async def count_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        status: str | None,
        consolidation_statuses: tuple[str, ...],
    ) -> int:
        conditions = [
            MemoryCaptureRow.space_id == space_id,
            MemoryCaptureRow.memory_scope_id == memory_scope_id,
        ]
        if status:
            conditions.append(MemoryCaptureRow.status == status)
        if consolidation_statuses:
            conditions.append(MemoryCaptureRow.consolidation_status.in_(consolidation_statuses))
        return int(
            (
                await self._session.execute(
                    select(func.count()).select_from(MemoryCaptureRow).where(*conditions)
                )
            ).scalar_one()
        )
