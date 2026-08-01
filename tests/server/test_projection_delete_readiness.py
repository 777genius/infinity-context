from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from infinity_context_adapters.graphiti.scope_identity import graphiti_group_id
from infinity_context_adapters.postgres.models import (
    MemoryComparisonBenchmarkRunRow,
    MemoryFactRow,
    MemoryOutboxRow,
    MemoryScopeRow,
    MemorySpaceRow,
    MemoryThreadRow,
)
from infinity_context_adapters.postgres.unit_of_work import (
    build_async_engine,
    create_schema,
)
from infinity_context_core.domain.errors import MemoryConflictError, MemoryValidationError
from infinity_context_core.ports.graph_evidence import GraphProjectionIdentitySnapshot
from infinity_context_server.derived_identity_evidence import (
    CanonicalProjectionScope,
    ProjectionDeleteLane,
    SqlAlchemyProjectionReadiness,
    _prove_delete_scope_exists,
)
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_deleted_projection_scope_requires_cleanup_pending_registry(tmp_path: Path) -> None:
    asyncio.run(_deleted_projection_scope_contract(tmp_path))


async def _deleted_projection_scope_contract(tmp_path: Path) -> None:
    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'readiness.db'}")
    await create_schema(engine)
    scope = CanonicalProjectionScope("space-1", "scope-1", "thread-1")
    try:
        async with AsyncSession(engine) as session:
            session.add_all(
                [
                    MemorySpaceRow(
                        id=scope.space_id,
                        slug="memory-comparison-readiness",
                        name="readiness",
                        status="deleted",
                        created_at=NOW,
                        updated_at=NOW,
                    ),
                    MemoryScopeRow(
                        id=scope.memory_scope_id,
                        space_id=scope.space_id,
                        external_ref="scope",
                        name="scope",
                        status="deleted",
                        created_at=NOW,
                        updated_at=NOW,
                    ),
                    MemoryThreadRow(
                        id=scope.thread_id,
                        space_id=scope.space_id,
                        memory_scope_id=scope.memory_scope_id,
                        external_ref="thread",
                        status="deleted",
                        created_at=NOW,
                        updated_at=NOW,
                    ),
                    MemoryComparisonBenchmarkRunRow(
                        run_id_sha256="a" * 64,
                        binding_commitment_sha256="b" * 64,
                        infinity_target_identity_sha256="c" * 64,
                        space_id=scope.space_id,
                        space_slug="memory-comparison-readiness",
                        idempotency_key_sha256="d" * 64,
                        registration_fingerprint_sha256="e" * 64,
                        state="cleanup_pending",
                        projection_cleanup_state="blocked",
                        cleanup_fingerprint_sha256="f" * 64,
                        cleanup_receipt_json={"state": "cleanup_pending"},
                        created_at=NOW,
                        updated_at=NOW,
                    ),
                ]
            )
            await session.commit()
            with pytest.raises(
                MemoryValidationError,
                match="not protected by sealed benchmark cleanup",
            ):
                await _prove_delete_scope_exists(session, scope)

            benchmark = await session.get(MemoryComparisonBenchmarkRunRow, "a" * 64)
            assert benchmark is not None
            manifest = _projection_manifest(scope)
            benchmark.projection_manifest_json = manifest
            benchmark.projection_manifest_sha256 = _manifest_sha256(manifest)
            benchmark.projection_cleanup_state = "pending"
            await session.commit()
            await _prove_delete_scope_exists(session, scope)

            space = await session.get(MemorySpaceRow, scope.space_id)
            memory_scope = await session.get(MemoryScopeRow, scope.memory_scope_id)
            thread = await session.get(MemoryThreadRow, scope.thread_id)
            assert space is not None and memory_scope is not None and thread is not None
            space.status = memory_scope.status = thread.status = "active"
            await session.commit()
            with pytest.raises(
                MemoryValidationError,
                match="not protected by sealed benchmark cleanup",
            ):
                await _prove_delete_scope_exists(session, scope)
            space.status = memory_scope.status = thread.status = "deleted"
            await session.commit()

            benchmark.state = "active"
            benchmark.projection_cleanup_state = "sealed"
            benchmark.cleanup_fingerprint_sha256 = None
            benchmark.cleanup_receipt_json = None
            await session.commit()
            with pytest.raises(
                MemoryValidationError,
                match="not protected by sealed benchmark cleanup",
            ):
                await _prove_delete_scope_exists(session, scope)
            benchmark.state = "cleanup_pending"
            benchmark.projection_cleanup_state = "pending"
            benchmark.cleanup_fingerprint_sha256 = "f" * 64
            benchmark.cleanup_receipt_json = {"state": "cleanup_pending"}
            await session.commit()

            benchmark.projection_manifest_sha256 = "0" * 64
            await session.commit()
            with pytest.raises(
                MemoryValidationError,
                match="not protected by sealed benchmark cleanup",
            ):
                await _prove_delete_scope_exists(session, scope)

            for field, invalid_value in (
                ("schema_version", "projection-manifest-v1"),
                ("run_id_sha256", "9" * 64),
                ("binding_commitment_sha256", "9" * 64),
                ("infinity_target_identity_sha256", "9" * 64),
                ("space_id", "space-2"),
            ):
                tampered = {**manifest, field: invalid_value}
                benchmark.projection_manifest_json = tampered
                benchmark.projection_manifest_sha256 = _manifest_sha256(tampered)
                await session.commit()
                with pytest.raises(
                    MemoryValidationError,
                    match="not protected by sealed benchmark cleanup",
                ):
                    await _prove_delete_scope_exists(session, scope)

            await session.execute(delete(MemoryComparisonBenchmarkRunRow))
            await session.commit()
            with pytest.raises(
                MemoryValidationError,
                match="not protected by sealed benchmark cleanup",
            ):
                await _prove_delete_scope_exists(session, scope)

            space = await session.get(MemorySpaceRow, scope.space_id)
            memory_scope = await session.get(MemoryScopeRow, scope.memory_scope_id)
            thread = await session.get(MemoryThreadRow, scope.thread_id)
            assert space is not None and memory_scope is not None and thread is not None
            space.status = memory_scope.status = thread.status = "active"
            await session.commit()
            await _prove_delete_scope_exists(session, scope)

            thread.status = "deleted"
            await session.commit()
            with pytest.raises(MemoryValidationError, match="lifecycle differs"):
                await _prove_delete_scope_exists(session, scope)
    finally:
        await engine.dispose()


def test_active_sealed_graphiti_lane_is_delete_ready(tmp_path: Path) -> None:
    asyncio.run(_exact_graphiti_lane_contract(tmp_path, deleted=False))


def test_tombstoned_pending_graphiti_accepts_done_upsert_without_delete_job(
    tmp_path: Path,
) -> None:
    asyncio.run(_exact_graphiti_lane_contract(tmp_path, deleted=True))


async def _exact_graphiti_lane_contract(tmp_path: Path, *, deleted: bool) -> None:
    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'exact-graphiti.db'}")
    await create_schema(engine)
    scope = CanonicalProjectionScope("space-exact", "scope-exact", "thread-exact")
    snapshot = _graph_snapshot(scope)
    manifest = _exact_projection_manifest(scope, snapshot)
    try:
        await _seed_exact_readiness(engine, scope, manifest, deleted=deleted)
        result = await SqlAlchemyProjectionReadiness(engine).prove_delete_ready(
            scope=scope,
            chunk_ids=(),
            fact_ids=("fact-1",),
            lane=ProjectionDeleteLane("3" * 64, "4" * 64, snapshot),
        )

        assert result.done_chunk_ids == ()
        assert result.done_fact_ids == ("fact-1",)
    finally:
        await engine.dispose()


def test_sealed_readiness_rejects_exact_lane_mismatches(tmp_path: Path) -> None:
    asyncio.run(_sealed_readiness_mismatch_contract(tmp_path))


async def _sealed_readiness_mismatch_contract(tmp_path: Path) -> None:
    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'mismatch.db'}")
    await create_schema(engine)
    scope = CanonicalProjectionScope("space-exact", "scope-exact", "thread-exact")
    snapshot = _graph_snapshot(scope)
    manifest = _exact_projection_manifest(scope, snapshot)
    readiness = SqlAlchemyProjectionReadiness(engine)
    try:
        await _seed_exact_readiness(engine, scope, manifest, deleted=False)
        graph_cases = (
            (("fact-other",), ProjectionDeleteLane("3" * 64, "4" * 64, snapshot)),
            (("fact-1",), ProjectionDeleteLane("9" * 64, "4" * 64, snapshot)),
            (("fact-1",), ProjectionDeleteLane("3" * 64, "9" * 64, snapshot)),
            (
                ("fact-1",),
                ProjectionDeleteLane(
                    "3" * 64,
                    "4" * 64,
                    _graph_snapshot(scope, entity_id="entity-other"),
                ),
            ),
        )
        for fact_ids, lane in graph_cases:
            with pytest.raises(MemoryConflictError, match="sealed benchmark projection manifest"):
                await readiness.prove_delete_ready(
                    scope=scope,
                    chunk_ids=(),
                    fact_ids=fact_ids,
                    lane=lane,
                )

        with pytest.raises(MemoryConflictError, match="Qdrant delete lane"):
            await readiness.prove_delete_ready(
                scope=scope,
                chunk_ids=("chunk-other",),
                fact_ids=(),
                lane=ProjectionDeleteLane("1" * 64, "2" * 64),
            )

        async with AsyncSession(engine) as session:
            benchmark = await session.get(MemoryComparisonBenchmarkRunRow, "a" * 64)
            assert benchmark is not None
            benchmark.projection_manifest_sha256 = "0" * 64
            await session.commit()
        with pytest.raises(
            MemoryValidationError,
            match="not protected by sealed benchmark cleanup",
        ):
            await readiness.prove_delete_ready(
                scope=scope,
                chunk_ids=(),
                fact_ids=("fact-1",),
                lane=ProjectionDeleteLane("3" * 64, "4" * 64, snapshot),
            )
    finally:
        await engine.dispose()


def test_tombstoned_graphiti_delete_job_still_must_be_terminal(tmp_path: Path) -> None:
    asyncio.run(_tombstoned_graphiti_delete_job_contract(tmp_path))


async def _tombstoned_graphiti_delete_job_contract(tmp_path: Path) -> None:
    engine = build_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'blocked-delete.db'}")
    await create_schema(engine)
    scope = CanonicalProjectionScope("space-exact", "scope-exact", "thread-exact")
    snapshot = _graph_snapshot(scope)
    manifest = _exact_projection_manifest(scope, snapshot)
    try:
        await _seed_exact_readiness(engine, scope, manifest, deleted=True)
        async with AsyncSession(engine) as session:
            session.add(_outbox("graph.delete_fact", "fact", "fact-1", status="dead"))
            await session.commit()

        with pytest.raises(MemoryConflictError, match="not terminal"):
            await SqlAlchemyProjectionReadiness(engine).prove_delete_ready(
                scope=scope,
                chunk_ids=(),
                fact_ids=("fact-1",),
                lane=ProjectionDeleteLane("3" * 64, "4" * 64, snapshot),
            )
    finally:
        await engine.dispose()


async def _seed_exact_readiness(
    engine: object,
    scope: CanonicalProjectionScope,
    manifest: dict[str, object],
    *,
    deleted: bool,
) -> None:
    status = "deleted" if deleted else "active"
    async with AsyncSession(engine) as session:
        session.add_all(
            [
                MemorySpaceRow(
                    id=scope.space_id,
                    slug="memory-comparison-exact",
                    name="exact",
                    status=status,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                MemoryScopeRow(
                    id=scope.memory_scope_id,
                    space_id=scope.space_id,
                    external_ref="scope-exact",
                    name="scope-exact",
                    status=status,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                MemoryThreadRow(
                    id=scope.thread_id,
                    space_id=scope.space_id,
                    memory_scope_id=scope.memory_scope_id,
                    external_ref="thread-exact",
                    status=status,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                MemoryFactRow(
                    id="fact-1",
                    space_id=scope.space_id,
                    memory_scope_id=scope.memory_scope_id,
                    thread_id=scope.thread_id,
                    kind="semantic",
                    text="fact",
                    status=status,
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
                MemoryComparisonBenchmarkRunRow(
                    run_id_sha256="a" * 64,
                    binding_commitment_sha256="b" * 64,
                    infinity_target_identity_sha256="c" * 64,
                    space_id=scope.space_id,
                    space_slug="memory-comparison-exact",
                    idempotency_key_sha256="d" * 64,
                    registration_fingerprint_sha256="e" * 64,
                    state="cleanup_pending" if deleted else "active",
                    projection_manifest_json=manifest,
                    projection_manifest_sha256=_manifest_sha256(manifest),
                    projection_cleanup_state="pending" if deleted else "sealed",
                    cleanup_fingerprint_sha256="f" * 64 if deleted else None,
                    cleanup_receipt_json={"state": "cleanup_pending"} if deleted else None,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                _outbox("graph.upsert_fact", "fact", "fact-1", status="done"),
            ]
        )
        await session.commit()


def _outbox(
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    *,
    status: str,
) -> MemoryOutboxRow:
    return MemoryOutboxRow(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=1,
        workload_class="projection",
        fairness_key=f"{aggregate_type}:{aggregate_id}",
        payload_json={"fact_id": aggregate_id},
        status=status,
        attempt_count=0,
        next_attempt_at=NOW,
        last_safe_error=None,
        last_safe_diagnostic_code=None,
        created_at=NOW,
        updated_at=NOW,
    )


def _graph_snapshot(
    scope: CanonicalProjectionScope,
    *,
    entity_id: str = "entity-1",
) -> GraphProjectionIdentitySnapshot:
    return GraphProjectionIdentitySnapshot(
        group_ids=(graphiti_group_id(scope.space_id, scope.memory_scope_id),),
        episode_ids=("episode-1",),
        entity_ids=(entity_id,),
        mentions_edge_ids=("mentions-1",),
        relates_to_edge_ids=("relates-1",),
    )


def _exact_projection_manifest(
    scope: CanonicalProjectionScope,
    snapshot: GraphProjectionIdentitySnapshot,
) -> dict[str, object]:
    manifest = _projection_manifest(scope)
    manifest_scope = manifest["scopes"][0]
    manifest_scope["chunk_ids"] = ["chunk-1"]
    manifest_scope["fact_ids"] = ["fact-1"]
    manifest_scope["qdrant"] = {
        "target_commitment_sha256": "1" * 64,
        "manifest_binding_sha256": "2" * 64,
    }
    manifest_scope["graphiti"] = {
        "target_commitment_sha256": "3" * 64,
        "manifest_binding_sha256": "4" * 64,
        "episode_ids": list(snapshot.episode_ids),
        "entity_ids": list(snapshot.entity_ids),
        "mentions_edge_ids": list(snapshot.mentions_edge_ids),
        "relates_to_edge_ids": list(snapshot.relates_to_edge_ids),
    }
    return manifest


def _projection_manifest(scope: CanonicalProjectionScope) -> dict[str, object]:
    return {
        "schema_version": "memory-comparison-projection-manifest.v1",
        "run_id_sha256": "a" * 64,
        "binding_commitment_sha256": "b" * 64,
        "infinity_target_identity_sha256": "c" * 64,
        "space_id": scope.space_id,
        "scopes": [
            {
                "memory_scope_id": scope.memory_scope_id,
                "thread_id": scope.thread_id,
                "chunk_ids": [],
                "fact_ids": [],
                "document_ids": [],
                "qdrant": None,
                "graphiti": None,
                "cognee": {
                    "disposition": "not_projected",
                    "policy_sha256": "1" * 64,
                },
            }
        ],
    }


def _manifest_sha256(manifest: dict[str, object]) -> str:
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()
