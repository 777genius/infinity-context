from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from types import SimpleNamespace

import pytest
from infinity_context_adapters.postgres import build_async_engine, upgrade_schema
from infinity_context_server import admin_outbox
from infinity_context_server import worker as worker_module
from postgres_test_database import PostgresTestDatabase
from postgres_versioned_schema_fixtures import install_versioned_schema_through
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.outbox_claim_test_support import (
    ClaimClock,
    assert_reclaimed_owner_is_fenced,
    assert_reschedule_aba_is_fenced,
    claim_snapshot,
    ownership_worker,
    seed_claim_job,
)


def test_outbox_ownership_upgrade_and_atomic_races_postgres(monkeypatch) -> None:
    url = os.getenv("INFINITY_CONTEXT_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
    asyncio.run(_assert_ownership(url, monkeypatch))


async def _assert_ownership(url: str, monkeypatch) -> None:
    asyncpg = pytest.importorskip("asyncpg")
    database = PostgresTestDatabase.from_url(url, prefix="outbox_ownership", asyncpg=asyncpg)
    await database.recreate()
    try:
        await install_versioned_schema_through(database, "0060_")
        raw = await database.connect()
        try:
            await raw.execute(
                "INSERT INTO memory_outbox "
                "(event_type,aggregate_type,aggregate_id,payload_json,status,"
                "attempt_count,next_attempt_at,created_at,updated_at) "
                "VALUES ('test.ownership','test','pre-upgrade','{}','running',0,"
                "'2026-10-22T00:00:00Z','2026-10-21T23:54:00Z','2026-10-21T23:54:00Z')"
            )
        finally:
            await raw.close()
        engine = build_async_engine(database.app_url)
        try:
            upgraded = await upgrade_schema(engine)
            assert upgraded.applied == ("0061_outbox_claim_ownership",)
            assert (await upgrade_schema(engine)).applied == ()
            clock = ClaimClock()
            worker = ownership_worker(engine, clock)
            original = await claim_snapshot(engine, 1)
            assert original["claim_token"] is None and original["status"] == "running"
            recovered = (await worker._claim_pending(limit=1))[0]
            assert recovered.attempt_count == 1 and recovered.claim_token
            assert await worker._mark_done(recovered)

            await assert_reclaimed_owner_is_fenced(engine)
            await assert_reschedule_aba_is_fenced(engine)
            # Remove the pending retry from the shared ABA behavior probe.
            async with engine.begin() as connection:
                await connection.execute(
                    text("UPDATE memory_outbox SET status='done' WHERE status='retry_pending'")
                )
            for action in ("heartbeat", "done", "retry"):
                await _assert_reclaim_wins_locked_race(engine, action)
            await _assert_heartbeat_wins_locked_race(engine, monkeypatch)
            await _assert_admin_replay_serializes_with_claim(engine, database.app_url, monkeypatch)
        finally:
            await engine.dispose()
    finally:
        await database.drop()


async def _wait_for_blocked_session(engine) -> None:
    async with asyncio.timeout(3):
        while True:
            async with engine.connect() as connection:
                blocked = await connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname=current_database() AND state='active' "
                        "AND wait_event_type='Lock' AND query LIKE '%memory_outbox%'"
                    )
                )
            if blocked:
                return
            await asyncio.sleep(0.01)


async def _assert_reclaim_wins_locked_race(engine, action: str) -> None:
    clock = ClaimClock()
    a, b = ownership_worker(engine, clock), ownership_worker(engine, clock)
    job_id = await seed_claim_job(engine, clock, f"locked-{action}")
    old = (await a._claim_pending(limit=1))[0]
    clock.advance(timedelta(minutes=6))
    locked, release = asyncio.Event(), asyncio.Event()
    recover = b._recover_expired_running_jobs

    async def held_recovery(session, **kwargs):
        await recover(session, **kwargs)
        await session.flush()
        locked.set()
        await release.wait()

    b._recover_expired_running_jobs = held_recovery
    claiming = asyncio.create_task(b._claim_pending(limit=1))
    stale = None
    try:
        await asyncio.wait_for(locked.wait(), timeout=3)
        operation = {
            "heartbeat": lambda: a._refresh_running_job(old),
            "done": lambda: a._mark_done(old),
            "retry": lambda: a._mark_retry_or_dead(old, ValueError()),
        }[action]
        stale = asyncio.create_task(operation())
        await _wait_for_blocked_session(engine)
        release.set()
        current = (await asyncio.wait_for(claiming, timeout=3))[0]
        expected = await claim_snapshot(engine, job_id)
        assert not await asyncio.wait_for(stale, timeout=3)
        assert current.claim_token != old.claim_token
        assert expected["status"] == "running" and expected["attempt_count"] == 1
        assert await claim_snapshot(engine, job_id) == expected
        assert await b._mark_done(current)
    finally:
        release.set()
        pending = [task for task in (claiming, stale) if task is not None]
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)


async def _assert_heartbeat_wins_locked_race(engine, monkeypatch) -> None:
    clock = ClaimClock()
    a, b = ownership_worker(engine, clock), ownership_worker(engine, clock)
    job_id = await seed_claim_job(engine, clock, "heartbeat-first")
    job = (await a._claim_pending(limit=1))[0]
    clock.advance(timedelta(minutes=6))
    locked, release = asyncio.Event(), asyncio.Event()

    class HeldHeartbeatSession(AsyncSession):
        async def commit(self):
            if not locked.is_set():
                locked.set()
                await release.wait()
            await super().commit()

    with monkeypatch.context() as context:
        context.setattr(worker_module, "AsyncSession", HeldHeartbeatSession)
        heartbeat = asyncio.create_task(a._refresh_running_job(job))
        try:
            await asyncio.wait_for(locked.wait(), timeout=3)
            # Recovery uses SKIP LOCKED; it must not steal a row renewed by A.
            assert await b._claim_pending(limit=1) == []
            release.set()
            assert await asyncio.wait_for(heartbeat, timeout=3)
        finally:
            release.set()
            if not heartbeat.done():
                heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
    assert await b._claim_pending(limit=1) == []
    assert (await claim_snapshot(engine, job_id))["claim_token"] == job.claim_token
    assert await a._mark_done(job)


async def _assert_admin_replay_serializes_with_claim(engine, url, monkeypatch) -> None:
    clock = ClaimClock()
    job_id = await seed_claim_job(engine, clock, "admin-replay")
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE memory_outbox SET status='dead',claim_token=:token WHERE id=:id"),
            {"id": job_id, "token": "f" * 32},
        )
    selected, release = asyncio.Event(), asyncio.Event()

    class HeldReplaySession(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            result = await super().execute(statement, *args, **kwargs)
            if statement.is_select and not selected.is_set():
                selected.set()
                await release.wait()
            return result

    with monkeypatch.context() as context:
        context.setattr(admin_outbox, "AsyncSession", HeldReplaySession)
        context.setattr(
            admin_outbox,
            "build_container",
            lambda _settings: SimpleNamespace(engine=build_async_engine(url), clock=clock),
        )
        first = asyncio.create_task(admin_outbox.replay_outbox(status="dead", limit=1))
        try:
            await asyncio.wait_for(selected.wait(), timeout=3)
            # The other administrator cannot retain an unlocked dead-row snapshot.
            second = await asyncio.wait_for(
                admin_outbox.replay_outbox(status="dead", limit=1), timeout=3
            )
            assert second["replayed"] == 0
            release.set()
            assert (await asyncio.wait_for(first, timeout=3))["replayed"] == 1
        finally:
            release.set()
            if not first.done():
                first.cancel()
            await asyncio.gather(first, return_exceptions=True)
        pending = await claim_snapshot(engine, job_id)
        assert pending["status"] == "pending" and pending["claim_token"] is None
        worker = ownership_worker(engine, clock)
        current = (await worker._claim_pending(limit=1))[0]
        expected = await claim_snapshot(engine, job_id)
        assert (await admin_outbox.replay_outbox(status="dead", limit=1))["replayed"] == 0
        assert await claim_snapshot(engine, job_id) == expected
        assert await worker._mark_done(current)
