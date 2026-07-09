"""Shared helpers for query anchor intent policies."""

from __future__ import annotations

from collections.abc import Iterable

from infinity_context_core.application.safe_payload import safe_metadata_text


def _metadata_text(value: object) -> str:
    if value is None:
        return ""
    return safe_metadata_text(str(value), limit=160).strip().casefold()

def _normalized(value: str) -> str:
    return value.casefold().replace("ё", "е").strip("._-:/#()[]{}")

def _bounded_unique(values: Iterable[str], *, limit: int = 12) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        safe = _metadata_text(value)
        if not safe or safe in seen:
            continue
        seen.add(safe)
        result.append(safe)
        if len(result) >= limit:
            break
    return result
