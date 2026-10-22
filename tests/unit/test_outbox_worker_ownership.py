from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from infinity_context_adapters.postgres.models import MemoryOutboxRow
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from tests.outbox_claim_test_support import (
    ClaimClock,
    assert_reclaimed_owner_is_fenced,
    assert_reschedule_aba_is_fenced,
    claim_snapshot,
    ownership_worker,
    seed_claim_job,
)


def test_outbox_reclaimed_and_rescheduled_claims_are_fenced(tmp_path: Path) -> None:
    async def run() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ownership.db'}")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(MemoryOutboxRow.__table__.create)
            await assert_reclaimed_owner_is_fenced(engine)
            await assert_reschedule_aba_is_fenced(engine)
        finally:
            await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("interrupt", ("reclaim", "cancel", "heartbeat_error"))
def test_running_handler_is_joined_after_interruption(tmp_path: Path, interrupt: str) -> None:
    async def run() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'interrupt.db'}")
        clock = ClaimClock()
        worker = ownership_worker(engine, clock)
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def handler(_job) -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        async def broken_heartbeat(_job) -> None:
            await started.wait()
            raise RuntimeError("provider details must not enter diagnostics")

        worker._dispatcher = SimpleNamespace(handle=handler)
        if interrupt == "heartbeat_error":
            worker._heartbeat_running_job = broken_heartbeat
        try:
            async with engine.begin() as connection:
                await connection.run_sync(MemoryOutboxRow.__table__.create)
            job_id = await seed_claim_job(engine, clock, interrupt)
            job = (await worker._claim_pending(limit=1))[0]
            process = asyncio.create_task(worker._process_claimed_job(job))
            await asyncio.wait_for(started.wait(), timeout=2)
            if interrupt == "reclaim":
                clock.advance(timedelta(minutes=6))
                other = ownership_worker(engine, clock)
                current = (await other._claim_pending(limit=1))[0]
                expected = await claim_snapshot(engine, job_id)
                await asyncio.wait_for(process, timeout=2)
                assert await claim_snapshot(engine, job_id) == expected
                # Even a queued stale job must not invoke its handler.
                started.clear()
                await worker._process_claimed_job(job)
                assert not started.is_set()
                assert await other._mark_done(current)
            elif interrupt == "cancel":
                expected = await claim_snapshot(engine, job_id)
                process.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await process
                assert await claim_snapshot(engine, job_id) == expected
            else:
                await asyncio.wait_for(process, timeout=2)
                result = await claim_snapshot(engine, job_id)
                assert result["status"] == "retry_pending"
                assert result["attempt_count"] == 1 and result["claim_token"] is None
                assert result["last_safe_error"] == "RuntimeError"
            assert cancelled.is_set()
            assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_terminal_and_missing_outbox_rows_reject_lifecycle_writes(tmp_path: Path) -> None:
    async def run() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'terminal.db'}")
        clock = ClaimClock()
        worker = ownership_worker(engine, clock)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(MemoryOutboxRow.__table__.create)
            job_id = await seed_claim_job(engine, clock, "terminal")
            job = (await worker._claim_pending(limit=1))[0]
            async with AsyncSession(engine) as session:
                row = await session.get(MemoryOutboxRow, job_id)
                row.attempt_count = 4
                await session.commit()
            assert await worker._mark_retry_or_dead(job, ValueError())
            dead = await claim_snapshot(engine, job_id)
            assert dead["status"] == "dead" and dead["attempt_count"] == 5
            assert dead["claim_token"] is None
            assert not await worker._mark_done(job)
            assert await claim_snapshot(engine, job_id) == dead
            async with AsyncSession(engine) as session:
                row = await session.get(MemoryOutboxRow, job_id)
                await session.delete(row)
                await session.commit()
            assert not await worker._mark_done(job)
            assert not await worker._mark_retry_or_dead(job, ValueError())
            assert not await worker._refresh_running_job(job)
        finally:
            await engine.dispose()

    asyncio.run(run())
