import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from infinity_context_core.application.dto_benchmark_runs import (
    CleanupBenchmarkRunCommand,
    RegisterBenchmarkRunCommand,
)
from infinity_context_core.application.use_cases.benchmark_runs import (
    CleanupBenchmarkRunUseCase,
    RegisterBenchmarkRunUseCase,
)
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.ports.benchmark_runs import (
    BenchmarkCleanupCounts,
    BenchmarkCleanupReceipt,
    BenchmarkRunRegistryRecord,
)

RUN = "a" * 64
BINDING = "b" * 64
TARGET = "c" * 64
REGISTER_KEY = "d" * 64
CLEANUP_KEY = "e" * 64
SLUG = "memory-comparison-managed-run"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_registration_is_idempotent_and_rejects_fingerprint_mismatch() -> None:
    repository = FakeBenchmarkRunRepository()
    factory = FakeUnitOfWorkFactory(repository)
    use_case = RegisterBenchmarkRunUseCase(uow_factory=factory, clock=FakeClock())

    first = asyncio.run(use_case.execute(_registration()))
    replay = asyncio.run(use_case.execute(_registration()))

    assert first.created is True
    assert replay.created is False
    assert replay.record == first.record
    assert repository.add_calls == 1
    assert replay.record.run_id_sha256 == RUN

    with pytest.raises(MemoryConflictError, match="fingerprint conflicted"):
        asyncio.run(use_case.execute(replace(_registration(), idempotency_key_sha256="1" * 64)))

    with pytest.raises(MemoryConflictError, match="fingerprint conflicted"):
        asyncio.run(use_case.execute(replace(_registration(), run_id_sha256="f" * 64)))

    with pytest.raises(MemoryConflictError, match="fingerprint conflicted"):
        asyncio.run(
            use_case.execute(replace(_registration(), infinity_target_identity_sha256="f" * 64))
        )


def test_cleanup_locks_once_and_replays_stored_pending_receipt() -> None:
    repository = FakeBenchmarkRunRepository()
    factory = FakeUnitOfWorkFactory(repository)
    register = RegisterBenchmarkRunUseCase(uow_factory=factory, clock=FakeClock())
    cleanup = CleanupBenchmarkRunUseCase(uow_factory=factory, clock=FakeClock())
    registered = asyncio.run(register.execute(_registration())).record
    command = CleanupBenchmarkRunCommand(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=TARGET,
        space_id=registered.space_id,
        space_slug=SLUG,
        idempotency_key_sha256=CLEANUP_KEY,
    )

    first = asyncio.run(cleanup.execute(command))
    replay = asyncio.run(cleanup.execute(command))

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.receipt == first.receipt
    assert first.receipt.projection_cleanup == "pending"
    assert repository.cleanup_calls == 1
    assert repository.for_update_calls == 2

    with pytest.raises(MemoryConflictError, match="binding conflicted"):
        asyncio.run(cleanup.execute(replace(command, space_slug=f"{SLUG}-wrong")))


def _registration() -> RegisterBenchmarkRunCommand:
    return RegisterBenchmarkRunCommand(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=TARGET,
        space_slug=SLUG,
        idempotency_key_sha256=REGISTER_KEY,
    )


class FakeClock:
    def now(self) -> datetime:
        return NOW


class FakeBenchmarkRunRepository:
    def __init__(self) -> None:
        self.record: BenchmarkRunRegistryRecord | None = None
        self.add_calls = 0
        self.cleanup_calls = 0
        self.for_update_calls = 0

    async def get_by_run_id_sha256(
        self, run_id_sha256: str, *, for_update: bool = False
    ) -> BenchmarkRunRegistryRecord | None:
        if for_update:
            self.for_update_calls += 1
        return self.record if self.record and self.record.run_id_sha256 == run_id_sha256 else None

    async def get_by_idempotency_key_sha256(
        self, idempotency_key_sha256: str
    ) -> BenchmarkRunRegistryRecord | None:
        if self.record and self.record.idempotency_key_sha256 == idempotency_key_sha256:
            return self.record
        return None

    async def add(self, record: BenchmarkRunRegistryRecord) -> None:
        self.add_calls += 1
        self.record = record

    async def begin_cleanup(
        self,
        record: BenchmarkRunRegistryRecord,
        *,
        cleanup_fingerprint_sha256: str,
        now: datetime,
    ) -> BenchmarkRunRegistryRecord:
        self.cleanup_calls += 1
        receipt = BenchmarkCleanupReceipt(
            run_id_sha256=record.run_id_sha256,
            space_id=record.space_id,
            space_slug=record.space_slug,
            disposition="cleanup_pending",
            projection_cleanup="pending",
            counts=BenchmarkCleanupCounts(0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
            vector_delete_outbox_ids=(),
            graph_delete_outbox_ids=(),
            cognee_delete_outbox_ids=(),
            receipt_sha256="f" * 64,
        )
        self.record = replace(
            record,
            state="cleanup_pending",
            cleanup_fingerprint_sha256=cleanup_fingerprint_sha256,
            cleanup_receipt=receipt,
            updated_at=now,
        )
        return self.record


class FakeUnitOfWork:
    def __init__(self, repository: FakeBenchmarkRunRepository) -> None:
        self.benchmark_runs = repository
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


class FakeUnitOfWorkFactory:
    def __init__(self, repository: FakeBenchmarkRunRepository) -> None:
        self.repository = repository

    def __call__(self) -> FakeUnitOfWork:
        return FakeUnitOfWork(self.repository)
