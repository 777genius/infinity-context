"""Public API payload sanitizers."""

from __future__ import annotations

from typing import Any

from memo_stack_core.application.sensitive_text import redact_sensitive_text

_MAX_DICT_ITEMS = 120
_MAX_LIST_ITEMS = 50
_MAX_DEPTH = 4


def safe_public_text(value: str, *, limit: int = 500) -> str:
    return redact_sensitive_text(value)[:limit]


def safe_public_metadata(metadata: Any, *, max_items: int = _MAX_DICT_ITEMS) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    safe = _safe_public_value(metadata, max_items=max_items, depth=0)
    return safe if isinstance(safe, dict) else {}


def _safe_public_value(value: Any, *, max_items: int, depth: int) -> Any:
    if isinstance(value, str):
        return safe_public_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if depth >= _MAX_DEPTH:
        return None
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for raw_key, raw_item in list(value.items())[:max_items]:
            key = safe_public_text(str(raw_key), limit=120)
            if not key or _looks_sensitive_key(key) or "[redacted]" in key:
                continue
            item = _safe_public_value(raw_item, max_items=max_items, depth=depth + 1)
            if _is_allowed_public_value(item):
                safe[key] = item
        return safe
    if isinstance(value, (list, tuple)):
        safe_items: list[Any] = []
        for raw_item in list(value)[:_MAX_LIST_ITEMS]:
            item = _safe_public_value(raw_item, max_items=max_items, depth=depth + 1)
            if _is_allowed_public_value(item):
                safe_items.append(item)
        return safe_items
    return None


def _is_allowed_public_value(value: Any) -> bool:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return True
    if isinstance(value, dict):
        return True
    return isinstance(value, list)


def _looks_sensitive_key(key: str) -> bool:
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
