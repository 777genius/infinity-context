"""Ports and DTOs for review-gated auto-memory extraction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from memo_stack_core.domain.entities import Confidence, MemoryKind, SourceRef, TrustLevel

ALLOWED_TTL_POLICIES = frozenset({"durable", "task", "short", "review", "delete_review"})


class CandidateOperation(StrEnum):
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"
    NOOP = "noop"
    REVIEW = "review"


@dataclass(frozen=True)
class SourceProvenance:
    source_type: str
    source_id: str
    trust_level: TrustLevel
    chunk_id: str | None = None
    actor_role: str | None = None
    source_authority: str | None = None


@dataclass(frozen=True)
class MemoryCandidate:
    text: str
    kind: MemoryKind
    confidence: Confidence
    source_refs: tuple[SourceRef, ...]
    safe_reason: str
    operation_hint: CandidateOperation = CandidateOperation.ADD
    category: str | None = None
    tags: tuple[str, ...] = ()
    ttl_policy: str | None = None
    target_fact_id: str | None = None
    target_fact_version: int | None = None
    target_hint: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    expires_at: datetime | None = None


class MemoryClassifierPort(Protocol):
    async def classify(self, *, text: str, source: SourceProvenance) -> tuple[MemoryCandidate, ...]:
        """Return fact candidates that still require admission/review."""


class MemoryExtractorPort(Protocol):
    version: str
    prompt_version: str | None
    requires_external_ai: bool

    async def extract_facts(
        self,
        *,
        text: str,
        source: SourceProvenance,
    ) -> tuple[MemoryCandidate, ...]:
        """Extract candidate facts. Implementations must not write active facts directly."""


FactExtractionPort = MemoryExtractorPort
