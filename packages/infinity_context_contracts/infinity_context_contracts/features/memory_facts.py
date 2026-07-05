"""Public contract DTOs for the memory_facts feature."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .._json import JsonObject, JsonValue, json_compatible

FEATURE_ID = "memory_facts"


@dataclass(frozen=True, slots=True)
class MemoryFactIdentityDto:
    """Stable public identity fields for a memory fact."""

    id: str
    space_id: str
    memory_scope_id: str
    thread_id: str | None = None

    def to_dict(self) -> JsonObject:
        return {
            "id": self.id,
            "space_id": self.space_id,
            "memory_scope_id": self.memory_scope_id,
            "thread_id": self.thread_id,
        }


@dataclass(frozen=True, slots=True)
class MemoryFactSourceRefDto:
    """Stable source reference shape attached to memory fact evidence."""

    source_type: str
    source_id: str
    chunk_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote_preview: str | None = None
    page_number: int | None = None
    time_start_ms: int | None = None
    time_end_ms: int | None = None
    bbox: Sequence[float] | None = None

    def to_dict(self) -> JsonObject:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "chunk_id": self.chunk_id,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "quote_preview": self.quote_preview,
            "page_number": self.page_number,
            "time_start_ms": self.time_start_ms,
            "time_end_ms": self.time_end_ms,
            "bbox": json_compatible(self.bbox),
        }


@dataclass(frozen=True, slots=True)
class MemoryFactVisibilityDto:
    """Stable lifecycle, trust, and version fields for a memory fact."""

    status: str = "active"
    version: int = 1
    confidence: str = "medium"
    trust_level: str = "medium"
    classification: str = "internal"
    ttl_policy: str | None = None
    expires_at: str | None = None

    def to_dict(self) -> JsonObject:
        return {
            "status": self.status,
            "version": self.version,
            "confidence": self.confidence,
            "trust_level": self.trust_level,
            "classification": self.classification,
            "ttl_policy": self.ttl_policy,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True, slots=True)
class MemoryFactReadDto:
    """Stable read model for a memory fact response item."""

    identity: MemoryFactIdentityDto
    text: str
    kind: str = "note"
    visibility: MemoryFactVisibilityDto = field(default_factory=MemoryFactVisibilityDto)
    category: str | None = None
    tags: Sequence[str] = field(default_factory=tuple)
    source_refs: Sequence[MemoryFactSourceRefDto | Mapping[str, JsonValue]] = field(
        default_factory=tuple
    )
    created_at: str | None = None
    updated_at: str | None = None
    indexing_status: str | None = None

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            **self.identity.to_dict(),
            "text": self.text,
            "kind": self.kind,
            **self.visibility.to_dict(),
            "category": self.category,
            "tags": json_compatible(self.tags),
            "source_refs": _source_refs_to_dicts(self.source_refs),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.indexing_status is not None:
            payload["indexing_status"] = self.indexing_status
        return payload


@dataclass(frozen=True, slots=True)
class RememberFactRequestDto:
    """Stable request shape for remembering a memory fact."""

    text: str
    source_refs: Sequence[MemoryFactSourceRefDto | Mapping[str, JsonValue]]
    space_id: str | None = None
    memory_scope_id: str | None = None
    thread_id: str | None = None
    space_slug: str | None = None
    memory_scope_external_ref: str | None = None
    thread_external_ref: str | None = None
    kind: str = "note"
    classification: str = "internal"
    category: str | None = None
    tags: Sequence[str] = field(default_factory=tuple)
    ttl_policy: str | None = None

    def to_dict(self) -> JsonObject:
        return {
            "space_id": self.space_id,
            "memory_scope_id": self.memory_scope_id,
            "thread_id": self.thread_id,
            "space_slug": self.space_slug,
            "memory_scope_external_ref": self.memory_scope_external_ref,
            "thread_external_ref": self.thread_external_ref,
            "text": self.text,
            "kind": self.kind,
            "source_refs": _source_refs_to_dicts(self.source_refs),
            "classification": self.classification,
            "category": self.category,
            "tags": json_compatible(self.tags),
            "ttl_policy": self.ttl_policy,
        }


@dataclass(frozen=True, slots=True)
class UpdateFactRequestDto:
    """Stable request shape for updating a memory fact."""

    expected_version: int
    text: str
    reason: str
    source_refs: Sequence[MemoryFactSourceRefDto | Mapping[str, JsonValue]]

    def to_dict(self) -> JsonObject:
        return {
            "expected_version": self.expected_version,
            "text": self.text,
            "reason": self.reason,
            "source_refs": _source_refs_to_dicts(self.source_refs),
        }


@dataclass(frozen=True, slots=True)
class ForgetFactPathParamsDto:
    """Stable path identity for DELETE /v1/facts/{fact_id}."""

    fact_id: str

    def to_path_params(self) -> JsonObject:
        return {"fact_id": self.fact_id}


@dataclass(frozen=True, slots=True)
class RememberFactResultDto:
    """Stable result wrapper for remember fact responses."""

    fact: MemoryFactReadDto

    def to_dict(self) -> JsonObject:
        return {"data": self.fact.to_dict()}


@dataclass(frozen=True, slots=True)
class UpdateFactResultDto:
    """Stable result wrapper for update fact responses."""

    fact: MemoryFactReadDto

    def to_dict(self) -> JsonObject:
        return {"data": self.fact.to_dict()}


@dataclass(frozen=True, slots=True)
class ForgetFactResultDto:
    """Stable result wrapper for forget fact responses."""

    fact: MemoryFactReadDto

    def to_dict(self) -> JsonObject:
        return {"data": self.fact.to_dict()}


def _source_refs_to_dicts(
    source_refs: Sequence[MemoryFactSourceRefDto | Mapping[str, JsonValue]],
) -> JsonValue:
    return json_compatible(
        [
            ref.to_dict() if isinstance(ref, MemoryFactSourceRefDto) else dict(ref)
            for ref in source_refs
        ]
    )


__all__ = [
    "FEATURE_ID",
    "ForgetFactPathParamsDto",
    "ForgetFactResultDto",
    "MemoryFactIdentityDto",
    "MemoryFactReadDto",
    "MemoryFactSourceRefDto",
    "MemoryFactVisibilityDto",
    "RememberFactRequestDto",
    "RememberFactResultDto",
    "UpdateFactRequestDto",
    "UpdateFactResultDto",
]
