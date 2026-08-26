"""Strict collection, scalar, and JSON-object validation for Retrieval DTOs."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime

_RFC3339_UTC = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$"
)


def canonical_string_sort_key(value: str) -> bytes:
    """Return the language-neutral Retrieval opaque-string ordering key."""

    return value.encode("utf-8")


def reject_unknown(payload: Mapping[str, object], allowed: set[str], path: str) -> None:
    unknown = sorted(set(payload) - allowed, key=canonical_string_sort_key)
    if unknown:
        prefix = f"{path}." if path else ""
        raise ValueError(f"{prefix}{unknown[0]} is unsupported")


def require_exact(payload: Mapping[str, object], expected: set[str], path: str) -> None:
    reject_unknown(payload, expected, path)
    missing = sorted(expected - set(payload), key=canonical_string_sort_key)
    if missing:
        prefix = f"{path}." if path else ""
        raise ValueError(f"{prefix}{missing[0]} is required")


def mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ValueError(f"{path} keys must be strings")
    return value  # type: ignore[return-value]


def sequence(value: object, path: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError(f"{path} must be an array")
    return value


def string(payload: Mapping[str, object], name: str, path: str = "") -> str:
    value = payload.get(name)
    field_path = f"{path}.{name}" if path else name
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field_path} must be a normalized non-blank string")
    _valid_unicode_text(value, field_path)
    return value


def optional_string(payload: Mapping[str, object], name: str, path: str) -> str | None:
    if payload.get(name) is None:
        return None
    return string(payload, name, path)


def string_sequence(payload: Mapping[str, object], name: str, path: str) -> tuple[str, ...]:
    values = sequence(payload.get(name, ()), f"{path}.{name}")
    result = tuple(
        string({name: value}, name, f"{path}.{name}.{index}") for index, value in enumerate(values)
    )
    if len(result) > 100 or len(set(result)) != len(result):
        raise ValueError(f"{path}.{name} must contain at most 100 unique strings")
    return result


def optional_number(payload: Mapping[str, object], name: str, path: str) -> float | None:
    if payload.get(name) is None:
        return None
    return number(payload[name], f"{path}.{name}")


def number(value: object, path: str) -> float:
    validated_number(value, path)
    return float(value)  # type: ignore[arg-type]


def integer(value: object, path: str) -> int:
    validated_integer(value, path)
    return value  # type: ignore[return-value]


def bounded_weight(value: float, path: str) -> None:
    validated_number(value, path)
    if not 0.1 <= value <= 10.0:
        raise ValueError(f"{path} must be within 0.1..10")


def validated_opaque(value: object, path: str, *, maximum: int = 256) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{path} must be a normalized non-blank string")
    if len(value) > maximum:
        raise ValueError(f"{path} exceeds {maximum} characters")
    _valid_unicode_text(value, path)


def validated_sha256(value: object, path: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{path} must be 64 lowercase hexadecimal characters")


def validated_string_values(values: Sequence[str], path: str) -> None:
    for value in values:
        validated_opaque(value, path)
    if len(values) > 100 or tuple(values) != tuple(
        sorted(set(values), key=canonical_string_sort_key)
    ):
        raise ValueError(f"{path} must contain at most 100 UTF-8 sorted unique strings")


def validated_number(value: object, path: str) -> None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"{path} must be a number")
    if not math.isfinite(value):
        raise ValueError(f"{path} must be finite")


def validated_integer(value: object, path: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{path} must be an integer")


def canonical_tuple(values: object, item_type: type, path: str) -> tuple:
    if isinstance(values, str | bytes):
        raise ValueError(f"{path} must be an array")
    try:
        result = tuple(values)  # type: ignore[arg-type]
    except TypeError as error:
        raise ValueError(f"{path} must be an array") from error
    if not all(isinstance(item, item_type) for item in result):
        raise ValueError(f"{path} contains an invalid runtime type")
    return result


def parsed_datetime(value: str, path: str) -> datetime:
    validated_opaque(value, path)
    if _RFC3339_UTC.fullmatch(value) is None:
        raise ValueError(f"{path} must be RFC3339 UTC using Z")
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError as error:
        raise ValueError(f"{path} must be RFC3339 UTC using Z") from error
    return parsed


def _valid_unicode_text(value: str, path: str) -> None:
    if any(
        0xD800 <= ord(character) <= 0xDFFF
        or ord(character) < 0x20
        or 0x7F <= ord(character) <= 0x9F
        for character in value
    ):
        raise ValueError(f"{path} contains invalid Unicode or control characters")


__all__ = (
    "bounded_weight",
    "canonical_tuple",
    "integer",
    "mapping",
    "number",
    "optional_number",
    "optional_string",
    "parsed_datetime",
    "reject_unknown",
    "require_exact",
    "sequence",
    "string",
    "string_sequence",
    "validated_integer",
    "validated_number",
    "validated_opaque",
    "validated_sha256",
    "validated_string_values",
)
