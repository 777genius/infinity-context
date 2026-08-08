"""SQLAlchemy row mapping for feature-owned canonical memory facts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from infinity_context_core.features.memory_facts.public import (
    FactCodeScopeReference,
    FactEpistemicContext,
    FactFreshness,
    FactTemporalExtent,
    MemoryFactEvidenceRef,
    MemoryFactIdentity,
    MemoryFactScope,
    MemoryFactSnapshot,
    MemoryFactSourceRef,
    MemoryFactVisibility,
)

from infinity_context_adapters.postgres.models import (
    MemoryFactRow,
    MemorySourceRefRow,
)

SNAPSHOT_SCHEMA_VERSION = 1


def memory_fact_snapshot_to_row(snapshot: MemoryFactSnapshot) -> MemoryFactRow:
    values = memory_fact_snapshot_row_values(snapshot)
    return MemoryFactRow(id=snapshot.identity.fact_id, **values)


def memory_fact_snapshot_row_values(snapshot: MemoryFactSnapshot) -> dict[str, object]:
    scope = snapshot.identity.scope
    temporal = _snapshot_temporal_extent(snapshot)
    freshness = snapshot.freshness
    epistemic = snapshot.epistemic_context
    code_scope = snapshot.code_scope
    return {
        "space_id": scope.space_id,
        "memory_scope_id": scope.memory_scope_id,
        "thread_id": scope.thread_id,
        "kind": snapshot.kind,
        "text": snapshot.text,
        "status": snapshot.visibility.status,
        "confidence": snapshot.visibility.confidence,
        "trust_level": snapshot.visibility.trust_level,
        "classification": snapshot.visibility.classification,
        "category": snapshot.category,
        "tags_json": list(snapshot.tags),
        "evidence_refs_json": memory_fact_evidence_refs_to_json(snapshot.evidence_refs),
        "ttl_policy": snapshot.visibility.ttl_policy,
        "expires_at": snapshot.visibility.expires_at,
        "temporal_kind": temporal.kind.value,
        "observed_at": temporal.observed_at,
        "valid_from": temporal.valid_from,
        "valid_to": temporal.valid_to,
        "occurred_from": temporal.occurred_from,
        "occurred_to": temporal.occurred_to,
        "temporal_basis": temporal.basis,
        "temporal_precision": temporal.precision,
        "last_confirmed_at": freshness.last_confirmed_at,
        "confirmation_basis": freshness.confirmation_basis,
        "purge_after": snapshot.purge_after,
        "epistemic_mode": epistemic.mode.value,
        "asserted_by": epistemic.asserted_by,
        "perspective_subject": epistemic.perspective_subject,
        "repository_id": code_scope.repository_id if code_scope is not None else None,
        "code_scope_id": code_scope.code_scope_id if code_scope is not None else None,
        "version": snapshot.visibility.version,
        "created_at": _required_datetime("created_at", snapshot.created_at),
        "updated_at": _required_datetime("updated_at", snapshot.updated_at),
    }


def memory_fact_row_to_snapshot(
    row: MemoryFactRow,
    source_refs: list[MemorySourceRefRow],
) -> MemoryFactSnapshot:
    observed_at = _aware(getattr(row, "observed_at", None) or row.created_at)
    last_confirmed_at = _aware_or_none(getattr(row, "last_confirmed_at", None))
    confirmation_basis = getattr(row, "confirmation_basis", None)
    if last_confirmed_at is not None and not confirmation_basis:
        confirmation_basis = "migrated_legacy"
    return MemoryFactSnapshot(
        identity=MemoryFactIdentity(
            fact_id=row.id,
            scope=MemoryFactScope(
                space_id=row.space_id,
                memory_scope_id=row.memory_scope_id,
                thread_id=row.thread_id,
            ),
        ),
        text=row.text,
        source_refs=tuple(memory_fact_source_ref_row_to_domain(ref) for ref in source_refs),
        visibility=MemoryFactVisibility(
            status=row.status,
            version=row.version,
            confidence=row.confidence,
            trust_level=row.trust_level,
            classification=row.classification,
            ttl_policy=row.ttl_policy,
            expires_at=_aware_or_none(row.expires_at),
        ),
        kind=row.kind,
        evidence_refs=memory_fact_evidence_refs_from_json(row.evidence_refs_json),
        category=row.category,
        tags=tuple(row.tags_json or ()),
        created_at=_aware(row.created_at),
        updated_at=_aware(row.updated_at),
        temporal_extent=FactTemporalExtent(
            kind=getattr(row, "temporal_kind", "state") or "state",
            observed_at=observed_at,
            valid_from=_aware_or_none(getattr(row, "valid_from", None)),
            valid_to=_aware_or_none(getattr(row, "valid_to", None)),
            occurred_from=_aware_or_none(getattr(row, "occurred_from", None)),
            occurred_to=_aware_or_none(getattr(row, "occurred_to", None)),
            basis=getattr(row, "temporal_basis", "migrated_legacy") or "migrated_legacy",
            precision=getattr(row, "temporal_precision", "unknown") or "unknown",
        ),
        freshness=FactFreshness(
            last_confirmed_at=last_confirmed_at,
            confirmation_basis=confirmation_basis,
        ),
        epistemic_context=FactEpistemicContext(
            mode=getattr(row, "epistemic_mode", "world_claim") or "world_claim",
            asserted_by=getattr(row, "asserted_by", None),
            perspective_subject=getattr(row, "perspective_subject", None),
        ),
        purge_after=_aware_or_none(getattr(row, "purge_after", None)),
        code_scope=(
            FactCodeScopeReference(
                repository_id=row.repository_id,
                code_scope_id=row.code_scope_id,
            )
            if getattr(row, "repository_id", None) is not None
            else None
        ),
    )


def memory_fact_snapshot_to_json(snapshot: MemoryFactSnapshot) -> dict[str, object]:
    temporal = _snapshot_temporal_extent(snapshot)
    scope = snapshot.identity.scope
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "identity": {
            "fact_id": snapshot.identity.fact_id,
            "space_id": scope.space_id,
            "memory_scope_id": scope.memory_scope_id,
            "thread_id": scope.thread_id,
        },
        "text": snapshot.text,
        "source_refs": [_source_ref_to_json(ref) for ref in snapshot.source_refs],
        "visibility": {
            "status": snapshot.visibility.status,
            "version": snapshot.visibility.version,
            "confidence": snapshot.visibility.confidence,
            "trust_level": snapshot.visibility.trust_level,
            "classification": snapshot.visibility.classification,
            "ttl_policy": snapshot.visibility.ttl_policy,
            "expires_at": _datetime_to_json(snapshot.visibility.expires_at),
        },
        "kind": snapshot.kind,
        "evidence_refs": [
            {
                "evidence_id": evidence.evidence_id,
                "source_ref": _source_ref_to_json(evidence.source_ref),
            }
            for evidence in snapshot.evidence_refs
        ],
        "category": snapshot.category,
        "tags": list(snapshot.tags),
        "created_at": _datetime_to_json(snapshot.created_at),
        "updated_at": _datetime_to_json(snapshot.updated_at),
        "temporal_extent": {
            "kind": temporal.kind.value,
            "observed_at": _datetime_to_json(temporal.observed_at),
            "valid_from": _datetime_to_json(temporal.valid_from),
            "valid_to": _datetime_to_json(temporal.valid_to),
            "occurred_from": _datetime_to_json(temporal.occurred_from),
            "occurred_to": _datetime_to_json(temporal.occurred_to),
            "basis": temporal.basis,
            "precision": temporal.precision,
        },
        "freshness": {
            "last_confirmed_at": _datetime_to_json(snapshot.freshness.last_confirmed_at),
            "confirmation_basis": snapshot.freshness.confirmation_basis,
        },
        "epistemic_context": {
            "mode": snapshot.epistemic_context.mode.value,
            "asserted_by": snapshot.epistemic_context.asserted_by,
            "perspective_subject": snapshot.epistemic_context.perspective_subject,
        },
        "purge_after": _datetime_to_json(snapshot.purge_after),
        "code_scope": (
            {
                "repository_id": snapshot.code_scope.repository_id,
                "code_scope_id": snapshot.code_scope.code_scope_id,
            }
            if snapshot.code_scope is not None
            else None
        ),
    }


def memory_fact_snapshot_from_json(payload: Mapping[str, object]) -> MemoryFactSnapshot:
    if int(payload.get("schema_version", 0)) != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("Unsupported memory fact snapshot schema")
    identity = _mapping(payload, "identity")
    visibility = _mapping(payload, "visibility")
    temporal = _mapping(payload, "temporal_extent")
    freshness = _mapping(payload, "freshness")
    epistemic = _mapping(payload, "epistemic_context")
    return MemoryFactSnapshot(
        identity=MemoryFactIdentity(
            fact_id=_string(identity, "fact_id"),
            scope=MemoryFactScope(
                space_id=_string(identity, "space_id"),
                memory_scope_id=_string(identity, "memory_scope_id"),
                thread_id=_optional_string(identity.get("thread_id")),
            ),
        ),
        text=_string(payload, "text"),
        source_refs=tuple(
            _source_ref_from_json(item)
            for item in _mapping_sequence(payload.get("source_refs"), "source_refs")
        ),
        visibility=MemoryFactVisibility(
            status=_string(visibility, "status"),
            version=int(visibility["version"]),
            confidence=_string(visibility, "confidence"),
            trust_level=_string(visibility, "trust_level"),
            classification=_string(visibility, "classification"),
            ttl_policy=_optional_string(visibility.get("ttl_policy")),
            expires_at=_datetime_from_json(visibility.get("expires_at")),
        ),
        kind=_string(payload, "kind"),
        evidence_refs=tuple(
            MemoryFactEvidenceRef(
                evidence_id=_optional_string(item.get("evidence_id")),
                source_ref=_source_ref_from_json(_mapping(item, "source_ref")),
            )
            for item in _mapping_sequence(payload.get("evidence_refs"), "evidence_refs")
        ),
        category=_optional_string(payload.get("category")),
        tags=tuple(str(tag) for tag in _sequence(payload.get("tags"), "tags")),
        created_at=_datetime_from_json(payload.get("created_at")),
        updated_at=_datetime_from_json(payload.get("updated_at")),
        temporal_extent=FactTemporalExtent(
            kind=_string(temporal, "kind"),
            observed_at=_required_json_datetime(temporal, "observed_at"),
            valid_from=_datetime_from_json(temporal.get("valid_from")),
            valid_to=_datetime_from_json(temporal.get("valid_to")),
            occurred_from=_datetime_from_json(temporal.get("occurred_from")),
            occurred_to=_datetime_from_json(temporal.get("occurred_to")),
            basis=_string(temporal, "basis"),
            precision=_string(temporal, "precision"),
        ),
        freshness=FactFreshness(
            last_confirmed_at=_datetime_from_json(freshness.get("last_confirmed_at")),
            confirmation_basis=_optional_string(freshness.get("confirmation_basis")),
        ),
        epistemic_context=FactEpistemicContext(
            mode=_string(epistemic, "mode"),
            asserted_by=_optional_string(epistemic.get("asserted_by")),
            perspective_subject=_optional_string(epistemic.get("perspective_subject")),
        ),
        purge_after=_datetime_from_json(payload.get("purge_after")),
        code_scope=_code_scope_from_json(payload.get("code_scope")),
    )


def memory_fact_source_ref_row_to_domain(row: MemorySourceRefRow) -> MemoryFactSourceRef:
    return MemoryFactSourceRef(
        source_type=row.source_type,
        source_id=row.source_id,
        chunk_id=row.chunk_id,
        char_start=row.char_start,
        char_end=row.char_end,
        quote_preview=row.quote_preview,
        page_number=row.page_number,
        time_start_ms=row.time_start_ms,
        time_end_ms=row.time_end_ms,
        bbox=tuple(row.bbox_json) if row.bbox_json is not None else None,
    )


def memory_fact_source_ref_to_row(
    fact_id: str,
    fact_version: int,
    ref: MemoryFactSourceRef,
) -> MemorySourceRefRow:
    return MemorySourceRefRow(
        fact_id=fact_id,
        fact_version=fact_version,
        source_type=ref.source_type,
        source_id=ref.source_id,
        chunk_id=ref.chunk_id,
        char_start=ref.char_start,
        char_end=ref.char_end,
        quote_preview=ref.quote_preview,
        page_number=ref.page_number,
        time_start_ms=ref.time_start_ms,
        time_end_ms=ref.time_end_ms,
        bbox_json=list(ref.bbox) if ref.bbox is not None else None,
    )


def memory_fact_evidence_refs_to_json(
    evidence_refs: tuple[MemoryFactEvidenceRef, ...],
) -> list[dict[str, object]]:
    return [
        {
            "evidence_id": evidence.evidence_id,
            "source_ref": _source_ref_to_json(evidence.source_ref),
        }
        for evidence in evidence_refs
    ]


def memory_fact_evidence_refs_from_json(
    payload: object,
) -> tuple[MemoryFactEvidenceRef, ...]:
    return tuple(
        MemoryFactEvidenceRef(
            evidence_id=_optional_string(item.get("evidence_id")),
            source_ref=_source_ref_from_json(_mapping(item, "source_ref")),
        )
        for item in _mapping_sequence(payload, "evidence_refs")
    )


def _code_scope_from_json(value: object) -> FactCodeScopeReference | None:
    if value is None:
        return None
    payload = _as_mapping(value, "code_scope")
    return FactCodeScopeReference(
        repository_id=_string(payload, "repository_id"),
        code_scope_id=_optional_string(payload.get("code_scope_id")),
    )


def _snapshot_temporal_extent(snapshot: MemoryFactSnapshot) -> FactTemporalExtent:
    if snapshot.temporal_extent is not None:
        return snapshot.temporal_extent
    observed_at = snapshot.created_at or snapshot.updated_at
    if observed_at is None:
        raise ValueError("Memory fact snapshot requires temporal_extent or created_at")
    return FactTemporalExtent(
        kind="state",
        observed_at=_aware(observed_at),
        basis="migrated_legacy",
        precision="unknown",
    )


def _source_ref_to_json(ref: MemoryFactSourceRef) -> dict[str, object]:
    values: dict[str, object | None] = {
        "source_type": ref.source_type,
        "source_id": ref.source_id,
        "chunk_id": ref.chunk_id,
        "char_start": ref.char_start,
        "char_end": ref.char_end,
        "quote_preview": ref.quote_preview,
        "page_number": ref.page_number,
        "time_start_ms": ref.time_start_ms,
        "time_end_ms": ref.time_end_ms,
        "bbox": list(ref.bbox) if ref.bbox is not None else None,
    }
    return {key: value for key, value in values.items() if value is not None}


def _source_ref_from_json(payload: Mapping[str, object]) -> MemoryFactSourceRef:
    bbox = payload.get("bbox")
    return MemoryFactSourceRef(
        source_type=_string(payload, "source_type"),
        source_id=_string(payload, "source_id"),
        chunk_id=_optional_string(payload.get("chunk_id")),
        char_start=_optional_int(payload.get("char_start")),
        char_end=_optional_int(payload.get("char_end")),
        quote_preview=_optional_string(payload.get("quote_preview")),
        page_number=_optional_int(payload.get("page_number")),
        time_start_ms=_optional_int(payload.get("time_start_ms")),
        time_end_ms=_optional_int(payload.get("time_end_ms")),
        bbox=tuple(float(value) for value in _sequence(bbox, "bbox")) if bbox is not None else None,
    )


def _datetime_to_json(value: datetime | None) -> str | None:
    return _aware(value).isoformat() if value is not None else None


def _datetime_from_json(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Snapshot datetime must be an ISO string")
    return _aware(datetime.fromisoformat(value))


def _required_json_datetime(payload: Mapping[str, object], key: str) -> datetime:
    value = _datetime_from_json(payload.get(key))
    if value is None:
        raise ValueError(f"Snapshot field {key} is required")
    return value


def _required_datetime(field_name: str, value: datetime | None) -> datetime:
    if value is None:
        raise ValueError(f"Memory fact snapshot requires {field_name}")
    return _aware(value)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value


def _aware_or_none(value: datetime | None) -> datetime | None:
    return _aware(value) if value is not None else None


def _mapping(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"Snapshot field {key} must be an object")
    return value


def _mapping_sequence(value: object, field_name: str) -> tuple[Mapping[str, object], ...]:
    return tuple(_as_mapping(item, field_name) for item in _sequence(value, field_name))


def _as_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Snapshot field {field_name} must contain objects")
    return value


def _sequence(value: object, field_name: str) -> tuple[object, ...]:
    if not isinstance(value, list | tuple):
        raise ValueError(f"Snapshot field {field_name} must be an array")
    return tuple(value)


def _string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Snapshot field {key} must be a non-blank string")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Snapshot optional string has invalid type")
    return value


def _optional_int(value: object) -> int | None:
    return int(value) if value is not None else None


__all__ = (
    "SNAPSHOT_SCHEMA_VERSION",
    "memory_fact_row_to_snapshot",
    "memory_fact_snapshot_from_json",
    "memory_fact_snapshot_row_values",
    "memory_fact_snapshot_to_json",
    "memory_fact_snapshot_to_row",
    "memory_fact_source_ref_to_row",
)
