"""Safe diagnostic primitive coercion helpers."""

from __future__ import annotations

from typing import Any

from infinity_context_core.application.safe_payload import safe_metadata, safe_metadata_text

_MAX_RETRIEVAL_SOURCES = 8
_MAX_RETRIEVAL_SOURCE_CANDIDATES = 64
_MAX_RETRIEVAL_TRACE_ENTRIES = 8
_MAX_DIAGNOSTIC_MAPPING_ITEMS = 24
_MAX_BUNDLE_DIAGNOSTIC_MAPPING_ITEMS = 64
_MAX_DIAGNOSTIC_LIST_ITEMS = 8
_MAX_DIAGNOSTIC_KEY_CHARS = 80
_MAX_DIAGNOSTIC_STRING_CHARS = 240
_MAX_RANKING_REASON_CHARS = 240
_MAX_EVIDENCE_LOCATION_GAPS = 8

def safe_diagnostic_mapping(value: object) -> dict[str, object]:
    return _bounded_mapping(
        safe_metadata(value, max_items=_MAX_DIAGNOSTIC_MAPPING_ITEMS),
        max_items=_MAX_DIAGNOSTIC_MAPPING_ITEMS,
    )

def _bounded_mapping(
    value: object,
    *,
    depth: int = 0,
    max_items: int = _MAX_DIAGNOSTIC_MAPPING_ITEMS,
) -> dict[str, object]:
    if not isinstance(value, dict) or depth > 2:
        return {}
    bounded: dict[str, object] = {}
    for raw_key, raw_value in list(value.items())[:max_items]:
        key = safe_metadata_text(str(raw_key), limit=_MAX_DIAGNOSTIC_KEY_CHARS).strip()
        if not key or "[redacted]" in key:
            continue
        item = _bounded_value(raw_value, depth=depth, max_items=max_items)
        if _is_safe_diagnostic_value(item):
            bounded[key] = item
    return bounded


def _bounded_value(
    value: object,
    *,
    depth: int,
    max_items: int,
) -> object:
    if isinstance(value, str):
        return safe_metadata_text(value, limit=_MAX_DIAGNOSTIC_STRING_CHARS)
    if isinstance(value, int | float | bool) or value is None:
        return value
    if isinstance(value, dict):
        return _bounded_mapping(value, depth=depth + 1, max_items=max_items)
    if isinstance(value, list):
        safe_items: list[object] = []
        for raw_item in value[:_MAX_DIAGNOSTIC_LIST_ITEMS]:
            item = _bounded_value(raw_item, depth=depth + 1, max_items=max_items)
            if _is_safe_diagnostic_value(item):
                safe_items.append(item)
        return safe_items
    return None


def _is_safe_diagnostic_value(value: object) -> bool:
    return isinstance(value, str | int | float | bool | dict | list) or value is None


def _safe_retrieval_source(value: object) -> str | None:
    if value is None:
        return None
    text = safe_metadata_text(str(value), limit=_MAX_DIAGNOSTIC_KEY_CHARS).strip()
    if "[redacted]" in text:
        return None
    return text or None


def _safe_optional_text(value: object, *, limit: int) -> str | None:
    if value is None:
        return None
    text = safe_metadata_text(str(value), limit=limit).strip()
    return text or None

def _non_negative_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value))
    return default


def _optional_non_negative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value))
    return None


def _optional_non_negative_float(value: object) -> float | None:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, int | float):
        return max(0.0, round(float(value), 4))
    return None

def _as_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _ordered_unique(
    values: tuple[str, ...],
    *,
    limit: int = _MAX_RETRIEVAL_SOURCES,
) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
        if len(result) >= limit:
            break
    return tuple(result)
