"""Safe payload helpers for diagnostics and provider metadata."""

from __future__ import annotations

from infinity_context_core.application.context_retrieval_performance import (
    cached_safe_metadata_text,
    remember_safe_metadata_text,
)
from infinity_context_core.application.sensitive_text import redact_sensitive_text

_MAX_METADATA_DEPTH = 4
_MAX_METADATA_DICT_ITEMS = 120
_MAX_METADATA_LIST_ITEMS = 50


def safe_metadata(
    metadata: object,
    *,
    max_items: int = _MAX_METADATA_DICT_ITEMS,
) -> dict[str, object]:
    if not isinstance(metadata, dict):
        return {}
    safe = _safe_metadata_value(metadata, depth=0, max_items=max_items)
    return safe if isinstance(safe, dict) else {}


def safe_metadata_text(text: str, *, limit: int = 500) -> str:
    safe_text = cached_safe_metadata_text(text)
    if safe_text is None:
        safe_text = redact_sensitive_text(text)
        remember_safe_metadata_text(text, safe_text)
    return safe_text[:limit]


def _safe_metadata_value(value: object, *, depth: int, max_items: int) -> object:
    if isinstance(value, str):
        return safe_metadata_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if depth >= _MAX_METADATA_DEPTH:
        return None
    if isinstance(value, dict):
        safe: dict[str, object] = {}
        for raw_key, raw_value in list(value.items())[:max_items]:
            key = safe_metadata_text(str(raw_key), limit=120)
            if not key or _looks_sensitive_metadata_key(key) or "[redacted]" in key:
                continue
            item = _safe_metadata_value(raw_value, depth=depth + 1, max_items=max_items)
            if _is_safe_metadata_value(item):
                safe[key] = item
        return safe
    if isinstance(value, (list, tuple)):
        safe_items: list[object] = []
        for raw_item in list(value)[:_MAX_METADATA_LIST_ITEMS]:
            item = _safe_metadata_value(raw_item, depth=depth + 1, max_items=max_items)
            if _is_safe_metadata_value(item):
                safe_items.append(item)
        return safe_items
    return None


def _is_safe_metadata_value(value: object) -> bool:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return True
    if isinstance(value, dict):
        return True
    return isinstance(value, list)


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
