from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from types import SimpleNamespace

from infinity_context_server.worker import OutboxWorker, OutboxWorkerFilter


def test_fresh_zero_job_projection_worker_registers_before_reconcile_and_retires(
    monkeypatch,
) -> None:
    events: list[str] = []

    class Locator:
        async def start_runtime(self, *, now):
            del now
            events.append("start")

        async def reconcile_active(self, *, now):
            del now
            events.append("reconcile")

        async def close_runtime(self, *, now):
            del now
            events.append("close")

    monkeypatch.setattr(
        "infinity_context_server.worker.build_outbox_event_dispatcher",
        lambda _container: SimpleNamespace(handle=None),
    )
    container = SimpleNamespace(
        retrieval_runtime=Locator(),
        clock=SimpleNamespace(now=lambda: datetime(2026, 8, 26, tzinfo=UTC)),
        settings=SimpleNamespace(asset_storage_maintenance_enabled=False),
    )
    worker = OutboxWorker(
        container,
        worker_filter=OutboxWorkerFilter.from_values(
            event_types=("vector.upsert_locator_profile",)
        ),
    )

    async def no_jobs(*, limit):
        del limit
        return []

    worker._claim_pending = no_jobs  # type: ignore[method-assign]

    async def scenario() -> None:
        assert await worker.run_once(limit=0) == 0
        await worker.aclose()

    asyncio.run(scenario())
    assert events == ["start", "reconcile", "close"]


def test_cancelled_worker_scope_retires_after_cancelled_work_cleanup(monkeypatch) -> None:
    events: list[str] = []
    work_started = asyncio.Event()
    work_cleaned = asyncio.Event()

    class Locator:
        async def start_runtime(self, *, now):
            del now
            events.append("start")

        async def reconcile_active(self, *, now):
            del now

        async def close_runtime(self, *, now):
            del now
            assert work_cleaned.is_set()
            events.append("close")

    monkeypatch.setattr(
        "infinity_context_server.worker.build_outbox_event_dispatcher",
        lambda _container: SimpleNamespace(handle=None),
    )
    worker = OutboxWorker(
        SimpleNamespace(
            retrieval_runtime=Locator(),
            clock=SimpleNamespace(now=lambda: datetime(2026, 8, 26, tzinfo=UTC)),
            settings=SimpleNamespace(asset_storage_maintenance_enabled=False),
        ),
        worker_filter=OutboxWorkerFilter.from_values(
            event_types=("vector.upsert_locator_profile",)
        ),
    )

    async def blocked_claim(*, limit):
        del limit
        work_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            work_cleaned.set()

    worker._claim_pending = blocked_claim  # type: ignore[method-assign]

    async def scenario() -> None:
        task = asyncio.create_task(worker.run_once())
        await work_started.wait()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await worker.aclose()

    asyncio.run(scenario())
    assert events == ["start", "close"]
