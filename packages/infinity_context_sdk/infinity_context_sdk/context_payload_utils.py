"""Safe payload parsing helpers for typed context SDK responses."""

from __future__ import annotations

from collections.abc import Mapping

from infinity_context_sdk._redaction import redact_sensitive_text

MAX_RETRIEVAL_SOURCES = 8
MAX_SOURCE_REFS = 20
MAX_MAPPING_ITEMS = 24
MAX_BUNDLE_DIAGNOSTIC_ITEMS = 128
MAX_LIST_ITEMS = 8
MAX_KEY_CHARS = 80
MAX_STRING_CHARS = 240
MAX_RANKING_REASON_CHARS = 240

_SENSITIVE_KEY_MARKERS = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "passwd",
    "credential",
    "authorization",
    "bearer",
)

def _int_mapping(value: object) -> dict[str, int]:
    result: dict[str, int] = {}
    for key, item in _bounded_mapping(value).items():
        if not isinstance(key, str):
            continue
        result[key] = _non_negative_int(item)
    return result


def _ranking_reason_for(retrieval_sources: tuple[str, ...]) -> str:
    if len(retrieval_sources) > 1:
        return _safe_text(
            f"hybrid match via {', '.join(retrieval_sources)}",
            default="hybrid match",
            limit=MAX_RANKING_REASON_CHARS,
        )
    if retrieval_sources:
        return _safe_text(
            f"matched via {retrieval_sources[0]}",
            default="matched",
            limit=MAX_RANKING_REASON_CHARS,
        )
    return "matched without retrieval channel diagnostics"


def _bounded_mapping(
    value: object,
    *,
    max_items: int = MAX_MAPPING_ITEMS,
    depth: int = 0,
) -> dict[str, object]:
    if not isinstance(value, Mapping) or depth > 2:
        return {}
    result: dict[str, object] = {}
    for raw_key, raw_value in list(value.items())[:max_items]:
        key = _safe_text(raw_key, default="", limit=MAX_KEY_CHARS).strip()
        if not key or _is_sensitive_key(key):
            continue
        item = _bounded_value(raw_value, max_items=max_items, depth=depth)
        if _is_safe_value(item):
            result[key] = item
    return result


def _bounded_value(value: object, *, max_items: int, depth: int) -> object:
    if isinstance(value, str):
        return _safe_text(value, default="", limit=MAX_STRING_CHARS)
    if isinstance(value, bool | int | float) or value is None:
        return value
    if isinstance(value, Mapping):
        return _bounded_mapping(value, max_items=max_items, depth=depth + 1)
    if isinstance(value, list | tuple):
        result: list[object] = []
        for raw_item in list(value)[:MAX_LIST_ITEMS]:
            item = _bounded_value(raw_item, max_items=max_items, depth=depth + 1)
            if _is_safe_value(item):
                result.append(item)
        return result
    return None


def _scalar_mapping(value: object) -> dict[str, object]:
    return {
        key: item
        for key, item in _bounded_mapping(value).items()
        if isinstance(item, str | int | float | bool) or item is None
    }


def _safe_text(value: object, *, default: str, limit: int = MAX_STRING_CHARS) -> str:
    if value is None:
        return default
    text = redact_sensitive_text(str(value)).strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 12)].rstrip()}...truncated"


def _optional_text(value: object, *, limit: int = MAX_STRING_CHARS) -> str | None:
    text = _safe_text(value, default="", limit=limit)
    return text or None


def _safe_text_tuple(value: object, *, limit: int) -> tuple[str, ...]:
    result: list[str] = []
    for item in _as_list(value):
        text = _optional_text(item, limit=MAX_KEY_CHARS)
        if not text or "[redacted]" in text or text in result:
            continue
        result.append(text)
        if len(result) >= limit:
            break
    return tuple(result)


def _safe_review_resolution_options(value: object) -> tuple[Mapping[str, str], ...]:
    options: list[Mapping[str, str]] = []
    for option in _as_list(value):
        if not isinstance(option, Mapping):
            continue
        safe_option = {
            key: text
            for key, text in (
                ("id", _optional_text(option.get("id"), limit=MAX_KEY_CHARS)),
                (
                    "review_action",
                    _optional_text(option.get("review_action"), limit=MAX_KEY_CHARS),
                ),
                ("effect", _optional_text(option.get("effect"), limit=MAX_STRING_CHARS)),
                (
                    "availability",
                    _optional_text(option.get("availability"), limit=MAX_KEY_CHARS),
                ),
            )
            if text and "[redacted]" not in text
        }
        if safe_option:
            options.append(safe_option)
        if len(options) >= MAX_LIST_ITEMS:
            break
    return tuple(options)


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _optional_bbox(value: object) -> tuple[float, float, float, float] | None:
    if not isinstance(value, list | tuple) or len(value) != 4:
        return None
    parsed: list[float] = []
    for item in value:
        if not isinstance(item, int | float):
            return None
        parsed.append(float(item))
    return (parsed[0], parsed[1], parsed[2], parsed[3])


def _safe_float(value: object) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _safe_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, int | float):
        return value != 0
    return False


def _non_negative_int(value: object, *, default: int = 0) -> int:
    number = _optional_int(value)
    return max(0, number if number is not None else default)


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list | tuple) else []


def _is_sensitive_key(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS)


def _is_safe_value(value: object) -> bool:
    return isinstance(value, str | int | float | bool | dict | list) or value is None
