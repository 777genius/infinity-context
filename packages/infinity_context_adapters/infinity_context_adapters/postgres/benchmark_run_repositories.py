"""Postgres authority for managed benchmark registration and canonical cleanup."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime

from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.ports.benchmark_runs import (
    BenchmarkCleanupCounts,
    BenchmarkCleanupReceipt,
    BenchmarkRunRegistryRecord,
)
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.models import (
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
                cleanup_fingerprint_sha256=None,
                cleanup_receipt_json=None,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )

    async def begin_cleanup(
        self,
        record: BenchmarkRunRegistryRecord,
        *,
        cleanup_fingerprint_sha256: str,
        now: datetime,
    ) -> BenchmarkRunRegistryRecord:
        row = await self._session.get(MemoryComparisonBenchmarkRunRow, record.run_id_sha256)
        if row is None or row.state != "active" or row.cleanup_receipt_json is not None:
            raise MemoryConflictError("Benchmark cleanup registry lock was lost")
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
        document_scopes = dict(
            (str(document_id), str(memory_scope_id))
            for document_id, memory_scope_id in (
                await self._session.execute(
                    select(MemoryDocumentRow.id, MemoryDocumentRow.memory_scope_id).where(
                        MemoryDocumentRow.space_id == record.space_id,
                        MemoryDocumentRow.status == "active",
                    )
                )
            ).all()
        )
        chunks_by_document: dict[str, list[str]] = {}
        chunk_document_rows = (
            await self._session.execute(
                select(MemoryChunkRow.id, MemoryChunkRow.document_id).where(
                    MemoryChunkRow.space_id == record.space_id,
                    MemoryChunkRow.status == "active",
                    MemoryChunkRow.document_id.is_not(None),
                )
            )
        ).all()
        for chunk_id, document_id in chunk_document_rows:
            chunks_by_document.setdefault(str(document_id), []).append(str(chunk_id))
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

        await self._soft_delete(MemoryFactRow, record.space_id, now=now)
        await self._soft_delete(MemoryDocumentRow, record.space_id, now=now)
        await self._soft_delete(MemoryChunkRow, record.space_id, now=now)
        await self._soft_delete(MemoryEpisodeRow, record.space_id, now=now)
        await self._soft_delete(MemoryThreadRow, record.space_id, now=now)
        await self._soft_delete(MemoryScopeRow, record.space_id, now=now)
        await self._soft_delete(MemorySpaceRow, record.space_id, now=now)

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
        cognee_jobs = [
            _outbox_row(
                event_type="cognee.forget_document",
                aggregate_type="benchmark_run",
                aggregate_id=document_id,
                payload={
                    "document_id": document_id,
                    "chunk_ids": sorted(chunks_by_document.get(document_id, [])),
                    "space_id": record.space_id,
                    "memory_scope_id": document_scopes[document_id],
                    "cleanup_run_id_sha256": record.run_id_sha256,
                },
                now=now,
            )
            for document_id in document_ids
        ]
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
            "projection_cleanup": "pending",
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
            projection_cleanup="pending",
            counts=counts,
            vector_delete_outbox_ids=tuple(job.id for job in vector_jobs),
            graph_delete_outbox_ids=tuple(job.id for job in graph_jobs),
            cognee_delete_outbox_ids=tuple(job.id for job in cognee_jobs),
            receipt_sha256=_json_sha256(receipt_without_hash),
        )
        row.state = "cleanup_pending"
        row.cleanup_fingerprint_sha256 = cleanup_fingerprint_sha256
        row.cleanup_receipt_json = _receipt_json(receipt)
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
    digests = (
        row.run_id_sha256,
        row.binding_commitment_sha256,
        row.infinity_target_identity_sha256,
        row.idempotency_key_sha256,
        row.registration_fingerprint_sha256,
    )
    if any(not _valid_digest(value) for value in digests):
        raise RuntimeError("benchmark_run_registry_invalid")
    if row.cleanup_fingerprint_sha256 is not None and not _valid_digest(
        row.cleanup_fingerprint_sha256
    ):
        raise RuntimeError("benchmark_run_registry_invalid")
    if row.state not in {"active", "cleanup_pending"}:
        raise RuntimeError("benchmark_run_registry_invalid")
    receipt = (
        _receipt_from_json(row.cleanup_receipt_json)
        if row.cleanup_receipt_json is not None
        else None
    )
    if row.state == "active" and (
        row.cleanup_fingerprint_sha256 is not None or receipt is not None
    ):
        raise RuntimeError("benchmark_run_registry_invalid")
    if row.state != "active" and (row.cleanup_fingerprint_sha256 is None or receipt is None):
        raise RuntimeError("benchmark_run_registry_invalid")
    if receipt is not None and (
        receipt.run_id_sha256 != row.run_id_sha256
        or receipt.space_id != row.space_id
        or receipt.space_slug != row.space_slug
    ):
        raise RuntimeError("benchmark_run_registry_invalid")
    return BenchmarkRunRegistryRecord(
        run_id_sha256=row.run_id_sha256,
        binding_commitment_sha256=row.binding_commitment_sha256,
        infinity_target_identity_sha256=row.infinity_target_identity_sha256,
        space_id=row.space_id,
        space_slug=row.space_slug,
        idempotency_key_sha256=row.idempotency_key_sha256,
        registration_fingerprint_sha256=row.registration_fingerprint_sha256,
        state=row.state,
        cleanup_fingerprint_sha256=row.cleanup_fingerprint_sha256,
        cleanup_receipt=receipt,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


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
        or value["projection_cleanup"] != "pending"
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
        projection_cleanup="pending",
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
