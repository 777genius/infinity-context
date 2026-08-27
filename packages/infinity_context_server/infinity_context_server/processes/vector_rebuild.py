"""Durable bounded recovery for the generic Qdrant projection."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
    MemoryOutboxRow,
    MemoryVectorRebuildOperationRow,
)
from infinity_context_core.domain.entities import LifecycleStatus
from infinity_context_core.domain.events import OutboxEvent
from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_server.processes.outbox import ClaimedOutboxJob, OutboxHandlerRegistry
from infinity_context_server.processes.projections import (
    OutboxProjectionError,
    ProjectionOutboxProcess,
    _can_embed,
    _chunk_canonical_version,
    _get_chunk_for_update,
    _raise_if_degraded,
    _require_same_fenced_space,
)

EVENT_TYPE = "vector.rebuild_scope_page"
MAX_BATCH_SIZE = 256
DEAD_REBUILD_CODES = (
    "vector.delete_canonical_versions_rebuild_required",
    "qdrant.delete_rebuild_required",
)


@dataclass(frozen=True, slots=True)
class _RebuildPage:
    operation_id: str
    space_id: str
    memory_scope_id: str
    canonical_watermark: int
    dead_event_watermark: int
    batch_size: int

    @classmethod
    def from_job(cls, job: ClaimedOutboxJob) -> _RebuildPage:
        payload = job.payload_json
        expected = {
            "operation_id",
            "space_id",
            "memory_scope_id",
            "canonical_watermark",
            "dead_event_watermark",
            "batch_size",
        }
        if set(payload) != expected:
            raise OutboxProjectionError(EVENT_TYPE, "vector.rebuild_payload_invalid")
        for key in ("operation_id", "space_id", "memory_scope_id"):
            if not isinstance(payload[key], str) or not payload[key]:
                raise OutboxProjectionError(EVENT_TYPE, "vector.rebuild_payload_invalid")
        for key in ("canonical_watermark", "dead_event_watermark"):
            if type(payload[key]) is not int or payload[key] < 0:
                raise OutboxProjectionError(EVENT_TYPE, "vector.rebuild_payload_invalid")
        batch_size = payload["batch_size"]
        if type(batch_size) is not int or not 1 <= batch_size <= MAX_BATCH_SIZE:
            raise OutboxProjectionError(EVENT_TYPE, "vector.rebuild_payload_invalid")
        return cls(
            operation_id=str(payload["operation_id"]),
            space_id=str(payload["space_id"]),
            memory_scope_id=str(payload["memory_scope_id"]),
            canonical_watermark=int(payload["canonical_watermark"]),
            dead_event_watermark=int(payload["dead_event_watermark"]),
            batch_size=batch_size,
        )

    def next_event(self) -> OutboxEvent:
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
                "canonical_watermark": self.canonical_watermark,
                "dead_event_watermark": self.dead_event_watermark,
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
        operation = await self._load_operation(page)
        if operation.status == "complete":
            return
        rows = await self._load_page(page, operation)
        for row in rows:
            try:
                await self._reconcile_chunk(page, row)
            except Exception:
                await self._record_failure(page)
                raise
            await self._record_processed(page, row)
        if len(rows) == page.batch_size:
            async with self._container.uow_factory() as uow:
                await uow.outbox.enqueue_or_reschedule(page.next_event())
                await uow.commit()
            return
        await self._complete(page)

    async def _load_operation(self, page: _RebuildPage) -> MemoryVectorRebuildOperationRow:
        async with AsyncSession(self._container.engine) as session:
            row = await session.get(MemoryVectorRebuildOperationRow, page.operation_id)
            if row is None or not _operation_matches(row, page):
                raise OutboxProjectionError(EVENT_TYPE, "vector.rebuild_operation_invalid")
            session.expunge(row)
            return row

    async def _load_page(
        self,
        page: _RebuildPage,
        operation: MemoryVectorRebuildOperationRow,
    ) -> list[MemoryChunkRow]:
        cursor = or_(
            MemoryChunkRow.retrieval_commit_watermark > operation.cursor_watermark,
            and_(
                MemoryChunkRow.retrieval_commit_watermark == operation.cursor_watermark,
                MemoryChunkRow.id > (operation.cursor_chunk_id or ""),
            ),
        )
        async with AsyncSession(self._container.engine) as session:
            return list(
                (
                    await session.execute(
                        select(MemoryChunkRow)
                        .where(
                            MemoryChunkRow.space_id == page.space_id,
                            MemoryChunkRow.memory_scope_id == page.memory_scope_id,
                            MemoryChunkRow.retrieval_commit_watermark <= page.canonical_watermark,
                            cursor,
                        )
                        .order_by(
                            MemoryChunkRow.retrieval_commit_watermark,
                            MemoryChunkRow.id,
                        )
                        .limit(page.batch_size)
                    )
                ).scalars()
            )

    async def _reconcile_chunk(self, page: _RebuildPage, row: MemoryChunkRow) -> None:
        expected_version = int(row.retrieval_version)
        if row.status == "active" and _can_embed(row.classification):
            await self._projection.handle_vector_upsert(
                _synthetic_upsert(
                    chunk_id=str(row.id),
                    canonical_version=expected_version,
                )
            )
            return

        async with (
            self._container.projection_fence.hold(str(row.space_id)),
            self._container.uow_factory() as uow,
        ):
            current = await _get_chunk_for_update(uow, str(row.id))
            if current is None:
                return
            _require_scope(current, page)
            _require_same_fenced_space(str(current.space_id), str(row.space_id))
            version = _chunk_canonical_version(current)
            if version != expected_version:
                return
            if current.status == LifecycleStatus.ACTIVE and _can_embed(current.classification):
                return
            result = await self._container.vector_index.delete_chunks_before_version(
                (str(row.id),), canonical_version=version
            )
            _raise_if_degraded(result.status, "vector.rebuild_delete", result.diagnostics)
            await uow.commit()

    async def _record_processed(self, page: _RebuildPage, chunk: MemoryChunkRow) -> None:
        async with AsyncSession(self._container.engine) as session:
            operation = await session.get(
                MemoryVectorRebuildOperationRow,
                page.operation_id,
                with_for_update=True,
            )
            if operation is None or not _operation_matches(operation, page):
                raise OutboxProjectionError(EVENT_TYPE, "vector.rebuild_operation_invalid")
            position = (int(chunk.retrieval_commit_watermark), str(chunk.id))
            current = (operation.cursor_watermark, operation.cursor_chunk_id or "")
            if position > current:
                operation.cursor_watermark, operation.cursor_chunk_id = position
                operation.processed_count += 1
                operation.updated_at = self._container.clock.now()
            await session.commit()

    async def _record_failure(self, page: _RebuildPage) -> None:
        async with AsyncSession(self._container.engine) as session:
            await session.execute(
                update(MemoryVectorRebuildOperationRow)
                .where(MemoryVectorRebuildOperationRow.operation_id == page.operation_id)
                .values(
                    failed_count=MemoryVectorRebuildOperationRow.failed_count + 1,
                    updated_at=self._container.clock.now(),
                )
            )
            await session.commit()

    async def _complete(self, page: _RebuildPage) -> None:
        now = self._container.clock.now()
        async with AsyncSession(self._container.engine) as session:
            operation = await session.get(
                MemoryVectorRebuildOperationRow,
                page.operation_id,
                with_for_update=True,
            )
            if operation is None or not _operation_matches(operation, page):
                raise OutboxProjectionError(EVENT_TYPE, "vector.rebuild_operation_invalid")
            if operation.status == "complete":
                return
            await session.execute(
                update(MemoryOutboxRow)
                .where(
                    MemoryOutboxRow.id <= page.dead_event_watermark,
                    MemoryOutboxRow.status == "dead",
                    MemoryOutboxRow.event_type == "vector.delete_chunks",
                    MemoryOutboxRow.last_safe_diagnostic_code.in_(DEAD_REBUILD_CODES),
                    dead_event_scope_condition(page.space_id, page.memory_scope_id),
                )
                .values(
                    status="done",
                    last_safe_error=None,
                    last_safe_diagnostic_code="vector.rebuild_recovered",
                    updated_at=now,
                )
            )
            operation.status = "complete"
            operation.completed_at = now
            operation.updated_at = now
            await session.commit()


def dead_event_scope_condition(space_id: str, memory_scope_id: str):
    """Resolve both current and legacy document-delete rows from canonical truth."""

    payload_document_id = MemoryOutboxRow.payload_json["document_id"].as_string()
    document_scope = exists(
        select(MemoryDocumentRow.id).where(
            MemoryDocumentRow.id.in_((MemoryOutboxRow.aggregate_id, payload_document_id)),
            MemoryDocumentRow.space_id == space_id,
            MemoryDocumentRow.memory_scope_id == memory_scope_id,
        )
    )
    chunk_scope = exists(
        select(MemoryChunkRow.id).where(
            or_(
                MemoryChunkRow.id == MemoryOutboxRow.aggregate_id,
                MemoryChunkRow.document_id.in_((MemoryOutboxRow.aggregate_id, payload_document_id)),
            ),
            MemoryChunkRow.space_id == space_id,
            MemoryChunkRow.memory_scope_id == memory_scope_id,
        )
    )
    payload_scope = and_(
        MemoryOutboxRow.payload_json["space_id"].as_string() == space_id,
        MemoryOutboxRow.payload_json["memory_scope_id"].as_string() == memory_scope_id,
    )
    return or_(payload_scope, document_scope, chunk_scope)


def _operation_matches(row: MemoryVectorRebuildOperationRow, page: _RebuildPage) -> bool:
    return (
        row.space_id == page.space_id
        and row.memory_scope_id == page.memory_scope_id
        and row.canonical_watermark == page.canonical_watermark
        and row.dead_event_watermark == page.dead_event_watermark
        and row.batch_size == page.batch_size
    )


def _require_scope(chunk, page: _RebuildPage) -> None:
    if str(chunk.space_id) != page.space_id or str(chunk.memory_scope_id) != page.memory_scope_id:
        raise OutboxProjectionError(EVENT_TYPE, "vector.rebuild_scope_changed")


def _synthetic_upsert(*, chunk_id: str, canonical_version: int) -> ClaimedOutboxJob:
    return ClaimedOutboxJob(
        id=0,
        event_type="vector.upsert_chunk",
        aggregate_type="chunk",
        aggregate_id=chunk_id,
        aggregate_version=canonical_version,
        attempt_count=0,
        workload_class="projection",
        fairness_key=f"chunk:{chunk_id}",
        payload_json={"chunk_id": chunk_id},
    )


__all__ = (
    "DEAD_REBUILD_CODES",
    "EVENT_TYPE",
    "GenericVectorRebuildProcess",
    "MAX_BATCH_SIZE",
    "dead_event_scope_condition",
)
