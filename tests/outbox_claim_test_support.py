"""Shared behavioral probes for SQLite and real-Postgres worker ownership."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from infinity_context_adapters.postgres.models import MemoryOutboxRow
from infinity_context_adapters.postgres.record_repositories import PostgresOutbox
from infinity_context_core.domain.events import OutboxEvent
from infinity_context_server.worker import OutboxWorker, OutboxWorkerFilter
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


@dataclass
class ClaimClock:
    value: datetime = datetime(2026, 10, 22, tzinfo=UTC)

    def now(self) -> datetime:
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


class DeferredExtractionError(Exception):
    diagnostic_code = "asset_extraction.lease_active"


def ownership_worker(engine: AsyncEngine, clock: ClaimClock) -> OutboxWorker:
    # Lifecycle tests isolate real worker methods from unrelated provider startup.
    worker = object.__new__(OutboxWorker)
    worker._container = SimpleNamespace(engine=engine, clock=clock)
    worker._filter = OutboxWorkerFilter()
    worker._running_heartbeat_interval = timedelta(seconds=0.05)
    return worker


async def seed_claim_job(engine: AsyncEngine, clock: ClaimClock, name: str) -> int:
    async with AsyncSession(engine) as session:
        row = MemoryOutboxRow(
            event_type="test.ownership",
            aggregate_type="test",
            aggregate_id=name,
            payload_json={},
            status="pending",
            workload_class="projection",
            fairness_key=f"test:{name}",
            attempt_count=0,
            next_attempt_at=clock.now(),
            created_at=clock.now(),
            updated_at=clock.now(),
        )
        session.add(row)
        await session.flush()
        job_id = row.id
        await session.commit()
    return job_id


async def claim_snapshot(engine: AsyncEngine, job_id: int) -> dict[str, object]:
    async with AsyncSession(engine) as session:
        row = await session.get(MemoryOutboxRow, job_id)
        assert row is not None
        return {column.name: getattr(row, column.name) for column in row.__table__.columns}


async def assert_reclaimed_owner_is_fenced(engine: AsyncEngine) -> None:
    clock = ClaimClock()
    a, b = ownership_worker(engine, clock), ownership_worker(engine, clock)
    job_id = await seed_claim_job(engine, clock, "reclaimed")
    old = (await a._claim_pending(limit=1))[0]
    assert old.claim_token and len(old.claim_token) == 32
    clock.advance(timedelta(minutes=6))
    current = (await b._claim_pending(limit=1))[0]
    assert current.id == old.id == job_id
    assert current.claim_token != old.claim_token
    assert current.attempt_count == old.attempt_count + 1
    expected = await claim_snapshot(engine, job_id)
    clock.advance(timedelta(seconds=1))
    assert not await a._refresh_running_job(old)
    assert not await a._mark_done(old)
    assert not await a._mark_retry_or_dead(old, ValueError("not logged"))
    assert not await a._mark_retry_or_dead(old, DeferredExtractionError())
    assert await claim_snapshot(engine, job_id) == expected
    no_token = replace(current, claim_token=None)
    assert not await a._refresh_running_job(no_token)
    assert not await a._mark_done(no_token)
    assert not await a._mark_retry_or_dead(no_token, ValueError())
    assert await claim_snapshot(engine, job_id) == expected
    assert await b._refresh_running_job(current)
    assert await b._mark_done(current)
    done = await claim_snapshot(engine, job_id)
    assert done["status"] == "done" and done["claim_token"] is None
    assert not await a._mark_retry_or_dead(old, ValueError())
    assert not await b._mark_retry_or_dead(current, ValueError())
    assert await claim_snapshot(engine, job_id) == done


async def assert_reschedule_aba_is_fenced(engine: AsyncEngine) -> None:
    clock = ClaimClock()
    a, b = ownership_worker(engine, clock), ownership_worker(engine, clock)
    job_id = await seed_claim_job(engine, clock, "aba")
    old = (await a._claim_pending(limit=1))[0]
    clock.advance(timedelta(minutes=6))
    async with AsyncSession(engine) as session:
        await b._recover_expired_running_jobs(session, now=clock.now(), limit=1)
        await session.commit()
    async with AsyncSession(engine) as session:
        await PostgresOutbox(session, clock.now()).enqueue_or_reschedule(
            OutboxEvent("test.ownership", "test", "aba")
        )
        await session.commit()
    current = (await b._claim_pending(limit=1))[0]
    assert current.attempt_count == old.attempt_count == 0
    assert current.claim_token != old.claim_token
    expected = await claim_snapshot(engine, job_id)
    assert not await a._mark_done(old)
    assert not await a._mark_retry_or_dead(old, DeferredExtractionError())
    assert not await a._refresh_running_job(old)
    assert await claim_snapshot(engine, job_id) == expected
    assert await b._mark_retry_or_dead(current, DeferredExtractionError())
    deferred = await claim_snapshot(engine, job_id)
    assert deferred["status"] == "retry_pending"
    assert deferred["attempt_count"] == 0 and deferred["claim_token"] is None
    clock.advance(timedelta(seconds=31))
    following = (await b._claim_pending(limit=1))[0]
    assert following.attempt_count == 0
    assert following.claim_token not in (old.claim_token, current.claim_token)
    assert not await a._mark_done(current)
    assert await b._mark_retry_or_dead(following, ValueError())
    retry = await claim_snapshot(engine, job_id)
    assert retry["status"] == "retry_pending" and retry["attempt_count"] == 1
    assert retry["claim_token"] is None
