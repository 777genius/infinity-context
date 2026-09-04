"""Pure mappings shared by the Postgres Retrieval profile adapters."""

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
from sqlalchemy import exists, select

from infinity_context_adapters.postgres.models import (
    MemoryChunkRow,
    MemoryDocumentRow,
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
        parent_eligible_condition(),
    )


def parent_eligible_condition() -> object:
    """Require the exact canonical document binding, not merely a live chunk."""

    return exists(
        select(MemoryDocumentRow.id).where(
            MemoryDocumentRow.id == MemoryChunkRow.document_id,
            MemoryDocumentRow.space_id == MemoryChunkRow.space_id,
            MemoryDocumentRow.memory_scope_id == MemoryChunkRow.memory_scope_id,
            MemoryDocumentRow.thread_id.is_not_distinct_from(MemoryChunkRow.thread_id),
            MemoryDocumentRow.source_type == MemoryChunkRow.source_type,
            MemoryDocumentRow.source_external_id == MemoryChunkRow.source_external_id,
            MemoryDocumentRow.classification == MemoryChunkRow.classification,
            MemoryDocumentRow.status == "active",
            MemoryDocumentRow.retrieval_projected.is_(True),
        )
    )


def eligible_value(row: MemoryChunkRow, parent: MemoryDocumentRow | None) -> tuple[bool, ...]:
    return (
        row.retrieval_locator is not None,
        row.status == "active",
        row.classification in ("public", "internal"),
        parent is not None,
        parent is not None and parent.id == row.document_id,
        parent is not None and parent.space_id == row.space_id,
        parent is not None and parent.memory_scope_id == row.memory_scope_id,
        parent is not None and parent.thread_id == row.thread_id,
        parent is not None and parent.source_type == row.source_type,
        parent is not None and parent.source_external_id == row.source_external_id,
        parent is not None and parent.classification == row.classification,
        parent is not None and parent.status == "active",
        parent is not None and bool(parent.retrieval_projected),
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
