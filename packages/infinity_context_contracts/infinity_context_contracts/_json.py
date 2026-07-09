"""JSON-compatible contract value helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from typing import Any, TypeAlias

JsonPrimitive: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


def json_compatible(value: Any) -> JsonValue:
    """Return a plain JSON-compatible representation of contract DTO values."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return json_compatible(value.to_dict())
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: json_compatible(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {
            str(item_key): json_compatible(item_value)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list | tuple):
        return [json_compatible(item) for item in value]
    raise TypeError(f"{type(value).__name__} is not JSON-compatible")
