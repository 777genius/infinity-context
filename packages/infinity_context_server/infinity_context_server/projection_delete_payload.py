"""Shared validation for exact version-fenced projection delete payloads."""

from __future__ import annotations

from collections.abc import Sequence

from infinity_context_adapters.postgres.models import MemoryOutboxRow
from infinity_context_core.domain.errors import MemoryConflictError


def require_versioned_chunk_delete_job(
    rows: Sequence[MemoryOutboxRow],
    *,
    aggregate_id: str,
    chunk_ids: list[str],
    metadata: dict[str, object],
) -> None:
    if len(rows) != 1:
        raise MemoryConflictError("Benchmark vector cleanup outbox proof conflicted")
    row = rows[0]
    if (
        row.event_type != "vector.delete_chunks"
        or row.aggregate_type != "benchmark_run"
        or row.aggregate_id != aggregate_id
        or not valid_versioned_chunk_delete_payload(
            row.payload_json,
            chunk_ids=chunk_ids,
            metadata=metadata,
        )
    ):
        raise MemoryConflictError("Benchmark cleanup outbox proof conflicted")


def valid_versioned_chunk_delete_payload(
    value: object,
    *,
    chunk_ids: list[str],
    metadata: dict[str, object],
) -> bool:
    if not isinstance(value, dict):
        return False
    versions = value.get("chunk_versions")
    if {key: item for key, item in value.items() if key != "chunk_versions"} != {
        "chunk_ids": chunk_ids,
        **metadata,
    }:
        return False
    if not isinstance(versions, list) or len(versions) != len(chunk_ids):
        return False
    parsed: list[str] = []
    for item in versions:
        if (
            not isinstance(item, dict)
            or set(item) != {"chunk_id", "canonical_version"}
            or not isinstance(item["chunk_id"], str)
            or not isinstance(item["canonical_version"], int)
            or isinstance(item["canonical_version"], bool)
            or item["canonical_version"] <= 0
        ):
            return False
        parsed.append(item["chunk_id"])
    return parsed == chunk_ids and len(parsed) == len(set(parsed))


__all__ = (
    "require_versioned_chunk_delete_job",
    "valid_versioned_chunk_delete_payload",
)
