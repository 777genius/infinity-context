"""Public contract DTOs for the context_building feature."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .._json import JsonObject, JsonValue, json_compatible

FEATURE_ID = "context_building"


@dataclass(frozen=True, slots=True)
class ContextBudgetDto:
    """Stable prompt-packing budget requested by context clients."""

    max_context_tokens: int
    reserved_response_tokens: int = 0
    max_items: int | None = None
    strategy: str = "balanced"

    def to_dict(self) -> JsonObject:
        return {
            "max_context_tokens": self.max_context_tokens,
            "reserved_response_tokens": self.reserved_response_tokens,
            "max_items": self.max_items,
            "strategy": self.strategy,
        }


@dataclass(frozen=True, slots=True)
class ContextEvidenceDto:
    """Evidence citation for a context item."""

    source_type: str
    source_id: str
    fact_id: str | None = None
    document_id: str | None = None
    chunk_id: str | None = None
    quote_preview: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    page_number: int | None = None
    time_start_ms: int | None = None
    time_end_ms: int | None = None
    bbox: Sequence[float] | None = None
    occurred_at: str | None = None
    score: float | None = None
    trust_level: str = "medium"
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        metadata = json_compatible(self.metadata)
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "fact_id": self.fact_id,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "quote_preview": self.quote_preview,
            "char_start": _explicit_or_metadata(
                self.char_start,
                metadata,
                "char_start",
            ),
            "char_end": _explicit_or_metadata(self.char_end, metadata, "char_end"),
            "page_number": self.page_number,
            "time_start_ms": self.time_start_ms,
            "time_end_ms": self.time_end_ms,
            "bbox": json_compatible(self.bbox),
            "occurred_at": _explicit_or_metadata(
                self.occurred_at,
                metadata,
                "occurred_at",
            ),
            "score": self.score,
            "trust_level": self.trust_level,
            "metadata": metadata,
        }


@dataclass(frozen=True, slots=True)
class ContextItemDto:
    """Prompt-ready evidence item returned by context building."""

    id: str
    text: str
    kind: str
    evidence: Sequence[ContextEvidenceDto | Mapping[str, JsonValue]] = field(
        default_factory=tuple
    )
    score: float | None = None
    token_count: int | None = None
    trust_level: str = "medium"
    classification: str = "internal"
    created_at: str | None = None
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        return {
            "id": self.id,
            "text": self.text,
            "kind": self.kind,
            "evidence": _evidence_to_dicts(self.evidence),
            "score": self.score,
            "token_count": self.token_count,
            "trust_level": self.trust_level,
            "classification": self.classification,
            "created_at": self.created_at,
            "metadata": json_compatible(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class BuildContextRequestDto:
    """Stable request shape for building prompt context."""

    query: str
    space_id: str | None = None
    memory_scope_id: str | None = None
    thread_id: str | None = None
    space_slug: str | None = None
    memory_scope_external_ref: str | None = None
    thread_external_ref: str | None = None
    budget: ContextBudgetDto | Mapping[str, JsonValue] | None = None
    include_kinds: Sequence[str] = field(default_factory=tuple)
    tags: Sequence[str] = field(default_factory=tuple)
    policy_mode: str | None = None
    include_diagnostics: bool = False
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        return {
            "query": self.query,
            "space_id": self.space_id,
            "memory_scope_id": self.memory_scope_id,
            "thread_id": self.thread_id,
            "space_slug": self.space_slug,
            "memory_scope_external_ref": self.memory_scope_external_ref,
            "thread_external_ref": self.thread_external_ref,
            "budget": json_compatible(self.budget),
            "include_kinds": json_compatible(self.include_kinds),
            "tags": json_compatible(self.tags),
            "policy_mode": self.policy_mode,
            "include_diagnostics": self.include_diagnostics,
            "metadata": json_compatible(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class BuildContextResultDto:
    """Stable result wrapper for built prompt context."""

    items: Sequence[ContextItemDto | Mapping[str, JsonValue]]
    rendered_context: str | None = None
    budget: ContextBudgetDto | Mapping[str, JsonValue] | None = None
    total_tokens: int | None = None
    degraded: bool = False
    diagnostics: Mapping[str, JsonValue] = field(default_factory=dict)
    built_at: str | None = None

    def to_dict(self) -> JsonObject:
        return {
            "data": {
                "items": _items_to_dicts(self.items),
                "rendered_context": self.rendered_context,
                "budget": json_compatible(self.budget),
                "total_tokens": self.total_tokens,
                "degraded": self.degraded,
                "diagnostics": json_compatible(self.diagnostics),
                "built_at": self.built_at,
            }
        }


def _evidence_to_dicts(
    evidence: Sequence[ContextEvidenceDto | Mapping[str, JsonValue]],
) -> JsonValue:
    return json_compatible(
        [
            item.to_dict() if isinstance(item, ContextEvidenceDto) else dict(item)
            for item in evidence
        ]
    )


def _items_to_dicts(
    items: Sequence[ContextItemDto | Mapping[str, JsonValue]],
) -> JsonValue:
    return json_compatible(
        [item.to_dict() if isinstance(item, ContextItemDto) else dict(item) for item in items]
    )


def _metadata_value(metadata: JsonValue, key: str) -> JsonValue:
    if isinstance(metadata, dict):
        return metadata.get(key)
    return None


def _explicit_or_metadata(
    value: JsonValue,
    metadata: JsonValue,
    key: str,
) -> JsonValue:
    if value is not None:
        return value
    return _metadata_value(metadata, key)


__all__ = [
    "FEATURE_ID",
    "BuildContextRequestDto",
    "BuildContextResultDto",
    "ContextBudgetDto",
    "ContextEvidenceDto",
    "ContextItemDto",
]
