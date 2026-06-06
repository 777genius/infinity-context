"""Default auto-memory taxonomy policy.

Taxonomy is resolver-owned metadata. It does not expand canonical MemoryKind.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from memo_stack_core.domain.entities import MemoryKind
from memo_stack_core.ports.auto_memory import MemoryCandidate

DEFAULT_TAXONOMY_VERSION = "memory-taxonomy-v1"
DEFAULT_CATEGORY = "uncategorized"
MAX_TAGS = 10
MAX_TAG_CHARS = 48

_TAG_RE = re.compile(r"[^a-z0-9_-]+")
_ALLOWED_CATEGORIES = {
    "architecture",
    "project_context",
    "user_preferences",
    "current_task",
    "documents",
    "procedures",
    "debug_notes",
    DEFAULT_CATEGORY,
}
_KIND_CATEGORY_DEFAULTS = {
    MemoryKind.ARCHITECTURE_DECISION: "architecture",
    MemoryKind.CONSTRAINT: "project_context",
    MemoryKind.USER_PREFERENCE: "user_preferences",
    MemoryKind.NOTE: DEFAULT_CATEGORY,
}
_TTL_DAYS = {
    "durable": None,
    "task": 3,
    "short": 7,
    "review": 30,
    "delete_review": 14,
}


@dataclass(frozen=True)
class TtlPolicy:
    name: str
    duration: timedelta | None


@dataclass(frozen=True)
class NormalizedTaxonomy:
    category: str
    tags: tuple[str, ...]
    ttl_policy: TtlPolicy
    unknown_labels: tuple[str, ...] = ()


class TaxonomyPolicyPort(Protocol):
    def normalize(self, candidate: MemoryCandidate) -> NormalizedTaxonomy:
        """Normalize category/tags/TTL without persisting raw extractor labels."""


class DefaultTaxonomyPolicy(TaxonomyPolicyPort):
    def normalize(self, candidate: MemoryCandidate) -> NormalizedTaxonomy:
        unknown: list[str] = []
        category = _normalize_label(candidate.category)
        if not category:
            category = _KIND_CATEGORY_DEFAULTS.get(candidate.kind, DEFAULT_CATEGORY)
        if category not in _ALLOWED_CATEGORIES:
            unknown.append(f"category:{category}")
            category = DEFAULT_CATEGORY
        tags = _normalize_tags(candidate.tags, unknown=unknown)
        ttl_name = _normalize_label(candidate.ttl_policy) or _default_ttl_for_category(category)
        if ttl_name not in _TTL_DAYS:
            unknown.append(f"ttl:{ttl_name}")
            ttl_name = "review"
        days = _TTL_DAYS[ttl_name]
        return NormalizedTaxonomy(
            category=category,
            tags=tags,
            ttl_policy=TtlPolicy(
                name=ttl_name,
                duration=None if days is None else timedelta(days=days),
            ),
            unknown_labels=tuple(unknown),
        )


def _normalize_tags(labels: Iterable[str], *, unknown: list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for label in labels:
        tag = _normalize_label(label)
        if not tag:
            continue
        if len(tag) > MAX_TAG_CHARS:
            unknown.append(f"tag:{tag[:MAX_TAG_CHARS]}")
            tag = tag[:MAX_TAG_CHARS].rstrip("_-")
        if tag and tag not in normalized:
            normalized.append(tag)
        if len(normalized) >= MAX_TAGS:
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
