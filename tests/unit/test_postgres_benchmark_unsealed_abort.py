from __future__ import annotations

import asyncio
from pathlib import Path

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
from infinity_context_core.ports.benchmark_runs import BenchmarkRunRegistryRecord
from sqlalchemy import select
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


async def _unsealed_abort_contract(tmp_path: Path) -> None:
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
        )
    )
    assert cleanup.projection_cleanup_state == "blocked"
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
        RUN,
        BINDING,
        TARGET,
        registered.record.space_id,
        SLUG,
        cleanup.receipt.receipt_sha256,
        "6" * 64,
    )
    use_case = FinalizeUnsealedBenchmarkAbortUseCase(
        uow_factory=factory,
        clock=FixedClock(),
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
