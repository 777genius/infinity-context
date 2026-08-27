from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from infinity_context_server.processes.outbox import ClaimedOutboxJob
from infinity_context_server.processes.vector_rebuild import (
    EVENT_TYPE,
    GenericVectorRebuildProcess,
)


class _Outbox:
    def __init__(self) -> None:
        self.events = []

    async def enqueue_or_reschedule(self, event) -> None:
        self.events.append(event)


class _Uow:
    def __init__(self, outbox: _Outbox) -> None:
        self.outbox = outbox
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


def _job(*, batch_size: int = 2) -> ClaimedOutboxJob:
    return ClaimedOutboxJob(
        id=1,
        event_type=EVENT_TYPE,
        aggregate_type="vector_rebuild",
        aggregate_id="rebuild-operation",
        aggregate_version=None,
        attempt_count=0,
        workload_class="projection",
        fairness_key="vector-rebuild:rebuild-operation",
        payload_json={
            "operation_id": "rebuild-operation",
            "space_id": "space",
            "memory_scope_id": "scope",
            "canonical_watermark": 50,
            "dead_event_watermark": 12,
            "batch_size": batch_size,
        },
    )


def _operation(*, status: str = "running") -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        cursor_watermark=0,
        cursor_chunk_id=None,
    )


def _row(chunk_id: str, watermark: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=chunk_id,
        retrieval_commit_watermark=watermark,
        retrieval_version=1,
    )


def test_rebuild_page_persists_bounded_cursor_only_after_every_row_succeeds() -> None:
    async def run() -> None:
        outbox = _Outbox()
        process = GenericVectorRebuildProcess(SimpleNamespace(uow_factory=lambda: _Uow(outbox)))
        processed: list[str] = []

        async def load_operation(_page):
            return _operation()

        async def load(_page, _operation_row):
            return [_row("chunk-a", 10), _row("chunk-b", 20)]

        async def reconcile(_page, row) -> None:
            processed.append(row.id)

        async def record(_page, row) -> None:
            processed.append(f"cursor:{row.retrieval_commit_watermark}:{row.id}")

        process._load_operation = load_operation  # type: ignore[method-assign]
        process._load_page = load  # type: ignore[method-assign]
        process._reconcile_chunk = reconcile  # type: ignore[method-assign]
        process._record_processed = record  # type: ignore[method-assign]
        await process.handle_page(_job())

        assert processed == [
            "chunk-a",
            "cursor:10:chunk-a",
            "chunk-b",
            "cursor:20:chunk-b",
        ]
        assert len(outbox.events) == 1
        assert outbox.events[0].payload["canonical_watermark"] == 50
        assert outbox.events[0].payload["batch_size"] == 2

    asyncio.run(run())


def test_rebuild_crash_before_cursor_commit_replays_same_page_without_advancing() -> None:
    async def run() -> None:
        outbox = _Outbox()
        process = GenericVectorRebuildProcess(SimpleNamespace(uow_factory=lambda: _Uow(outbox)))
        calls: list[str] = []
        fail_once = True

        cursor = 0
        completed = False

        async def load_operation(_page):
            return SimpleNamespace(
                status="running",
                cursor_watermark=cursor,
                cursor_chunk_id="chunk-a" if cursor else None,
            )

        async def load(_page, operation):
            rows = [_row("chunk-a", 10), _row("chunk-b", 20)]
            return [
                row for row in rows if row.retrieval_commit_watermark > operation.cursor_watermark
            ]

        async def reconcile(_page, row) -> None:
            nonlocal fail_once
            calls.append(row.id)
            if row.id == "chunk-b" and fail_once:
                fail_once = False
                raise RuntimeError("crash after an idempotent provider effect")

        async def record(_page, row) -> None:
            nonlocal cursor
            cursor = row.retrieval_commit_watermark

        async def failure(_page) -> None:
            return None

        async def complete(_page) -> None:
            nonlocal completed
            completed = True

        process._load_operation = load_operation  # type: ignore[method-assign]
        process._load_page = load  # type: ignore[method-assign]
        process._reconcile_chunk = reconcile  # type: ignore[method-assign]
        process._record_processed = record  # type: ignore[method-assign]
        process._record_failure = failure  # type: ignore[method-assign]
        process._complete = complete  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="provider effect"):
            await process.handle_page(_job())
        assert outbox.events == []

        await process.handle_page(_job())
        assert calls == ["chunk-a", "chunk-b", "chunk-b"]
        assert completed is True

    asyncio.run(run())


def test_final_short_page_completes_dead_recovery_without_successor() -> None:
    async def run() -> None:
        outbox = _Outbox()
        process = GenericVectorRebuildProcess(SimpleNamespace(uow_factory=lambda: _Uow(outbox)))
        completed: list[str] = []

        async def load_operation(_page):
            return _operation()

        async def load(_page, _operation_row):
            return [_row("chunk-z", 30)]

        async def reconcile(_page, _row) -> None:
            return None

        async def record(_page, _row) -> None:
            return None

        async def complete(page) -> None:
            completed.append(page.operation_id)

        process._load_operation = load_operation  # type: ignore[method-assign]
        process._load_page = load  # type: ignore[method-assign]
        process._reconcile_chunk = reconcile  # type: ignore[method-assign]
        process._record_processed = record  # type: ignore[method-assign]
        process._complete = complete  # type: ignore[method-assign]
        await process.handle_page(_job(batch_size=2))

        assert outbox.events == []
        assert completed == ["rebuild-operation"]

    asyncio.run(run())
