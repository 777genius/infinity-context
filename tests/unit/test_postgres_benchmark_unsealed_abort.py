from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from infinity_context_adapters.noop import SystemClock
from infinity_context_adapters.postgres.benchmark_run_repositories import (
    PostgresBenchmarkRunRepository,
)
from infinity_context_adapters.postgres.models import (
    MemoryComparisonBenchmarkRunRow,
    MemoryOutboxRow,
    MemorySpaceRow,
)
from infinity_context_adapters.postgres.unit_of_work import (
    PostgresUnitOfWorkFactory,
    build_async_engine,
    build_session_factory,
    create_schema,
)
from infinity_context_core.application.dto_benchmark_runs import (
    CleanupBenchmarkRunCommand,
    FinalizeUnsealedBenchmarkAbortCommand,
)
from infinity_context_core.application.use_cases.benchmark_runs import (
    CleanupBenchmarkRunUseCase,
    RegisterBenchmarkRunUseCase,
)
from infinity_context_core.application.use_cases.benchmark_unsealed_abort import (
    FinalizeUnsealedBenchmarkAbortUseCase,
)
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.ports.benchmark_cleanup_plan import (
    COGNEE_NOT_PROJECTED_POLICY_SHA256,
)
from infinity_context_core.ports.benchmark_runs import BenchmarkRunRegistryRecord
from infinity_context_core.ports.benchmark_unsealed_projection import (
    BenchmarkUnsealedProjectionCleanupProof,
    benchmark_unsealed_projection_proof_sha256,
)
from infinity_context_server.benchmark_unsealed_outbox_validation import (
    require_obsolete_upserts_pruned,
)
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from test_postgres_benchmark_run_repository import (
    BINDING,
    RUN,
    SLUG,
    TARGET,
    FixedClock,
    _registration,
    _seed_canonical_rows,
)


class _OrderingSession:
    def __init__(self) -> None:
        self.events: list[tuple[str, type[object] | None]] = []

    def add(self, row: object) -> None:
        self.events.append(("add", type(row)))

    async def flush(self) -> None:
        self.events.append(("flush", None))


class _ProjectionAbsence:
    def __init__(self, engine: object, *, drift: str | None = None) -> None:
        self._engine = engine
        self._drift = drift

    async def prove_absence(
        self, *, record: BenchmarkRunRegistryRecord
    ) -> BenchmarkUnsealedProjectionCleanupProof:
        if self._drift is not None:
            async with AsyncSession(self._engine) as session:
                if self._drift == "outbox":
                    outbox_id = record.cleanup_receipt.vector_delete_outbox_ids[0]
                    await session.execute(
                        update(MemoryOutboxRow)
                        .where(MemoryOutboxRow.id == outbox_id)
                        .values(status="pending")
                    )
                else:
                    await session.execute(
                        update(MemorySpaceRow)
                        .where(MemorySpaceRow.id == record.space_id)
                        .values(status="active")
                    )
                await session.commit()
        proof_sha256 = benchmark_unsealed_projection_proof_sha256(
            run_id_sha256=record.run_id_sha256,
            cleanup_plan_sha256=record.cleanup_plan_sha256,
            cleanup_receipt_sha256=record.cleanup_receipt.receipt_sha256,
            inventory_sha256="1" * 64,
            qdrant_pass_receipt_sha256s=("2" * 64, "3" * 64),
            graphiti_pass_receipt_sha256s=("4" * 64, "5" * 64),
            cognee_policy_sha256=COGNEE_NOT_PROJECTED_POLICY_SHA256,
        )
        return BenchmarkUnsealedProjectionCleanupProof(
            record.run_id_sha256,
            record.cleanup_plan_sha256,
            record.cleanup_receipt.receipt_sha256,
            "1" * 64,
            ("2" * 64, "3" * 64),
            ("4" * 64, "5" * 64),
            "not_projected",
            COGNEE_NOT_PROJECTED_POLICY_SHA256,
            proof_sha256,
        )


def test_add_flushes_space_before_benchmark_registry_foreign_key() -> None:
    session = _OrderingSession()
    now = FixedClock().now()
    record = BenchmarkRunRegistryRecord(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=TARGET,
        space_id=f"benchmark-space-{RUN[:48]}",
        space_slug=SLUG,
        idempotency_key_sha256="d" * 64,
        registration_fingerprint_sha256="e" * 64,
        state="active",
        projection_manifest_json=None,
        projection_manifest_sha256=None,
        projection_cleanup_state="unsealed",
        cleanup_fingerprint_sha256=None,
        cleanup_receipt=None,
        finalization_fingerprint_sha256=None,
        completion_receipt=None,
        completed_at=None,
        created_at=now,
        updated_at=now,
    )

    asyncio.run(
        PostgresBenchmarkRunRepository(session).add(record)  # type: ignore[arg-type]
    )

    assert session.events == [
        ("add", MemorySpaceRow),
        ("flush", None),
        ("add", MemoryComparisonBenchmarkRunRow),
    ]


def test_unsealed_abort_finalizes_exact_tombstones_and_done_outbox(tmp_path: Path) -> None:
    asyncio.run(_unsealed_abort_contract(tmp_path))


@pytest.mark.parametrize("drift", ["outbox", "tombstone"])
def test_unsealed_abort_rechecks_canonical_state_after_external_proof(
    tmp_path: Path, drift: str
) -> None:
    with pytest.raises(MemoryConflictError, match="tombstone|outbox"):
        asyncio.run(_unsealed_abort_contract(tmp_path, drift=drift))


async def _unsealed_abort_contract(tmp_path: Path, *, drift: str | None = None) -> None:
    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'abort.db'}")
    await create_schema(engine)
    factory = PostgresUnitOfWorkFactory(
        session_factory=build_session_factory(engine),
        clock=SystemClock(),
    )
    registered = await RegisterBenchmarkRunUseCase(
        uow_factory=factory,
        clock=FixedClock(),
    ).execute(_registration())
    await _seed_canonical_rows(engine, registered.record.space_id)
    cleanup = await CleanupBenchmarkRunUseCase(
        uow_factory=factory,
        clock=FixedClock(),
    ).execute(
        CleanupBenchmarkRunCommand(
            RUN,
            BINDING,
            TARGET,
            registered.record.space_id,
            SLUG,
            "e" * 64,
            registered.record.cleanup_plan_sha256,
        )
    )
    assert cleanup.projection_cleanup_state == "blocked"
    assert cleanup.receipt.counts.obsolete_upsert_jobs == 2
    assert cleanup.receipt.counts.cognee_delete_jobs == 0
    assert cleanup.receipt.cognee_delete_outbox_ids == ()
    async with AsyncSession(engine) as session:
        remaining_upserts = tuple(
            (
                await session.execute(
                    select(MemoryOutboxRow.id).where(
                        MemoryOutboxRow.event_type.in_(("vector.upsert_chunk", "graph.upsert_fact"))
                    )
                )
            ).scalars()
        )
        pending_record = await PostgresBenchmarkRunRepository(session).get_by_run_id_sha256(RUN)
        await require_obsolete_upserts_pruned(
            session,
            record=pending_record,
            aggregate_ids=("chunk-1", "fact-1"),
        )
    assert remaining_upserts == ()
    outbox_ids = (
        *cleanup.receipt.vector_delete_outbox_ids,
        *cleanup.receipt.graph_delete_outbox_ids,
        *cleanup.receipt.cognee_delete_outbox_ids,
    )
    async with AsyncSession(engine) as session:
        rows = tuple(
            (
                await session.execute(
                    select(MemoryOutboxRow).where(MemoryOutboxRow.id.in_(outbox_ids))
                )
            ).scalars()
        )
        for row in rows:
            row.status = "done"
        await session.commit()
    command = FinalizeUnsealedBenchmarkAbortCommand(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=TARGET,
        space_id=registered.record.space_id,
        space_slug=SLUG,
        expected_cleanup_receipt_sha256=cleanup.receipt.receipt_sha256,
        expected_cleanup_plan_sha256=registered.record.cleanup_plan_sha256,
        idempotency_key_sha256="6" * 64,
    )
    use_case = FinalizeUnsealedBenchmarkAbortUseCase(
        uow_factory=factory,
        clock=FixedClock(),
        projection_absence=_ProjectionAbsence(engine, drift=drift),
    )
    first = await use_case.execute(command)
    replay = await use_case.execute(command)
    assert first.replayed is False and replay.replayed is True
    assert first.receipt.projection_cleanup == "unsealed_abort_complete"
    assert replay.receipt == first.receipt
    async with AsyncSession(engine) as session:
        record = await session.get(MemoryComparisonBenchmarkRunRow, RUN)
        assert record.state == "cleanup_aborted"
        assert record.projection_manifest_json is None
    await engine.dispose()
