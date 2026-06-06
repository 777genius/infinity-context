"""Provider adapter ports and adapter result DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class PortStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class PortDiagnostic:
    code: str
    safe_message: str
    retryable: bool
    details: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AdapterCapabilities:
    name: str
    enabled: bool
    healthy: bool
    supports_upsert: bool
    supports_delete: bool
    supports_search: bool
    supports_filters: bool
    supports_temporal_queries: bool = False
    degraded_reason: str | None = None


class MemoryAdapterPort(Protocol):
    async def capabilities(self) -> AdapterCapabilities:
        """Return safe adapter capability metadata."""


@dataclass(frozen=True)
class EmbeddingResult:
    status: PortStatus
    vectors: tuple[tuple[float, ...], ...]
    model: str | None = None
    dimensions: int | None = None
    diagnostics: tuple[PortDiagnostic, ...] = ()

    @classmethod
    def degraded(cls, code: str, retryable: bool = True) -> EmbeddingResult:
        return cls(
            status=PortStatus.DEGRADED,
            vectors=(),
            diagnostics=(
                PortDiagnostic(
                    code=code,
                    safe_message="Embedding generation degraded",
                    retryable=retryable,
                ),
            ),
        )


class EmbeddingPort(MemoryAdapterPort, Protocol):
    async def embed_texts(self, texts: tuple[str, ...]) -> EmbeddingResult:
        """Return embeddings for query or chunk texts."""


@dataclass(frozen=True)
class VectorCandidate:
    chunk_id: str
    space_id: str
    profile_id: str
    score: float
    projection_version: str
    preview: str | None = None


@dataclass(frozen=True)
class GraphCandidate:
    source_fact_ids: tuple[str, ...]
    source_chunk_ids: tuple[str, ...]
    relation_label: str
    score: float
    diagnostics: dict[str, str]


@dataclass(frozen=True)
class VectorSearchResult:
    status: PortStatus
    items: tuple[VectorCandidate, ...]
    diagnostics: tuple[PortDiagnostic, ...] = ()

    @classmethod
    def ok(cls, items: list[VectorCandidate]) -> VectorSearchResult:
        return cls(status=PortStatus.OK, items=tuple(items))

    @classmethod
    def degraded(cls, code: str, retryable: bool = True) -> VectorSearchResult:
        return cls(
            status=PortStatus.DEGRADED,
            items=(),
            diagnostics=(
                PortDiagnostic(
                    code=code,
                    safe_message="Vector retrieval degraded",
                    retryable=retryable,
                ),
            ),
        )


@dataclass(frozen=True)
class VectorUpsertItem:
    chunk_id: str
    space_id: str
    profile_id: str
    thread_id: str | None
    text: str
    vector: tuple[float, ...]
    projection_version: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorWriteResult:
    status: PortStatus
    affected_count: int
    diagnostics: tuple[PortDiagnostic, ...] = ()

    @classmethod
    def ok(cls, affected_count: int) -> VectorWriteResult:
        return cls(status=PortStatus.OK, affected_count=affected_count)

    @classmethod
    def degraded(cls, code: str, retryable: bool = True) -> VectorWriteResult:
        return cls(
            status=PortStatus.DEGRADED,
            affected_count=0,
            diagnostics=(
                PortDiagnostic(
                    code=code,
                    safe_message="Vector write degraded",
                    retryable=retryable,
                ),
            ),
        )


class VectorMemoryPort(MemoryAdapterPort, Protocol):
    async def upsert_chunks(self, items: tuple[VectorUpsertItem, ...]) -> VectorWriteResult:
        """Upsert derived chunk vectors. Never owns canonical lifecycle."""

    async def delete_chunks(self, chunk_ids: tuple[str, ...]) -> VectorWriteResult:
        """Delete derived chunk vectors by canonical chunk ids."""

    async def search_chunks(
        self,
        *,
        space_id: str,
        profile_ids: tuple[str, ...],
        thread_id: str | None = None,
        query_vector: tuple[float, ...],
        limit: int,
    ) -> VectorSearchResult:
        """Search derived vector candidates."""


@dataclass(frozen=True)
class GraphSearchResult:
    status: PortStatus
    items: tuple[GraphCandidate, ...]
    diagnostics: tuple[PortDiagnostic, ...] = ()

    @classmethod
    def ok(cls, items: list[GraphCandidate]) -> GraphSearchResult:
        return cls(status=PortStatus.OK, items=tuple(items))

    @classmethod
    def degraded(cls, code: str, retryable: bool = True) -> GraphSearchResult:
        return cls(
            status=PortStatus.DEGRADED,
            items=(),
            diagnostics=(
                PortDiagnostic(
                    code=code,
                    safe_message="Graph retrieval degraded",
                    retryable=retryable,
                ),
            ),
        )


class GraphMemoryPort(MemoryAdapterPort, Protocol):
    async def upsert_fact(
        self,
        fact_id: str,
        text: str,
        metadata: dict[str, str],
    ) -> VectorWriteResult:
        """Upsert a fact-derived graph node or episode. Derived only."""

    async def delete_fact(self, fact_id: str) -> VectorWriteResult:
        """Delete or tombstone a fact-derived graph projection."""

    async def search(
        self,
        *,
        space_id: str,
        profile_ids: tuple[str, ...],
        thread_id: str | None = None,
        query: str,
        limit: int,
    ) -> GraphSearchResult:
        """Search graph candidates that must be hydrated through Postgres."""
