"""Recovery-only validation for pruned benchmark projection upserts."""

from __future__ import annotations

from collections.abc import Sequence

from infinity_context_adapters.postgres.models import MemoryOutboxRow
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.ports.benchmark_cleanup_plan import (
    MAX_CLEANUP_PLAN_RECOVERY_ROWS_PER_KIND,
    MAX_CLEANUP_PLAN_RECOVERY_TOTAL_ROWS,
)
from infinity_context_core.ports.benchmark_runs import BenchmarkRunRegistryRecord
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

MAX_RECOVERY_OBSOLETE_UPSERT_JOBS = MAX_CLEANUP_PLAN_RECOVERY_TOTAL_ROWS * 4
MAX_RECOVERY_DELETE_OUTBOX_ROWS = MAX_CLEANUP_PLAN_RECOVERY_ROWS_PER_KIND + 1
_UPSERT_EVENT_TYPES = frozenset(
    {
        "vector.upsert_chunk",
        "vector.upsert_chunks",
        "graph.upsert_fact",
        "cognee.ingest_document",
    }
)
_DELETE_EVENT_TYPES = frozenset(
    {"vector.delete_chunks", "graph.delete_fact", "cognee.forget_document"}
)


def require_obsolete_upsert_count(counts: object) -> None:
    obsolete_jobs = getattr(counts, "obsolete_upsert_jobs", None)
    if (
        type(obsolete_jobs) is not int
        or not 0 <= obsolete_jobs <= MAX_RECOVERY_OBSOLETE_UPSERT_JOBS
    ):
        raise MemoryConflictError("Unsealed cleanup obsolete upsert count is invalid")


async def require_obsolete_upserts_pruned(
    session: AsyncSession,
    *,
    record: BenchmarkRunRegistryRecord,
    aggregate_ids: tuple[str, ...],
) -> None:
    ownership = MemoryOutboxRow.payload_json["space_id"].as_string() == record.space_id
    if aggregate_ids:
        ownership = or_(ownership, MemoryOutboxRow.aggregate_id.in_(aggregate_ids))
    remaining = await session.scalar(
        select(MemoryOutboxRow.id)
        .where(
            MemoryOutboxRow.status.in_(("pending", "retry_pending")),
            MemoryOutboxRow.event_type.in_(_UPSERT_EVENT_TYPES),
            ownership,
        )
        .limit(1)
    )
    if remaining is not None:
        raise MemoryConflictError("Unsealed cleanup obsolete upsert jobs remain")


async def require_exact_delete_jobs(
    session: AsyncSession,
    *,
    record: BenchmarkRunRegistryRecord,
    chunks: Sequence[object],
    facts: Sequence[object],
    documents: Sequence[object],
) -> tuple[int, ...]:
    receipt = record.cleanup_receipt
    if receipt is None:
        raise MemoryConflictError("Unsealed cleanup receipt is missing")
    lane_ids = (
        receipt.vector_delete_outbox_ids,
        receipt.graph_delete_outbox_ids,
        receipt.cognee_delete_outbox_ids,
    )
    if any(ids != tuple(sorted(set(ids))) for ids in lane_ids):
        raise MemoryConflictError("Unsealed cleanup outbox IDs are not canonical")
    if receipt.cognee_delete_outbox_ids or receipt.counts.cognee_delete_jobs:
        raise MemoryConflictError("Cognee recovery lane must have zero jobs")
    all_ids = tuple(identity for ids in lane_ids for identity in ids)
    if len(all_ids) > MAX_RECOVERY_DELETE_OUTBOX_ROWS:
        raise MemoryConflictError("Unsealed cleanup outbox inventory exceeds cap")
    rows = (
        tuple(
            (
                await session.execute(
                    select(MemoryOutboxRow)
                    .where(MemoryOutboxRow.id.in_(all_ids))
                    .order_by(MemoryOutboxRow.id)
                    .limit(min(len(all_ids) + 1, MAX_RECOVERY_DELETE_OUTBOX_ROWS))
                )
            ).scalars()
        )
        if all_ids
        else ()
    )
    if tuple(row.id for row in rows) != tuple(sorted(all_ids)):
        raise MemoryConflictError("Unsealed cleanup outbox inventory is incomplete")
    expected_vector = 1 if chunks else 0
    if len(receipt.vector_delete_outbox_ids) != expected_vector:
        raise MemoryConflictError("Unsealed vector cleanup job count differs")
    if len(receipt.graph_delete_outbox_ids) not in {0, len(facts)}:
        raise MemoryConflictError("Unsealed graph cleanup job count differs")
    if receipt.counts.vector_delete_jobs != len(
        receipt.vector_delete_outbox_ids
    ) or receipt.counts.graph_delete_jobs != len(receipt.graph_delete_outbox_ids):
        raise MemoryConflictError("Unsealed cleanup receipt job counts differ")
    allowed_ids = set(all_ids)
    related = (
        MemoryOutboxRow.aggregate_type == "benchmark_run",
        MemoryOutboxRow.event_type.in_(_DELETE_EVENT_TYPES),
        or_(
            MemoryOutboxRow.aggregate_id == record.run_id_sha256,
            MemoryOutboxRow.payload_json["cleanup_run_id_sha256"].as_string()
            == record.run_id_sha256,
            MemoryOutboxRow.payload_json["space_id"].as_string() == record.space_id,
        ),
    )
    related_count = await session.scalar(select(func.count(MemoryOutboxRow.id)).where(*related))
    if related_count != len(allowed_ids):
        raise MemoryConflictError("Unsealed cleanup has unregistered delete jobs")
    discovered = tuple(
        (
            await session.execute(
                select(MemoryOutboxRow)
                .where(*related)
                .order_by(MemoryOutboxRow.id)
                .limit(min(len(allowed_ids) + 1, MAX_RECOVERY_DELETE_OUTBOX_ROWS))
            )
        ).scalars()
    )
    if {row.id for row in discovered} != allowed_ids:
        raise MemoryConflictError("Unsealed cleanup has unregistered delete jobs")
    if any(row.status != "done" for row in rows):
        raise MemoryConflictError("Unsealed cleanup delete jobs are not complete")
    _require_delete_payloads(record, rows, chunks=chunks, facts=facts, documents=documents)
    return tuple(sorted(all_ids))


def _require_delete_payloads(
    record: BenchmarkRunRegistryRecord,
    rows: Sequence[MemoryOutboxRow],
    *,
    chunks: Sequence[object],
    facts: Sequence[object],
    documents: Sequence[object],
) -> None:
    expected_chunks = sorted(str(row.id) for row in chunks)
    expected_facts = sorted(str(row.id) for row in facts)
    vector = [row for row in rows if row.event_type == "vector.delete_chunks"]
    graph = [row for row in rows if row.event_type == "graph.delete_fact"]
    if vector and vector[0].payload_json != {
        "chunk_ids": expected_chunks,
        "space_id": record.space_id,
        "cleanup_run_id_sha256": record.run_id_sha256,
    }:
        raise MemoryConflictError("Unsealed vector cleanup payload differs")
    if sorted(row.aggregate_id for row in graph) != expected_facts:
        raise MemoryConflictError("Unsealed graph cleanup payload identities differ")
    for row in graph:
        if row.payload_json != {
            "fact_id": row.aggregate_id,
            "space_id": record.space_id,
            "cleanup_run_id_sha256": record.run_id_sha256,
        }:
            raise MemoryConflictError("Unsealed graph cleanup payload differs")
    del documents


__all__ = (
    "MAX_RECOVERY_OBSOLETE_UPSERT_JOBS",
    "MAX_RECOVERY_DELETE_OUTBOX_ROWS",
    "require_exact_delete_jobs",
    "require_obsolete_upsert_count",
    "require_obsolete_upserts_pruned",
)
