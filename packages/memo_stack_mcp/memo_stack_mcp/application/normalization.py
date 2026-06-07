"""Small normalization helpers for MCP application services."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def normalize_optional_label(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def normalize_tool_tags(values: Iterable[str]) -> list[str]:
    tags: list[str] = []
    for value in values:
        normalized = normalize_optional_label(value)
        if normalized and normalized not in tags:
            tags.append(normalized)
        if len(tags) >= 10:
            break
    return tags


def drop_none_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: drop_none_values(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [drop_none_values(item) for item in value]
    return value
