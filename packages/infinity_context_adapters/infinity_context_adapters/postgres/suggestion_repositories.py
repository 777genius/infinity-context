"""Canonical suggestion persistence and review queries."""

from __future__ import annotations

from datetime import datetime

from infinity_context_core.domain.entities import (
    MemorySuggestion,
)
from infinity_context_core.ports.repositories import (
    SuggestionRepositoryPort,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.mappers import (
    apply_suggestion_to_row,
    suggestion_row_to_domain,
    suggestion_to_row,
)
from infinity_context_adapters.postgres.models import (
    MemorySuggestionRow,
)
from infinity_context_adapters.postgres.repository_helpers import (
    _retrieval_candidate_limit,
)


class PostgresSuggestionRepository(SuggestionRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, suggestion: MemorySuggestion) -> MemorySuggestion:
        self._session.add(suggestion_to_row(suggestion))
        return suggestion

    async def get_by_id(self, suggestion_id: str) -> MemorySuggestion | None:
        row = await self._session.get(MemorySuggestionRow, suggestion_id)
        return suggestion_row_to_domain(row) if row is not None else None

    async def get_for_update(self, suggestion_id: str) -> MemorySuggestion | None:
        row = (
            await self._session.execute(
                select(MemorySuggestionRow)
                .where(MemorySuggestionRow.id == suggestion_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        return suggestion_row_to_domain(row) if row is not None else None

    async def save(self, suggestion: MemorySuggestion) -> MemorySuggestion:
        row = await self._session.get(MemorySuggestionRow, str(suggestion.id))
        if row is None:
            msg = "Suggestion row missing during save"
            raise RuntimeError(msg)
        apply_suggestion_to_row(suggestion, row)
        return suggestion

    async def list_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        status: str | None,
        operation: str | None,
        category: str | None,
        tag: str | None,
        limit: int,
    ) -> list[MemorySuggestion]:
        conditions = [
            MemorySuggestionRow.space_id == space_id,
            MemorySuggestionRow.memory_scope_id == memory_scope_id,
        ]
        if status:
            conditions.append(MemorySuggestionRow.status == status)
        if operation:
            conditions.append(MemorySuggestionRow.operation == operation)
        if category:
            conditions.append(MemorySuggestionRow.category == category)
        rows = (
            await self._session.execute(
                select(MemorySuggestionRow)
                .where(*conditions)
                .order_by(MemorySuggestionRow.updated_at.desc())
                .limit(_retrieval_candidate_limit(limit) if tag else limit)
            )
        ).scalars()
        suggestions = [suggestion_row_to_domain(row) for row in rows]
        if tag:
            suggestions = [suggestion for suggestion in suggestions if tag in suggestion.tags]
        return suggestions[:limit]

    async def find_pending_duplicate(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
        candidate_fingerprint: str,
        operation: str,
        target_fact_id: str | None,
    ) -> MemorySuggestion | None:
        conditions = [
            MemorySuggestionRow.space_id == space_id,
            MemorySuggestionRow.memory_scope_id == memory_scope_id,
            MemorySuggestionRow.status == "pending",
            MemorySuggestionRow.candidate_fingerprint == candidate_fingerprint,
            MemorySuggestionRow.operation == operation,
        ]
        conditions.append(
            MemorySuggestionRow.thread_id.is_(None)
            if thread_id is None
            else MemorySuggestionRow.thread_id == thread_id
        )
        if target_fact_id:
            conditions.append(MemorySuggestionRow.target_fact_id == target_fact_id)
        else:
            conditions.append(MemorySuggestionRow.target_fact_id.is_(None))
        row = (
            await self._session.execute(select(MemorySuggestionRow).where(*conditions).limit(1))
        ).scalar_one_or_none()
        return suggestion_row_to_domain(row) if row is not None else None

    async def list_expired_pending(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> list[MemorySuggestion]:
        rows = (
            await self._session.execute(
                select(MemorySuggestionRow)
                .where(
                    MemorySuggestionRow.status == "pending",
                    MemorySuggestionRow.expires_at.is_not(None),
                    MemorySuggestionRow.expires_at <= now,
                )
                .order_by(MemorySuggestionRow.expires_at, MemorySuggestionRow.id)
                .limit(limit)
            )
        ).scalars()
        return [suggestion_row_to_domain(row) for row in rows]

    async def list_pending_for_capture(
        self,
        *,
        capture_id: str,
        limit: int,
    ) -> list[MemorySuggestion]:
        rows = (
            await self._session.execute(
                select(MemorySuggestionRow)
                .where(
                    MemorySuggestionRow.status == "pending",
                    MemorySuggestionRow.created_from_capture_id == capture_id,
                )
                .order_by(MemorySuggestionRow.created_at, MemorySuggestionRow.id)
                .limit(limit)
            )
        ).scalars()
        return [suggestion_row_to_domain(row) for row in rows]

    async def count_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        status: str | None,
    ) -> int:
        conditions = [
            MemorySuggestionRow.space_id == space_id,
            MemorySuggestionRow.memory_scope_id == memory_scope_id,
        ]
        if status:
            conditions.append(MemorySuggestionRow.status == status)
        return int(
            (
                await self._session.execute(
                    select(func.count()).select_from(MemorySuggestionRow).where(*conditions)
                )
            ).scalar_one()
        )
