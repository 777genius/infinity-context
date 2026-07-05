"""Outbox worker for derived adapter side effects."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta

from infinity_context_adapters.postgres import create_schema
from infinity_context_adapters.postgres.models import MemoryOutboxRow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_server.composition import Container, build_container
from infinity_context_server.config import Settings
from infinity_context_server.processes import ClaimedOutboxJob, build_outbox_event_dispatcher
from infinity_context_server.storage_maintenance import run_asset_storage_maintenance

MAX_ATTEMPTS = 5
RUNNING_LEASE_TIMEOUT = timedelta(minutes=5)
RUNNING_HEARTBEAT_INTERVAL = timedelta(seconds=60)

WORKER_ROLE_WORKLOAD_CLASSES: dict[str, tuple[str, ...]] = {
    "all": (),
    "projection": ("projection", "auto_memory"),
    "extraction": ("extraction",),
}


@dataclass(frozen=True)
class OutboxWorkerFilter:
    workload_classes: tuple[str, ...] = ()
    event_types: tuple[str, ...] = ()

    @classmethod
    def from_values(
        cls,
        *,
        workload_classes: Iterable[str] = (),
        event_types: Iterable[str] = (),
    ) -> OutboxWorkerFilter:
        return cls(
            workload_classes=_normalize_filter_values(workload_classes),
            event_types=_normalize_filter_values(event_types),
        )


class OutboxWorker:
    def __init__(
        self,
        container: Container,
        *,
        worker_filter: OutboxWorkerFilter | None = None,
        running_heartbeat_interval: timedelta | None = None,
    ) -> None:
        self._container = container
        self._filter = worker_filter or OutboxWorkerFilter()
        self._running_heartbeat_interval = (
            running_heartbeat_interval or RUNNING_HEARTBEAT_INTERVAL
        )
        self._dispatcher = build_outbox_event_dispatcher(container)

    async def run_once(self, *, limit: int = 25, concurrency: int = 1) -> int:
        normalized_limit = max(0, int(limit))
        if _should_run_suggestion_maintenance(self._filter):
            await self._container.expire_pending_suggestions.execute(limit=normalized_limit)
        if self._should_run_storage_maintenance():
            await run_asset_storage_maintenance(self._container)
        jobs = await self._claim_pending(limit=normalized_limit)
        await self._process_claimed_jobs(jobs, concurrency=concurrency)
        return len(jobs)

    def _should_run_storage_maintenance(self) -> bool:
        settings = self._container.settings
        if not settings.asset_storage_maintenance_enabled:
            return False
        if not _should_run_storage_maintenance(self._filter):
            return False
        return self._container.runtime_metrics.storage_maintenance_due(
            now=self._container.clock.now(),
            interval_seconds=settings.asset_storage_maintenance_interval_seconds,
        )

    async def _handle_with_heartbeat(self, job: ClaimedOutboxJob) -> None:
        heartbeat = asyncio.create_task(self._heartbeat_running_job(job.id))
        try:
            await self._handle(job)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    async def _heartbeat_running_job(self, job_id: int) -> None:
        interval = max(0.05, self._running_heartbeat_interval.total_seconds())
        while True:
            await asyncio.sleep(interval)
            async with AsyncSession(self._container.engine) as session:
                row = await session.get(MemoryOutboxRow, job_id)
                if row is None or row.status != "running":
                    return
                row.updated_at = self._container.clock.now()
                await session.commit()

    async def _process_claimed_jobs(
        self,
        jobs: list[ClaimedOutboxJob],
        *,
        concurrency: int,
    ) -> None:
        max_concurrency = _bounded_worker_concurrency(concurrency, job_count=len(jobs))
        if max_concurrency <= 0:
            return
        if max_concurrency == 1:
            for job in jobs:
                await self._process_claimed_job(job)
            return
        semaphore = asyncio.Semaphore(max_concurrency)

        async def process(job: ClaimedOutboxJob) -> None:
            async with semaphore:
                await self._process_claimed_job(job)

        await asyncio.gather(*(process(job) for job in jobs))

    async def _process_claimed_job(self, job: ClaimedOutboxJob) -> None:
        try:
            await self._handle_with_heartbeat(job)
        except Exception as exc:
            await self._mark_retry_or_dead(job.id, exc)
        else:
            await self._mark_done(job.id)

    async def _claim_pending(self, *, limit: int) -> list[ClaimedOutboxJob]:
        now = self._container.clock.now()
        async with AsyncSession(self._container.engine) as session:
            await self._recover_expired_running_jobs(session, now=now, limit=limit)
            query = (
                select(MemoryOutboxRow)
                .where(
                    MemoryOutboxRow.status.in_(("pending", "retry_pending")),
                    MemoryOutboxRow.next_attempt_at <= now,
                )
                .order_by(MemoryOutboxRow.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            query = _apply_worker_filter(query, self._filter)
            rows = list((await session.execute(query)).scalars())
            claimed = [
                ClaimedOutboxJob(
                    id=row.id,
                    event_type=row.event_type,
                    aggregate_id=row.aggregate_id,
                    aggregate_version=row.aggregate_version,
                    attempt_count=row.attempt_count,
                    workload_class=row.workload_class,
                    fairness_key=row.fairness_key,
                    payload_json=dict(row.payload_json),
                )
                for row in rows
            ]
            for row in rows:
                row.status = "running"
                row.updated_at = now
            await session.commit()
            return claimed

    async def _recover_expired_running_jobs(
        self,
        session: AsyncSession,
        *,
        now,
        limit: int,
    ) -> None:
        lease_cutoff = now - RUNNING_LEASE_TIMEOUT
        query = (
            select(MemoryOutboxRow)
            .where(
                MemoryOutboxRow.status == "running",
                MemoryOutboxRow.updated_at <= lease_cutoff,
            )
            .order_by(MemoryOutboxRow.updated_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        query = _apply_worker_filter(query, self._filter)
        rows = list((await session.execute(query)).scalars())
        for row in rows:
            row.attempt_count += 1
            row.last_safe_error = "Worker lease expired"
            row.last_safe_diagnostic_code = "worker.lease_expired"
            row.updated_at = now
            if row.attempt_count >= MAX_ATTEMPTS:
                row.status = "dead"
            else:
                row.status = "retry_pending"
                row.next_attempt_at = now

    async def _handle(self, job: ClaimedOutboxJob) -> None:
        await self._dispatcher.handle(job)

    async def _mark_done(self, job_id: int) -> None:
        now = self._container.clock.now()
        async with AsyncSession(self._container.engine) as session:
            row = await session.get(MemoryOutboxRow, job_id)
            if row:
                row.status = "done"
                row.last_safe_error = None
                row.last_safe_diagnostic_code = None
                row.updated_at = now
            await session.commit()

    async def _mark_retry_or_dead(self, job_id: int, exc: Exception) -> None:
        now = self._container.clock.now()
        async with AsyncSession(self._container.engine) as session:
            row = await session.get(MemoryOutboxRow, job_id)
            if row:
                row.last_safe_error = _safe_error(exc)[:400]
                diagnostic_code = _safe_diagnostic_code(exc)[:120]
                row.last_safe_diagnostic_code = diagnostic_code
                row.updated_at = now
                retry_after_at = _retry_after_from_exception(exc)
                if diagnostic_code in {
                    "asset_extraction.lease_active",
                    "asset_extraction.retry_not_ready",
                }:
                    row.status = "retry_pending"
                    row.next_attempt_at = retry_after_at or now + timedelta(seconds=30)
                else:
                    row.attempt_count += 1
                    if row.attempt_count >= MAX_ATTEMPTS:
                        row.status = "dead"
                    else:
                        row.status = "retry_pending"
                        row.next_attempt_at = now + timedelta(seconds=2**row.attempt_count)
            await session.commit()


def _safe_error(exc: Exception) -> str:
    return _diagnostic_exception(exc).__class__.__name__[:400]


def _safe_diagnostic_code(exc: Exception) -> str:
    code_source = _diagnostic_exception(exc)
    code = getattr(code_source, "diagnostic_code", None)
    if isinstance(code, str) and code.strip():
        return code
    return exc.__class__.__name__


def _diagnostic_exception(exc: Exception) -> BaseException:
    current: BaseException = exc
    seen: set[int] = set()
    while id(current) not in seen:
        seen.add(id(current))
        code = getattr(current, "diagnostic_code", None)
        if isinstance(code, str) and code.strip():
            return current
        next_exc = current.__cause__ or current.__context__
        if next_exc is None:
            return current
        current = next_exc
    return exc


def _retry_after_from_exception(exc: Exception) -> datetime | None:
    value = getattr(exc, "retry_after_at", None)
    return value if isinstance(value, datetime) else None


def _bounded_worker_concurrency(value: int, *, job_count: int) -> int:
    if job_count <= 0:
        return 0
    try:
        requested = int(value)
    except (TypeError, ValueError):
        requested = 1
    return min(max(1, requested), job_count)


def _normalize_filter_values(values: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(value.strip() for value in values if value.strip()))
    return normalized


def _apply_worker_filter(query, worker_filter: OutboxWorkerFilter):
    if worker_filter.workload_classes:
        query = query.where(MemoryOutboxRow.workload_class.in_(worker_filter.workload_classes))
    if worker_filter.event_types:
        query = query.where(MemoryOutboxRow.event_type.in_(worker_filter.event_types))
    return query


def _should_run_suggestion_maintenance(worker_filter: OutboxWorkerFilter) -> bool:
    if worker_filter.event_types:
        return False
    if not worker_filter.workload_classes:
        return True
    return any(value in {"projection", "auto_memory"} for value in worker_filter.workload_classes)


def _should_run_storage_maintenance(worker_filter: OutboxWorkerFilter) -> bool:
    if worker_filter.event_types:
        return False
    if not worker_filter.workload_classes:
        return True
    return "extraction" in worker_filter.workload_classes


def _worker_filter_from_args(args: argparse.Namespace) -> OutboxWorkerFilter:
    workload_classes = tuple(args.workload_class or ())
    if not workload_classes:
        workload_classes = WORKER_ROLE_WORKLOAD_CLASSES[args.role]
    return OutboxWorkerFilter.from_values(
        workload_classes=workload_classes,
        event_types=tuple(args.event_type or ()),
    )


async def _run(args: argparse.Namespace) -> None:
    container = build_container(Settings())
    if container.settings.auto_create_schema:
        await create_schema(container.engine)
    worker = OutboxWorker(container, worker_filter=_worker_filter_from_args(args))
    try:
        while True:
            count = await worker.run_once(limit=args.limit, concurrency=args.concurrency)
            print({"processed": count})
            if args.once:
                return
            await asyncio.sleep(args.sleep_seconds)
    finally:
        await container.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Infinity Context outbox worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help=(
            "Maximum claimed outbox jobs handled concurrently in this process. "
            "Defaults to 1 for conservative parser/provider resource isolation."
        ),
    )
    parser.add_argument("--sleep-seconds", type=float, default=2.0)
    parser.add_argument(
        "--role",
        choices=tuple(WORKER_ROLE_WORKLOAD_CLASSES),
        default="all",
        help=(
            "Worker contract preset. 'projection' excludes extraction jobs; "
            "'extraction' processes only asset extraction jobs; 'all' keeps legacy behavior."
        ),
    )
    parser.add_argument(
        "--workload-class",
        action="append",
        help="Restrict this worker to one workload class. Can be passed more than once.",
    )
    parser.add_argument(
        "--event-type",
        action="append",
        help="Restrict this worker to one outbox event type. Can be passed more than once.",
    )
    args = parser.parse_args()
    if not args.once and not args.loop:
        args.once = True
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
