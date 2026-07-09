"""Suggestion response mappers owned by the memory_facts server seam."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from infinity_context_server.features.memory_facts.mappers import (
    _redact_sensitive_text,
    fact_to_response,
    source_ref_to_response,
)

_MAX_METADATA_DEPTH = 4
_MAX_METADATA_DICT_ITEMS = 120
_MAX_METADATA_LIST_ITEMS = 50
_MAX_PUBLIC_SUGGESTION_REVIEW_AUDIT_EVENTS = 10
_PUBLIC_SUGGESTION_REVIEW_AUDIT_FIELDS = {
    "event_type": 120,
    "suggestion_id": 160,
    "space_id": 80,
    "memory_scope_id": 80,
    "operation": 40,
    "action": 16,
    "previous_status": 40,
    "new_status": 40,
    "reviewed_at": 80,
    "target_fact_id": 160,
    "target_fact_version": 40,
    "created_from_capture_id": 160,
    "reason": 320,
}
_DUPLICATE_FACT_MERGE_REVIEW_KIND = "duplicate_fact_merge"


def suggestion_to_response(suggestion: object) -> dict[str, Any]:
    status = _enum_or_text(_required_value(suggestion, "status"))
    review_actionable = status == "pending"
    review_payload = _safe_public_metadata(
        _review_payload_with_default_contract(_value(suggestion, "review_payload", {}) or {}),
        max_items=40,
    )
    review_kind = _suggestion_review_kind(review_payload)
    target_fact_id = _value(suggestion, "target_fact_id", None)
    expires_at = _value(suggestion, "expires_at", None)
    reviewed_at = _value(suggestion, "reviewed_at", None)
    return {
        "id": str(_required_value(suggestion, "id")),
        "space_id": str(_required_value(suggestion, "space_id")),
        "memory_scope_id": str(_required_value(suggestion, "memory_scope_id")),
        "candidate_text": _required_value(suggestion, "candidate_text"),
        "kind": _enum_or_text(_required_value(suggestion, "kind")),
        "operation": _enum_or_text(_required_value(suggestion, "operation")),
        "status": status,
        "source_refs": [
            source_ref_to_response(ref) for ref in _value(suggestion, "source_refs", ())
        ],
        "confidence": _enum_or_text(_required_value(suggestion, "confidence")),
        "trust_level": _enum_or_text(_required_value(suggestion, "trust_level")),
        "safe_reason": _safe_public_reason(
            str(_required_value(suggestion, "safe_reason")),
            limit=320,
        ),
        "target_fact_id": str(target_fact_id) if target_fact_id else None,
        "target_fact_version": _value(suggestion, "target_fact_version", None),
        "category": _value(suggestion, "category", None),
        "tags": list(_value(suggestion, "tags", ())),
        "ttl_policy": _value(suggestion, "ttl_policy", None),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "expiry_reason": _value(suggestion, "expiry_reason", None),
        "created_from_capture_id": _value(suggestion, "created_from_capture_id", None),
        "candidate_fingerprint": _value(suggestion, "candidate_fingerprint", None),
        "review_payload": review_payload,
        "review_kind": review_kind,
        "review_actionable": review_actionable,
        "available_review_actions": _available_review_actions(
            review_actionable,
            review_kind=review_kind,
        ),
        "review_state_reason": _suggestion_review_state_reason(status),
        "review_resolution_options": _suggestion_review_resolution_options(review_payload),
        "review_reason": _safe_optional_reason(
            _value(suggestion, "review_reason", None),
            limit=320,
        ),
        "review_audit": _suggestion_review_audit_to_response(suggestion),
        "created_at": _required_value(suggestion, "created_at").isoformat(),
        "updated_at": _required_value(suggestion, "updated_at").isoformat(),
        "reviewed_at": reviewed_at.isoformat() if reviewed_at else None,
    }


def suggestion_result_to_response(result: object) -> dict[str, Any]:
    body: dict[str, Any] = {
        "suggestion": suggestion_to_response(_required_value(result, "suggestion"))
    }
    fact = _value(result, "fact", None)
    if fact is not None:
        body["fact"] = fact_to_response(fact, _value(result, "indexing_status", None))
    return body


def review_suggestions_batch_to_response(result: object) -> dict[str, Any]:
    return {
        "applied": _required_value(result, "applied"),
        "failed": _required_value(result, "failed"),
        "stopped": _required_value(result, "stopped"),
        "results": [
            {
                "suggestion_id": _required_value(item, "suggestion_id"),
                "action": _required_value(item, "action"),
                "status": _required_value(item, "status"),
                **_review_batch_item_payload(item),
            }
            for item in _required_value(result, "results")
        ],
    }


def create_suggestions_batch_to_response(result: object) -> dict[str, Any]:
    return {
        "created": _required_value(result, "created"),
        "existing": _required_value(result, "existing"),
        "failed": _required_value(result, "failed"),
        "stopped": _required_value(result, "stopped"),
        "results": [
            {
                "index": _required_value(item, "index"),
                "status": _required_value(item, "status"),
                **_create_batch_item_payload(item),
            }
            for item in _required_value(result, "results")
        ],
    }


def _review_batch_item_payload(item: object) -> dict[str, Any]:
    result = _value(item, "result", None)
    if result is None:
        return {
            "error_code": _value(item, "error_code", None),
            "error_message": _value(item, "error_message", None),
        }
    return suggestion_result_to_response(result)


def _create_batch_item_payload(item: object) -> dict[str, Any]:
    result = _value(item, "result", None)
    if result is None:
        return {
            "error_code": _value(item, "error_code", None),
            "error_message": _value(item, "error_message", None),
        }
    return {"suggestion": suggestion_to_response(_required_value(result, "suggestion"))}


def _suggestion_review_kind(review_payload: dict[str, Any]) -> str:
    value = review_payload.get("review_kind")
    return str(value).strip() if value else "candidate_review"


def _available_review_actions(review_actionable: bool, *, review_kind: str) -> list[str]:
    if not review_actionable:
        return []
    actions = ["approve", "reject", "expire"]
    if review_kind == "conflict_review":
        actions.append("resolve_conflict")
    if review_kind == "duplicate_fact_merge":
        actions.append("resolve_duplicate")
    return actions


def _suggestion_review_state_reason(status: str) -> str:
    if status == "pending":
        return "pending_review"
    return f"{status}_review"


def _suggestion_review_resolution_options(
    review_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    options = review_payload.get("resolution_options")
    if not isinstance(options, list):
        return []
    safe_options: list[dict[str, Any]] = []
    for option in options[:10]:
        if isinstance(option, dict):
            safe_option = _safe_public_metadata(option, max_items=20)
            if safe_option:
                safe_options.append(safe_option)
    return safe_options


def _suggestion_review_audit_to_response(suggestion: object) -> dict[str, Any]:
    review_payload = _value(suggestion, "review_payload", {}) or {}
    raw_events = review_payload.get("review_events") if isinstance(review_payload, dict) else None
    events = (
        [item for item in raw_events if isinstance(item, dict)]
        if isinstance(raw_events, list)
        else []
    )
    public_events = [
        _suggestion_review_audit_event_to_response(item)
        for item in events[-_MAX_PUBLIC_SUGGESTION_REVIEW_AUDIT_EVENTS:]
    ]
    return {
        "events": public_events,
        "event_count": len(events),
        "truncated": len(events) > len(public_events),
    }


def _suggestion_review_audit_event_to_response(event: dict[str, Any]) -> dict[str, Any]:
    public: dict[str, Any] = {}
    for key, limit in _PUBLIC_SUGGESTION_REVIEW_AUDIT_FIELDS.items():
        value = event.get(key)
        if value is None:
            continue
        if isinstance(value, str | int | float | bool):
            sanitizer = _safe_public_reason if key == "reason" else _safe_public_text
            public[key] = sanitizer(str(value), limit=limit)
    return public


def _review_payload_with_default_contract(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("review_kind") == _DUPLICATE_FACT_MERGE_REVIEW_KIND:
        return {**_duplicate_fact_merge_review_contract(), **payload}
    return dict(payload)


def _duplicate_fact_merge_review_contract() -> dict[str, Any]:
    return {
        "review_kind": _DUPLICATE_FACT_MERGE_REVIEW_KIND,
        "recommended_action": "merge_source_refs_into_existing_fact",
        "recommended_resolution_action": "merge_source_refs",
        "default_resolution": "merge_or_keep_separate_after_review",
        "duplicate_merge_policy_version": "duplicate-merge-review-v1",
        "review_risk": "medium",
        "recommendation_confidence": "medium",
        "requires_review": True,
        "auto_merge_eligible": False,
        "recommendation_reason_codes": ["human_review_required", "legacy_payload"],
        "resolution_options": [
            {
                "id": "merge_source_refs",
                "review_action": "resolve_duplicate",
                "effect": "merge_source_refs_into_existing_fact",
                "availability": "available",
                "resolution_action": "merge_source_refs",
            },
            {
                "id": "keep_separate_fact",
                "review_action": "resolve_duplicate",
                "effect": "create_new_fact_keep_existing_fact",
                "availability": "available",
                "resolution_action": "keep_separate_fact",
            },
            {
                "id": "reject_duplicate_candidate",
                "review_action": "reject",
                "effect": "keep_existing_fact_without_candidate_source_refs",
                "availability": "available",
                "resolution_action": "reject_candidate",
            },
            {
                "id": "expire_duplicate_candidate",
                "review_action": "expire",
                "effect": "hide_pending_duplicate_merge_review",
                "availability": "available",
                "resolution_action": "expire_candidate",
            },
        ],
    }


def _safe_optional_reason(value: object, *, limit: int) -> str | None:
    if value is None:
        return None
    return _safe_public_reason(str(value), limit=limit)


def _safe_public_reason(value: str, *, limit: int = 500) -> str:
    if _contains_sensitive_text(value):
        return "[redacted]"
    return _safe_public_text(value, limit=limit)


def _safe_public_text(value: str, *, limit: int = 500) -> str:
    return _redact_sensitive_text(value)[:limit]


def _contains_sensitive_text(value: str | None) -> bool:
    return bool(value) and _redact_sensitive_text(value) != value


def _safe_public_metadata(
    metadata: Any,
    *,
    max_items: int = _MAX_METADATA_DICT_ITEMS,
) -> dict[str, Any]:
    if isinstance(metadata, Mapping):
        metadata = dict(metadata)
    safe = _safe_metadata_value(metadata, depth=0, max_items=max_items)
    return safe if isinstance(safe, dict) else {}


def _safe_metadata_value(value: object, *, depth: int, max_items: int) -> object:
    if isinstance(value, str):
        return _safe_public_text(value)
    if isinstance(value, int | float | bool) or value is None:
        return value
    if depth >= _MAX_METADATA_DEPTH:
        return None
    if isinstance(value, dict):
        safe: dict[str, object] = {}
        for raw_key, raw_value in list(value.items())[:max_items]:
            key = _safe_public_text(str(raw_key), limit=120)
            if not key or _looks_sensitive_metadata_key(key) or "[redacted]" in key:
                continue
            item = _safe_metadata_value(raw_value, depth=depth + 1, max_items=max_items)
            if _is_safe_metadata_value(item):
                safe[key] = item
        return safe
    if isinstance(value, list | tuple):
        safe_items: list[object] = []
        for raw_item in list(value)[:_MAX_METADATA_LIST_ITEMS]:
            item = _safe_metadata_value(raw_item, depth=depth + 1, max_items=max_items)
            if _is_safe_metadata_value(item):
                safe_items.append(item)
        return safe_items
    return None


def _is_safe_metadata_value(value: object) -> bool:
    if isinstance(value, str | int | float | bool) or value is None:
        return True
    return isinstance(value, dict | list)


def _looks_sensitive_metadata_key(key: str) -> bool:
    lowered = key.lower()
    return any(
        marker in lowered
        for marker in (
            "api_key",
            "apikey",
            "auth",
            "authorization",
            "credential",
            "password",
            "passwd",
            "private_key",
            "secret",
            "token",
        )
    )


def _required_value(source: object, name: str) -> Any:
    value = _value(source, name, None)
    if value is None:
        raise KeyError(name)
    return value


def _value(source: object, name: str, default: object) -> Any:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _enum_or_text(value: object) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


__all__ = (
    "create_suggestions_batch_to_response",
    "review_suggestions_batch_to_response",
    "suggestion_result_to_response",
    "suggestion_to_response",
)
