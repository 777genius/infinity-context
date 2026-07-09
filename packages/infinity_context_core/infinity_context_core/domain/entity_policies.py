"""Shared domain entity policy helpers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from infinity_context_core.domain.entity_types import (
    _AUDIT_SECRET_MARKERS,
    Confidence,
    DataClassification,
)
from infinity_context_core.domain.errors import MemoryValidationError


def _max_confidence(current: Confidence, observed: Confidence | None) -> Confidence:
    if observed is None:
        return current
    rank = {
        Confidence.LOW: 0,
        Confidence.MEDIUM: 1,
        Confidence.HIGH: 2,
    }
    return observed if rank[observed] > rank[current] else current

def _latest_datetime(current: datetime, observed: datetime | None) -> datetime:
    if observed is None:
        return current
    comparable_current = current
    comparable_observed = observed
    if comparable_current.tzinfo is None and comparable_observed.tzinfo is not None:
        comparable_current = comparable_current.replace(tzinfo=comparable_observed.tzinfo)
    elif comparable_current.tzinfo is not None and comparable_observed.tzinfo is None:
        comparable_observed = comparable_observed.replace(tzinfo=comparable_current.tzinfo)
    return observed if comparable_observed > comparable_current else current

def _merge_temporal_window(
    *,
    current_from: datetime | None,
    current_to: datetime | None,
    observed_from: datetime | None,
    observed_to: datetime | None,
) -> tuple[datetime | None, datetime | None]:
    if observed_from is None and observed_to is None:
        return current_from, current_to
    starts = tuple(item for item in (current_from, observed_from) if item is not None)
    next_from = min(starts) if starts else None
    next_to = None if current_to is None or observed_to is None else max(current_to, observed_to)
    return next_from, next_to

def _optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None

def _unique_strings(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        safe = value.strip()
        if not safe or safe in seen:
            continue
        seen.add(safe)
        result.append(safe)
        if len(result) >= 50:
            break
    return tuple(result)

def _append_anchor_audit(
    metadata: Mapping[str, object],
    *,
    key: str,
    event: Mapping[str, object],
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    next_metadata = {**dict(metadata), **dict(extra or {})}
    existing = metadata.get(key)
    events = list(existing) if isinstance(existing, list) else []
    events.append(dict(event))
    next_metadata[key] = events[-20:]
    return next_metadata

def _safe_audit_text(value: str, *, max_chars: int) -> str:
    normalized = value.strip()[:max_chars]
    lowered = normalized.lower()
    if any(marker in lowered for marker in _AUDIT_SECRET_MARKERS):
        return "[redacted]"
    return normalized

def _classification_value(value: str) -> str:
    try:
        return DataClassification(value).value
    except ValueError as exc:
        raise MemoryValidationError("Unknown data classification") from exc

def _validate_taxonomy(*, tags: tuple[str, ...], ttl_policy: str | None) -> None:
    if len(tags) > 10:
        raise MemoryValidationError("Fact tags exceed limit")
    if any(len(tag) > 48 for tag in tags):
        raise MemoryValidationError("Fact tag exceeds max length")
    if ttl_policy is not None and len(ttl_policy) > 80:
        raise MemoryValidationError("Fact ttl_policy exceeds max length")

def _validate_temporal_range(
    *,
    valid_from: datetime | None,
    valid_to: datetime | None,
) -> None:
    if valid_from is None or valid_to is None:
        return
    comparable_from = valid_from
    comparable_to = valid_to
    if comparable_from.tzinfo is None and comparable_to.tzinfo is not None:
        comparable_from = comparable_from.replace(tzinfo=comparable_to.tzinfo)
    elif comparable_from.tzinfo is not None and comparable_to.tzinfo is None:
        comparable_to = comparable_to.replace(tzinfo=comparable_from.tzinfo)
    if comparable_to <= comparable_from:
        raise MemoryValidationError("Temporal valid_to must be after valid_from")
