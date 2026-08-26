"""Pure mappings shared by the Postgres Retrieval V2 profile adapters."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from infinity_context_core.features.context_building.public import (
    CanonicalProjectionItem,
    ProfileCleanup,
    ProfileCoverageAttestation,
    RetrievalProfileIdentity,
)

from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryLocatorProfileCleanupRow,
    MemoryLocatorProfileRow,
)

ROUTABLE_PROFILE_STATES = ("building", "active", "retained")


def profile_identity(row: MemoryLocatorProfileRow) -> RetrievalProfileIdentity:
    return RetrievalProfileIdentity(
        row.profile_id, row.generation, row.profile_digest, row.collection_name
    )


def profile_cleanup(
    profile: MemoryLocatorProfileRow, row: MemoryLocatorProfileCleanupRow
) -> ProfileCleanup:
    return ProfileCleanup(
        identity=profile_identity(profile),
        phase=row.phase,
        attempt_count=row.attempt_count,
        last_error_code=row.last_error_code,
    )


def require_building(row: MemoryLocatorProfileRow | None) -> None:
    if row is None or row.state != "building":
        raise RuntimeError("retrieval_profile_not_building")


def require_routable(row: MemoryLocatorProfileRow | None) -> None:
    if row is None or row.state not in ROUTABLE_PROFILE_STATES:
        raise RuntimeError("retrieval_profile_not_routable")


def require_promotable(row: MemoryLocatorProfileRow | None) -> None:
    if row is None or row.state not in ("building", "retained"):
        raise RuntimeError("retrieval_profile_not_promotable")


def eligible_conditions() -> tuple[object, ...]:
    return (
        MemoryChunkRow.retrieval_locator.is_not(None),
        MemoryChunkRow.status == "active",
        MemoryChunkRow.classification.in_(("public", "internal")),
    )


def eligible_value(row: MemoryChunkRow) -> tuple[bool, bool, bool]:
    return (
        row.retrieval_locator is not None,
        row.status == "active",
        row.classification in ("public", "internal"),
    )


def projection_item(row: MemoryChunkRow) -> CanonicalProjectionItem:
    metadata = {
        "actor_keys": list(row.retrieval_actor_keys_json),
        "canonical_identity": str(row.id),
        "canonical_version": int(row.retrieval_version),
        "category": row.retrieval_category,
        "chunk_key": str(row.id),
        "document_key": str(row.document_id or ""),
        "end_at": _json_time(row.retrieval_end_at),
        "kind": row.retrieval_kind,
        "lifecycle_status": "active",
        "locator": row.retrieval_locator,
        "projection_generation": row.retrieval_projection_generation,
        "projection_version": "document-retrieval-projection.v1",
        "relative_end_ms": row.retrieval_relative_end_ms,
        "relative_start_ms": row.retrieval_relative_start_ms,
        "sequence_ordinal": row.retrieval_sequence_ordinal,
        "source_key": row.retrieval_source_key,
        "space_id": str(row.space_id),
        "memory_scope_id": str(row.memory_scope_id),
        "thread_id": str(row.thread_id) if row.thread_id is not None else None,
        "start_at": _json_time(row.retrieval_start_at),
        "tags": list(row.retrieval_tags_json),
    }
    encoded = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()
    return CanonicalProjectionItem(
        canonical_identity=str(row.id),
        canonical_version=int(row.retrieval_version),
        canonical_watermark=int(row.retrieval_commit_watermark),
        payload_digest=hashlib.sha256(encoded).hexdigest(),
        space_id=str(row.space_id),
        memory_scope_id=str(row.memory_scope_id),
        thread_id=str(row.thread_id) if row.thread_id is not None else None,
        text=row.normalized_text,
        vector_metadata=tuple(metadata.items()),
    )


def profile_coverage(row: MemoryLocatorProfileRow) -> ProfileCoverageAttestation:
    return ProfileCoverageAttestation(
        expected_count=int(row.expected_count),
        projected_count=int(row.projected_count),
        expected_digest=row.expected_digest,
        projected_digest=row.projected_digest,
        canonical_watermark=int(row.canonical_watermark),
        projected_watermark=int(row.projected_watermark),
        backfill_complete=bool(row.backfill_complete),
    )


def _json_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
