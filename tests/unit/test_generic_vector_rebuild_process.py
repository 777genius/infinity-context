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


def _job(*, cursor: str | None = None, batch_size: int = 2) -> ClaimedOutboxJob:
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
            "upper_bound_id": "chunk-z",
            "cursor": cursor,
            "batch_size": batch_size,
        },
    )


def test_rebuild_page_persists_bounded_cursor_only_after_every_row_succeeds() -> None:
    async def run() -> None:
        outbox = _Outbox()
        process = GenericVectorRebuildProcess(
            SimpleNamespace(uow_factory=lambda: _Uow(outbox))
        )
        processed: list[str] = []

        async def load(_page):
            return [SimpleNamespace(id="chunk-a"), SimpleNamespace(id="chunk-b")]

        async def reconcile(_page, chunk_id: str) -> None:
            processed.append(chunk_id)

        process._load_page = load  # type: ignore[method-assign]
        process._reconcile_chunk = reconcile  # type: ignore[method-assign]
        await process.handle_page(_job())

        assert processed == ["chunk-a", "chunk-b"]
        assert len(outbox.events) == 1
        assert outbox.events[0].payload["cursor"] == "chunk-b"
        assert outbox.events[0].payload["batch_size"] == 2

    asyncio.run(run())


def test_rebuild_crash_before_cursor_commit_replays_same_page_without_advancing() -> None:
    async def run() -> None:
        outbox = _Outbox()
        process = GenericVectorRebuildProcess(
            SimpleNamespace(uow_factory=lambda: _Uow(outbox))
        )
        calls: list[str] = []
        fail_once = True

        async def load(_page):
            return [SimpleNamespace(id="chunk-a"), SimpleNamespace(id="chunk-b")]

        async def reconcile(_page, chunk_id: str) -> None:
            nonlocal fail_once
            calls.append(chunk_id)
            if chunk_id == "chunk-b" and fail_once:
                fail_once = False
                raise RuntimeError("crash after an idempotent provider effect")

        process._load_page = load  # type: ignore[method-assign]
        process._reconcile_chunk = reconcile  # type: ignore[method-assign]
        with pytest.raises(RuntimeError, match="provider effect"):
            await process.handle_page(_job())
        assert outbox.events == []

        await process.handle_page(_job())
        assert calls == ["chunk-a", "chunk-b", "chunk-a", "chunk-b"]
        assert outbox.events[0].payload["cursor"] == "chunk-b"

    asyncio.run(run())


def test_final_short_page_completes_dead_recovery_without_successor() -> None:
    async def run() -> None:
        outbox = _Outbox()
        process = GenericVectorRebuildProcess(
            SimpleNamespace(uow_factory=lambda: _Uow(outbox))
        )
        completed: list[str] = []

        async def load(_page):
            return [SimpleNamespace(id="chunk-z")]

        async def reconcile(_page, _chunk_id: str) -> None:
            return None

        async def complete(page) -> None:
            completed.append(page.operation_id)

        process._load_page = load  # type: ignore[method-assign]
        process._reconcile_chunk = reconcile  # type: ignore[method-assign]
        process._complete_dead_rebuild_events = complete  # type: ignore[method-assign]
        await process.handle_page(_job(cursor="chunk-y", batch_size=2))

        assert outbox.events == []
        assert completed == ["rebuild-operation"]

    asyncio.run(run())
