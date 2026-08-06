"""Optional stable taxonomy normalization owned by the memory_facts feature."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from infinity_context_core.features.memory_facts.domain.value_objects import (
    FactRetention,
)

DEFAULT_FACT_CATEGORY = "uncategorized"
MAX_FACT_TAGS = 10
MAX_FACT_TAG_CHARS = 48

_TAG_RE = re.compile(r"[^a-z0-9_-]+")
_ALLOWED_CATEGORIES = {
    "architecture",
    "project_context",
    "user_preferences",
    "current_task",
    "documents",
    "procedures",
    "debug_notes",
    DEFAULT_FACT_CATEGORY,
}
_KIND_CATEGORY_DEFAULTS = {
    "architecture_decision": "architecture",
    "constraint": "project_context",
    "user_preference": "user_preferences",
    "note": DEFAULT_FACT_CATEGORY,
}
_TTL_DAYS = {
    "durable": None,
    "task": 3,
    "short": 7,
    "review": 30,
    "delete_review": 14,
}


@dataclass(frozen=True, slots=True)
class FactTtlPolicy:
    name: str
    duration: timedelta | None


@dataclass(frozen=True, slots=True)
class NormalizedFactTaxonomy:
    category: str
    tags: tuple[str, ...]
    ttl_policy: FactTtlPolicy
    unknown_labels: tuple[str, ...] = ()


def normalize_fact_taxonomy_fields(
    *,
    kind: str,
    category: str | None,
    tags: Iterable[str],
    ttl_policy: str | None,
) -> NormalizedFactTaxonomy:
    """Normalize stable API taxonomy without constraining the aggregate's extension fields."""

    unknown: list[str] = []
    normalized_category = _normalize_label(category)
    if not normalized_category:
        normalized_category = _KIND_CATEGORY_DEFAULTS.get(kind, DEFAULT_FACT_CATEGORY)
    if normalized_category not in _ALLOWED_CATEGORIES:
        unknown.append(f"category:{normalized_category}")
        normalized_category = DEFAULT_FACT_CATEGORY
    normalized_tags = _normalize_tags(tags, unknown=unknown)
    ttl_name = _normalize_label(ttl_policy) or _default_ttl_for_category(normalized_category)
    if ttl_name not in _TTL_DAYS:
        unknown.append(f"ttl:{ttl_name}")
        ttl_name = "review"
    days = _TTL_DAYS[ttl_name]
    return NormalizedFactTaxonomy(
        category=normalized_category,
        tags=normalized_tags,
        ttl_policy=FactTtlPolicy(
            name=ttl_name,
            duration=None if days is None else timedelta(days=days),
        ),
        unknown_labels=tuple(unknown),
    )


def materialize_fact_retention_expiry(
    retention: FactRetention | None,
    *,
    now: datetime,
) -> FactRetention | None:
    """Derive prompt expiry for a canonical TTL while preserving explicit overrides."""

    if retention is None or retention.context_expires_at is not None:
        return retention
    ttl_policy = retention.ttl_policy
    if ttl_policy not in _TTL_DAYS or (days := _TTL_DAYS[ttl_policy]) is None:
        return retention
    return FactRetention(
        ttl_policy=ttl_policy,
        context_expires_at=now + timedelta(days=days),
        purge_after=retention.purge_after,
    )


def _normalize_tags(labels: Iterable[str], *, unknown: list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for label in labels:
        tag = _normalize_label(label)
        if not tag:
            continue
        if len(tag) > MAX_FACT_TAG_CHARS:
            unknown.append(f"tag:{tag[:MAX_FACT_TAG_CHARS]}")
            tag = tag[:MAX_FACT_TAG_CHARS].rstrip("_-")
        if tag and tag not in normalized:
            normalized.append(tag)
        if len(normalized) >= MAX_FACT_TAGS:
            break
    return tuple(normalized)


def _normalize_label(value: str | None) -> str | None:
    if value is None:
        return None
    label = _TAG_RE.sub("_", value.strip().lower()).strip("_-")
    return label or None


def _default_ttl_for_category(category: str) -> str:
    if category in {"current_task", "debug_notes"}:
        return "task"
    if category == "documents":
        return "review"
    return "durable"


__all__ = (
    "DEFAULT_FACT_CATEGORY",
    "FactTtlPolicy",
    "MAX_FACT_TAG_CHARS",
    "MAX_FACT_TAGS",
    "NormalizedFactTaxonomy",
    "normalize_fact_taxonomy_fields",
)
