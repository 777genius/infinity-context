"""DTO mappers for the memory_facts server feature mirror."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from math import isfinite
from typing import Any

from infinity_context_contracts.features.memory_facts import (
    ForgetFactResultDto,
    MemoryFactIdentityDto,
    MemoryFactReadDto,
    MemoryFactSourceRefDto,
    MemoryFactVisibilityDto,
    RememberFactRequestDto,
    RememberFactResultDto,
    UpdateFactResultDto,
)
from infinity_context_core.features.memory_facts.public import (
    ForgetFactCommand,
    ForgetFactResult,
    MemoryFactEvidenceRef,
    MemoryFactIdentity,
    MemoryFactScope,
    MemoryFactSnapshot,
    MemoryFactSourceRef,
    RememberFactCommand,
    RememberFactResult,
    UpdateFactCommand,
    UpdateFactResult,
)

_MISSING = object()


def memory_fact_scope_from_ids(
    *,
    space_id: str,
    memory_scope_id: str,
    thread_id: str | None = None,
) -> MemoryFactScope:
    return MemoryFactScope(
        space_id=_required_text(space_id, "space_id"),
        memory_scope_id=_required_text(memory_scope_id, "memory_scope_id"),
        thread_id=_optional_text(thread_id),
    )


def memory_fact_scope_from_contract(request: object) -> MemoryFactScope:
    return memory_fact_scope_from_ids(
        space_id=_required_text(_value(request, "space_id", None), "space_id"),
        memory_scope_id=_required_text(
            _value(request, "memory_scope_id", None),
            "memory_scope_id",
        ),
        thread_id=_optional_text(_value(request, "thread_id", None)),
    )


def remember_fact_command_from_contract(
    request: RememberFactRequestDto | object,
    *,
    idempotency_key: str | None = None,
) -> RememberFactCommand:
    return remember_fact_request_to_command(
        request,
        scope=memory_fact_scope_from_contract(request),
        idempotency_key=idempotency_key,
    )


def remember_fact_request_to_command(
    request: object,
    *,
    scope: MemoryFactScope,
    idempotency_key: str | None = None,
) -> RememberFactCommand:
    return RememberFactCommand(
        scope=scope,
        text=_required_content(request, "text"),
        source_refs=tuple(
            source_ref_request_to_public(ref)
            for ref in _required_sequence(request, "source_refs")
        ),
        kind=_required_text(_value(request, "kind", "note"), "kind"),
        evidence_refs=tuple(
            evidence_ref_request_to_public(ref)
            for ref in _value(request, "evidence_refs", ())
        ),
        category=_optional_text(_value(request, "category", None)),
        tags=_string_tuple(_value(request, "tags", ())),
        idempotency_key=idempotency_key,
    )


def update_fact_command_from_http(
    fact_id: str,
    request: object,
    *,
    idempotency_key: str | None = None,
) -> UpdateFactCommand:
    return update_fact_request_to_command(
        request,
        scope=memory_fact_scope_from_contract(request),
        fact_id=fact_id,
        idempotency_key=idempotency_key,
    )


def update_fact_request_to_command(
    request: object,
    *,
    scope: MemoryFactScope,
    fact_id: str,
    idempotency_key: str | None = None,
) -> UpdateFactCommand:
    return UpdateFactCommand(
        identity=MemoryFactIdentity(fact_id=fact_id, scope=scope),
        expected_version=int(_required_value(request, "expected_version")),
        text=_required_content(request, "text"),
        source_refs=tuple(
            source_ref_request_to_public(ref)
            for ref in _required_sequence(request, "source_refs")
        ),
        kind=_required_text(_value(request, "kind", "note"), "kind"),
        evidence_refs=tuple(
            evidence_ref_request_to_public(ref)
            for ref in _value(request, "evidence_refs", ())
        ),
        category=_optional_text(_value(request, "category", None)),
        tags=_string_tuple(_value(request, "tags", ())),
        reason=_optional_text(_value(request, "reason", None)),
        idempotency_key=idempotency_key,
    )


def forget_fact_command_from_http(
    fact_id: str,
    request: object,
    *,
    idempotency_key: str | None = None,
) -> ForgetFactCommand:
    expected_version = _value(request, "expected_version", None)
    return forget_fact_request_to_command(
        scope=memory_fact_scope_from_contract(request),
        fact_id=fact_id,
        expected_version=int(expected_version) if expected_version is not None else None,
        reason=_optional_text(_value(request, "reason", None)),
        idempotency_key=idempotency_key,
    )


def forget_fact_request_to_command(
    *,
    scope: MemoryFactScope,
    fact_id: str,
    expected_version: int | None = None,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> ForgetFactCommand:
    return ForgetFactCommand(
        identity=MemoryFactIdentity(fact_id=fact_id, scope=scope),
        expected_version=expected_version,
        reason=reason,
        idempotency_key=idempotency_key,
    )


def source_ref_request_to_public(source_ref: object) -> MemoryFactSourceRef:
    return MemoryFactSourceRef(
        source_type=_required_str(source_ref, "source_type"),
        source_id=_required_str(source_ref, "source_id"),
        chunk_id=_value(source_ref, "chunk_id", None),
        char_start=_value(source_ref, "char_start", None),
        char_end=_value(source_ref, "char_end", None),
        quote_preview=_value(source_ref, "quote_preview", None),
        page_number=_value(source_ref, "page_number", None),
        time_start_ms=_value(source_ref, "time_start_ms", None),
        time_end_ms=_value(source_ref, "time_end_ms", None),
        bbox=_bbox_or_none(_value(source_ref, "bbox", None)),
    )


def evidence_ref_request_to_public(evidence_ref: object) -> MemoryFactEvidenceRef:
    return MemoryFactEvidenceRef(
        source_ref=source_ref_request_to_public(
            _required_value(evidence_ref, "source_ref")
        ),
        evidence_id=_value(evidence_ref, "evidence_id", None),
    )


def memory_fact_snapshot_to_contract(fact: MemoryFactSnapshot) -> MemoryFactReadDto:
    visibility = fact.visibility
    scope = fact.identity.scope
    return MemoryFactReadDto(
        identity=MemoryFactIdentityDto(
            id=fact.identity.fact_id,
            space_id=scope.space_id,
            memory_scope_id=scope.memory_scope_id,
            thread_id=scope.thread_id,
        ),
        text=fact.text,
        kind=fact.kind,
        visibility=MemoryFactVisibilityDto(
            status=visibility.status,
            version=visibility.version,
            confidence=visibility.confidence,
            trust_level=visibility.trust_level,
            classification=visibility.classification,
            ttl_policy=visibility.ttl_policy,
            expires_at=_datetime_to_response(visibility.expires_at),
        ),
        category=fact.category,
        tags=fact.tags,
        source_refs=tuple(source_ref_to_contract(ref) for ref in fact.source_refs),
        created_at=_datetime_to_response(fact.created_at),
        updated_at=_datetime_to_response(fact.updated_at),
    )


def remember_fact_result_to_contract(
    result: RememberFactResult,
) -> RememberFactResultDto:
    return RememberFactResultDto(fact=memory_fact_snapshot_to_contract(result.fact))


def update_fact_result_to_contract(result: UpdateFactResult) -> UpdateFactResultDto:
    return UpdateFactResultDto(fact=memory_fact_snapshot_to_contract(result.fact))


def forget_fact_result_to_contract(result: ForgetFactResult) -> ForgetFactResultDto:
    return ForgetFactResultDto(fact=memory_fact_snapshot_to_contract(result.fact))


def memory_fact_snapshot_to_response(fact: MemoryFactSnapshot) -> dict[str, Any]:
    visibility = fact.visibility
    scope = fact.identity.scope
    return {
        "id": fact.identity.fact_id,
        "space_id": scope.space_id,
        "memory_scope_id": scope.memory_scope_id,
        "thread_id": scope.thread_id,
        "text": fact.text,
        "kind": fact.kind,
        "status": visibility.status,
        "version": visibility.version,
        "confidence": visibility.confidence,
        "trust_level": visibility.trust_level,
        "classification": visibility.classification,
        "category": fact.category,
        "tags": list(fact.tags),
        "ttl_policy": visibility.ttl_policy,
        "expires_at": _datetime_to_response(visibility.expires_at),
        "source_refs": [
            source_ref_to_response(source_ref) for source_ref in fact.source_refs
        ],
        "evidence_refs": [
            evidence_ref_to_response(evidence_ref)
            for evidence_ref in fact.evidence_refs
        ],
        "created_at": _datetime_to_response(fact.created_at),
        "updated_at": _datetime_to_response(fact.updated_at),
    }


def memory_fact_result_to_response(
    result: RememberFactResult | UpdateFactResult | ForgetFactResult,
) -> dict[str, Any]:
    body = memory_fact_snapshot_to_response(result.fact)
    body["outbox_message_ids"] = list(result.outbox_message_ids)
    tombstone_id = getattr(result, "tombstone_id", None)
    if tombstone_id is not None:
        body["tombstone_id"] = tombstone_id
    return body


def legacy_memory_fact_to_response(
    fact: object,
    indexing_status: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": str(_required_value(fact, "id")),
        "space_id": str(_required_value(fact, "space_id")),
        "memory_scope_id": str(_required_value(fact, "memory_scope_id")),
        "thread_id": _optional_identifier(_value(fact, "thread_id", None)),
        "text": _required_content(fact, "text"),
        "kind": _enum_or_text(_value(fact, "kind", "note")),
        "status": _enum_or_text(_value(fact, "status", "active")),
        "version": int(_required_value(fact, "version")),
        "confidence": _enum_or_text(_value(fact, "confidence", "medium")),
        "trust_level": _enum_or_text(_value(fact, "trust_level", "medium")),
        "classification": str(_value(fact, "classification", "internal")),
        "category": _optional_text(_value(fact, "category", None)),
        "tags": list(_value(fact, "tags", ())),
        "ttl_policy": _optional_text(_value(fact, "ttl_policy", None)),
        "expires_at": _datetime_to_response(_value(fact, "expires_at", None)),
        "source_refs": [
            source_ref_to_response(source_ref)
            for source_ref in _value(fact, "source_refs", ())
        ],
        "created_at": _datetime_to_response(_required_value(fact, "created_at")),
        "updated_at": _datetime_to_response(_required_value(fact, "updated_at")),
    }
    if indexing_status is not None:
        body["indexing_status"] = indexing_status
    return body


def fact_to_response(
    fact: MemoryFactSnapshot | object,
    indexing_status: str | None = None,
) -> dict[str, Any]:
    if isinstance(fact, MemoryFactSnapshot):
        body = memory_fact_snapshot_to_response(fact)
        if indexing_status is not None:
            body["indexing_status"] = indexing_status
        return body
    return legacy_memory_fact_to_response(fact, indexing_status)


def source_ref_to_contract(source_ref: MemoryFactSourceRef) -> MemoryFactSourceRefDto:
    return MemoryFactSourceRefDto(
        source_type=source_ref.source_type,
        source_id=source_ref.source_id,
        chunk_id=source_ref.chunk_id,
        char_start=source_ref.char_start,
        char_end=source_ref.char_end,
        quote_preview=source_ref.quote_preview,
        page_number=source_ref.page_number,
        time_start_ms=source_ref.time_start_ms,
        time_end_ms=source_ref.time_end_ms,
        bbox=source_ref.bbox,
    )


def source_ref_to_response(source_ref: MemoryFactSourceRef | object) -> dict[str, Any]:
    quote_preview = _value(source_ref, "quote_preview", None)
    char_start, char_end = _range_pair(
        _value(source_ref, "char_start", None),
        _value(source_ref, "char_end", None),
    )
    time_start_ms, time_end_ms = _range_pair(
        _value(source_ref, "time_start_ms", None),
        _value(source_ref, "time_end_ms", None),
    )
    return {
        "source_type": _safe_public_text(_required_str(source_ref, "source_type"), limit=80),
        "source_id": _safe_public_text(_required_str(source_ref, "source_id"), limit=160),
        "chunk_id": _optional_public_text(
            _value(source_ref, "chunk_id", None),
            limit=160,
        ),
        "char_start": char_start,
        "char_end": char_end,
        "quote_preview": _safe_public_text(str(quote_preview)) if quote_preview else None,
        "page_number": _positive_int(_value(source_ref, "page_number", None)),
        "time_start_ms": time_start_ms,
        "time_end_ms": time_end_ms,
        "bbox": _bbox_to_response(_value(source_ref, "bbox", None)),
    }


def evidence_ref_to_response(evidence_ref: MemoryFactEvidenceRef) -> dict[str, Any]:
    return {
        "evidence_id": evidence_ref.evidence_id,
        "source_ref": source_ref_to_response(evidence_ref.source_ref),
    }


fact_result_to_response = memory_fact_result_to_response


def _required_str(source: object, name: str) -> str:
    return _required_text(_required_value(source, name), name)


def _required_content(source: object, name: str) -> str:
    value = _required_value(source, name)
    text = str(value)
    if not text.strip():
        raise ValueError(f"{name} is required")
    return text


def _required_sequence(source: object, name: str) -> Sequence[object]:
    value = _required_value(source, name)
    if isinstance(value, Sequence) and not isinstance(value, str):
        return value
    raise TypeError(f"{name} must be a sequence")


def _required_value(source: object, name: str) -> object:
    value = _value(source, name, _MISSING)
    if value is _MISSING:
        raise KeyError(name)
    return value


def _value(source: object, name: str, default: object) -> Any:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _required_text(value: object, field_name: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _optional_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _optional_identifier(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _enum_or_text(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


def _optional_public_text(value: object, *, limit: int) -> str | None:
    if value is None:
        return None
    text = _safe_public_text(str(value), limit=limit).strip()
    return text or None


def _safe_public_text(value: str, *, limit: int = 500) -> str:
    return value[:limit]


def _range_pair(start: object, end: object) -> tuple[int | None, int | None]:
    parsed_start = _non_negative_int(start)
    parsed_end = _non_negative_int(end)
    if (start is not None and parsed_start is None) or (
        end is not None and parsed_end is None
    ):
        return None, None
    if parsed_start is not None and parsed_end is not None and parsed_end < parsed_start:
        return None, None
    return parsed_start, parsed_end


def _positive_int(value: object) -> int | None:
    parsed = _non_negative_int(value)
    return parsed if parsed is not None and parsed >= 1 else None


def _non_negative_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _bbox_to_response(value: object) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        bbox = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    if not all(isfinite(item) for item in bbox):
        return None
    if any(item < 0 for item in bbox) or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        return None
    return bbox


def _string_tuple(values: object) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str) or not isinstance(values, Sequence):
        raise ValueError("tags must be a sequence")
    return tuple(text for value in values if (text := str(value).strip()))


def _bbox_or_none(value: object) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ValueError("bbox must be a sequence")
    coords = tuple(float(item) for item in value)
    if len(coords) != 4:
        raise ValueError("bbox must contain four coordinates")
    return coords


def _datetime_to_response(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


__all__ = (
    "evidence_ref_request_to_public",
    "evidence_ref_to_response",
    "fact_result_to_response",
    "fact_to_response",
    "forget_fact_command_from_http",
    "forget_fact_request_to_command",
    "forget_fact_result_to_contract",
    "legacy_memory_fact_to_response",
    "memory_fact_scope_from_contract",
    "memory_fact_result_to_response",
    "memory_fact_scope_from_ids",
    "memory_fact_snapshot_to_contract",
    "memory_fact_snapshot_to_response",
    "remember_fact_command_from_contract",
    "remember_fact_request_to_command",
    "remember_fact_result_to_contract",
    "source_ref_to_contract",
    "source_ref_request_to_public",
    "source_ref_to_response",
    "update_fact_command_from_http",
    "update_fact_request_to_command",
    "update_fact_result_to_contract",
)
