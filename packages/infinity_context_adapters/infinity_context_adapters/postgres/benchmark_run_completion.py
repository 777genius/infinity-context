"""Postgres-owned terminal proof for managed benchmark cleanup."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime

from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.ports.benchmark_runs import (
    BenchmarkAbortCompletionReceipt,
    BenchmarkCleanupCompletionReceipt,
    BenchmarkRunRegistryRecord,
)
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_adapters.postgres.models import (
    MemoryAnchorRow,
    MemoryAssetExtractionJobRow,
    MemoryAssetRow,
    MemoryCaptureRow,
    MemoryChunkRow,
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

_UNSUPPORTED_MODELS = (
    MemoryAnchorRow,
    MemoryAssetRow,
    MemoryAssetExtractionJobRow,
    MemoryFactRelationRow,
    MemorySuggestionRow,
    MemoryCaptureRow,
    MemoryContextLinkRow,
    MemoryContextLinkSuggestionRow,
)


async def require_canonical_tombstones(
    session: AsyncSession,
    *,
    record: BenchmarkRunRegistryRecord,
) -> None:
    receipt = record.cleanup_receipt
    if receipt is None:
        raise MemoryConflictError("Benchmark cleanup initiation receipt is missing")
    space = await session.get(MemorySpaceRow, record.space_id)
    if space is None or space.slug != record.space_slug or space.status != "deleted":
        raise MemoryConflictError("Benchmark canonical space tombstone is incomplete")
    manifest = record.projection_manifest_json
    if manifest is None:
        raise MemoryConflictError("Benchmark projection manifest is missing")
    scopes = manifest["scopes"]
    exact_identities = (
        (MemoryScopeRow, "memory_scopes", {scope["memory_scope_id"] for scope in scopes}),
        (
            MemoryThreadRow,
            "threads",
            {scope["thread_id"] for scope in scopes if scope["thread_id"] is not None},
        ),
        (MemoryFactRow, "facts", {item for scope in scopes for item in scope["fact_ids"]}),
        (
            MemoryDocumentRow,
            "documents",
            {item for scope in scopes for item in scope["document_ids"]},
        ),
        (MemoryChunkRow, "chunks", {item for scope in scopes for item in scope["chunk_ids"]}),
    )
    if manifest.get("schema_version") == "memory-comparison-projection-manifest.v2":
        exact_identities += (
            (
                MemoryEpisodeRow,
                "episodes",
                {item for scope in scopes for item in scope["episode_ids"]},
            ),
        )
    for model, count_field, expected_ids in exact_identities:
        rows = set(
            (str(identity), status)
            for identity, status in (
                await session.execute(
                    select(model.id, model.status).where(model.space_id == record.space_id)
                )
            ).all()
        )
        if getattr(receipt.counts, count_field) != len(expected_ids) or rows != {
            (identity, "deleted") for identity in expected_ids
        }:
            raise MemoryConflictError("Benchmark canonical tombstones are incomplete")
    if manifest.get("schema_version") != "memory-comparison-projection-manifest.v2":
        episode_statuses = tuple(
            (
                await session.execute(
                    select(MemoryEpisodeRow.status).where(
                        MemoryEpisodeRow.space_id == record.space_id
                    )
                )
            ).scalars()
        )
        if len(episode_statuses) != receipt.counts.episodes or any(
            status != "deleted" for status in episode_statuses
        ):
            raise MemoryConflictError("Benchmark canonical tombstones are incomplete")
    for model in _UNSUPPORTED_MODELS:
        found = await session.scalar(
            select(model.space_id).where(model.space_id == record.space_id).limit(1)
        )
        if found is not None:
            raise MemoryConflictError("Benchmark canonical inventory contains unsupported rows")


async def require_exact_cleanup_outbox_completion(
    session: AsyncSession,
    *,
    record: BenchmarkRunRegistryRecord,
) -> None:
    receipt = record.cleanup_receipt
    manifest = record.projection_manifest_json
    if receipt is None or manifest is None:
        raise MemoryConflictError("Benchmark cleanup proof inputs are incomplete")
    lane_ids = (
        receipt.vector_delete_outbox_ids,
        receipt.graph_delete_outbox_ids,
        receipt.cognee_delete_outbox_ids,
    )
    if any(ids != tuple(sorted(ids)) for ids in lane_ids):
        raise MemoryConflictError("Benchmark cleanup outbox receipt is not canonical")
    all_ids = tuple(item for lane in lane_ids for item in lane)
    rows = (
        tuple((await session.execute(_cleanup_outbox_rows_query(all_ids))).scalars())
        if all_ids
        else ()
    )
    if tuple(row.id for row in rows) != tuple(sorted(all_ids)):
        raise MemoryConflictError("Benchmark cleanup outbox proof is incomplete")
    by_id = {row.id: row for row in rows}
    scopes = manifest["scopes"]
    chunk_ids = sorted(item for scope in scopes for item in scope["chunk_ids"])
    fact_ids = sorted(item for scope in scopes for item in scope["fact_ids"])
    documents = {
        document_id: scope["memory_scope_id"]
        for scope in scopes
        for document_id in scope["document_ids"]
    }
    _require_vector_jobs(by_id, receipt.vector_delete_outbox_ids, record, chunk_ids)
    _require_graph_jobs(by_id, receipt.graph_delete_outbox_ids, record, fact_ids)
    await _require_cognee_jobs(
        session,
        by_id,
        receipt.cognee_delete_outbox_ids,
        record,
        documents,
    )


async def unsealed_abort_cleanup_verification_sha256(
    session: AsyncSession,
    *,
    record: BenchmarkRunRegistryRecord,
) -> str:
    """Verify exact tombstones and completed delete jobs without provider calls."""

    receipt = record.cleanup_receipt
    if (
        receipt is None
        or receipt.projection_cleanup != "blocked"
        or record.projection_manifest_json is not None
        or record.projection_manifest_sha256 is not None
    ):
        raise MemoryConflictError("Benchmark unsealed abort proof inputs are incomplete")
    space = await session.get(MemorySpaceRow, record.space_id)
    if space is None or space.slug != record.space_slug or space.status != "deleted":
        raise MemoryConflictError("Benchmark canonical space tombstone is incomplete")

    inventories: dict[str, list[str]] = {}
    models = (
        (MemoryFactRow, "facts"),
        (MemoryDocumentRow, "documents"),
        (MemoryChunkRow, "chunks"),
        (MemoryEpisodeRow, "episodes"),
        (MemoryThreadRow, "threads"),
        (MemoryScopeRow, "memory_scopes"),
    )
    for model, count_field in models:
        rows = tuple(
            (
                await session.execute(
                    select(model.id, model.status)
                    .where(model.space_id == record.space_id)
                    .order_by(model.id)
                )
            ).all()
        )
        if len(rows) != getattr(receipt.counts, count_field) or any(
            status != "deleted" for _, status in rows
        ):
            raise MemoryConflictError("Benchmark canonical tombstones are incomplete")
        inventories[count_field] = [str(identity) for identity, _ in rows]
    for model in _UNSUPPORTED_MODELS:
        found = await session.scalar(
            select(model.space_id).where(model.space_id == record.space_id).limit(1)
        )
        if found is not None:
            raise MemoryConflictError("Benchmark canonical inventory contains unsupported rows")

    lane_ids = (
        receipt.vector_delete_outbox_ids,
        receipt.graph_delete_outbox_ids,
        receipt.cognee_delete_outbox_ids,
    )
    if any(ids != tuple(sorted(ids)) for ids in lane_ids):
        raise MemoryConflictError("Benchmark cleanup outbox receipt is not canonical")
    all_ids = tuple(item for lane in lane_ids for item in lane)
    rows = (
        tuple((await session.execute(_cleanup_outbox_rows_query(all_ids))).scalars())
        if all_ids
        else ()
    )
    if tuple(row.id for row in rows) != tuple(sorted(all_ids)):
        raise MemoryConflictError("Benchmark cleanup outbox proof is incomplete")
    by_id = {row.id: row for row in rows}
    _require_vector_jobs(
        by_id,
        receipt.vector_delete_outbox_ids,
        record,
        inventories["chunks"],
    )
    _require_graph_jobs(
        by_id,
        receipt.graph_delete_outbox_ids,
        record,
        inventories["facts"],
    )
    documents = dict(
        (str(document_id), str(memory_scope_id))
        for document_id, memory_scope_id in (
            await session.execute(
                select(MemoryDocumentRow.id, MemoryDocumentRow.memory_scope_id)
                .where(MemoryDocumentRow.space_id == record.space_id)
                .order_by(MemoryDocumentRow.id)
            )
        ).all()
    )
    await _require_cognee_jobs(
        session,
        by_id,
        receipt.cognee_delete_outbox_ids,
        record,
        documents,
    )
    return _json_sha256(
        {
            "schema_version": "memory-comparison-unsealed-abort-verification.v1",
            "run_id_sha256": record.run_id_sha256,
            "binding_commitment_sha256": record.binding_commitment_sha256,
            "infinity_target_identity_sha256": record.infinity_target_identity_sha256,
            "space_id": record.space_id,
            "space_slug": record.space_slug,
            "cleanup_initiation_receipt_sha256": receipt.receipt_sha256,
            "canonical_inventory": inventories,
            "delete_outbox_ids": [list(ids) for ids in lane_ids],
        }
    )


def _cleanup_outbox_rows_query(
    outbox_ids: tuple[int, ...],
) -> Select[tuple[MemoryOutboxRow]]:
    return (
        select(MemoryOutboxRow)
        .where(MemoryOutboxRow.id.in_(outbox_ids))
        .order_by(MemoryOutboxRow.id)
        .with_for_update()
    )


def _require_vector_jobs(
    by_id: dict[int, MemoryOutboxRow],
    ids: tuple[int, ...],
    record: BenchmarkRunRegistryRecord,
    chunk_ids: list[str],
) -> None:
    expected_count = 1 if chunk_ids else 0
    if len(ids) != expected_count:
        raise MemoryConflictError("Benchmark vector cleanup outbox proof conflicted")
    if not ids:
        return
    _require_versioned_vector_job(by_id[ids[0]], record=record, chunk_ids=chunk_ids)


def _require_versioned_vector_job(
    row: MemoryOutboxRow,
    *,
    record: BenchmarkRunRegistryRecord,
    chunk_ids: list[str],
) -> None:
    payload = row.payload_json
    versions = payload.get("chunk_versions")
    expected_base = {
        "chunk_ids": chunk_ids,
        "space_id": record.space_id,
        "cleanup_run_id_sha256": record.run_id_sha256,
    }
    if (
        row.status != "done"
        or row.event_type != "vector.delete_chunks"
        or row.aggregate_type != "benchmark_run"
        or row.aggregate_id != record.run_id_sha256
        or {key: value for key, value in payload.items() if key != "chunk_versions"}
        != expected_base
        or not _valid_chunk_versions(versions, chunk_ids)
    ):
        raise MemoryConflictError("Benchmark cleanup outbox proof conflicted")


def _valid_chunk_versions(value: object, chunk_ids: list[str]) -> bool:
    if not isinstance(value, list) or len(value) != len(chunk_ids):
        return False
    parsed: list[str] = []
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) != {"chunk_id", "canonical_version"}
            or not isinstance(item["chunk_id"], str)
            or not isinstance(item["canonical_version"], int)
            or isinstance(item["canonical_version"], bool)
            or not 1 <= item["canonical_version"] <= 9_007_199_254_740_991
        ):
            return False
        parsed.append(item["chunk_id"])
    return parsed == chunk_ids and len(parsed) == len(set(parsed))


def _require_graph_jobs(
    by_id: dict[int, MemoryOutboxRow],
    ids: tuple[int, ...],
    record: BenchmarkRunRegistryRecord,
    fact_ids: list[str],
) -> None:
    if len(ids) not in {0, len(fact_ids)}:
        raise MemoryConflictError("Benchmark graph cleanup outbox proof conflicted")
    if not ids:
        return
    for outbox_id, fact_id in zip(ids, fact_ids, strict=True):
        _require_job(
            by_id[outbox_id],
            event_type="graph.delete_fact",
            aggregate_id=fact_id,
            payload={
                "fact_id": fact_id,
                "space_id": record.space_id,
                "cleanup_run_id_sha256": record.run_id_sha256,
            },
        )


async def _require_cognee_jobs(
    session: AsyncSession,
    by_id: dict[int, MemoryOutboxRow],
    ids: tuple[int, ...],
    record: BenchmarkRunRegistryRecord,
    documents: dict[str, str],
) -> None:
    document_ids = sorted(documents)
    if len(ids) not in {0, len(document_ids)}:
        raise MemoryConflictError("Benchmark Cognee cleanup outbox proof conflicted")
    if not ids:
        return
    chunks_by_document = {
        document_id: sorted(
            str(value)
            for value in (
                await session.execute(
                    select(MemoryChunkRow.id).where(
                        MemoryChunkRow.document_id == document_id,
                        MemoryChunkRow.space_id == record.space_id,
                    )
                )
            ).scalars()
        )
        for document_id in document_ids
    }
    for outbox_id, document_id in zip(ids, document_ids, strict=True):
        memory_scope_id = documents[document_id]
        _require_job(
            by_id[outbox_id],
            event_type="cognee.forget_document",
            aggregate_id=document_id,
            payload={
                "document_id": document_id,
                "chunk_ids": chunks_by_document[document_id],
                "space_id": record.space_id,
                "memory_scope_id": memory_scope_id,
                "cleanup_run_id_sha256": record.run_id_sha256,
            },
        )


def _require_job(
    row: MemoryOutboxRow,
    *,
    event_type: str,
    aggregate_id: str,
    payload: dict[str, object],
) -> None:
    if (
        row.status != "done"
        or row.event_type != event_type
        or row.aggregate_type != "benchmark_run"
        or row.aggregate_id != aggregate_id
        or row.payload_json != payload
    ):
        raise MemoryConflictError("Benchmark cleanup outbox proof conflicted")


def build_completion_receipt(
    *,
    record: BenchmarkRunRegistryRecord,
    projection_absence_proof_sha256: str,
    completed_at: datetime,
) -> BenchmarkCleanupCompletionReceipt:
    if record.projection_manifest_sha256 is None or record.cleanup_receipt is None:
        raise MemoryConflictError("Benchmark cleanup proof inputs are incomplete")
    material: dict[str, object] = {
        "run_id_sha256": record.run_id_sha256,
        "space_id": record.space_id,
        "space_slug": record.space_slug,
        "disposition": "cleanup_complete",
        "projection_cleanup": "complete",
        "projection_manifest_sha256": record.projection_manifest_sha256,
        "cleanup_initiation_receipt_sha256": record.cleanup_receipt.receipt_sha256,
        "projection_absence_proof_sha256": projection_absence_proof_sha256,
        "completed_at": _timestamp_json(completed_at),
    }
    return BenchmarkCleanupCompletionReceipt(
        run_id_sha256=record.run_id_sha256,
        space_id=record.space_id,
        space_slug=record.space_slug,
        disposition="cleanup_complete",
        projection_cleanup="complete",
        projection_manifest_sha256=record.projection_manifest_sha256,
        cleanup_initiation_receipt_sha256=record.cleanup_receipt.receipt_sha256,
        projection_absence_proof_sha256=projection_absence_proof_sha256,
        completed_at=_parse_timestamp(material["completed_at"]),
        receipt_sha256=_json_sha256(material),
    )


def completion_receipt_json(
    receipt: BenchmarkCleanupCompletionReceipt,
) -> dict[str, object]:
    return {
        "run_id_sha256": receipt.run_id_sha256,
        "space_id": receipt.space_id,
        "space_slug": receipt.space_slug,
        "disposition": receipt.disposition,
        "projection_cleanup": receipt.projection_cleanup,
        "projection_manifest_sha256": receipt.projection_manifest_sha256,
        "cleanup_initiation_receipt_sha256": receipt.cleanup_initiation_receipt_sha256,
        "projection_absence_proof_sha256": receipt.projection_absence_proof_sha256,
        "completed_at": _timestamp_json(receipt.completed_at),
        "receipt_sha256": receipt.receipt_sha256,
    }


def completion_receipt_from_json(
    value: dict[str, object],
) -> BenchmarkCleanupCompletionReceipt:
    expected = {
        "run_id_sha256",
        "space_id",
        "space_slug",
        "disposition",
        "projection_cleanup",
        "projection_manifest_sha256",
        "cleanup_initiation_receipt_sha256",
        "projection_absence_proof_sha256",
        "completed_at",
        "receipt_sha256",
    }
    if type(value) is not dict or set(value) != expected:
        raise RuntimeError("benchmark_cleanup_completion_receipt_invalid")
    digest_fields = (
        "run_id_sha256",
        "projection_manifest_sha256",
        "cleanup_initiation_receipt_sha256",
        "projection_absence_proof_sha256",
        "receipt_sha256",
    )
    if (
        any(not _valid_digest(value[field]) for field in digest_fields)
        or type(value["space_id"]) is not str
        or not value["space_id"]
        or type(value["space_slug"]) is not str
        or not value["space_slug"]
        or value["disposition"] != "cleanup_complete"
        or value["projection_cleanup"] != "complete"
    ):
        raise RuntimeError("benchmark_cleanup_completion_receipt_invalid")
    completed_at = _parse_timestamp(value["completed_at"])
    material = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if not hmac.compare_digest(str(value["receipt_sha256"]), _json_sha256(material)):
        raise RuntimeError("benchmark_cleanup_completion_receipt_invalid")
    return BenchmarkCleanupCompletionReceipt(
        run_id_sha256=value["run_id_sha256"],
        space_id=value["space_id"],
        space_slug=value["space_slug"],
        disposition="cleanup_complete",
        projection_cleanup="complete",
        projection_manifest_sha256=value["projection_manifest_sha256"],
        cleanup_initiation_receipt_sha256=value["cleanup_initiation_receipt_sha256"],
        projection_absence_proof_sha256=value["projection_absence_proof_sha256"],
        completed_at=completed_at,
        receipt_sha256=value["receipt_sha256"],
    )


def build_abort_completion_receipt(
    *,
    record: BenchmarkRunRegistryRecord,
    projection_absence_proof_sha256: str,
    completed_at: datetime,
) -> BenchmarkAbortCompletionReceipt:
    if (
        record.cleanup_receipt is None
        or record.cleanup_plan_sha256 is None
        or not _valid_digest(projection_absence_proof_sha256)
    ):
        raise MemoryConflictError("Benchmark abort proof inputs are incomplete")
    material: dict[str, object] = {
        "run_id_sha256": record.run_id_sha256,
        "binding_commitment_sha256": record.binding_commitment_sha256,
        "infinity_target_identity_sha256": record.infinity_target_identity_sha256,
        "space_id": record.space_id,
        "space_slug": record.space_slug,
        "disposition": "abort_complete",
        "projection_cleanup": "unsealed_abort_complete",
        "cleanup_initiation_receipt_sha256": record.cleanup_receipt.receipt_sha256,
        "cleanup_plan_sha256": record.cleanup_plan_sha256,
        "projection_absence_proof_sha256": projection_absence_proof_sha256,
        "completed_at": _timestamp_json(completed_at),
    }
    return BenchmarkAbortCompletionReceipt(
        run_id_sha256=record.run_id_sha256,
        binding_commitment_sha256=record.binding_commitment_sha256,
        infinity_target_identity_sha256=record.infinity_target_identity_sha256,
        space_id=record.space_id,
        space_slug=record.space_slug,
        disposition="abort_complete",
        projection_cleanup="unsealed_abort_complete",
        cleanup_initiation_receipt_sha256=record.cleanup_receipt.receipt_sha256,
        cleanup_plan_sha256=record.cleanup_plan_sha256,
        projection_absence_proof_sha256=projection_absence_proof_sha256,
        completed_at=_parse_timestamp(material["completed_at"]),
        receipt_sha256=_json_sha256(material),
    )


def abort_completion_receipt_json(
    receipt: BenchmarkAbortCompletionReceipt,
) -> dict[str, object]:
    return {
        "run_id_sha256": receipt.run_id_sha256,
        "binding_commitment_sha256": receipt.binding_commitment_sha256,
        "infinity_target_identity_sha256": receipt.infinity_target_identity_sha256,
        "space_id": receipt.space_id,
        "space_slug": receipt.space_slug,
        "disposition": receipt.disposition,
        "projection_cleanup": receipt.projection_cleanup,
        "cleanup_initiation_receipt_sha256": receipt.cleanup_initiation_receipt_sha256,
        "cleanup_plan_sha256": receipt.cleanup_plan_sha256,
        "projection_absence_proof_sha256": receipt.projection_absence_proof_sha256,
        "completed_at": _timestamp_json(receipt.completed_at),
        "receipt_sha256": receipt.receipt_sha256,
    }


def abort_completion_receipt_from_json(
    value: dict[str, object],
) -> BenchmarkAbortCompletionReceipt:
    expected = {
        "run_id_sha256",
        "binding_commitment_sha256",
        "infinity_target_identity_sha256",
        "space_id",
        "space_slug",
        "disposition",
        "projection_cleanup",
        "cleanup_initiation_receipt_sha256",
        "cleanup_plan_sha256",
        "projection_absence_proof_sha256",
        "completed_at",
        "receipt_sha256",
    }
    digest_fields = (
        "run_id_sha256",
        "binding_commitment_sha256",
        "infinity_target_identity_sha256",
        "cleanup_initiation_receipt_sha256",
        "cleanup_plan_sha256",
        "projection_absence_proof_sha256",
        "receipt_sha256",
    )
    if (
        type(value) is not dict
        or set(value) != expected
        or any(not _valid_digest(value[field]) for field in digest_fields)
        or type(value["space_id"]) is not str
        or not value["space_id"]
        or type(value["space_slug"]) is not str
        or not value["space_slug"]
        or value["disposition"] != "abort_complete"
        or value["projection_cleanup"] != "unsealed_abort_complete"
    ):
        raise RuntimeError("benchmark_abort_completion_receipt_invalid")
    completed_at = _parse_timestamp(value["completed_at"])
    material = {key: item for key, item in value.items() if key != "receipt_sha256"}
    if not hmac.compare_digest(str(value["receipt_sha256"]), _json_sha256(material)):
        raise RuntimeError("benchmark_abort_completion_receipt_invalid")
    return BenchmarkAbortCompletionReceipt(
        run_id_sha256=value["run_id_sha256"],
        binding_commitment_sha256=value["binding_commitment_sha256"],
        infinity_target_identity_sha256=value["infinity_target_identity_sha256"],
        space_id=value["space_id"],
        space_slug=value["space_slug"],
        disposition="abort_complete",
        projection_cleanup="unsealed_abort_complete",
        cleanup_initiation_receipt_sha256=value["cleanup_initiation_receipt_sha256"],
        cleanup_plan_sha256=value["cleanup_plan_sha256"],
        projection_absence_proof_sha256=value["projection_absence_proof_sha256"],
        completed_at=completed_at,
        receipt_sha256=value["receipt_sha256"],
    )


def same_completion_timestamp(left: datetime, right: datetime) -> bool:
    try:
        database_value = right.replace(tzinfo=UTC) if right.tzinfo is None else right
        return _timestamp_json(left) == _timestamp_json(database_value)
    except (AttributeError, RuntimeError):
        return False


def _timestamp_json(value: datetime) -> str:
    if type(value) is not datetime or value.tzinfo is None:
        raise RuntimeError("benchmark_cleanup_completion_receipt_invalid")
    utc = value.astimezone(UTC)
    return utc.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise RuntimeError("benchmark_cleanup_completion_receipt_invalid")
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError:
        raise RuntimeError("benchmark_cleanup_completion_receipt_invalid") from None
    if _timestamp_json(parsed) != value:
        raise RuntimeError("benchmark_cleanup_completion_receipt_invalid")
    return parsed


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


__all__ = (
    "abort_completion_receipt_from_json",
    "abort_completion_receipt_json",
    "build_abort_completion_receipt",
    "build_completion_receipt",
    "completion_receipt_from_json",
    "completion_receipt_json",
    "require_canonical_tombstones",
    "require_exact_cleanup_outbox_completion",
    "same_completion_timestamp",
    "unsealed_abort_cleanup_verification_sha256",
)
