"""Strict JSON primitives for the subscription-runtime bridge boundary."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, NoReturn


class BridgeJsonError(ValueError):
    """Raised when bridge JSON is ambiguous, non-finite, or non-canonical."""


def canonical_json_bytes(value: object) -> bytes:
    """Encode deterministic UTF-8 JSON with recursively sorted object keys."""

    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise BridgeJsonError("bridge_json_not_canonicalizable") from exc
    return encoded.encode("utf-8")


def strict_json_loads(raw: bytes, *, maximum_bytes: int) -> object:
    """Decode bounded UTF-8 JSON while rejecting duplicate keys and NaN/Infinity."""

    if not isinstance(raw, bytes) or not raw or len(raw) > maximum_bytes:
        raise BridgeJsonError("bridge_json_size_invalid")
    try:
        text = raw.decode("utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=_exact_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BridgeJsonError("bridge_json_invalid") from exc


def strict_canonical_json_object(raw: bytes, *, maximum_bytes: int) -> dict[str, Any]:
    """Decode an exact canonical top-level object without changing its bytes."""

    value = strict_json_loads(raw, maximum_bytes=maximum_bytes)
    if not isinstance(value, dict):
        raise BridgeJsonError("bridge_json_object_required")
    if canonical_json_bytes(value) != raw:
        raise BridgeJsonError("bridge_json_bytes_not_canonical")
    return value


def exact_object(
    value: object,
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    label: str,
) -> dict[str, Any]:
    """Require an object with no missing or unrecognized keys."""

    if not isinstance(value, dict):
        raise BridgeJsonError(f"{label}_object_invalid")
    keys = frozenset(value)
    if not required.issubset(keys) or not keys.issubset(required | optional):
        raise BridgeJsonError(f"{label}_schema_invalid")
    return value


def _exact_object(pairs: list[tuple[str, Any]]) -> Mapping[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BridgeJsonError("bridge_json_duplicate_key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> NoReturn:
    raise BridgeJsonError("bridge_json_nonfinite_number")


__all__ = (
    "BridgeJsonError",
    "canonical_json_bytes",
    "exact_object",
    "strict_canonical_json_object",
    "strict_json_loads",
)
