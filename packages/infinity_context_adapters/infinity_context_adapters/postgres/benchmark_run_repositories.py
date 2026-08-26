"""Postgres authority for managed benchmark registration and canonical cleanup."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime

from infinity_context_core.application.use_cases.benchmark_runs import (
    BENCHMARK_COGNEE_NOT_PROJECTED_POLICY_SHA256,
)
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.ports.benchmark_cleanup_plan import (
    ManagedBenchmarkCleanupPlan,
)
from infinity_context_core.ports.benchmark_runs import (
    BenchmarkCleanupCounts,
    BenchmarkCleanupReceipt,
    BenchmarkRunRegistryRecord,
)
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.benchmark_run_completion import (
    abort_completion_receipt_json,
    build_abort_completion_receipt,
    build_completion_receipt,
    completion_receipt_json,
    require_canonical_tombstones,
    require_exact_cleanup_outbox_completion,
    unsealed_abort_cleanup_verification_sha256,
)
from infinity_context_adapters.postgres.benchmark_run_record_codec import (
    benchmark_run_record_from_row as _decode_record,
)
from infinity_context_adapters.postgres.models import (
    MemoryAnchorRow,
    MemoryAssetExtractionJobRow,
    MemoryAssetRow,
    MemoryCaptureRow,
    MemoryChunkRow,
    MemoryComparisonBenchmarkRunRow,
    MemoryContextLinkRow,
    MemoryContextLinkSuggestionRow,
    MemoryDocumentRow,
    MemoryEpisodeRow,
    MemoryFactRelationRow,
    MemoryFactRow,
    MemoryOutboxRow,
    MemoryScopeRow,
    MemorySpaceRow,
    MemorySuggestionRow,
    MemoryThreadRow,
)

_UPSERT_EVENT_TYPES = (
    "vector.upsert_chunk",
    "vector.upsert_chunks",
    "graph.upsert_fact",
    "cognee.ingest_document",
)


class PostgresBenchmarkRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_run_id_sha256(
        self,
        run_id_sha256: str,
        *,
        for_update: bool = False,
    ) -> BenchmarkRunRegistryRecord | None:
        query = _registry_query(run_id_sha256, for_update=for_update)
        row = (await self._session.execute(query)).scalar_one_or_none()
        return _to_record(row) if row is not None else None

    async def get_by_space_id(
        self,
        space_id: str,
    ) -> BenchmarkRunRegistryRecord | None:
        row = (
            await self._session.execute(
                select(MemoryComparisonBenchmarkRunRow).where(
                    MemoryComparisonBenchmarkRunRow.space_id == space_id
                )
            )
        ).scalar_one_or_none()
        return _to_record(row) if row is not None else None

    async def get_by_space_slug(
        self,
        space_slug: str,
    ) -> BenchmarkRunRegistryRecord | None:
        row = (
            await self._session.execute(
                select(MemoryComparisonBenchmarkRunRow).where(
                    MemoryComparisonBenchmarkRunRow.space_slug == space_slug
                )
            )
        ).scalar_one_or_none()
        return _to_record(row) if row is not None else None

    async def get_by_idempotency_key_sha256(
        self,
        idempotency_key_sha256: str,
    ) -> BenchmarkRunRegistryRecord | None:
        row = (
            await self._session.execute(
                select(MemoryComparisonBenchmarkRunRow).where(
                    MemoryComparisonBenchmarkRunRow.idempotency_key_sha256 == idempotency_key_sha256
                )
            )
        ).scalar_one_or_none()
        return _to_record(row) if row is not None else None

    async def add(self, record: BenchmarkRunRegistryRecord) -> None:
        self._session.add(
            MemorySpaceRow(
                id=record.space_id,
                slug=record.space_slug,
                name=record.space_slug,
                status="active",
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )
        # Flush the canonical space first. Postgres enforces the benchmark
        # registry foreign key immediately, and the two mappers intentionally
        # have no ORM relationship that could otherwise order their inserts.
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise MemoryConflictError("Canonical write conflicted with existing data") from exc
        self._session.add(
            MemoryComparisonBenchmarkRunRow(
                run_id_sha256=record.run_id_sha256,
                binding_commitment_sha256=record.binding_commitment_sha256,
                infinity_target_identity_sha256=record.infinity_target_identity_sha256,
                space_id=record.space_id,
                space_slug=record.space_slug,
                idempotency_key_sha256=record.idempotency_key_sha256,
                registration_fingerprint_sha256=record.registration_fingerprint_sha256,
                state=record.state,
                cleanup_plan_json=record.cleanup_plan_json,
                cleanup_plan_sha256=record.cleanup_plan_sha256,
                cleanup_plan_state=record.cleanup_plan_state,
                projection_manifest_json=None,
                projection_manifest_sha256=None,
                projection_cleanup_state="unsealed",
                cleanup_fingerprint_sha256=None,
                cleanup_receipt_json=None,
                finalization_fingerprint_sha256=None,
                completion_receipt_json=None,
                completed_at=None,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )

    async def load_cleanup_plan(self, space_id: str) -> ManagedBenchmarkCleanupPlan | None:
        record = await self.get_by_space_id(space_id)
        if record is None or record.cleanup_plan_state == "recovery_blocked":
            return None
        if record.cleanup_plan_json is None or record.cleanup_plan_sha256 is None:
            raise RuntimeError("benchmark_cleanup_plan_invalid")
        return ManagedBenchmarkCleanupPlan(record.cleanup_plan_json, record.cleanup_plan_sha256)

    async def seal_projection_manifest(
        self,
        record: BenchmarkRunRegistryRecord,
        *,
        projection_manifest_json: dict[str, object],
        projection_manifest_sha256: str,
        now: datetime,
    ) -> BenchmarkRunRegistryRecord:
        row = await self._session.get(MemoryComparisonBenchmarkRunRow, record.run_id_sha256)
        if (
            row is None
            or row.state != "active"
            or row.cleanup_plan_state != "sealed"
            or row.cleanup_plan_json is None
            or row.cleanup_plan_sha256 is None
            or row.projection_cleanup_state != "unsealed"
            or row.projection_manifest_json is not None
            or row.projection_manifest_sha256 is not None
        ):
            raise MemoryConflictError("Projection manifest registry lock was lost")
        await _require_projection_manifest_inventory(
            self._session,
            space_id=record.space_id,
            manifest=projection_manifest_json,
        )
        await _require_no_unmanifested_benchmark_rows(
            self._session,
            space_id=record.space_id,
        )
        await _require_cognee_not_projected_authority(
            self._session,
            manifest=projection_manifest_json,
        )
        row.projection_manifest_json = projection_manifest_json
        row.projection_manifest_sha256 = projection_manifest_sha256
        row.projection_cleanup_state = "sealed"
        row.updated_at = now
        await self._session.flush()
        return _to_record(row)

    async def begin_cleanup(
        self,
        record: BenchmarkRunRegistryRecord,
        *,
        cleanup_fingerprint_sha256: str,
        now: datetime,
    ) -> BenchmarkRunRegistryRecord:
        row = await self._session.get(MemoryComparisonBenchmarkRunRow, record.run_id_sha256)
        if (
            row is None
            or row.state != "active"
            or row.cleanup_plan_state != "sealed"
            or row.cleanup_plan_json is None
            or row.cleanup_plan_sha256 is None
            or row.cleanup_receipt_json is not None
        ):
            raise MemoryConflictError("Benchmark cleanup registry lock was lost")
        if row.projection_cleanup_state not in {"unsealed", "sealed"}:
            raise MemoryConflictError("Benchmark projection cleanup state conflicted")
        await _require_no_unmanifested_benchmark_rows(
            self._session,
            space_id=record.space_id,
        )
        projection_cleanup = "pending" if row.projection_cleanup_state == "sealed" else "blocked"
        space = (
            await self._session.execute(
                select(MemorySpaceRow).where(MemorySpaceRow.id == record.space_id).with_for_update()
            )
        ).scalar_one_or_none()
        if space is None or space.slug != record.space_slug or space.status != "active":
            raise MemoryConflictError("Benchmark canonical space conflicted")
        fact_ids = await self._ids(MemoryFactRow, record.space_id)
        document_ids = await self._ids(MemoryDocumentRow, record.space_id)
        chunk_ids = await self._ids(MemoryChunkRow, record.space_id)
        episode_ids = await self._ids(MemoryEpisodeRow, record.space_id)
        thread_ids = await self._ids(MemoryThreadRow, record.space_id)
        memory_scope_ids = await self._ids(MemoryScopeRow, record.space_id)
        await _require_managed_cognee_never_projected(
            self._session,
            cleanup_plan=record.cleanup_plan_json,
            document_ids=document_ids,
        )
        aggregate_ids = (*fact_ids, *document_ids, *chunk_ids, *episode_ids)
        obsolete_jobs = 0
        if aggregate_ids:
            result = await self._session.execute(
                delete(MemoryOutboxRow).where(
                    MemoryOutboxRow.status.in_(("pending", "retry_pending")),
                    MemoryOutboxRow.event_type.in_(_UPSERT_EVENT_TYPES),
                    MemoryOutboxRow.aggregate_id.in_(aggregate_ids),
                )
            )
            obsolete_jobs = int(result.rowcount or 0)
        vector_jobs: list[MemoryOutboxRow] = []
        if chunk_ids:
            vector_jobs.append(
                _outbox_row(
                    event_type="vector.delete_chunks",
                    aggregate_type="benchmark_run",
                    aggregate_id=record.run_id_sha256,
                    payload={
                        "chunk_ids": list(chunk_ids),
                        "space_id": record.space_id,
                        "cleanup_run_id_sha256": record.run_id_sha256,
                    },
                    now=now,
                )
            )
        graph_jobs: list[MemoryOutboxRow] = []
        if record.projection_manifest_json is None:
            graph_jobs = [
                _outbox_row(
                    event_type="graph.delete_fact",
                    aggregate_type="benchmark_run",
                    aggregate_id=fact_id,
                    payload={
                        "fact_id": fact_id,
                        "space_id": record.space_id,
                        "cleanup_run_id_sha256": record.run_id_sha256,
                    },
                    now=now,
                )
                for fact_id in fact_ids
            ]
        cognee_jobs: list[MemoryOutboxRow] = []
        self._session.add_all([*vector_jobs, *graph_jobs, *cognee_jobs])
        await self._session.flush()
        counts = BenchmarkCleanupCounts(
            facts=len(fact_ids),
            documents=len(document_ids),
            chunks=len(chunk_ids),
            episodes=len(episode_ids),
            threads=len(thread_ids),
            memory_scopes=len(memory_scope_ids),
            obsolete_upsert_jobs=obsolete_jobs,
            vector_delete_jobs=len(vector_jobs),
            graph_delete_jobs=len(graph_jobs),
            cognee_delete_jobs=len(cognee_jobs),
        )
        receipt_without_hash = {
            "run_id_sha256": record.run_id_sha256,
            "space_id": record.space_id,
            "space_slug": record.space_slug,
            "disposition": "cleanup_pending",
            "projection_cleanup": projection_cleanup,
            "counts": _counts_json(counts),
            "vector_delete_outbox_ids": [job.id for job in vector_jobs],
            "graph_delete_outbox_ids": [job.id for job in graph_jobs],
            "cognee_delete_outbox_ids": [job.id for job in cognee_jobs],
        }
        receipt = BenchmarkCleanupReceipt(
            run_id_sha256=record.run_id_sha256,
            space_id=record.space_id,
            space_slug=record.space_slug,
            disposition="cleanup_pending",
            projection_cleanup=projection_cleanup,
            counts=counts,
            vector_delete_outbox_ids=tuple(job.id for job in vector_jobs),
            graph_delete_outbox_ids=tuple(job.id for job in graph_jobs),
            cognee_delete_outbox_ids=tuple(job.id for job in cognee_jobs),
            receipt_sha256=_json_sha256(receipt_without_hash),
        )
        row.state = "cleanup_pending"
        row.projection_cleanup_state = projection_cleanup
        row.cleanup_fingerprint_sha256 = cleanup_fingerprint_sha256
        row.cleanup_receipt_json = _receipt_json(receipt)
        row.updated_at = now
        await self._session.flush()
        await self._soft_delete(MemoryFactRow, record.space_id, now=now)
        await self._soft_delete(MemoryDocumentRow, record.space_id, now=now)
        await self._soft_delete(MemoryChunkRow, record.space_id, now=now)
        await self._soft_delete(MemoryEpisodeRow, record.space_id, now=now)
        await self._soft_delete(MemoryThreadRow, record.space_id, now=now)
        await self._soft_delete(MemoryScopeRow, record.space_id, now=now)
        await self._soft_delete(MemorySpaceRow, record.space_id, now=now)
        return _to_record(row)

    async def finalize_cleanup(
        self,
        record: BenchmarkRunRegistryRecord,
        *,
        finalization_fingerprint_sha256: str,
        projection_absence_proof_sha256: str,
        now: datetime,
    ) -> BenchmarkRunRegistryRecord:
        row = await self._session.get(MemoryComparisonBenchmarkRunRow, record.run_id_sha256)
        if (
            row is None
            or row.state != "cleanup_pending"
            or row.projection_cleanup_state != "pending"
            or row.projection_manifest_json is None
            or row.projection_manifest_sha256 is None
            or row.cleanup_receipt_json is None
            or row.finalization_fingerprint_sha256 is not None
            or row.completion_receipt_json is not None
            or row.completed_at is not None
        ):
            raise MemoryConflictError("Benchmark cleanup finalization lock was lost")
        current = _to_record(row)
        if current != record or current.cleanup_receipt is None:
            raise MemoryConflictError("Benchmark cleanup finalization lock was lost")
        await require_canonical_tombstones(self._session, record=current)
        await require_exact_cleanup_outbox_completion(self._session, record=current)
        completion = build_completion_receipt(
            record=current,
            projection_absence_proof_sha256=projection_absence_proof_sha256,
            completed_at=now,
        )
        row.state = "cleanup_complete"
        row.projection_cleanup_state = "complete"
        row.finalization_fingerprint_sha256 = finalization_fingerprint_sha256
        row.completion_receipt_json = completion_receipt_json(completion)
        row.completed_at = now
        row.updated_at = now
        await self._session.flush()
        return _to_record(row)

    async def finalize_unsealed_abort(
        self,
        record: BenchmarkRunRegistryRecord,
        *,
        finalization_fingerprint_sha256: str,
        projection_absence_proof_sha256: str,
        now: datetime,
    ) -> BenchmarkRunRegistryRecord:
        row = await self._session.get(MemoryComparisonBenchmarkRunRow, record.run_id_sha256)
        if (
            row is None
            or row.state != "cleanup_pending"
            or row.projection_cleanup_state != "blocked"
            or row.projection_manifest_json is not None
            or row.projection_manifest_sha256 is not None
            or row.cleanup_receipt_json is None
            or row.finalization_fingerprint_sha256 is not None
            or row.completion_receipt_json is not None
            or row.completed_at is not None
        ):
            raise MemoryConflictError("Benchmark abort finalization lock was lost")
        current = _to_record(row)
        if current != record or current.cleanup_receipt is None:
            raise MemoryConflictError("Benchmark abort finalization lock was lost")
        await unsealed_abort_cleanup_verification_sha256(self._session, record=current)
        completion = build_abort_completion_receipt(
            record=current,
            projection_absence_proof_sha256=projection_absence_proof_sha256,
            completed_at=now,
        )
        row.state = "cleanup_aborted"
        row.projection_cleanup_state = "unsealed_abort_complete"
        row.finalization_fingerprint_sha256 = finalization_fingerprint_sha256
        row.completion_receipt_json = abort_completion_receipt_json(completion)
        row.completed_at = now
        row.updated_at = now
        await self._session.flush()
        return _to_record(row)

    async def _ids(self, model: type, space_id: str) -> tuple[str, ...]:
        rows = (
            await self._session.execute(
                select(model.id)
                .where(model.space_id == space_id, model.status == "active")
                .order_by(model.id)
            )
        ).scalars()
        return tuple(str(value) for value in rows)

    async def _soft_delete(
        self,
        model: type,
        space_id: str,
        *,
        now: datetime,
    ) -> None:
        values: dict[str, object] = {"status": "deleted"}
        if "updated_at" in model.__table__.columns:
            values["updated_at"] = now
        await self._session.execute(
            update(model)
            .where(model.id == space_id if model is MemorySpaceRow else model.space_id == space_id)
            .where(model.status == "active")
            .values(**values)
        )


def _registry_query(run_id_sha256: str, *, for_update: bool):
    query = select(MemoryComparisonBenchmarkRunRow).where(
        MemoryComparisonBenchmarkRunRow.run_id_sha256 == run_id_sha256
    )
    return query.with_for_update() if for_update else query


async def _require_projection_manifest_inventory(
    session: AsyncSession,
    *,
    space_id: str,
    manifest: dict[str, object],
) -> None:
    schema_version = manifest.get("schema_version")
    supports_episodes = schema_version == "memory-comparison-projection-manifest.v2"
    scopes = manifest.get("scopes")
    if type(scopes) is not list:
        raise MemoryConflictError("Projection manifest canonical inventory differs")
    expected: dict[type, set[tuple[str, str, str | None]]] = {
        MemoryChunkRow: set(),
        MemoryFactRow: set(),
        MemoryDocumentRow: set(),
    }
    field_by_model = {
        MemoryChunkRow: "chunk_ids",
        MemoryFactRow: "fact_ids",
        MemoryDocumentRow: "document_ids",
    }
    manifest_scopes: set[tuple[str, str | None]] = set()
    expected_episodes: set[tuple[str, str, str]] = set()
    for scope in scopes:
        if type(scope) is not dict:
            raise MemoryConflictError("Projection manifest canonical inventory differs")
        memory_scope_id = str(scope.get("memory_scope_id"))
        raw_thread_id = scope.get("thread_id")
        thread_id = str(raw_thread_id) if raw_thread_id is not None else None
        manifest_scopes.add((memory_scope_id, thread_id))
        if supports_episodes:
            episode_ids = scope.get("episode_ids")
            if type(episode_ids) is not list:
                raise MemoryConflictError("Projection manifest canonical inventory differs")
            if episode_ids:
                if thread_id is None:
                    raise MemoryConflictError("Projection manifest canonical inventory differs")
                expected_episodes.update(
                    (str(identity), memory_scope_id, thread_id) for identity in episode_ids
                )
        for model, field_name in field_by_model.items():
            identities = scope.get(field_name)
            if type(identities) is not list:
                raise MemoryConflictError("Projection manifest canonical inventory differs")
            expected[model].update(
                (str(identity), memory_scope_id, thread_id) for identity in identities
            )
    active_scope_ids = set(
        str(value)
        for value in (
            await session.execute(
                select(MemoryScopeRow.id).where(
                    MemoryScopeRow.space_id == space_id,
                    MemoryScopeRow.status == "active",
                )
            )
        ).scalars()
    )
    active_threads = set(
        (str(memory_scope_id), str(thread_id))
        for memory_scope_id, thread_id in (
            await session.execute(
                select(MemoryThreadRow.memory_scope_id, MemoryThreadRow.id).where(
                    MemoryThreadRow.space_id == space_id,
                    MemoryThreadRow.status == "active",
                )
            )
        ).all()
    )
    manifest_scope_ids = {memory_scope_id for memory_scope_id, _ in manifest_scopes}
    manifest_threads = {
        (memory_scope_id, thread_id)
        for memory_scope_id, thread_id in manifest_scopes
        if thread_id is not None
    }
    if manifest_scope_ids != active_scope_ids or manifest_threads != active_threads:
        raise MemoryConflictError("Projection manifest canonical inventory differs")
    if supports_episodes:
        actual_episodes = set(
            (str(identity), str(memory_scope_id), str(thread_id))
            for identity, memory_scope_id, thread_id in (
                await session.execute(
                    select(
                        MemoryEpisodeRow.id,
                        MemoryEpisodeRow.memory_scope_id,
                        MemoryEpisodeRow.thread_id,
                    ).where(
                        MemoryEpisodeRow.space_id == space_id,
                        MemoryEpisodeRow.status == "active",
                    )
                )
            ).all()
        )
        if actual_episodes != expected_episodes:
            raise MemoryConflictError("Projection manifest canonical inventory differs")
    else:
        active_episode = await session.scalar(
            select(MemoryEpisodeRow.id)
            .where(
                MemoryEpisodeRow.space_id == space_id,
                MemoryEpisodeRow.status == "active",
            )
            .limit(1)
        )
        if active_episode is not None:
            raise MemoryConflictError("Projection manifest cannot bind active episodes")
    for model, expected_rows in expected.items():
        actual_rows = set(
            (
                str(identity),
                str(memory_scope_id),
                str(thread_id) if thread_id is not None else None,
            )
            for identity, memory_scope_id, thread_id in (
                await session.execute(
                    select(model.id, model.memory_scope_id, model.thread_id).where(
                        model.space_id == space_id,
                        model.status == "active",
                    )
                )
            ).all()
        )
        if actual_rows != expected_rows:
            raise MemoryConflictError("Projection manifest canonical inventory differs")
    if supports_episodes:
        await _require_v2_chunk_ownership(
            session,
            space_id=space_id,
            expected_episodes=expected_episodes,
            expected_documents=expected[MemoryDocumentRow],
        )


async def _require_v2_chunk_ownership(
    session: AsyncSession,
    *,
    space_id: str,
    expected_episodes: set[tuple[str, str, str]],
    expected_documents: set[tuple[str, str, str | None]],
) -> None:
    owned_episode_ids: set[tuple[str, str, str]] = set()
    rows = (
        await session.execute(
            select(
                MemoryChunkRow.memory_scope_id,
                MemoryChunkRow.thread_id,
                MemoryChunkRow.document_id,
                MemoryChunkRow.episode_id,
            ).where(
                MemoryChunkRow.space_id == space_id,
                MemoryChunkRow.status == "active",
            )
        )
    ).all()
    for memory_scope_id, thread_id, document_id, episode_id in rows:
        scope_id = str(memory_scope_id)
        canonical_thread_id = str(thread_id) if thread_id is not None else None
        owners = int(document_id is not None) + int(episode_id is not None)
        if owners != 1:
            raise MemoryConflictError("Projection manifest chunk ownership differs")
        if episode_id is not None:
            if canonical_thread_id is None:
                raise MemoryConflictError("Projection manifest chunk ownership differs")
            owner = (str(episode_id), scope_id, canonical_thread_id)
            if owner not in expected_episodes:
                raise MemoryConflictError("Projection manifest chunk ownership differs")
            owned_episode_ids.add(owner)
        elif (str(document_id), scope_id, canonical_thread_id) not in expected_documents:
            raise MemoryConflictError("Projection manifest chunk ownership differs")
    if owned_episode_ids != expected_episodes:
        raise MemoryConflictError("Projection manifest chunk ownership differs")


_UNEXPECTED_BENCHMARK_MODELS = (
    MemoryAnchorRow,
    MemoryAssetRow,
    MemoryAssetExtractionJobRow,
    MemoryFactRelationRow,
    MemorySuggestionRow,
    MemoryCaptureRow,
    MemoryContextLinkRow,
    MemoryContextLinkSuggestionRow,
)


async def _require_no_unmanifested_benchmark_rows(
    session: AsyncSession,
    *,
    space_id: str,
) -> None:
    for model in _UNEXPECTED_BENCHMARK_MODELS:
        found = await session.scalar(
            select(model.space_id).where(model.space_id == space_id).limit(1)
        )
        if found is not None:
            raise MemoryConflictError("Benchmark canonical inventory contains unsupported rows")


async def _require_cognee_not_projected_authority(
    session: AsyncSession,
    *,
    manifest: dict[str, object],
) -> None:
    scopes = manifest["scopes"]
    document_ids: list[str] = []
    for scope in scopes:
        cognee = scope["cognee"]
        if cognee != {
            "disposition": "not_projected",
            "policy_sha256": BENCHMARK_COGNEE_NOT_PROJECTED_POLICY_SHA256,
        }:
            raise MemoryConflictError("Benchmark Cognee projection policy conflicted")
        document_ids.extend(scope["document_ids"])
    if not document_ids:
        return
    existing = await session.scalar(
        select(MemoryOutboxRow.id)
        .where(
            MemoryOutboxRow.event_type == "cognee.ingest_document",
            MemoryOutboxRow.aggregate_id.in_(tuple(document_ids)),
        )
        .limit(1)
    )
    if existing is not None:
        raise MemoryConflictError("Benchmark Cognee projection history conflicted")


async def _require_managed_cognee_never_projected(
    session: AsyncSession,
    *,
    cleanup_plan: dict[str, object],
    document_ids: tuple[str, ...],
) -> None:
    if cleanup_plan.get("cognee") != {
        "disposition": "not_projected",
        "policy_sha256": BENCHMARK_COGNEE_NOT_PROJECTED_POLICY_SHA256,
    }:
        raise MemoryConflictError("Benchmark Cognee projection policy conflicted")
    if not document_ids:
        return
    existing = await session.scalar(
        select(MemoryOutboxRow.id)
        .where(
            MemoryOutboxRow.event_type == "cognee.ingest_document",
            MemoryOutboxRow.aggregate_id.in_(document_ids),
        )
        .limit(1)
    )
    if existing is not None:
        raise MemoryConflictError("Benchmark Cognee projection history conflicted")


def _outbox_row(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, object],
    now: datetime,
) -> MemoryOutboxRow:
    return MemoryOutboxRow(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        aggregate_version=None,
        workload_class="projection",
        fairness_key=f"benchmark_cleanup:{payload['space_id']}",
        payload_json=payload,
        status="pending",
        attempt_count=0,
        next_attempt_at=now,
        last_safe_error=None,
        last_safe_diagnostic_code=None,
        created_at=now,
        updated_at=now,
    )


def _to_record(row: MemoryComparisonBenchmarkRunRow) -> BenchmarkRunRegistryRecord:
    return _decode_record(row, receipt_from_json=_receipt_from_json)


def _counts_json(counts: BenchmarkCleanupCounts) -> dict[str, int]:
    return {
        "facts": counts.facts,
        "documents": counts.documents,
        "chunks": counts.chunks,
        "episodes": counts.episodes,
        "threads": counts.threads,
        "memory_scopes": counts.memory_scopes,
        "obsolete_upsert_jobs": counts.obsolete_upsert_jobs,
        "vector_delete_jobs": counts.vector_delete_jobs,
        "graph_delete_jobs": counts.graph_delete_jobs,
        "cognee_delete_jobs": counts.cognee_delete_jobs,
    }


def _receipt_json(receipt: BenchmarkCleanupReceipt) -> dict[str, object]:
    return {
        "run_id_sha256": receipt.run_id_sha256,
        "space_id": receipt.space_id,
        "space_slug": receipt.space_slug,
        "disposition": receipt.disposition,
        "projection_cleanup": receipt.projection_cleanup,
        "counts": _counts_json(receipt.counts),
        "vector_delete_outbox_ids": list(receipt.vector_delete_outbox_ids),
        "graph_delete_outbox_ids": list(receipt.graph_delete_outbox_ids),
        "cognee_delete_outbox_ids": list(receipt.cognee_delete_outbox_ids),
        "receipt_sha256": receipt.receipt_sha256,
    }


def _receipt_from_json(value: dict[str, object]) -> BenchmarkCleanupReceipt:
    expected_keys = {
        "run_id_sha256",
        "space_id",
        "space_slug",
        "disposition",
        "projection_cleanup",
        "counts",
        "vector_delete_outbox_ids",
        "graph_delete_outbox_ids",
        "cognee_delete_outbox_ids",
        "receipt_sha256",
    }
    count_keys = {
        "facts",
        "documents",
        "chunks",
        "episodes",
        "threads",
        "memory_scopes",
        "obsolete_upsert_jobs",
        "vector_delete_jobs",
        "graph_delete_jobs",
        "cognee_delete_jobs",
    }
    if type(value) is not dict or set(value) != expected_keys:
        raise RuntimeError("benchmark_cleanup_receipt_invalid")
    counts_value = value["counts"]
    if type(counts_value) is not dict or set(counts_value) != count_keys:
        raise RuntimeError("benchmark_cleanup_receipt_invalid")
    if any(type(item) is not int or item < 0 for item in counts_value.values()):
        raise RuntimeError("benchmark_cleanup_receipt_invalid")
    list_keys = (
        "vector_delete_outbox_ids",
        "graph_delete_outbox_ids",
        "cognee_delete_outbox_ids",
    )
    if any(
        type(value[key]) is not list
        or any(type(item) is not int or item <= 0 for item in value[key])
        for key in list_keys
    ):
        raise RuntimeError("benchmark_cleanup_receipt_invalid")
    outbox_ids = [item for key in list_keys for item in value[key]]
    if len(set(outbox_ids)) != len(outbox_ids):
        raise RuntimeError("benchmark_cleanup_receipt_invalid")
    if (
        not _valid_digest(value["run_id_sha256"])
        or type(value["space_id"]) is not str
        or not value["space_id"]
        or type(value["space_slug"]) is not str
        or not value["space_slug"]
        or value["disposition"] != "cleanup_pending"
        or value["projection_cleanup"] not in {"pending", "blocked"}
        or not _valid_digest(value["receipt_sha256"])
    ):
        raise RuntimeError("benchmark_cleanup_receipt_invalid")
    material = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if not hmac.compare_digest(str(value["receipt_sha256"]), _json_sha256(material)):
        raise RuntimeError("benchmark_cleanup_receipt_invalid")
    counts = BenchmarkCleanupCounts(**counts_value)
    if (
        counts.vector_delete_jobs != len(value["vector_delete_outbox_ids"])
        or counts.graph_delete_jobs != len(value["graph_delete_outbox_ids"])
        or counts.cognee_delete_jobs != len(value["cognee_delete_outbox_ids"])
    ):
        raise RuntimeError("benchmark_cleanup_receipt_invalid")
    return BenchmarkCleanupReceipt(
        run_id_sha256=value["run_id_sha256"],
        space_id=value["space_id"],
        space_slug=value["space_slug"],
        disposition="cleanup_pending",
        projection_cleanup=value["projection_cleanup"],
        counts=counts,
        vector_delete_outbox_ids=tuple(value["vector_delete_outbox_ids"]),
        graph_delete_outbox_ids=tuple(value["graph_delete_outbox_ids"]),
        cognee_delete_outbox_ids=tuple(value["cognee_delete_outbox_ids"]),
        receipt_sha256=value["receipt_sha256"],
    )


def _valid_digest(value: object) -> bool:
    if type(value) is not str or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()


def _json_sha256(value: dict[str, object]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


__all__ = ("PostgresBenchmarkRunRepository",)
