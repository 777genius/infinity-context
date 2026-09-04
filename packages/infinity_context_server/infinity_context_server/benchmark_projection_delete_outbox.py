"""Bounded validation for exact managed benchmark projection-delete outbox jobs."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_adapters.postgres.models import MemoryOutboxRow
from infinity_context_core.domain.errors import MemoryConflictError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infinity_context_server import projection_delete_payload

_MAX_DELETE_OUTBOX_IDS = 5_000


@dataclass(frozen=True, slots=True)
class SealedBenchmarkDeleteScope:
    manifest_scope: dict[str, object]
    run_id_sha256: str
    all_chunk_ids: tuple[str, ...]
    all_fact_ids: tuple[str, ...]
    all_episode_ids: tuple[str, ...] = ()


def validate_delete_outbox_ids(value: tuple[int, ...] | None) -> None:
    if value is None:
        return
    if (
        type(value) is not tuple
        or len(value) > _MAX_DELETE_OUTBOX_IDS
        or any(type(item) is not int or item <= 0 for item in value)
        or value != tuple(sorted(value))
        or len(value) != len(set(value))
    ):
        raise MemoryConflictError("Projection delete outbox receipt is invalid")


def projection_manifest_ids(
    manifest: dict[str, object],
    field_name: str,
) -> tuple[str, ...]:
    scopes = manifest.get("scopes")
    if type(scopes) is not list:
        raise MemoryConflictError("Projection manifest scopes are invalid")
    identities: list[str] = []
    for scope in scopes:
        if type(scope) is not dict or type(scope.get(field_name)) is not list:
            raise MemoryConflictError("Projection manifest identities are invalid")
        values = scope[field_name]
        if any(type(value) is not str for value in values):
            raise MemoryConflictError("Projection manifest identities are invalid")
        identities.extend(values)
    return tuple(sorted(identities))


async def load_exact_projection_delete_events(
    session: AsyncSession,
    *,
    event_type: str,
    expected_ids: tuple[str, ...],
    exact_outbox_ids: tuple[int, ...],
    space_id: str,
    sealed_scope: SealedBenchmarkDeleteScope,
) -> list[MemoryOutboxRow]:
    """Load only receipt-bound rows and validate the complete run-level lane."""

    validate_delete_outbox_ids(exact_outbox_ids)
    all_expected = (
        sealed_scope.all_chunk_ids
        if event_type == "vector.delete_chunks"
        else sealed_scope.all_fact_ids
    )
    if not set(expected_ids).issubset(all_expected):
        raise MemoryConflictError("Projection delete outbox scope conflicted")

    if not exact_outbox_ids:
        if event_type == "vector.delete_chunks" and all_expected:
            raise MemoryConflictError("Benchmark vector cleanup outbox proof conflicted")
        return []

    rows = list(
        (
            await session.execute(
                select(MemoryOutboxRow)
                .where(MemoryOutboxRow.id.in_(exact_outbox_ids))
                .order_by(MemoryOutboxRow.id)
            )
        ).scalars()
    )
    if tuple(row.id for row in rows) != exact_outbox_ids:
        raise MemoryConflictError("Projection delete outbox proof is incomplete")
    if any(row.status != "done" for row in rows):
        raise MemoryConflictError("Relevant projection outbox work is not terminal")

    if event_type == "vector.delete_chunks":
        projection_delete_payload.require_versioned_chunk_delete_job(
            rows,
            aggregate_id=sealed_scope.run_id_sha256,
            chunk_ids=list(sealed_scope.all_chunk_ids),
            metadata={
                "space_id": space_id,
                "cleanup_run_id_sha256": sealed_scope.run_id_sha256,
            },
        )
    elif event_type == "graph.delete_fact":
        _require_graph_jobs(rows, sealed_scope, space_id)
    else:
        raise MemoryConflictError("Projection delete outbox event type is unsupported")
    return rows


def _require_graph_jobs(
    rows: list[MemoryOutboxRow],
    sealed_scope: SealedBenchmarkDeleteScope,
    space_id: str,
) -> None:
    if len(rows) != len(sealed_scope.all_fact_ids):
        raise MemoryConflictError("Benchmark graph cleanup outbox proof conflicted")
    for row, fact_id in zip(rows, sealed_scope.all_fact_ids, strict=True):
        _require_job(
            row,
            event_type="graph.delete_fact",
            aggregate_id=fact_id,
            payload={
                "fact_id": fact_id,
                "space_id": space_id,
                "cleanup_run_id_sha256": sealed_scope.run_id_sha256,
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
        row.event_type != event_type
        or row.aggregate_type != "benchmark_run"
        or row.aggregate_id != aggregate_id
        or row.payload_json != payload
    ):
        raise MemoryConflictError("Benchmark cleanup outbox proof conflicted")


__all__ = (
    "SealedBenchmarkDeleteScope",
    "load_exact_projection_delete_events",
    "projection_manifest_ids",
    "validate_delete_outbox_ids",
)
