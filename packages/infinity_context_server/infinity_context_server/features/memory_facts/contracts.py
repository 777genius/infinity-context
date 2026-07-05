"""HTTP request models for the memory_facts server feature."""

from __future__ import annotations

from infinity_context_contracts.features.memory_facts import (
    MemoryFactSourceRefDto,
    RememberFactRequestDto,
    UpdateFactRequestDto,
)
from pydantic import BaseModel, ConfigDict, Field


class MemoryFactSourceRefHttpRequest(BaseModel):
    """HTTP shape for source evidence attached to a memory fact."""

    model_config = ConfigDict(extra="forbid")

    source_type: str = Field(min_length=1, max_length=80)
    source_id: str = Field(min_length=1, max_length=240)
    chunk_id: str | None = Field(default=None, min_length=1, max_length=160)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    quote_preview: str | None = Field(default=None, max_length=1000)
    page_number: int | None = Field(default=None, ge=1)
    time_start_ms: int | None = Field(default=None, ge=0)
    time_end_ms: int | None = Field(default=None, ge=0)
    bbox: tuple[float, float, float, float] | None = None

    def to_contract(self) -> MemoryFactSourceRefDto:
        return MemoryFactSourceRefDto(
            source_type=self.source_type,
            source_id=self.source_id,
            chunk_id=self.chunk_id,
            char_start=self.char_start,
            char_end=self.char_end,
            quote_preview=self.quote_preview,
            page_number=self.page_number,
            time_start_ms=self.time_start_ms,
            time_end_ms=self.time_end_ms,
            bbox=self.bbox,
        )


class RememberFactHttpRequest(BaseModel):
    """HTTP request accepted by the feature-owned fact creation seam."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)
    source_refs: list[MemoryFactSourceRefHttpRequest] = Field(min_length=1)
    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    memory_scope_id: str | None = Field(default=None, min_length=1, max_length=80)
    thread_id: str | None = Field(default=None, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    memory_scope_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    thread_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    kind: str = Field(default="note", min_length=1, max_length=80)
    classification: str = Field(default="internal", min_length=1, max_length=80)
    category: str | None = Field(default=None, max_length=80)
    tags: list[str] = Field(default_factory=list, max_length=20)
    ttl_policy: str | None = Field(default=None, max_length=80)

    def to_contract(self) -> RememberFactRequestDto:
        return RememberFactRequestDto(
            text=self.text,
            source_refs=tuple(ref.to_contract() for ref in self.source_refs),
            space_id=self.space_id,
            memory_scope_id=self.memory_scope_id,
            thread_id=self.thread_id,
            space_slug=self.space_slug,
            memory_scope_external_ref=self.memory_scope_external_ref,
            thread_external_ref=self.thread_external_ref,
            kind=self.kind,
            classification=self.classification,
            category=self.category,
            tags=tuple(self.tags),
            ttl_policy=self.ttl_policy,
        )


class UpdateFactHttpRequest(BaseModel):
    """HTTP request accepted by the feature-owned fact update seam."""

    model_config = ConfigDict(extra="forbid")

    space_id: str = Field(min_length=1, max_length=80)
    memory_scope_id: str = Field(min_length=1, max_length=80)
    thread_id: str | None = Field(default=None, max_length=80)
    expected_version: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=1, max_length=240)
    source_refs: list[MemoryFactSourceRefHttpRequest] = Field(min_length=1)

    def to_contract(self) -> UpdateFactRequestDto:
        return UpdateFactRequestDto(
            expected_version=self.expected_version,
            text=self.text,
            reason=self.reason,
            source_refs=tuple(ref.to_contract() for ref in self.source_refs),
        )


class ForgetFactHttpRequest(BaseModel):
    """HTTP request accepted by the feature-owned fact tombstone seam."""

    model_config = ConfigDict(extra="forbid")

    space_id: str = Field(min_length=1, max_length=80)
    memory_scope_id: str = Field(min_length=1, max_length=80)
    thread_id: str | None = Field(default=None, max_length=80)
    expected_version: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=240)


__all__ = (
    "ForgetFactHttpRequest",
    "MemoryFactSourceRefHttpRequest",
    "RememberFactHttpRequest",
    "UpdateFactHttpRequest",
)
