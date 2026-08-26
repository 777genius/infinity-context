"""Postgres-canonical recovery inventory for unsealed benchmark cleanup."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

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
    MemoryScopeRow,
    MemorySourceRefRow,
    MemorySpaceRow,
    MemorySuggestionRow,
    MemoryThreadRow,
)
from infinity_context_core.domain.errors import MemoryConflictError
from infinity_context_core.ports.benchmark_cleanup_plan import (
    MAX_CLEANUP_PLAN_RECOVERY_ROWS_PER_KIND,
    MAX_CLEANUP_PLAN_RECOVERY_TOTAL_ROWS,
    validate_managed_benchmark_cleanup_plan,
)
from infinity_context_core.ports.benchmark_runs import BenchmarkRunRegistryRecord
from infinity_context_core.ports.benchmark_unsealed_projection import (
    BenchmarkUnsealedRecoveryInventory,
)
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from infinity_context_server.benchmark_unsealed_inventory_validation import (
    projection_scopes as _projection_scopes,
)
from infinity_context_server.benchmark_unsealed_inventory_validation import (
    require_chunk_source_hashes,
    require_managed_inventory_links,
)
from infinity_context_server.benchmark_unsealed_outbox_validation import (
    require_exact_delete_jobs as _require_exact_delete_jobs,
)
from infinity_context_server.benchmark_unsealed_outbox_validation import (
    require_obsolete_upsert_count,
    require_obsolete_upserts_pruned,
)

MAX_RECOVERY_ROWS_PER_KIND = MAX_CLEANUP_PLAN_RECOVERY_ROWS_PER_KIND
MAX_RECOVERY_TOTAL_ROWS = MAX_CLEANUP_PLAN_RECOVERY_TOTAL_ROWS
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


class ServerBenchmarkUnsealedRecoveryInventory:
    """Load a bounded exact allowlist for one registered benchmark space."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def load_inventory(
        self, *, record: BenchmarkRunRegistryRecord
    ) -> BenchmarkUnsealedRecoveryInventory:
        plan = _validated_plan(record)
        receipt = record.cleanup_receipt
        if receipt is None or receipt.projection_cleanup != "blocked":
            raise MemoryConflictError("Unsealed cleanup receipt is missing")
        async with AsyncSession(self._engine) as session:
            space = await session.get(MemorySpaceRow, record.space_id)
            if space is None or space.slug != record.space_slug or space.status != "deleted":
                raise MemoryConflictError("Unsealed canonical space tombstone is incomplete")
            scopes = await _rows(session, MemoryScopeRow, record.space_id)
            threads = await _rows(session, MemoryThreadRow, record.space_id)
            facts = await _rows(session, MemoryFactRow, record.space_id)
            documents = await _rows(session, MemoryDocumentRow, record.space_id)
            chunks = await _rows(session, MemoryChunkRow, record.space_id)
            episodes = await _rows(session, MemoryEpisodeRow, record.space_id)
            expected_fact_refs = plan["cardinality"]["expected_fact_count"]
            fact_source_refs = await _fact_source_refs(
                session,
                facts,
                expected_count=expected_fact_refs,
            )
            rows_by_name = {
                "memory_scopes": scopes,
                "threads": threads,
                "facts": facts,
                "documents": documents,
                "chunks": chunks,
                "episodes": episodes,
            }
            _require_counts_and_tombstones(rows_by_name, receipt.counts)
            _require_caps({**rows_by_name, "fact_source_refs": fact_source_refs})
            await _require_no_unsupported_rows(session, record.space_id)
            await require_obsolete_upserts_pruned(
                session,
                record=record,
                aggregate_ids=tuple(
                    str(row.id) for row in (*facts, *documents, *chunks, *episodes)
                ),
            )
            delete_ids = await _require_exact_delete_jobs(
                session,
                record=record,
                chunks=chunks,
                facts=facts,
                documents=documents,
            )
        require_managed_inventory_links(
            plan,
            scopes=scopes,
            threads=threads,
            episodes=episodes,
            documents=documents,
            chunks=chunks,
            facts=facts,
            fact_source_refs=fact_source_refs,
        )
        require_chunk_source_hashes(chunks)
        scope_inventory = _projection_scopes(scopes, threads, chunks, facts)
        inventory_material = {
            "schema_version": "benchmark-unsealed-recovery-inventory.v1",
            "run_id_sha256": record.run_id_sha256,
            "space_id": record.space_id,
            "cleanup_plan_sha256": record.cleanup_plan_sha256,
            "cleanup_receipt_sha256": receipt.receipt_sha256,
            "obsolete_upsert_jobs": receipt.counts.obsolete_upsert_jobs,
            "scopes": [
                {
                    "memory_scope_id": item.memory_scope_id,
                    "thread_id": item.thread_id,
                    "chunk_ids": list(item.chunk_ids),
                    "fact_ids": list(item.fact_ids),
                }
                for item in scope_inventory
            ],
            "document_source_external_ids": _values(documents, "source_external_id"),
            "episode_source_external_ids": _values(episodes, "source_external_id"),
            "chunk_source_external_ids": _values(chunks, "source_external_id"),
            "chunk_source_hashes": _values(chunks, "source_hash"),
            "fact_source_ref_ids": sorted(row.id for row in fact_source_refs),
            "delete_outbox_ids": list(delete_ids),
        }
        return BenchmarkUnsealedRecoveryInventory(
            run_id_sha256=record.run_id_sha256,
            space_id=record.space_id,
            cleanup_plan_sha256=str(record.cleanup_plan_sha256),
            cleanup_receipt_sha256=receipt.receipt_sha256,
            scopes=scope_inventory,
            document_source_external_ids=tuple(inventory_material["document_source_external_ids"]),
            episode_source_external_ids=tuple(inventory_material["episode_source_external_ids"]),
            chunk_source_external_ids=tuple(inventory_material["chunk_source_external_ids"]),
            chunk_source_hashes=tuple(inventory_material["chunk_source_hashes"]),
            delete_outbox_ids=delete_ids,
            inventory_sha256=_json_sha256(inventory_material),
        )


async def _rows(session: AsyncSession, model: type, space_id: str) -> tuple[object, ...]:
    return tuple(
        (
            await session.execute(
                select(model)
                .where(model.space_id == space_id)
                .order_by(model.id)
                .limit(MAX_RECOVERY_ROWS_PER_KIND + 1)
            )
        ).scalars()
    )


async def _fact_source_refs(
    session: AsyncSession,
    facts: Sequence[MemoryFactRow],
    *,
    expected_count: int,
) -> tuple[MemorySourceRefRow, ...]:
    if (
        type(expected_count) is not int
        or expected_count < 0
        or expected_count > MAX_RECOVERY_ROWS_PER_KIND
    ):
        raise MemoryConflictError("Unsealed fact source reference count exceeds cap")
    if not facts:
        if expected_count:
            raise MemoryConflictError("Unsealed fact source reference count differs")
        return ()
    versions = {(row.id, row.version) for row in facts}
    rows = tuple(
        (
            await session.execute(
                select(MemorySourceRefRow)
                .where(
                    tuple_(
                        MemorySourceRefRow.fact_id,
                        MemorySourceRefRow.fact_version,
                    ).in_(versions)
                )
                .order_by(
                    MemorySourceRefRow.fact_id,
                    MemorySourceRefRow.fact_version,
                    MemorySourceRefRow.id,
                )
                .limit(expected_count + 1)
            )
        ).scalars()
    )
    if len(rows) != expected_count:
        raise MemoryConflictError("Unsealed fact source reference count differs")
    return rows


def _require_counts_and_tombstones(
    rows_by_name: dict[str, tuple[object, ...]], counts: object
) -> None:
    for name, rows in rows_by_name.items():
        if len(rows) != getattr(counts, name) or any(row.status != "deleted" for row in rows):
            raise MemoryConflictError("Unsealed canonical tombstones differ from cleanup receipt")
    require_obsolete_upsert_count(counts)


def _require_caps(rows_by_name: dict[str, tuple[object, ...]]) -> None:
    if any(len(rows) > MAX_RECOVERY_ROWS_PER_KIND for rows in rows_by_name.values()):
        raise MemoryConflictError("Unsealed recovery inventory exceeds per-kind cap")
    if sum(map(len, rows_by_name.values())) > MAX_RECOVERY_TOTAL_ROWS:
        raise MemoryConflictError("Unsealed recovery inventory exceeds total cap")


async def _require_no_unsupported_rows(session: AsyncSession, space_id: str) -> None:
    for model in _UNSUPPORTED_MODELS:
        if await session.scalar(select(model.space_id).where(model.space_id == space_id).limit(1)):
            raise MemoryConflictError("Unsealed canonical inventory contains unsupported rows")


def _validated_plan(record: BenchmarkRunRegistryRecord) -> dict[str, object]:
    plan = record.cleanup_plan_json
    sha256 = record.cleanup_plan_sha256
    if type(plan) is not dict or type(sha256) is not str:
        raise MemoryConflictError("Unsealed cleanup plan is missing or invalid")
    if record.cleanup_plan_state != "sealed":
        raise MemoryConflictError("Unsealed cleanup plan is not recoverable")
    return validate_managed_benchmark_cleanup_plan(
        plan,
        sha256,
        run_id_sha256=record.run_id_sha256,
        binding_commitment_sha256=record.binding_commitment_sha256,
        infinity_target_identity_sha256=record.infinity_target_identity_sha256,
        space_slug=record.space_slug,
    ).value


def _values(rows: Sequence[object], name: str) -> list[str]:
    return sorted(str(getattr(row, name)) for row in rows)


def _json_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


__all__ = ("ServerBenchmarkUnsealedRecoveryInventory",)
