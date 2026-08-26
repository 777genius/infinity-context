from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from infinity_context_core.ports.adapters import VectorWriteResult
from infinity_context_server.processes.outbox import ClaimedOutboxJob
from infinity_context_server.processes.projections import (
    OutboxProjectionError,
    ProjectionOutboxProcess,
)


class _Vector:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.deleted: list[tuple[str, ...]] = []

    async def delete_chunks(self, chunk_ids: tuple[str, ...]) -> VectorWriteResult:
        self.deleted.append(chunk_ids)
        if self.fail:
            return VectorWriteResult.degraded("delete.failed")
        return VectorWriteResult.ok(len(chunk_ids))

    async def delete_chunks_if_version(
        self, chunk_ids: tuple[str, ...], *, canonical_version: int
    ) -> VectorWriteResult:
        self.deleted.append(chunk_ids)
        if self.fail:
            return VectorWriteResult.degraded("delete.failed")
        return VectorWriteResult.ok(len(chunk_ids))


class _Maintenance:
    marked: list[tuple[str, tuple[str, ...]]]

    def __init__(self) -> None:
        self.marked = []
        self.pending_calls: list[str] = []
        self.authorized = True

    async def pending(self, lane, *, limit):
        self.pending_calls.append(lane)
        return ("chunk-pending",)

    async def pending_deletes(self, lane, *, limit):
        self.pending_calls.append(lane)
        return (("chunk-pending", 4),)

    async def current_delete_ids(self, chunk_ids, *, canonical_version):
        return chunk_ids if self.authorized else ()

    async def mark_deleted(self, lane, chunk_ids, *, completed_at, canonical_version=None) -> None:
        self.marked.append((lane, chunk_ids))

    async def tracks(self, chunk_ids) -> bool:
        return True


class _AmbiguousVector(_Vector):
    async def locator_points_absent(self, chunk_ids) -> None:
        return None


def test_both_projection_deletes_are_attempted_when_legacy_delete_fails() -> None:
    legacy = _Vector(fail=True)
    locator = _Vector()
    maintenance = _Maintenance()
    container = SimpleNamespace(
        vector_index=legacy,
        locator_vector_index=locator,
        locator_projection_maintenance=maintenance,
        clock=SimpleNamespace(now=lambda: datetime.now(UTC)),
    )
    process = ProjectionOutboxProcess(container)

    with pytest.raises(OutboxProjectionError):
        asyncio.run(process._delete_vector_chunks(("chunk-a",)))

    assert legacy.deleted == [("chunk-a",)]
    assert locator.deleted == [("chunk-a",)]
    assert maintenance.marked == [("locator", ("chunk-a",))]


def test_locator_tombstone_stays_pending_without_delete_connectivity() -> None:
    legacy = _Vector()
    maintenance = _Maintenance()
    container = SimpleNamespace(
        vector_index=legacy,
        locator_vector_index=None,
        locator_projection_maintenance=maintenance,
        clock=SimpleNamespace(now=lambda: datetime.now(UTC)),
    )

    asyncio.run(ProjectionOutboxProcess(container)._delete_vector_chunks(("chunk-a",)))

    assert maintenance.marked == [("legacy", ("chunk-a",))]


def test_reconciliation_skips_unobservable_projection_lanes() -> None:
    maintenance = _Maintenance()
    container = SimpleNamespace(
        vector_index=_Vector(),
        locator_vector_index=None,
        locator_projection_maintenance=maintenance,
        clock=SimpleNamespace(now=lambda: datetime.now(UTC)),
    )

    asyncio.run(ProjectionOutboxProcess(container).reconcile_vector_tombstones())

    assert maintenance.pending_calls == []


def test_stale_versioned_delete_never_touches_either_vector_lane() -> None:
    legacy = _Vector()
    locator = _Vector()
    maintenance = _Maintenance()
    maintenance.authorized = False
    container = SimpleNamespace(
        vector_index=legacy,
        locator_vector_index=locator,
        locator_projection_maintenance=maintenance,
        clock=SimpleNamespace(now=lambda: datetime.now(UTC)),
    )
    job = ClaimedOutboxJob(
        id=1,
        event_type="vector.delete_chunks",
        aggregate_id="chunk-a",
        aggregate_version=3,
        attempt_count=0,
        workload_class="projection",
        fairness_key="chunk:chunk-a",
        payload_json={"chunk_ids": ["chunk-a"]},
    )

    asyncio.run(ProjectionOutboxProcess(container).handle_vector_delete_chunks(job))

    assert legacy.deleted == []
    assert locator.deleted == []


def test_current_versioned_delete_is_conditioned_in_both_vector_lanes() -> None:
    legacy = _Vector()
    locator = _Vector()
    maintenance = _Maintenance()
    container = SimpleNamespace(
        vector_index=legacy,
        locator_vector_index=locator,
        locator_projection_maintenance=maintenance,
        clock=SimpleNamespace(now=lambda: datetime.now(UTC)),
    )
    job = ClaimedOutboxJob(
        id=2,
        event_type="vector.delete_chunks",
        aggregate_id="chunk-a",
        aggregate_version=4,
        attempt_count=0,
        workload_class="projection",
        fairness_key="chunk:chunk-a",
        payload_json={"chunk_ids": ["chunk-a"]},
    )

    asyncio.run(ProjectionOutboxProcess(container).handle_vector_delete_chunks(job))

    assert legacy.deleted == [("chunk-a",)]
    assert locator.deleted == [("chunk-a",)]


def test_ambiguous_delete_defers_to_observing_tombstone_reconciliation() -> None:
    legacy = _AmbiguousVector(fail=True)
    maintenance = _Maintenance()
    container = SimpleNamespace(
        vector_index=legacy,
        locator_vector_index=None,
        locator_projection_maintenance=maintenance,
        clock=SimpleNamespace(now=lambda: datetime.now(UTC)),
    )

    asyncio.run(ProjectionOutboxProcess(container)._delete_vector_chunks(("chunk-a",)))

    assert legacy.deleted == [("chunk-a",)]
    assert maintenance.marked == []
