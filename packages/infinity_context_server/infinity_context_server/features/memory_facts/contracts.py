"""HTTP request models for the memory_facts server feature."""

from __future__ import annotations

from datetime import datetime

from infinity_context_contracts.features.memory_facts import (
    MemoryFactEpistemicContextDto,
    MemoryFactFreshnessDto,
    MemoryFactRetentionDto,
    MemoryFactSourceRefDto,
    MemoryFactTemporalDto,
    RememberFactRequestDto,
    UpdateFactRequestDto,
)
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


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


class MemoryFactTemporalHttpRequest(BaseModel):
    """Typed state, event or timeless temporal extent."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(pattern="^(state|event|timeless)$")
    observed_at: AwareDatetime
    valid_from: AwareDatetime | None = None
    valid_to: AwareDatetime | None = None
    occurred_from: AwareDatetime | None = None
    occurred_to: AwareDatetime | None = None
    basis: str = Field(default="asserted", pattern="^(asserted|inferred|unknown)$")
    precision: str = Field(default="exact", min_length=1, max_length=40)

    def to_contract(self) -> MemoryFactTemporalDto:
        return MemoryFactTemporalDto(
            kind=self.kind,
            observed_at=self.observed_at.isoformat(),
            valid_from=_isoformat(self.valid_from),
            valid_to=_isoformat(self.valid_to),
            occurred_from=_isoformat(self.occurred_from),
            occurred_to=_isoformat(self.occurred_to),
            basis=self.basis,
            precision=self.precision,
        )


class MemoryFactFreshnessHttpRequest(BaseModel):
    """Read-compatible shape; creation rejects confirmation without governance."""

    model_config = ConfigDict(extra="forbid")

    last_confirmed_at: AwareDatetime | None = None
    confirmation_basis: str | None = Field(default=None, min_length=1, max_length=120)

    def to_contract(self) -> MemoryFactFreshnessDto:
        return MemoryFactFreshnessDto(
            last_confirmed_at=_isoformat(self.last_confirmed_at),
            confirmation_basis=self.confirmation_basis,
        )


class MemoryFactRetentionHttpRequest(BaseModel):
    """Retention policy independent from real-world validity."""

    model_config = ConfigDict(extra="forbid")

    ttl_policy: str | None = Field(default=None, min_length=1, max_length=80)
    context_expires_at: AwareDatetime | None = None
    purge_after: AwareDatetime | None = None

    def to_contract(self) -> MemoryFactRetentionDto:
        return MemoryFactRetentionDto(
            ttl_policy=self.ttl_policy,
            context_expires_at=_isoformat(self.context_expires_at),
            purge_after=_isoformat(self.purge_after),
        )


class MemoryFactEpistemicContextHttpRequest(BaseModel):
    """Claim ownership and perspective semantics."""

    model_config = ConfigDict(extra="forbid")

    mode: str = Field(default="world_claim", pattern="^(world_claim|perspective|hypothesis)$")
    asserted_by: str | None = Field(default=None, min_length=1, max_length=160)
    perspective_subject: str | None = Field(default=None, min_length=1, max_length=160)

    def to_contract(self) -> MemoryFactEpistemicContextDto:
        return MemoryFactEpistemicContextDto(
            mode=self.mode,
            asserted_by=self.asserted_by,
            perspective_subject=self.perspective_subject,
        )


class SourceRefRequest(BaseModel):
    """Legacy /v1 source reference request shape owned by the facts seam."""

    model_config = ConfigDict(extra="forbid")

    source_type: str = Field(min_length=1, max_length=80)
    source_id: str = Field(min_length=1, max_length=160)
    chunk_id: str | None = Field(default=None, max_length=160)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    quote_preview: str | None = Field(default=None, max_length=240)
    page_number: int | None = Field(default=None, ge=1)
    time_start_ms: int | None = Field(default=None, ge=0)
    time_end_ms: int | None = Field(default=None, ge=0)
    bbox: tuple[float, float, float, float] | None = None


class RememberFactRequest(BaseModel):
    """Legacy /v1 fact creation request shape."""

    model_config = ConfigDict(extra="forbid")

    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    memory_scope_id: str | None = Field(default=None, min_length=1, max_length=80)
    thread_id: str | None = Field(default=None, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    memory_scope_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    thread_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    repository_id: str | None = Field(default=None, min_length=1, max_length=80)
    code_scope_id: str | None = Field(default=None, min_length=1, max_length=96)
    text: str = Field(min_length=1, max_length=4000)
    kind: str = "note"
    source_refs: list[SourceRefRequest] = Field(min_length=1)
    classification: str = Field(default="internal", max_length=40)
    category: str | None = Field(default=None, max_length=80)
    tags: list[str] = Field(default_factory=list, max_length=10)
    ttl_policy: str | None = Field(default=None, max_length=80)
    temporal: MemoryFactTemporalHttpRequest | None = None
    freshness: MemoryFactFreshnessHttpRequest | None = None
    retention: MemoryFactRetentionHttpRequest | None = None
    epistemic_context: MemoryFactEpistemicContextHttpRequest | None = None


class UpdateFactRequest(BaseModel):
    """Legacy /v1 fact update request shape."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=1, max_length=240)
    source_refs: list[SourceRefRequest] = Field(min_length=1)


class LinkFactRequest(BaseModel):
    """Legacy /v1 fact relation write request shape."""

    model_config = ConfigDict(extra="forbid")

    target_fact_id: str = Field(min_length=1, max_length=160)
    relation_type: str = Field(default="related_to", max_length=80)
    reason: str = Field(min_length=1, max_length=320)
    observed_at: AwareDatetime | None = None
    valid_from: AwareDatetime | None = None
    valid_to: AwareDatetime | None = None


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
    temporal: MemoryFactTemporalHttpRequest | None = None
    freshness: MemoryFactFreshnessHttpRequest | None = None
    retention: MemoryFactRetentionHttpRequest | None = None
    epistemic_context: MemoryFactEpistemicContextHttpRequest | None = None

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
            temporal=self.temporal.to_contract() if self.temporal is not None else None,
            freshness=self.freshness.to_contract() if self.freshness is not None else None,
            retention=self.retention.to_contract() if self.retention is not None else None,
            epistemic_context=(
                self.epistemic_context.to_contract() if self.epistemic_context is not None else None
            ),
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
    retention: MemoryFactRetentionHttpRequest | None = None

    def to_contract(self) -> UpdateFactRequestDto:
        return UpdateFactRequestDto(
            expected_version=self.expected_version,
            text=self.text,
            reason=self.reason,
            source_refs=tuple(ref.to_contract() for ref in self.source_refs),
            retention=self.retention.to_contract() if self.retention is not None else None,
        )


class ForgetFactHttpRequest(BaseModel):
    """HTTP request accepted by the feature-owned fact tombstone seam."""

    model_config = ConfigDict(extra="forbid")

    space_id: str = Field(min_length=1, max_length=80)
    memory_scope_id: str = Field(min_length=1, max_length=80)
    thread_id: str | None = Field(default=None, max_length=80)
    expected_version: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=240)


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


__all__ = (
    "ForgetFactHttpRequest",
    "LinkFactRequest",
    "MemoryFactSourceRefHttpRequest",
    "MemoryFactEpistemicContextHttpRequest",
    "MemoryFactFreshnessHttpRequest",
    "MemoryFactRetentionHttpRequest",
    "MemoryFactTemporalHttpRequest",
    "RememberFactRequest",
    "RememberFactHttpRequest",
    "SourceRefRequest",
    "UpdateFactRequest",
    "UpdateFactHttpRequest",
)
