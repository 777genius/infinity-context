"""Postgres repositories for idempotency records and outbox events."""

from __future__ import annotations

from datetime import datetime

from infinity_context_core.domain.events import OutboxEvent
from infinity_context_core.domain.idempotency import IdempotencyRecord
from infinity_context_core.ports.repositories import IdempotencyRepositoryPort
from infinity_context_core.ports.unit_of_work import OutboxPort
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.models import (
    MemoryIdempotencyRecordRow,
    MemoryOutboxRow,
)


class PostgresIdempotencyRepository(IdempotencyRepositoryPort):
    def __init__(self, session: AsyncSession, now: datetime) -> None:
        self._session = session
        self._now = now

    async def find(self, *, space_id: str, key: str) -> IdempotencyRecord | None:
        row = (
            await self._session.execute(
                select(MemoryIdempotencyRecordRow).where(
                    MemoryIdempotencyRecordRow.space_id == space_id,
                    MemoryIdempotencyRecordRow.key == key,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return IdempotencyRecord(
            space_id=row.space_id,
            key=row.key,
            fingerprint=row.fingerprint,
            result_type=row.result_type,
            result_id=row.result_id,
        )

    async def save(self, record: IdempotencyRecord) -> None:
        self._session.add(
            MemoryIdempotencyRecordRow(
                space_id=record.space_id,
                key=record.key,
                fingerprint=record.fingerprint,
                result_type=record.result_type,
                result_id=record.result_id,
                created_at=self._now,
            )
        )


class PostgresOutbox(OutboxPort):
    def __init__(self, session: AsyncSession, now: datetime) -> None:
        self._session = session
        self._now = now

    async def enqueue(self, event: OutboxEvent) -> None:
        self._session.add(
            MemoryOutboxRow(
                event_type=event.event_type,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                aggregate_version=event.aggregate_version,
                workload_class=event.workload_class,
                fairness_key=(event.fairness_key or f"{event.aggregate_type}:{event.aggregate_id}"),
                payload_json=event.payload,
                status="pending",
                attempt_count=0,
                next_attempt_at=self._now,
                created_at=self._now,
                updated_at=self._now,
            )
        )

    async def enqueue_or_reschedule(self, event: OutboxEvent) -> None:
        row = (
            await self._session.execute(
                select(MemoryOutboxRow)
                .where(
                    MemoryOutboxRow.event_type == event.event_type,
                    MemoryOutboxRow.aggregate_type == event.aggregate_type,
                    MemoryOutboxRow.aggregate_id == event.aggregate_id,
                    MemoryOutboxRow.status.in_(("pending", "retry_pending")),
                )
                .order_by(MemoryOutboxRow.created_at, MemoryOutboxRow.id)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if row is None:
            await self.enqueue(event)
            return
        row.aggregate_version = event.aggregate_version
        row.workload_class = event.workload_class
        row.fairness_key = event.fairness_key or f"{event.aggregate_type}:{event.aggregate_id}"
        row.payload_json = event.payload
        row.status = "pending"
        row.attempt_count = 0
        row.next_attempt_at = self._now
        row.last_safe_error = None
        row.last_safe_diagnostic_code = None
        row.updated_at = self._now
