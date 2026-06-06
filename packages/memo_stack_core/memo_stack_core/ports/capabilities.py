"""Capability-specific memory ports.

These contracts describe what Memo Stack Core can ask from an engine adapter. They
do not describe provider SDKs. Canonical lifecycle stays in Memo Stack Core and
Postgres; adapters may index, project, recall, or report health.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from memo_stack_core.domain.entities import SourceRef
from memo_stack_core.domain.errors import MemoryValidationError


class MemoryCapability(StrEnum):
    DOCUMENT_MEMORY = "document_memory"
    RAG_RECALL = "rag_recall"
    SESSION_MEMORY = "session_memory"
    TEMPORAL_FACT_GRAPH = "temporal_fact_graph"
    FACT_PROJECTION = "fact_projection"
    VECTOR_RECALL = "vector_recall"
    PROJECTION_FORGET = "projection_forget"
    ENGINE_HEALTH = "engine_health"


class CapabilityStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


class CapabilityMode(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    FALLBACK = "fallback"
    SHADOW = "shadow"
    DISABLED = "disabled"


class ConsistencyMode(StrEnum):
    CANONICAL_ONLY = "canonical_only"
    BEST_EFFORT = "best_effort"
    REQUIRE_FRESH_PROJECTION = "require_fresh_projection"


class ProjectionFreshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    REBUILDING = "rebuilding"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class CapabilityDiagnostic:
    code: str
    safe_message: str
    retryable: bool = False
    details: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise MemoryValidationError("CapabilityDiagnostic.code is required")
        if not self.safe_message.strip():
            raise MemoryValidationError("CapabilityDiagnostic.safe_message is required")


@dataclass(frozen=True)
class CapabilityDescriptor:
    capability: MemoryCapability
    adapter_name: str
    mode: CapabilityMode
    status: CapabilityStatus
    enabled: bool
    supports_scope_filter: bool
    supports_source_refs: bool
    supports_update: bool = False
    supports_delete: bool = False
    external_ai_allowed: bool = False
    projection_freshness: ProjectionFreshness = ProjectionFreshness.NOT_APPLICABLE
    projection_lag_seconds: int | None = None
    schema_version: str | None = None
    adapter_version: str | None = None
    degraded_reason: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.adapter_name.strip():
            raise MemoryValidationError("CapabilityDescriptor.adapter_name is required")
        if self.projection_lag_seconds is not None and self.projection_lag_seconds < 0:
            raise MemoryValidationError(
                "CapabilityDescriptor.projection_lag_seconds must be non-negative"
            )
        if self.status == CapabilityStatus.DISABLED and self.enabled:
            raise MemoryValidationError("Disabled capability descriptor cannot be enabled")
        if self.mode == CapabilityMode.DISABLED and self.enabled:
            raise MemoryValidationError("Disabled capability mode cannot be enabled")


@dataclass(frozen=True)
class MemoryScopeFilter:
    space_id: str
    profile_ids: tuple[str, ...]
    thread_id: str | None = None
    category: str | None = None
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.space_id.strip():
            raise MemoryValidationError("MemoryScopeFilter.space_id is required")
        if not self.profile_ids:
            raise MemoryValidationError("MemoryScopeFilter.profile_ids is required")
        if any(not profile_id.strip() for profile_id in self.profile_ids):
            raise MemoryValidationError("MemoryScopeFilter.profile_ids cannot contain blanks")
        if len(set(self.profile_ids)) != len(self.profile_ids):
            raise MemoryValidationError("MemoryScopeFilter.profile_ids cannot contain duplicates")
        if self.thread_id is not None and not self.thread_id.strip():
            raise MemoryValidationError("MemoryScopeFilter.thread_id cannot be blank")


@dataclass(frozen=True)
class CapabilityRecallQuery:
    scope: MemoryScopeFilter
    query: str
    limit: int
    consistency_mode: ConsistencyMode = ConsistencyMode.BEST_EFFORT
    min_score: float | None = None

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise MemoryValidationError("CapabilityRecallQuery.query is required")
        if self.limit < 1:
            raise MemoryValidationError("CapabilityRecallQuery.limit must be positive")
        if self.min_score is not None and not 0 <= self.min_score <= 1:
            raise MemoryValidationError("CapabilityRecallQuery.min_score must be between 0 and 1")


@dataclass(frozen=True)
class CapabilityRecallCandidate:
    item_id: str
    item_type: str
    text: str
    score: float
    source_refs: tuple[SourceRef, ...]
    capability: MemoryCapability
    adapter_name: str
    diagnostics: tuple[CapabilityDiagnostic, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.item_id.strip():
            raise MemoryValidationError("CapabilityRecallCandidate.item_id is required")
        if not self.item_type.strip():
            raise MemoryValidationError("CapabilityRecallCandidate.item_type is required")
        if not self.text.strip():
            raise MemoryValidationError("CapabilityRecallCandidate.text is required")
        if not 0 <= self.score <= 1:
            raise MemoryValidationError("CapabilityRecallCandidate.score must be between 0 and 1")
        if not self.adapter_name.strip():
            raise MemoryValidationError("CapabilityRecallCandidate.adapter_name is required")


@dataclass(frozen=True)
class CapabilityRecallResult:
    status: CapabilityStatus
    items: tuple[CapabilityRecallCandidate, ...]
    diagnostics: tuple[CapabilityDiagnostic, ...] = ()
    projection_freshness: ProjectionFreshness = ProjectionFreshness.UNKNOWN


@dataclass(frozen=True)
class DocumentMemoryWrite:
    document_id: str
    space_id: str
    profile_id: str
    title: str
    text: str
    source_refs: tuple[SourceRef, ...]
    chunk_ids: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.document_id.strip():
            raise MemoryValidationError("DocumentMemoryWrite.document_id is required")
        if not self.space_id.strip():
            raise MemoryValidationError("DocumentMemoryWrite.space_id is required")
        if not self.profile_id.strip():
            raise MemoryValidationError("DocumentMemoryWrite.profile_id is required")
        if not self.title.strip():
            raise MemoryValidationError("DocumentMemoryWrite.title is required")
        if not self.text.strip():
            raise MemoryValidationError("DocumentMemoryWrite.text is required")
        if any(not chunk_id.strip() for chunk_id in self.chunk_ids):
            raise MemoryValidationError("DocumentMemoryWrite.chunk_ids cannot contain blanks")


@dataclass(frozen=True)
class FactProjectionWrite:
    fact_id: str
    space_id: str
    profile_id: str
    text: str
    version: int
    source_refs: tuple[SourceRef, ...]
    valid_at: datetime | None = None
    invalid_at: datetime | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.fact_id.strip():
            raise MemoryValidationError("FactProjectionWrite.fact_id is required")
        if not self.space_id.strip():
            raise MemoryValidationError("FactProjectionWrite.space_id is required")
        if not self.profile_id.strip():
            raise MemoryValidationError("FactProjectionWrite.profile_id is required")
        if not self.text.strip():
            raise MemoryValidationError("FactProjectionWrite.text is required")
        if self.version < 1:
            raise MemoryValidationError("FactProjectionWrite.version must be positive")
        if (
            self.valid_at is not None
            and self.invalid_at is not None
            and self.invalid_at < self.valid_at
        ):
            raise MemoryValidationError("FactProjectionWrite.invalid_at must be >= valid_at")


@dataclass(frozen=True)
class ProjectionWriteResult:
    status: CapabilityStatus
    affected_ids: tuple[str, ...]
    diagnostics: tuple[CapabilityDiagnostic, ...] = ()
    projection_freshness: ProjectionFreshness = ProjectionFreshness.UNKNOWN


@dataclass(frozen=True)
class ProjectionForgetRequest:
    canonical_ids: tuple[str, ...]
    reason: str

    def __post_init__(self) -> None:
        if not self.canonical_ids:
            raise MemoryValidationError("ProjectionForgetRequest.canonical_ids is required")
        if any(not canonical_id.strip() for canonical_id in self.canonical_ids):
            raise MemoryValidationError(
                "ProjectionForgetRequest.canonical_ids cannot contain blanks"
            )
        if not self.reason.strip():
            raise MemoryValidationError("ProjectionForgetRequest.reason is required")


@dataclass(frozen=True)
class ProjectionForgetResult:
    status: CapabilityStatus
    forgotten_ids: tuple[str, ...]
    diagnostics: tuple[CapabilityDiagnostic, ...] = ()


@dataclass(frozen=True)
class EngineHealthSnapshot:
    adapter_name: str
    status: CapabilityStatus
    capabilities: tuple[CapabilityDescriptor, ...]
    diagnostics: tuple[CapabilityDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        if not self.adapter_name.strip():
            raise MemoryValidationError("EngineHealthSnapshot.adapter_name is required")


class EngineHealthPort(Protocol):
    async def capability_descriptors(self) -> tuple[CapabilityDescriptor, ...]:
        """Return safe capability metadata for diagnostics and routing."""

    async def health(self) -> EngineHealthSnapshot:
        """Return safe health metadata without leaking provider secrets."""


class DocumentMemoryPort(EngineHealthPort, Protocol):
    async def ingest_document(self, command: DocumentMemoryWrite) -> ProjectionWriteResult:
        """Index or project a canonical document for future recall."""

    async def forget_document(self, command: ProjectionForgetRequest) -> ProjectionForgetResult:
        """Forget derived document projections by canonical ids."""


class RagRecallPort(EngineHealthPort, Protocol):
    async def recall(self, query: CapabilityRecallQuery) -> CapabilityRecallResult:
        """Return RAG candidates that Memo Stack Core may hydrate and rank."""


class SessionMemoryPort(EngineHealthPort, Protocol):
    async def recall_session(self, query: CapabilityRecallQuery) -> CapabilityRecallResult:
        """Return short-lived or session-scoped memory candidates."""


class TemporalFactGraphPort(EngineHealthPort, Protocol):
    async def upsert_fact(self, command: FactProjectionWrite) -> ProjectionWriteResult:
        """Project a canonical fact into a temporal graph."""

    async def search_facts(self, query: CapabilityRecallQuery) -> CapabilityRecallResult:
        """Return temporal fact candidates."""


class FactProjectionPort(EngineHealthPort, Protocol):
    async def upsert_fact_projection(self, command: FactProjectionWrite) -> ProjectionWriteResult:
        """Project a canonical fact into a derived engine."""


class VectorRecallPort(EngineHealthPort, Protocol):
    async def recall_vectors(self, query: CapabilityRecallQuery) -> CapabilityRecallResult:
        """Return vector recall candidates."""


class ProjectionForgetPort(EngineHealthPort, Protocol):
    async def forget_projection(self, command: ProjectionForgetRequest) -> ProjectionForgetResult:
        """Forget derived projections by canonical ids."""
