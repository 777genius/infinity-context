"""Default auto-memory taxonomy policy.

Taxonomy is resolver-owned metadata. It does not expand canonical MemoryKind.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from infinity_context_core.domain.entities import MemoryKind
from infinity_context_core.features.memory_facts.public import (
    FactTtlPolicy,
    NormalizedFactTaxonomy,
    normalize_fact_taxonomy_fields,
)
from infinity_context_core.ports.auto_memory import MemoryCandidate

DEFAULT_TAXONOMY_VERSION = "memory-taxonomy-v1"
DEFAULT_CATEGORY = "uncategorized"
MAX_TAGS = 10
MAX_TAG_CHARS = 48

TtlPolicy = FactTtlPolicy
NormalizedTaxonomy = NormalizedFactTaxonomy


class TaxonomyPolicyPort(Protocol):
    def normalize(self, candidate: MemoryCandidate) -> NormalizedTaxonomy:
        """Normalize category/tags/TTL without persisting raw extractor labels."""


class DefaultTaxonomyPolicy(TaxonomyPolicyPort):
    def normalize(self, candidate: MemoryCandidate) -> NormalizedTaxonomy:
        return normalize_taxonomy_fields(
            kind=candidate.kind.value,
            category=candidate.category,
            tags=candidate.tags,
            ttl_policy=candidate.ttl_policy,
        )


def normalize_taxonomy_fields(
    *,
    kind: MemoryKind | str,
    category: str | None,
    tags: Iterable[str],
    ttl_policy: str | None,
) -> NormalizedTaxonomy:
    """Normalize stable taxonomy fields without requiring an extraction candidate."""

    return normalize_fact_taxonomy_fields(
        kind=kind.value if isinstance(kind, MemoryKind) else kind,
        category=category,
        tags=tags,
        ttl_policy=ttl_policy,
    )
