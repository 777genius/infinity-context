"""Strict JSON object decoding at raw PostgreSQL adapter boundaries."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping

from infinity_context_core.ports.managed_cleanup_v3_contracts import (
    ManagedCleanupV3Error,
    canonical_bytes,
)


def strict_json_object(value: object, diagnostic_code: str) -> dict[str, object]:
    """Accept a decoded mapping or JSON text without weakening JSON semantics."""

    def reject_constant(_value: str) -> object:
        raise ValueError("non-finite JSON number")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = item
        return result

    try:
        if isinstance(value, str):
            decoded = json.loads(
                value,
                object_pairs_hook=unique_object,
                parse_constant=reject_constant,
            )
            decoded = _normalize_json_value(decoded)
        elif isinstance(value, Mapping):
            decoded = _normalize_json_value(value)
        else:
            raise TypeError("JSON value is not an object")
        if type(decoded) is not dict:
            raise TypeError("JSON value is not an object")
        canonical_bytes(decoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ManagedCleanupV3Error(diagnostic_code) from exc
    return decoded


def _normalize_json_value(value: object) -> object:
    if value is None or type(value) in (bool, str, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number")
        return value
    if type(value) is list:
        return [_normalize_json_value(item) for item in value]
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str or key in result:
                raise ValueError("invalid JSON object key")
            result[key] = _normalize_json_value(item)
        return result
    raise TypeError("non-JSON value")


__all__ = ("strict_json_object",)
