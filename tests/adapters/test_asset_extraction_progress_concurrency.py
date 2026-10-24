"""Deterministic real-repository progress races; no timing sleeps or model calls."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from infinity_context_adapters.postgres.asset_repositories import PostgresAssetExtractionRepository
from infinity_context_adapters.postgres.models import MemoryAssetExtractionJobRow
from infinity_context_adapters.postgres.unit_of_work import (
    PostgresUnitOfWorkFactory,
    build_session_factory,
)
from infinity_context_core.application.dto import CancelAssetExtractionCommand
from infinity_context_core.application.use_cases.asset_extraction_lifecycle import save_progress
from infinity_context_core.application.use_cases.asset_extractions import (
    CancelAssetExtractionUseCase,
)
from infinity_context_core.domain.assets import MemoryAssetId
from infinity_context_core.domain.entities import MemoryScopeId, SpaceId
from infinity_context_core.domain.errors import MemoryNotFoundError, MemoryValidationError
from infinity_context_core.domain.extraction import (
    AssetExtractionJob,
    AssetExtractionJobId,
    AssetExtractionStatus,
)
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

NOW = datetime(2026, 6, 18, tzinfo=UTC)


class _Clock:
    def __init__(self, value=NOW + timedelta(seconds=2)):
        self.value = value

    def now(self):
        return self.value


def _job():
    return AssetExtractionJob.create(
        job_id=AssetExtractionJobId("extract_1"),
        asset_id=MemoryAssetId("asset_1"),
        space_id=SpaceId("space_1"),
        memory_scope_id=MemoryScopeId("scope_1"),
        thread_id=None,
        parser_profile="standard_local",
        parser_config_hash="config",
        source_sha256_hex="a" * 64,
        now=NOW,
    ).mark_running(now=NOW, lease_owner="worker_1", lease_expires_at=NOW + timedelta(minutes=15))


def _normalized(job):
    values = asdict(job)
    for key, value in values.items():
        if isinstance(value, datetime):
            values[key] = (
                value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
            )
    return values


@asynccontextmanager
async def _database(tmp_path: Path, backend: str):
    url = f"sqlite+aiosqlite:///{tmp_path / 'progress.db'}"
    schema = None
    if backend == "postgres":
        url = os.environ.get("INFINITY_CONTEXT_TEST_POSTGRES_URL", "")
        if not url:
            pytest.skip("INFINITY_CONTEXT_TEST_POSTGRES_URL is not configured")
        schema = "asset_progress_" + uuid4().hex
    base = create_async_engine(url)
    engine = base
    try:
        if schema:
            async with base.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            engine = base.execution_options(schema_translate_map={None: schema})

        async with engine.begin() as connection:
            await connection.run_sync(MemoryAssetExtractionJobRow.__table__.create)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await PostgresAssetExtractionRepository(session).create(_job())
            await session.commit()
        yield engine
    finally:
        if schema:
            async with base.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await base.dispose()


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
@pytest.mark.parametrize("winner", ["cancellation", "terminal", "replacement"])
def test_lifecycle_progress_cannot_erase_a_committed_transition(
    tmp_path, monkeypatch, backend, winner
):
    asyncio.run(_lifecycle_race(tmp_path, monkeypatch, backend, winner))


async def _lifecycle_race(tmp_path, monkeypatch, backend, winner):
    async with _database(tmp_path, backend) as engine:
        clock = _Clock()
        factory = PostgresUnitOfWorkFactory(
            session_factory=build_session_factory(engine), clock=clock
        )
        snapshot_ready, release = asyncio.Event(), asyncio.Event()
        original_get = PostgresAssetExtractionRepository.get_by_id

        async def paused_get(repository, job_id):
            result = await original_get(repository, job_id)
            if (
                asyncio.current_task().get_name() == "stale-progress"
                and not snapshot_ready.is_set()
            ):
                snapshot_ready.set()
                await release.wait()
            return result

        monkeypatch.setattr(PostgresAssetExtractionRepository, "get_by_id", paused_get)
        task = asyncio.create_task(
            save_progress(
                uow_factory=factory,
                clock=clock,
                execution_lease=timedelta(minutes=15),
                job=_job(),
                stage="extracting_content",
                percent=45,
                message="Extracting",
            ),
            name="stale-progress",
        )
        await asyncio.wait_for(snapshot_ready.wait(), 5)
        if winner == "cancellation":
            result = await CancelAssetExtractionUseCase(uow_factory=factory, clock=clock).execute(
                CancelAssetExtractionCommand(job_id="extract_1")
            )
            expected = result.job
        else:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                repository = PostgresAssetExtractionRepository(session)
                current = await repository.get_by_id("extract_1")
                if winner == "terminal":
                    expected = current.mark_canceled(
                        now=clock.now(), code="canceled", message="gone"
                    )
                else:
                    expected = (
                        current.mark_canceled(
                            now=clock.now(),
                            code="canceled",
                            message="gone",
                        )
                        .reset_for_retry(now=clock.now())
                        .mark_running(
                            now=clock.now(),
                            lease_owner="worker_2",
                            lease_expires_at=clock.now() + timedelta(minutes=20),
                        )
                    )
                await repository.save(expected)
                await session.commit()
        release.set()
        saved = await asyncio.wait_for(task, 5)
        async with AsyncSession(engine) as session:
            persisted = await PostgresAssetExtractionRepository(session).get_by_id("extract_1")
        assert _normalized(saved) == _normalized(expected)
        assert _normalized(persisted) == _normalized(expected)


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_progress_conflict_reload_bypasses_a_strong_identity_map_reference(tmp_path, backend):
    asyncio.run(_cached_conflict(tmp_path, backend))


async def _cached_conflict(tmp_path, backend):
    async with (
        _database(tmp_path, backend) as engine,
        AsyncSession(engine, expire_on_commit=False) as first,
    ):
        held = await first.get(MemoryAssetExtractionJobRow, "extract_1")
        repository = PostgresAssetExtractionRepository(first)
        expected = await repository.get_by_id("extract_1")
        async with AsyncSession(engine, expire_on_commit=False) as second:
            other = PostgresAssetExtractionRepository(second)
            canceled = (await other.get_by_id("extract_1")).request_cancellation(
                now=NOW + timedelta(seconds=1)
            )
            await other.save(canceled)
            await second.commit()
        proposed = expected.record_heartbeat(now=NOW + timedelta(seconds=2))
        actual = await repository.save_running_progress(proposed, expected=expected)
        assert held is await first.get(MemoryAssetExtractionJobRow, "extract_1")
        assert held.cancellation_requested_at is not None
        assert _normalized(actual) == _normalized(canceled)
        await first.commit()


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
@pytest.mark.parametrize("backward_clock", [False, True])
def test_owned_progress_is_monotonic_and_does_not_commit(tmp_path, backend, backward_clock):
    asyncio.run(_positive_progress(tmp_path, backend, backward_clock))


async def _positive_progress(tmp_path, backend, backward_clock):
    async with _database(tmp_path, backend) as engine:
        clock = _Clock(NOW - timedelta(hours=1) if backward_clock else NOW + timedelta(seconds=2))
        factory = PostgresUnitOfWorkFactory(
            session_factory=build_session_factory(engine), clock=clock
        )
        result = await save_progress(
            uow_factory=factory,
            clock=clock,
            execution_lease=timedelta(minutes=1),
            job=_job(),
            stage="extracting_content",
            percent=45,
            message="Extracting",
        )
        expected_time = NOW if backward_clock else clock.now()
        assert _normalized(result)["updated_at"] == expected_time
        assert _normalized(result)["heartbeat_at"] == expected_time
        assert _normalized(result)["lease_expires_at"] == NOW + timedelta(minutes=15)
        assert result.metadata["processing_stage"] == "extracting_content"
        async with AsyncSession(engine, expire_on_commit=False) as session:
            repository = PostgresAssetExtractionRepository(session)
            before = await repository.get_by_id("extract_1")
            await repository.save_running_progress(
                before.record_heartbeat(now=NOW + timedelta(seconds=3)), expected=before
            )
            await session.rollback()
        async with AsyncSession(engine) as session:
            persisted = await PostgresAssetExtractionRepository(session).get_by_id("extract_1")
        assert _normalized(persisted) == _normalized(result)


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
@pytest.mark.parametrize(
    "invalid",
    [
        "id",
        "attempt",
        "lease",
        "started",
        "status",
        "cancel",
        "updated",
        "heartbeat",
        "expiry",
        "expected_status",
        "expected_cancel",
        "heartbeat_none",
        "expiry_none",
    ],
)
def test_invalid_progress_cannot_write(tmp_path, backend, invalid):
    asyncio.run(_invalid_progress(tmp_path, backend, invalid))


async def _invalid_progress(tmp_path, backend, invalid):
    async with (
        _database(tmp_path, backend) as engine,
        AsyncSession(engine, expire_on_commit=False) as session,
    ):
        repository = PostgresAssetExtractionRepository(session)
        expected = await repository.get_by_id("extract_1")
        persisted_before = expected
        proposed = expected.record_heartbeat(now=NOW + timedelta(seconds=2))
        mutations = {
            "id": {"id": AssetExtractionJobId("other")},
            "attempt": {"attempt_count": 2},
            "lease": {"lease_owner": "other"},
            "started": {"started_at": NOW + timedelta(seconds=1)},
            "status": {"status": AssetExtractionStatus.CANCELED},
            "cancel": {"cancellation_requested_at": NOW},
            "updated": {"updated_at": NOW - timedelta(seconds=1)},
            "heartbeat": {"heartbeat_at": NOW - timedelta(seconds=1)},
            "expiry": {"lease_expires_at": NOW - timedelta(seconds=1)},
            "heartbeat_none": {"heartbeat_at": None},
            "expiry_none": {"lease_expires_at": None},
        }
        if invalid == "expected_status":
            expected = replace(expected, status=AssetExtractionStatus.CANCELED)
        elif invalid == "expected_cancel":
            expected = replace(expected, cancellation_requested_at=NOW)
        else:
            proposed = replace(proposed, **mutations[invalid])
        with pytest.raises(MemoryValidationError):
            await repository.save_running_progress(proposed, expected=expected)
        assert _normalized(await repository.get_by_id("extract_1")) == _normalized(persisted_before)


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_missing_progress_job_raises_not_found(tmp_path, backend):
    asyncio.run(_missing_progress(tmp_path, backend))


async def _missing_progress(tmp_path, backend):
    async with _database(tmp_path, backend) as engine, AsyncSession(engine) as session:
        with pytest.raises(MemoryNotFoundError):
            await PostgresAssetExtractionRepository(session).save_running_progress(
                replace(_job(), id=AssetExtractionJobId("missing")),
                expected=replace(_job(), id=AssetExtractionJobId("missing")),
            )


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_generic_lifecycle_reset_semantics_remain_unchanged(tmp_path, backend):
    asyncio.run(_resets(tmp_path, backend))


async def _resets(tmp_path, backend):
    async with (
        _database(tmp_path, backend) as engine,
        AsyncSession(engine, expire_on_commit=False) as session,
    ):
        repository = PostgresAssetExtractionRepository(session)
        current = await repository.get_by_id("extract_1")
        canceled = current.mark_canceled(now=NOW, code="canceled", message="gone")
        await repository.save(canceled)
        retried = canceled.reset_for_retry(now=NOW)
        assert (await repository.save(retried)).cancellation_requested_at is None
        running = retried.mark_running(
            now=NOW, lease_owner="new", lease_expires_at=NOW + timedelta(minutes=15)
        )
        assert (await repository.save(running)).cancellation_requested_at is None
        requested = running.request_cancellation(now=NOW)
        await repository.save(requested)
        succeeded = requested.mark_succeeded(
            now=NOW,
            result_document_ids=("doc",),
            parser_name="test",
            parser_version=None,
            model_version=None,
        )
        assert (await repository.save(succeeded)).cancellation_requested_at is None
        await session.commit()


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_progress_matches_nullable_owner_snapshot_and_equivalent_offset_times(tmp_path, backend):
    asyncio.run(_nullable_and_offset(tmp_path, backend))


async def _nullable_and_offset(tmp_path, backend):
    async with (
        _database(tmp_path, backend) as engine,
        AsyncSession(engine, expire_on_commit=False) as session,
    ):
        repository = PostgresAssetExtractionRepository(session)
        nullable = replace(
            _job(), lease_owner=None, started_at=None, heartbeat_at=None, lease_expires_at=None
        )
        await repository.save(nullable)
        await session.commit()
        proposed = nullable.record_heartbeat(
            now=NOW + timedelta(seconds=1), lease_expires_at=NOW + timedelta(minutes=15)
        )
        result = await repository.save_running_progress(proposed, expected=nullable)
        await session.commit()
        assert result.lease_owner is None and result.started_at is None
        offset = timezone(timedelta(hours=3))
        expected = replace(
            result,
            updated_at=result.updated_at.replace(tzinfo=UTC).astimezone(offset),
            heartbeat_at=result.heartbeat_at.replace(tzinfo=UTC).astimezone(offset),
            lease_expires_at=result.lease_expires_at.replace(tzinfo=UTC).astimezone(offset),
        )
        proposed = expected.record_heartbeat(now=(NOW + timedelta(seconds=2)).astimezone(offset))
        result = await repository.save_running_progress(proposed, expected=expected)
        assert _normalized(result)["updated_at"] == NOW + timedelta(seconds=2)
        await session.commit()


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_progress_statement_writes_only_its_four_owned_columns(tmp_path, backend):
    asyncio.run(_owned_columns(tmp_path, backend))


async def _owned_columns(tmp_path, backend):
    async with _database(tmp_path, backend) as engine:
        assignments = []

        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def observe(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.startswith("UPDATE ") and "memory_asset_extraction_jobs" in statement:
                clause = statement.split(" SET ", 1)[1].split(" WHERE ", 1)[0]
                assignments.append(
                    {part.split("=", 1)[0].strip().strip('"') for part in clause.split(",")}
                )

        async with AsyncSession(engine, expire_on_commit=False) as session:
            repository = PostgresAssetExtractionRepository(session)
            expected = await repository.get_by_id("extract_1")
            await repository.save_running_progress(
                expected.record_heartbeat(now=NOW + timedelta(seconds=1)), expected=expected
            )
            await session.commit()
        assert assignments == [{"metadata_json", "heartbeat_at", "lease_expires_at", "updated_at"}]
