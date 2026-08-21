import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from benchmark_cleanup_plan_fixtures import cleanup_plan_pair
from infinity_context_adapters.noop import SystemClock
from infinity_context_adapters.postgres.benchmark_run_repositories import (
    _json_sha256,
    _receipt_from_json,
)
from infinity_context_adapters.postgres.models import (
    MemoryAssetRow,
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
    FinalizeBenchmarkRunCleanupCommand,
    RegisterBenchmarkRunCommand,
    SealProjectionManifestCommand,
)
from infinity_context_core.application.use_cases.benchmark_runs import (
    BENCHMARK_COGNEE_NOT_PROJECTED_POLICY_SHA256,
    CleanupBenchmarkRunUseCase,
    FinalizeBenchmarkRunCleanupUseCase,
    RegisterBenchmarkRunUseCase,
    SealProjectionManifestUseCase,
)
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.ports.benchmark_runs import (
    BenchmarkProjectionCleanupProof,
    BenchmarkRunRegistryRecord,
)
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

RUN = "a" * 64
BINDING = "b" * 64
TARGET = "c" * 64
SLUG = "memory-comparison-managed-run"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_receipt_rejects_duplicate_ids_within_one_lane() -> None:
    value = _receipt_value(vector_ids=[1, 1], graph_ids=[2], cognee_ids=[3])
    with pytest.raises(RuntimeError, match="benchmark_cleanup_receipt_invalid"):
        _receipt_from_json(value)


def test_receipt_rejects_duplicate_ids_across_lanes() -> None:
    value = _receipt_value(vector_ids=[1], graph_ids=[1], cognee_ids=[3])
    with pytest.raises(RuntimeError, match="benchmark_cleanup_receipt_invalid"):
        _receipt_from_json(value)


def test_unsealed_cleanup_rejects_unsupported_rows_without_stranding_space(
    tmp_path: Path,
) -> None:
    asyncio.run(_unsealed_cleanup_rejection_contract(tmp_path))


async def _unsealed_cleanup_rejection_contract(tmp_path: Path) -> None:
    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'unsealed.db'}")
    await create_schema(engine)
    factory = PostgresUnitOfWorkFactory(
        session_factory=build_session_factory(engine),
        clock=SystemClock(),
    )
    registered = await RegisterBenchmarkRunUseCase(uow_factory=factory, clock=FixedClock()).execute(
        _registration()
    )
    async with AsyncSession(engine) as session:
        session.add(
            MemoryAssetRow(
                id="asset-blocker",
                space_id=registered.record.space_id,
                memory_scope_id="scope-none",
                thread_id=None,
                filename="blocker.txt",
                content_type="text/plain",
                byte_size=1,
                sha256_hex="8" * 64,
                storage_backend="test",
                storage_key="asset-blocker",
                status="stored",
                classification="internal",
                metadata_json={},
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.commit()
    command = CleanupBenchmarkRunCommand(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=TARGET,
        space_id=registered.record.space_id,
        space_slug=SLUG,
        idempotency_key_sha256="e" * 64,
        cleanup_plan_sha256=_cleanup_plan_sha256(),
    )
    with pytest.raises(MemoryConflictError, match="unsupported rows"):
        await CleanupBenchmarkRunUseCase(uow_factory=factory, clock=FixedClock()).execute(command)
    async with AsyncSession(engine) as session:
        registry = await session.get(MemoryComparisonBenchmarkRunRow, RUN)
        space = await session.get(MemorySpaceRow, registered.record.space_id)
        asset = await session.get(MemoryAssetRow, "asset-blocker")
        assert registry.state == "active"
        assert registry.projection_cleanup_state == "unsealed"
        assert registry.cleanup_receipt_json is None
        assert space.status == "active"
        assert asset.status == "stored"
    await engine.dispose()


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
    finalize = FinalizeBenchmarkRunCleanupUseCase(
        uow_factory=factory,
        clock=FixedClock(),
        projection_absence=ExactAbsenceProof(),
    )
    seal_manifest = SealProjectionManifestUseCase(uow_factory=factory, clock=FixedClock())
    try:
        registered = await register.execute(_registration())
        assert registered.created is True
        replay = await register.execute(_registration())
        assert replay.created is False
        assert replay.record.space_id == registered.record.space_id

        await _seed_canonical_rows(engine, registered.record.space_id)
        manifest = _manifest(registered.record.space_id)
        with pytest.raises(MemoryConflictError, match="cannot bind active episodes"):
            await seal_manifest.execute(
                SealProjectionManifestCommand(
                    run_id_sha256=RUN,
                    projection_manifest_json=manifest,
                    projection_manifest_sha256=_manifest_sha256(manifest),
                )
            )
        async with AsyncSession(engine) as session:
            await session.execute(
                delete(MemoryEpisodeRow).where(MemoryEpisodeRow.id == "episode-1")
            )
            await session.commit()
        async with AsyncSession(engine) as session:
            session.add(_upsert_job("cognee.ingest_document", "document", "document-1"))
            await session.commit()
        with pytest.raises(MemoryConflictError, match="Cognee projection history"):
            await seal_manifest.execute(
                SealProjectionManifestCommand(
                    run_id_sha256=RUN,
                    projection_manifest_json=manifest,
                    projection_manifest_sha256=_manifest_sha256(manifest),
                )
            )
        async with AsyncSession(engine) as session:
            await session.execute(
                delete(MemoryOutboxRow).where(
                    MemoryOutboxRow.event_type == "cognee.ingest_document"
                )
            )
            session.add(
                MemoryAssetRow(
                    id="asset-1",
                    space_id=registered.record.space_id,
                    memory_scope_id="scope-1",
                    thread_id="thread-1",
                    filename="unexpected.txt",
                    content_type="text/plain",
                    byte_size=1,
                    sha256_hex="8" * 64,
                    storage_backend="test",
                    storage_key="asset-1",
                    status="stored",
                    classification="internal",
                    metadata_json={},
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await session.commit()
        with pytest.raises(MemoryConflictError, match="unsupported rows"):
            await seal_manifest.execute(
                SealProjectionManifestCommand(
                    run_id_sha256=RUN,
                    projection_manifest_json=manifest,
                    projection_manifest_sha256=_manifest_sha256(manifest),
                )
            )
        async with AsyncSession(engine) as session:
            await session.execute(delete(MemoryAssetRow).where(MemoryAssetRow.id == "asset-1"))
            await session.commit()
        async with AsyncSession(engine) as session:
            session.add(
                MemoryScopeRow(
                    id="scope-extra",
                    space_id=registered.record.space_id,
                    external_ref="extra",
                    name="extra",
                    status="active",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await session.commit()
        with pytest.raises(MemoryConflictError, match="canonical inventory differs"):
            await seal_manifest.execute(
                SealProjectionManifestCommand(
                    run_id_sha256=RUN,
                    projection_manifest_json=manifest,
                    projection_manifest_sha256=_manifest_sha256(manifest),
                )
            )
        async with AsyncSession(engine) as session:
            await session.execute(delete(MemoryScopeRow).where(MemoryScopeRow.id == "scope-extra"))
            session.add(
                MemoryThreadRow(
                    id="thread-extra",
                    space_id=registered.record.space_id,
                    memory_scope_id="scope-1",
                    external_ref="extra",
                    status="active",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await session.commit()
        with pytest.raises(MemoryConflictError, match="canonical inventory differs"):
            await seal_manifest.execute(
                SealProjectionManifestCommand(
                    run_id_sha256=RUN,
                    projection_manifest_json=manifest,
                    projection_manifest_sha256=_manifest_sha256(manifest),
                )
            )
        async with AsyncSession(engine) as session:
            await session.execute(
                delete(MemoryThreadRow).where(MemoryThreadRow.id == "thread-extra")
            )
            await session.commit()
        incomplete_manifest = _manifest(registered.record.space_id)
        incomplete_manifest["scopes"][0]["chunk_ids"] = []
        incomplete_manifest["scopes"][0]["qdrant"] = None
        with pytest.raises(MemoryConflictError, match="canonical inventory differs"):
            await seal_manifest.execute(
                SealProjectionManifestCommand(
                    run_id_sha256=RUN,
                    projection_manifest_json=incomplete_manifest,
                    projection_manifest_sha256=_manifest_sha256(incomplete_manifest),
                )
            )
        sealed = await seal_manifest.execute(
            SealProjectionManifestCommand(
                run_id_sha256=RUN,
                projection_manifest_json=manifest,
                projection_manifest_sha256=_manifest_sha256(manifest),
            )
        )
        assert sealed.replayed is False
        assert sealed.record.projection_cleanup_state == "sealed"
        sealed_replay = await seal_manifest.execute(
            SealProjectionManifestCommand(
                run_id_sha256=RUN,
                projection_manifest_json=manifest,
                projection_manifest_sha256=_manifest_sha256(manifest),
            )
        )
        assert sealed_replay.replayed is True

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

        conflicting_plan, conflicting_plan_sha256 = cleanup_plan_pair(
            run_id="f" * 64,
            binding=BINDING,
            target=TARGET,
            space_slug="memory-comparison-preexisting",
        )
        conflicting_run = RegisterBenchmarkRunCommand(
            run_id_sha256="f" * 64,
            binding_commitment_sha256=BINDING,
            infinity_target_identity_sha256=TARGET,
            space_slug="memory-comparison-preexisting",
            idempotency_key_sha256="9" * 64,
            cleanup_plan_json=conflicting_plan,
            cleanup_plan_sha256=conflicting_plan_sha256,
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

        command = CleanupBenchmarkRunCommand(
            run_id_sha256=RUN,
            binding_commitment_sha256=BINDING,
            infinity_target_identity_sha256=TARGET,
            space_id=registered.record.space_id,
            space_slug=SLUG,
            idempotency_key_sha256="e" * 64,
            cleanup_plan_sha256=_cleanup_plan_sha256(),
        )
        with pytest.raises(MemoryConflictError, match="binding conflicted"):
            await cleanup.execute(replace(command, infinity_target_identity_sha256="8" * 64))
        first = await cleanup.execute(command)
        assert first.replayed is False
        assert first.receipt.projection_cleanup == "pending"
        assert first.receipt.counts.facts == 1
        assert first.receipt.counts.documents == 1
        assert first.receipt.counts.chunks == 1
        assert first.receipt.counts.episodes == 0
        assert first.receipt.counts.obsolete_upsert_jobs == 2
        assert first.receipt.counts.vector_delete_jobs == 1
        assert first.receipt.counts.graph_delete_jobs == 0
        assert first.receipt.counts.cognee_delete_jobs == 0

        before_replay_jobs = await _outbox_count(engine)
        second = await cleanup.execute(command)
        assert second.replayed is True
        assert second.receipt == first.receipt
        assert await _outbox_count(engine) == before_replay_jobs
        manifest_replay_after_cleanup = await seal_manifest.execute(
            SealProjectionManifestCommand(
                run_id_sha256=RUN,
                projection_manifest_json=manifest,
                projection_manifest_sha256=_manifest_sha256(manifest),
            )
        )
        assert manifest_replay_after_cleanup.replayed is True
        assert manifest_replay_after_cleanup.record.projection_cleanup_state == "pending"
        await _assert_deleted_and_queued(engine, registered.record.space_id)
        finalization_command = FinalizeBenchmarkRunCleanupCommand(
            run_id_sha256=RUN,
            expected_cleanup_receipt_sha256=first.receipt.receipt_sha256,
            expected_cleanup_plan_sha256=_cleanup_plan_sha256(),
            idempotency_key_sha256="6" * 64,
        )
        await _set_cleanup_job_state(engine, status="done", tampered=True)
        with pytest.raises(MemoryConflictError, match="outbox proof conflicted"):
            await finalize.execute(finalization_command)
        await _set_cleanup_job_state(engine, status="done", tampered=False)
        await _set_chunk_status(engine, status="active")
        with pytest.raises(MemoryConflictError, match="tombstones are incomplete"):
            await finalize.execute(finalization_command)
        await _set_chunk_status(engine, status="deleted")
        completed = await finalize.execute(finalization_command)
        completed_replay = await finalize.execute(
            FinalizeBenchmarkRunCleanupCommand(
                run_id_sha256=RUN,
                expected_cleanup_receipt_sha256=first.receipt.receipt_sha256,
                expected_cleanup_plan_sha256=_cleanup_plan_sha256(),
                idempotency_key_sha256="6" * 64,
            )
        )
        assert completed.replayed is False
        assert completed_replay.replayed is True
        assert completed_replay.receipt == completed.receipt
        assert completed.receipt.disposition == "cleanup_complete"
        assert completed.receipt.cleanup_initiation_receipt_sha256 == first.receipt.receipt_sha256
        async with factory() as uow:
            terminal = await uow.benchmark_runs.get_by_run_id_sha256(RUN)
        assert terminal.state == "cleanup_complete"
        assert terminal.projection_cleanup_state == "complete"
        assert terminal.completion_receipt == completed.receipt
        await _tamper_completion_receipt_and_require_rejection(engine, factory)
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
        ):
            statuses = list(
                (
                    await session.execute(select(model.status).where(model.space_id == space_id))
                ).scalars()
            )
            assert statuses == ["deleted"]
        assert not list(
            (
                await session.execute(
                    select(MemoryEpisodeRow.id).where(MemoryEpisodeRow.space_id == space_id)
                )
            ).scalars()
        )
        events = list(
            (
                await session.execute(
                    select(MemoryOutboxRow.event_type).order_by(MemoryOutboxRow.id)
                )
            ).scalars()
        )
        assert events == [
            "vector.delete_chunks",
        ]
        registry = await session.get(MemoryComparisonBenchmarkRunRow, RUN)
        assert registry is not None
        assert registry.state == "cleanup_pending"
        assert registry.cleanup_receipt_json["projection_cleanup"] == "pending"
        assert registry.projection_cleanup_state == "pending"
        assert registry.projection_manifest_json == _manifest(space_id)
        assert registry.projection_manifest_sha256 == _manifest_sha256(_manifest(space_id))


async def _set_cleanup_job_state(engine, *, status: str, tampered: bool) -> None:
    async with AsyncSession(engine) as session:
        row = (
            await session.execute(
                select(MemoryOutboxRow).where(MemoryOutboxRow.event_type == "vector.delete_chunks")
            )
        ).scalar_one()
        row.status = status
        payload = dict(row.payload_json)
        payload["space_id"] = "wrong-space" if tampered else f"benchmark-space-{RUN[:48]}"
        row.payload_json = payload
        await session.commit()


async def _set_chunk_status(engine, *, status: str) -> None:
    async with AsyncSession(engine) as session:
        chunk = await session.get(MemoryChunkRow, "chunk-1")
        chunk.status = status
        await session.commit()


async def _tamper_completion_receipt_and_require_rejection(engine, factory) -> None:
    async with AsyncSession(engine) as session:
        row = await session.get(MemoryComparisonBenchmarkRunRow, RUN)
        receipt = dict(row.completion_receipt_json)
        receipt["projection_absence_proof_sha256"] = "9" * 64
        row.completion_receipt_json = receipt
        await session.commit()
    async with factory() as uow:
        with pytest.raises(RuntimeError, match="benchmark_cleanup_completion_receipt_invalid"):
            await uow.benchmark_runs.get_by_run_id_sha256(RUN)


async def _outbox_count(engine) -> int:
    async with AsyncSession(engine) as session:
        return int(await session.scalar(select(func.count()).select_from(MemoryOutboxRow)) or 0)


def _registration() -> RegisterBenchmarkRunCommand:
    cleanup_plan, cleanup_plan_sha256 = cleanup_plan_pair(
        run_id=RUN, binding=BINDING, target=TARGET, space_slug=SLUG
    )
    return RegisterBenchmarkRunCommand(
        run_id_sha256=RUN,
        binding_commitment_sha256=BINDING,
        infinity_target_identity_sha256=TARGET,
        space_slug=SLUG,
        idempotency_key_sha256="d" * 64,
        cleanup_plan_json=cleanup_plan,
        cleanup_plan_sha256=cleanup_plan_sha256,
    )


def _cleanup_plan_sha256() -> str:
    return cleanup_plan_pair(run_id=RUN, binding=BINDING, target=TARGET, space_slug=SLUG)[1]


def _manifest(space_id: str) -> dict[str, object]:
    return {
        "schema_version": "memory-comparison-projection-manifest.v1",
        "run_id_sha256": RUN,
        "binding_commitment_sha256": BINDING,
        "infinity_target_identity_sha256": TARGET,
        "space_id": space_id,
        "cleanup_plan_sha256": _cleanup_plan_sha256(),
        "scopes": [
            {
                "memory_scope_id": "scope-1",
                "thread_id": "thread-1",
                "chunk_ids": ["chunk-1"],
                "fact_ids": ["fact-1"],
                "document_ids": ["document-1"],
                "qdrant": {
                    "target_commitment_sha256": "1" * 64,
                    "manifest_binding_sha256": "2" * 64,
                },
                "graphiti": {
                    "target_commitment_sha256": "3" * 64,
                    "manifest_binding_sha256": "4" * 64,
                    "episode_ids": ["provider-episode-1"],
                    "entity_ids": ["provider-entity-1"],
                    "mentions_edge_ids": ["provider-mentions-edge-1"],
                    "relates_to_edge_ids": ["provider-relates-edge-1"],
                },
                "cognee": {
                    "disposition": "not_projected",
                    "policy_sha256": BENCHMARK_COGNEE_NOT_PROJECTED_POLICY_SHA256,
                },
            }
        ],
    }


def _manifest_sha256(value: dict[str, object]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


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


class ExactAbsenceProof:
    async def prove_absence(
        self, *, record: BenchmarkRunRegistryRecord
    ) -> BenchmarkProjectionCleanupProof:
        return BenchmarkProjectionCleanupProof(
            run_id_sha256=record.run_id_sha256,
            projection_manifest_sha256=record.projection_manifest_sha256,
            cleanup_initiation_receipt_sha256=record.cleanup_receipt.receipt_sha256,
            qdrant_absent=True,
            graphiti_absent=True,
            cognee_absent=True,
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
