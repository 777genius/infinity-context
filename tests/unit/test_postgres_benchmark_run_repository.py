import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from infinity_context_adapters.noop import SystemClock
from infinity_context_adapters.postgres.benchmark_run_repositories import (
    _json_sha256,
    _receipt_from_json,
    _registry_query,
)
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryComparisonBenchmarkRunRow,
    MemoryDocumentRow,
    MemoryEpisodeRow,
    MemoryFactRow,
    MemoryOutboxRow,
    MemoryScopeRow,
    MemorySpaceRow,
    MemoryThreadRow,
)
from infinity_context_adapters.postgres.unit_of_work import (
    PostgresUnitOfWorkFactory,
    build_async_engine,
    build_session_factory,
    create_schema,
)
from infinity_context_core.application.dto_benchmark_runs import (
    CleanupBenchmarkRunCommand,
    RegisterBenchmarkRunCommand,
)
from infinity_context_core.application.use_cases.benchmark_runs import (
    CleanupBenchmarkRunUseCase,
    RegisterBenchmarkRunUseCase,
)
from infinity_context_core.domain.errors import MemoryConflictError
from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.schema import CreateTable

RUN = "a" * 64
BINDING = "b" * 64
TARGET = "c" * 64
SLUG = "memory-comparison-managed-run"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_cleanup_query_uses_postgres_row_lock() -> None:
    sql = str(_registry_query(RUN, for_update=True).compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql


def test_registry_model_enforces_current_state_coupling() -> None:
    ddl = str(
        CreateTable(MemoryComparisonBenchmarkRunRow.__table__).compile(dialect=postgresql.dialect())
    )
    assert "cleaned" not in ddl
    assert "state = 'active' AND cleanup_fingerprint_sha256 IS NULL" in ddl
    assert "state = 'cleanup_pending' AND cleanup_fingerprint_sha256 IS NOT NULL" in ddl


def test_receipt_rejects_duplicate_ids_within_one_lane() -> None:
    value = _receipt_value(vector_ids=[1, 1], graph_ids=[2], cognee_ids=[3])
    with pytest.raises(RuntimeError, match="benchmark_cleanup_receipt_invalid"):
        _receipt_from_json(value)


def test_receipt_rejects_duplicate_ids_across_lanes() -> None:
    value = _receipt_value(vector_ids=[1], graph_ids=[1], cognee_ids=[3])
    with pytest.raises(RuntimeError, match="benchmark_cleanup_receipt_invalid"):
        _receipt_from_json(value)


def test_sqlite_contract_for_atomic_registration_cleanup_and_replay(tmp_path: Path) -> None:
    asyncio.run(_sqlite_contract(tmp_path))


async def _sqlite_contract(tmp_path: Path) -> None:
    database_path = tmp_path / "benchmark.db"
    engine = build_async_engine(f"sqlite+aiosqlite:///{database_path}")
    await create_schema(engine)
    factory = PostgresUnitOfWorkFactory(
        session_factory=build_session_factory(engine),
        clock=SystemClock(),
    )
    register = RegisterBenchmarkRunUseCase(uow_factory=factory, clock=FixedClock())
    cleanup = CleanupBenchmarkRunUseCase(uow_factory=factory, clock=FixedClock())
    try:
        registered = await register.execute(_registration())
        assert registered.created is True
        replay = await register.execute(_registration())
        assert replay.created is False
        assert replay.record.space_id == registered.record.space_id

        async with AsyncSession(engine) as session:
            session.add(
                MemorySpaceRow(
                    id="preexisting-space",
                    slug="memory-comparison-preexisting",
                    name="preexisting",
                    status="active",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await session.commit()

        conflicting_run = RegisterBenchmarkRunCommand(
            run_id_sha256="f" * 64,
            binding_commitment_sha256=BINDING,
            infinity_target_identity_sha256=TARGET,
            space_slug="memory-comparison-preexisting",
            idempotency_key_sha256="9" * 64,
        )
        with pytest.raises(MemoryConflictError):
            await register.execute(conflicting_run)
        async with AsyncSession(engine) as session:
            assert (
                await session.get(MemoryComparisonBenchmarkRunRow, conflicting_run.run_id_sha256)
                is None
            )
            assert (
                await session.get(
                    MemorySpaceRow, f"benchmark-space-{conflicting_run.run_id_sha256[:48]}"
                )
                is None
            )
            preexisting = await session.get(MemorySpaceRow, "preexisting-space")
            assert preexisting is not None and preexisting.status == "active"

        await _seed_canonical_rows(engine, registered.record.space_id)
        command = CleanupBenchmarkRunCommand(
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            infinity_target_identity_sha256=TARGET,
            space_id=registered.record.space_id,
            space_slug=SLUG,
            idempotency_key_sha256="e" * 64,
        )
        with pytest.raises(MemoryConflictError, match="binding conflicted"):
            await cleanup.execute(replace(command, infinity_target_identity_sha256="8" * 64))
        first = await cleanup.execute(command)
        assert first.replayed is False
        assert first.receipt.projection_cleanup == "pending"
        assert first.receipt.counts.facts == 1
        assert first.receipt.counts.documents == 1
        assert first.receipt.counts.chunks == 1
        assert first.receipt.counts.episodes == 1
        assert first.receipt.counts.obsolete_upsert_jobs == 3
        assert first.receipt.counts.vector_delete_jobs == 1
        assert first.receipt.counts.graph_delete_jobs == 1
        assert first.receipt.counts.cognee_delete_jobs == 1

        before_replay_jobs = await _outbox_count(engine)
        second = await cleanup.execute(command)
        assert second.replayed is True
        assert second.receipt == first.receipt
        assert await _outbox_count(engine) == before_replay_jobs
        await _assert_deleted_and_queued(engine, registered.record.space_id)
        await _tamper_receipt_and_require_rejection(engine, factory)
    finally:
        await engine.dispose()


async def _seed_canonical_rows(engine, space_id: str) -> None:
    async with AsyncSession(engine) as session:
        session.add_all(
            [
                MemoryScopeRow(
                    id="scope-1",
                    space_id=space_id,
                    external_ref="corpus-1",
                    name="corpus-1",
                    status="active",
                    created_at=NOW,
                    updated_at=NOW,
                ),
                MemoryThreadRow(
                    id="thread-1",
                    space_id=space_id,
                    memory_scope_id="scope-1",
                    external_ref="thread-1",
                    status="active",
                    created_at=NOW,
                    updated_at=NOW,
                ),
                MemoryFactRow(
                    id="fact-1",
                    space_id=space_id,
                    memory_scope_id="scope-1",
                    thread_id="thread-1",
                    kind="semantic",
                    text="fact",
                    status="active",
                    confidence="high",
                    trust_level="trusted",
                    classification="internal",
                    category=None,
                    tags_json=[],
                    ttl_policy=None,
                    expires_at=None,
                    version=1,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                MemoryDocumentRow(
                    id="document-1",
                    space_id=space_id,
                    memory_scope_id="scope-1",
                    thread_id="thread-1",
                    title="document",
                    source_type="benchmark",
                    source_external_id="source-1",
                    content_hash="1" * 64,
                    classification="internal",
                    status="active",
                    created_at=NOW,
                    updated_at=NOW,
                ),
                MemoryChunkRow(
                    id="chunk-1",
                    space_id=space_id,
                    memory_scope_id="scope-1",
                    thread_id="thread-1",
                    document_id="document-1",
                    episode_id=None,
                    source_type="benchmark",
                    source_external_id="source-1",
                    source_hash="2" * 64,
                    kind="document",
                    text="chunk",
                    normalized_text="chunk",
                    status="active",
                    sequence=0,
                    char_start=0,
                    char_end=5,
                    token_estimate=1,
                    classification="internal",
                    created_at=NOW,
                    updated_at=NOW,
                    metadata_json={},
                ),
                MemoryEpisodeRow(
                    id="episode-1",
                    space_id=space_id,
                    memory_scope_id="scope-1",
                    thread_id="thread-1",
                    source_type="benchmark",
                    source_external_id="episode-source",
                    text="episode",
                    speaker="user",
                    trust_level="trusted",
                    status="active",
                    occurred_at=NOW,
                    created_at=NOW,
                    metadata_json={},
                ),
                _upsert_job("vector.upsert_chunk", "chunk", "chunk-1"),
                _upsert_job("graph.upsert_fact", "fact", "fact-1"),
                _upsert_job("cognee.ingest_document", "document", "document-1"),
            ]
        )
        await session.commit()


async def _assert_deleted_and_queued(engine, space_id: str) -> None:
    async with AsyncSession(engine) as session:
        assert (
            await session.scalar(select(MemorySpaceRow.status).where(MemorySpaceRow.id == space_id))
            == "deleted"
        )
        for model in (
            MemoryScopeRow,
            MemoryThreadRow,
            MemoryFactRow,
            MemoryDocumentRow,
            MemoryChunkRow,
            MemoryEpisodeRow,
        ):
            statuses = list(
                (
                    await session.execute(select(model.status).where(model.space_id == space_id))
                ).scalars()
            )
            assert statuses == ["deleted"]
        events = list(
            (
                await session.execute(
                    select(MemoryOutboxRow.event_type).order_by(MemoryOutboxRow.id)
                )
            ).scalars()
        )
        assert events == [
            "vector.delete_chunks",
            "graph.delete_fact",
            "cognee.forget_document",
        ]
        registry = await session.get(MemoryComparisonBenchmarkRunRow, RUN)
        assert registry is not None
        assert registry.state == "cleanup_pending"
        assert registry.cleanup_receipt_json["projection_cleanup"] == "pending"


async def _outbox_count(engine) -> int:
    async with AsyncSession(engine) as session:
        return int(await session.scalar(select(func.count()).select_from(MemoryOutboxRow)) or 0)


def _registration() -> RegisterBenchmarkRunCommand:
    return RegisterBenchmarkRunCommand(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=TARGET,
        space_slug=SLUG,
        idempotency_key_sha256="d" * 64,
    )


def _upsert_job(event_type: str, aggregate_type: str, aggregate_id: str) -> MemoryOutboxRow:
    return MemoryOutboxRow(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=None,
        workload_class="projection",
        fairness_key=f"{aggregate_type}:{aggregate_id}",
        payload_json={},
        status="pending",
        attempt_count=0,
        next_attempt_at=NOW,
        last_safe_error=None,
        last_safe_diagnostic_code=None,
        created_at=NOW,
        updated_at=NOW,
    )


class FixedClock:
    def now(self) -> datetime:
        return NOW


async def _tamper_receipt_and_require_rejection(engine, factory) -> None:
    async with AsyncSession(engine) as session:
        row = await session.get(MemoryComparisonBenchmarkRunRow, RUN)
        receipt = dict(row.cleanup_receipt_json)
        counts = dict(receipt["counts"])
        counts["facts"] = 999
        receipt["counts"] = counts
        row.cleanup_receipt_json = receipt
        await session.commit()
    async with factory() as uow:
        with pytest.raises(RuntimeError, match="benchmark_cleanup_receipt_invalid"):
            await uow.benchmark_runs.get_by_run_id_sha256(RUN)


def _receipt_value(
    *, vector_ids: list[int], graph_ids: list[int], cognee_ids: list[int]
) -> dict[str, object]:
    value: dict[str, object] = {
        "run_id_sha256": RUN,
        "space_id": "benchmark-space",
        "space_slug": SLUG,
        "disposition": "cleanup_pending",
        "projection_cleanup": "pending",
        "counts": {
            "facts": 0,
            "documents": 0,
            "chunks": 0,
            "episodes": 0,
            "threads": 0,
            "memory_scopes": 0,
            "obsolete_upsert_jobs": 0,
            "vector_delete_jobs": len(vector_ids),
            "graph_delete_jobs": len(graph_ids),
            "cognee_delete_jobs": len(cognee_ids),
        },
        "vector_delete_outbox_ids": vector_ids,
        "graph_delete_outbox_ids": graph_ids,
        "cognee_delete_outbox_ids": cognee_ids,
    }
    value["receipt_sha256"] = _json_sha256(value)
    return value
