from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from infinity_context_adapters.noop import SystemClock
from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryEpisodeRow,
    MemoryOutboxRow,
    MemoryScopeRow,
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
    SealProjectionManifestCommand,
)
from infinity_context_core.application.use_cases.benchmark_runs import (
    BENCHMARK_COGNEE_NOT_PROJECTED_POLICY_SHA256,
    CleanupBenchmarkRunUseCase,
    RegisterBenchmarkRunUseCase,
    SealProjectionManifestUseCase,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.unit.benchmark_cleanup_plan_fixtures import cleanup_plan_pair

RUN = "a" * 64
BINDING = "b" * 64
TARGET = "c" * 64
SLUG = "memory-comparison-managed-run"
NOW = datetime(2026, 1, 1, tzinfo=UTC)
CLEANUP_PLAN, CLEANUP_PLAN_SHA256 = cleanup_plan_pair(
    run_id=RUN,
    binding=BINDING,
    target=TARGET,
    space_slug=SLUG,
)


def test_v2_episode_cleanup_tombstones_and_replays_idempotently(tmp_path: Path) -> None:
    asyncio.run(_contract(tmp_path))


async def _contract(tmp_path: Path) -> None:
    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'episode-v2.db'}")
    await create_schema(engine)
    factory = PostgresUnitOfWorkFactory(
        session_factory=build_session_factory(engine),
        clock=SystemClock(),
    )
    try:
        registered = await RegisterBenchmarkRunUseCase(
            uow_factory=factory,
            clock=FixedClock(),
        ).execute(
            RegisterBenchmarkRunCommand(
                run_id_sha256=RUN,
                binding_commitment_sha256=BINDING,
                infinity_target_identity_sha256=TARGET,
                space_slug=SLUG,
                idempotency_key_sha256="d" * 64,
                cleanup_plan_json=CLEANUP_PLAN,
                cleanup_plan_sha256=CLEANUP_PLAN_SHA256,
            )
        )
        await _seed_rows(engine, registered.record.space_id)
        manifest = _manifest(registered.record.space_id)
        await SealProjectionManifestUseCase(uow_factory=factory, clock=FixedClock()).execute(
            SealProjectionManifestCommand(
                run_id_sha256=RUN,
                projection_manifest_json=manifest,
                projection_manifest_sha256=_sha256(manifest),
            )
        )
        cleanup = CleanupBenchmarkRunUseCase(uow_factory=factory, clock=FixedClock())
        command = CleanupBenchmarkRunCommand(
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            infinity_target_identity_sha256=TARGET,
            space_id=registered.record.space_id,
            space_slug=SLUG,
            idempotency_key_sha256="e" * 64,
            cleanup_plan_sha256=CLEANUP_PLAN_SHA256,
        )

        first = await cleanup.execute(command)
        job_count = await _outbox_count(engine)
        replay = await cleanup.execute(command)

        assert first.receipt.counts.episodes == 1
        assert first.receipt.counts.chunks == 1
        assert first.receipt.counts.vector_delete_jobs == 1
        assert replay.replayed is True
        assert replay.receipt == first.receipt
        assert await _outbox_count(engine) == job_count
        async with AsyncSession(engine) as session:
            episode = await session.get(MemoryEpisodeRow, "episode-1")
            chunk = await session.get(MemoryChunkRow, "episode-chunk-1")
            vector_job = (
                await session.execute(
                    select(MemoryOutboxRow).where(
                        MemoryOutboxRow.event_type == "vector.delete_chunks"
                    )
                )
            ).scalar_one()
            assert episode is not None and episode.status == "deleted"
            assert chunk is not None and chunk.status == "deleted"
            assert vector_job.payload_json["chunk_ids"] == ["episode-chunk-1"]
    finally:
        await engine.dispose()


async def _seed_rows(engine: object, space_id: str) -> None:
    async with AsyncSession(engine) as session:
        session.add_all(
            [
                MemoryScopeRow(
                    id="scope-1",
                    space_id=space_id,
                    external_ref="scope-1",
                    name="scope-1",
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
                MemoryChunkRow(
                    id="episode-chunk-1",
                    space_id=space_id,
                    memory_scope_id="scope-1",
                    thread_id="thread-1",
                    document_id=None,
                    episode_id="episode-1",
                    source_type="benchmark",
                    source_external_id="episode-source",
                    source_hash="7" * 64,
                    kind="episode",
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
                _upsert_job(),
            ]
        )
        await session.commit()


def _upsert_job() -> MemoryOutboxRow:
    return MemoryOutboxRow(
        event_type="vector.upsert_chunk",
        aggregate_type="chunk",
        aggregate_id="episode-chunk-1",
        aggregate_version=None,
        workload_class="projection",
        fairness_key="chunk:episode-chunk-1",
        payload_json={},
        status="pending",
        attempt_count=0,
        next_attempt_at=NOW,
        last_safe_error=None,
        last_safe_diagnostic_code=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _manifest(space_id: str) -> dict[str, object]:
    return {
        "schema_version": "memory-comparison-projection-manifest.v2",
        "run_id_sha256": RUN,
        "binding_commitment_sha256": BINDING,
        "infinity_target_identity_sha256": TARGET,
        "space_id": space_id,
        "cleanup_plan_sha256": CLEANUP_PLAN_SHA256,
        "scopes": [
            {
                "memory_scope_id": "scope-1",
                "thread_id": "thread-1",
                "episode_ids": ["episode-1"],
                "chunk_ids": ["episode-chunk-1"],
                "fact_ids": [],
                "document_ids": [],
                "qdrant": {
                    "target_commitment_sha256": "1" * 64,
                    "manifest_binding_sha256": "2" * 64,
                },
                "graphiti": None,
                "cognee": {
                    "disposition": "not_projected",
                    "policy_sha256": BENCHMARK_COGNEE_NOT_PROJECTED_POLICY_SHA256,
                },
            }
        ],
    }


def _sha256(value: dict[str, object]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


async def _outbox_count(engine: object) -> int:
    async with AsyncSession(engine) as session:
        return int(await session.scalar(select(func.count()).select_from(MemoryOutboxRow)) or 0)


class FixedClock:
    def now(self) -> datetime:
        return NOW
