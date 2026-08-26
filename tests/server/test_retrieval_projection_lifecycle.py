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


class _ProfileOutbox:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, datetime]] = []

    async def upsert(self, job: ClaimedOutboxJob, *, now: datetime) -> None:
        self.calls.append(("upsert", job.id, now))

    async def delete(self, job: ClaimedOutboxJob, *, now: datetime) -> None:
        self.calls.append(("delete", job.id, now))


def _job(event_type: str, *, job_id: int = 1) -> ClaimedOutboxJob:
    return ClaimedOutboxJob(
        id=job_id,
        event_type=event_type,
        aggregate_id="chunk-a",
        aggregate_version=4,
        attempt_count=0,
        workload_class="projection",
        fairness_key="profile:profile-a",
        payload_json={"profile_id": "profile-a", "chunk_ids": ["chunk-a"]},
    )


def test_vector_delete_uses_only_the_configured_vector_adapter() -> None:
    vector = _Vector()
    process = ProjectionOutboxProcess(SimpleNamespace(vector_index=vector))

    asyncio.run(process.handle_vector_delete_chunks(_job("vector.delete_chunks")))

    assert vector.deleted == [("chunk-a",)]


def test_vector_delete_propagates_the_configured_adapter_failure() -> None:
    vector = _Vector(fail=True)
    process = ProjectionOutboxProcess(SimpleNamespace(vector_index=vector))

    with pytest.raises(OutboxProjectionError):
        asyncio.run(process.handle_vector_delete_chunks(_job("vector.delete_chunks")))

    assert vector.deleted == [("chunk-a",)]


def test_retrieval_profile_events_use_the_profile_outbox_only() -> None:
    now = datetime(2026, 8, 26, tzinfo=UTC)
    outbox = _ProfileOutbox()
    process = ProjectionOutboxProcess(
        SimpleNamespace(
            retrieval_profile_outbox=outbox,
            clock=SimpleNamespace(now=lambda: now),
        )
    )

    asyncio.run(process.handle_locator_profile_upsert(_job("vector.upsert_locator_profile")))
    asyncio.run(
        process.handle_locator_profile_delete(_job("vector.delete_locator_profile", job_id=2))
    )

    assert outbox.calls == [("upsert", 1, now), ("delete", 2, now)]
