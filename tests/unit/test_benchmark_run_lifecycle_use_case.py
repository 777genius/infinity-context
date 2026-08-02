from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal

import pytest
from infinity_context_core.application import (
    GetBenchmarkRunLifecycleQuery,
    GetBenchmarkRunLifecycleUseCase,
)
from infinity_context_core.domain.errors import (
    MemoryConflictError,
    MemoryNotFoundError,
    MemoryValidationError,
)
from infinity_context_core.ports.benchmark_runs import (
    BenchmarkCleanupCompletionReceipt,
    BenchmarkCleanupCounts,
    BenchmarkCleanupReceipt,
    BenchmarkRunRegistryRecord,
)

RUN = "a" * 64
SPACE_ID = f"benchmark-space-{RUN[:48]}"
SPACE_SLUG = "memory-comparison-managed-run"
MANIFEST = "b" * 64
INITIATION = "c" * 64
NOW = datetime(2026, 1, 1, 2, 3, 4, 5000, tzinfo=UTC)


@pytest.mark.parametrize(
    "record",
    [
        pytest.param(lambda: _record(), id="active-unsealed"),
        pytest.param(
            lambda: replace(
                _record(),
                projection_manifest_json={"sealed": True},
                projection_manifest_sha256=MANIFEST,
                projection_cleanup_state="sealed",
            ),
            id="active-sealed",
        ),
        pytest.param(
            lambda: replace(
                _record(),
                state="cleanup_pending",
                projection_cleanup_state="blocked",
                cleanup_fingerprint_sha256="d" * 64,
                cleanup_receipt=_initiation_receipt("blocked"),
            ),
            id="cleanup-blocked",
        ),
        pytest.param(
            lambda: replace(
                _record(),
                state="cleanup_pending",
                projection_manifest_json={"sealed": True},
                projection_manifest_sha256=MANIFEST,
                projection_cleanup_state="pending",
                cleanup_fingerprint_sha256="d" * 64,
                cleanup_receipt=_initiation_receipt("pending"),
            ),
            id="cleanup-pending",
        ),
        pytest.param(lambda: _complete_record(), id="cleanup-complete"),
    ],
)
def test_get_lifecycle_accepts_every_authoritative_state(
    record: Callable[[], BenchmarkRunRegistryRecord],
) -> None:
    record = record()
    repository = FakeRepository(record)
    result = asyncio.run(
        GetBenchmarkRunLifecycleUseCase(uow_factory=FakeFactory(repository)).execute(
            GetBenchmarkRunLifecycleQuery(run_id_sha256=RUN)
        )
    )

    assert result.record is record
    assert repository.for_update_values == [False]


def test_get_lifecycle_accepts_legacy_blocked_state_with_pending_receipt() -> None:
    record = replace(
        _record(),
        state="cleanup_pending",
        projection_cleanup_state="blocked",
        cleanup_fingerprint_sha256="d" * 64,
        cleanup_receipt=_initiation_receipt("pending"),
    )

    result = asyncio.run(
        GetBenchmarkRunLifecycleUseCase(uow_factory=FakeFactory(FakeRepository(record))).execute(
            GetBenchmarkRunLifecycleQuery(run_id_sha256=RUN)
        )
    )

    assert result.record.projection_cleanup_state == "blocked"
    assert result.record.cleanup_receipt.projection_cleanup == "pending"


def test_get_lifecycle_validates_digest_before_repository_read() -> None:
    repository = FakeRepository(_record())

    with pytest.raises(MemoryValidationError, match="digest"):
        asyncio.run(
            GetBenchmarkRunLifecycleUseCase(uow_factory=FakeFactory(repository)).execute(
                GetBenchmarkRunLifecycleQuery(run_id_sha256="not-a-digest")
            )
        )

    assert repository.for_update_values == []


def test_get_lifecycle_reports_not_found_without_write_lock() -> None:
    repository = FakeRepository(None)

    with pytest.raises(MemoryNotFoundError, match="not found"):
        asyncio.run(
            GetBenchmarkRunLifecycleUseCase(uow_factory=FakeFactory(repository)).execute(
                GetBenchmarkRunLifecycleQuery(run_id_sha256=RUN)
            )
        )

    assert repository.for_update_values == [False]


def test_get_lifecycle_fails_closed_for_inconsistent_snapshot() -> None:
    record = replace(_record(), cleanup_fingerprint_sha256="d" * 64)

    with pytest.raises(MemoryConflictError, match="inconsistent"):
        asyncio.run(
            GetBenchmarkRunLifecycleUseCase(
                uow_factory=FakeFactory(FakeRepository(record))
            ).execute(GetBenchmarkRunLifecycleQuery(run_id_sha256=RUN))
        )


def _record() -> BenchmarkRunRegistryRecord:
    return BenchmarkRunRegistryRecord(
        run_id_sha256=RUN,
        binding_commitment_sha256="1" * 64,
        infinity_target_identity_sha256="2" * 64,
        space_id=SPACE_ID,
        space_slug=SPACE_SLUG,
        idempotency_key_sha256="3" * 64,
        registration_fingerprint_sha256="4" * 64,
        state="active",
        projection_manifest_json=None,
        projection_manifest_sha256=None,
        projection_cleanup_state="unsealed",
        cleanup_fingerprint_sha256=None,
        cleanup_receipt=None,
        finalization_fingerprint_sha256=None,
        completion_receipt=None,
        completed_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _initiation_receipt(
    projection_cleanup: Literal["pending", "blocked"],
) -> BenchmarkCleanupReceipt:
    return BenchmarkCleanupReceipt(
        run_id_sha256=RUN,
        space_id=SPACE_ID,
        space_slug=SPACE_SLUG,
        disposition="cleanup_pending",
        projection_cleanup=projection_cleanup,
        counts=BenchmarkCleanupCounts(1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
        vector_delete_outbox_ids=(11,),
        graph_delete_outbox_ids=(12,),
        cognee_delete_outbox_ids=(13,),
        receipt_sha256=INITIATION,
    )


def _complete_record() -> BenchmarkRunRegistryRecord:
    completion = BenchmarkCleanupCompletionReceipt(
        run_id_sha256=RUN,
        space_id=SPACE_ID,
        space_slug=SPACE_SLUG,
        disposition="cleanup_complete",
        projection_cleanup="complete",
        projection_manifest_sha256=MANIFEST,
        cleanup_initiation_receipt_sha256=INITIATION,
        projection_absence_proof_sha256="e" * 64,
        completed_at=NOW,
        receipt_sha256="f" * 64,
    )
    return replace(
        _record(),
        state="cleanup_complete",
        projection_manifest_json={"sealed": True},
        projection_manifest_sha256=MANIFEST,
        projection_cleanup_state="complete",
        cleanup_fingerprint_sha256="d" * 64,
        cleanup_receipt=_initiation_receipt("pending"),
        finalization_fingerprint_sha256="6" * 64,
        completion_receipt=completion,
        completed_at=NOW,
    )


class FakeRepository:
    def __init__(self, record: BenchmarkRunRegistryRecord | None) -> None:
        self.record = record
        self.for_update_values: list[bool] = []

    async def get_by_run_id_sha256(
        self,
        run_id_sha256: str,
        *,
        for_update: bool = False,
    ) -> BenchmarkRunRegistryRecord | None:
        self.for_update_values.append(for_update)
        if self.record is None or self.record.run_id_sha256 != run_id_sha256:
            return None
        return self.record


class FakeUnitOfWork:
    def __init__(self, repository: FakeRepository) -> None:
        self.benchmark_runs = repository

    async def __aenter__(self) -> FakeUnitOfWork:
        return self

    async def __aexit__(
        self,
        _exc_type: object,
        _exc: object,
        _traceback: object,
    ) -> None:
        return None


class FakeFactory:
    def __init__(self, repository: FakeRepository) -> None:
        self.repository = repository

    def __call__(self) -> FakeUnitOfWork:
        return FakeUnitOfWork(self.repository)
