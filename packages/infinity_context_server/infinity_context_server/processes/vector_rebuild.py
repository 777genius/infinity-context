"""Durable bounded recovery for the generic Qdrant projection."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_adapters.postgres.models import MemoryChunkRow, MemoryOutboxRow
from infinity_context_core.domain.entities import LifecycleStatus
from infinity_context_core.domain.events import OutboxEvent
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_server.processes.outbox import ClaimedOutboxJob, OutboxHandlerRegistry
from infinity_context_server.processes.projections import (
    OutboxProjectionError,
    ProjectionOutboxProcess,
    _can_embed,
    _chunk_canonical_version,
    _raise_if_degraded,
    _require_same_fenced_space,
)

EVENT_TYPE = "vector.rebuild_scope_page"
MAX_BATCH_SIZE = 256
_DEAD_REBUILD_CODES = (
    "vector.delete_canonical_versions_rebuild_required",
    "qdrant.delete_rebuild_required",
)


@dataclass(frozen=True, slots=True)
class _RebuildPage:
    operation_id: str
    space_id: str
    memory_scope_id: str
    upper_bound_id: str
    cursor: str | None
    batch_size: int

    @classmethod
    def from_job(cls, job: ClaimedOutboxJob) -> _RebuildPage:
        payload = job.payload_json
        if set(payload) != {
            "operation_id",
            "space_id",
            "memory_scope_id",
            "upper_bound_id",
            "cursor",
            "batch_size",
        }:
            raise OutboxProjectionError(EVENT_TYPE, "vector.rebuild_payload_invalid")
        values = {key: payload[key] for key in payload}
        for key in ("operation_id", "space_id", "memory_scope_id", "upper_bound_id"):
            if not isinstance(values[key], str) or not values[key]:
                raise OutboxProjectionError(EVENT_TYPE, "vector.rebuild_payload_invalid")
        cursor = values["cursor"]
        if cursor is not None and (not isinstance(cursor, str) or not cursor):
            raise OutboxProjectionError(EVENT_TYPE, "vector.rebuild_payload_invalid")
        batch_size = values["batch_size"]
        if type(batch_size) is not int or not 1 <= batch_size <= MAX_BATCH_SIZE:
            raise OutboxProjectionError(EVENT_TYPE, "vector.rebuild_payload_invalid")
        return cls(
            operation_id=str(values["operation_id"]),
            space_id=str(values["space_id"]),
            memory_scope_id=str(values["memory_scope_id"]),
            upper_bound_id=str(values["upper_bound_id"]),
            cursor=cursor,
            batch_size=batch_size,
        )

    def next_event(self, cursor: str) -> OutboxEvent:
        return OutboxEvent(
            event_type=EVENT_TYPE,
            aggregate_type="vector_rebuild",
            aggregate_id=self.operation_id,
            workload_class="projection",
            fairness_key=f"vector-rebuild:{self.operation_id}",
            payload={
                "operation_id": self.operation_id,
                "space_id": self.space_id,
                "memory_scope_id": self.memory_scope_id,
                "upper_bound_id": self.upper_bound_id,
                "cursor": cursor,
                "batch_size": self.batch_size,
            },
        )


class GenericVectorRebuildProcess:
    def __init__(self, container) -> None:
        self._container = container
        self._projection = ProjectionOutboxProcess(container)

    def handlers(self) -> OutboxHandlerRegistry:
        return {EVENT_TYPE: self.handle_page}

    async def handle_page(self, job: ClaimedOutboxJob) -> None:
        page = _RebuildPage.from_job(job)
        rows = await self._load_page(page)
        for row in rows:
            await self._reconcile_chunk(page, str(row.id))
        if len(rows) == page.batch_size:
            async with self._container.uow_factory() as uow:
                await uow.outbox.enqueue_or_reschedule(page.next_event(str(rows[-1].id)))
                await uow.commit()
            return
        await self._complete_dead_rebuild_events(page)

    async def _load_page(self, page: _RebuildPage) -> list[MemoryChunkRow]:
        conditions = [
            MemoryChunkRow.space_id == page.space_id,
            MemoryChunkRow.memory_scope_id == page.memory_scope_id,
            MemoryChunkRow.id <= page.upper_bound_id,
        ]
        if page.cursor is not None:
            conditions.append(MemoryChunkRow.id > page.cursor)
        async with AsyncSession(self._container.engine) as session:
            return list(
                (
                    await session.execute(
                        select(MemoryChunkRow)
                        .where(*conditions)
                        .order_by(MemoryChunkRow.id)
                        .limit(page.batch_size)
                    )
                ).scalars()
            )

    async def _reconcile_chunk(self, page: _RebuildPage, chunk_id: str) -> None:
        async with self._container.uow_factory() as uow:
            observed = await uow.chunks.get_by_id(chunk_id)
        if observed is None:
            return
        _require_scope(observed, page)
        if observed.status == LifecycleStatus.ACTIVE and _can_embed(observed.classification):
            await self._projection.handle_vector_upsert(
                _synthetic_upsert(job_id=0, chunk_id=chunk_id)
            )
            return

        initial_space_id = str(observed.space_id)
        async with self._container.projection_fence.hold(initial_space_id):
            async with self._container.uow_factory() as uow:
                current = await uow.chunks.get_by_id(chunk_id)
            if current is None:
                return
            _require_scope(current, page)
            _require_same_fenced_space(str(current.space_id), initial_space_id)
            version = _chunk_canonical_version(current)
            if version is None:
                raise OutboxProjectionError(EVENT_TYPE, "vector.rebuild_canonical_version_invalid")
            if current.status == LifecycleStatus.ACTIVE and _can_embed(current.classification):
                reproject = True
            else:
                result = await self._container.vector_index.delete_chunks_before_version(
                    (chunk_id,), canonical_version=version
                )
                _raise_if_degraded(result.status, "vector.rebuild_delete", result.diagnostics)
                reproject = False
        async with self._container.uow_factory() as uow:
            after = await uow.chunks.get_by_id(chunk_id)
        if after is not None:
            _require_scope(after, page)
            if after.status == LifecycleStatus.ACTIVE and _can_embed(after.classification):
                reproject = True
            elif _chunk_canonical_version(after) != version:
                raise OutboxProjectionError(
                    EVENT_TYPE,
                    "vector.rebuild_canonical_generation_changed",
                )
        if reproject:
            await self._projection.handle_vector_upsert(
                _synthetic_upsert(job_id=0, chunk_id=chunk_id)
            )

    async def _complete_dead_rebuild_events(self, page: _RebuildPage) -> None:
        now = self._container.clock.now()
        async with AsyncSession(self._container.engine) as session:
            await session.execute(
                update(MemoryOutboxRow)
                .where(
                    MemoryOutboxRow.status == "dead",
                    MemoryOutboxRow.event_type.in_(("vector.delete_chunks", EVENT_TYPE)),
                    MemoryOutboxRow.last_safe_diagnostic_code.in_(_DEAD_REBUILD_CODES),
                    MemoryOutboxRow.payload_json["space_id"].as_string() == page.space_id,
                    MemoryOutboxRow.payload_json["memory_scope_id"].as_string()
                    == page.memory_scope_id,
                )
                .values(
                    status="done",
                    last_safe_error=None,
                    last_safe_diagnostic_code="vector.rebuild_recovered",
                    updated_at=now,
                )
            )
            await session.commit()


def _require_scope(chunk, page: _RebuildPage) -> None:
    if str(chunk.space_id) != page.space_id or str(chunk.memory_scope_id) != page.memory_scope_id:
        raise OutboxProjectionError(EVENT_TYPE, "vector.rebuild_scope_changed")


def _synthetic_upsert(*, job_id: int, chunk_id: str) -> ClaimedOutboxJob:
    return ClaimedOutboxJob(
        id=job_id,
        event_type="vector.upsert_chunk",
        aggregate_type="chunk",
        aggregate_id=chunk_id,
        aggregate_version=None,
        attempt_count=0,
        workload_class="projection",
        fairness_key=f"chunk:{chunk_id}",
        payload_json={"chunk_id": chunk_id},
    )


__all__ = ("EVENT_TYPE", "GenericVectorRebuildProcess", "MAX_BATCH_SIZE")
