"""Unit of work port."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol

from infinity_context_core.domain.entities import SourceRef
from infinity_context_core.domain.events import OutboxEvent
from infinity_context_core.ports.assets import (
    AssetRepositoryPort,
    ContextLinkRepositoryPort,
    ContextLinkSuggestionRepositoryPort,
)
from infinity_context_core.ports.benchmark_runs import BenchmarkRunRepositoryPort
from infinity_context_core.ports.captures import CaptureRepositoryPort
from infinity_context_core.ports.extraction import AssetExtractionRepositoryPort
from infinity_context_core.ports.repositories import (
    AnchorRepositoryPort,
    ChunkRepositoryPort,
    DocumentRepositoryPort,
    EpisodeRepositoryPort,
    FactRelationRepositoryPort,
    FactRepositoryPort,
    IdempotencyRepositoryPort,
    ScopeRepositoryPort,
    SuggestionRepositoryPort,
    UserRepositoryPort,
)
from infinity_context_core.ports.usage import UsageRepositoryPort


class OutboxPort(Protocol):
    async def enqueue(self, event: OutboxEvent) -> None:
        """Persist an outbox event in the current transaction."""

    async def enqueue_or_reschedule(self, event: OutboxEvent) -> None:
        """Persist an event or make its matching unprocessed delivery ready now."""


class UnitOfWorkPort(Protocol):
    benchmark_runs: BenchmarkRunRepositoryPort
    scope: ScopeRepositoryPort
    users: UserRepositoryPort
    facts: FactRepositoryPort
    fact_relations: FactRelationRepositoryPort
    assets: AssetRepositoryPort
    asset_extractions: AssetExtractionRepositoryPort
    context_links: ContextLinkRepositoryPort
    context_link_suggestions: ContextLinkSuggestionRepositoryPort
    anchors: AnchorRepositoryPort
    episodes: EpisodeRepositoryPort
    documents: DocumentRepositoryPort
    chunks: ChunkRepositoryPort
    captures: CaptureRepositoryPort
    suggestions: SuggestionRepositoryPort
    usage: UsageRepositoryPort
    idempotency: IdempotencyRepositoryPort
    outbox: OutboxPort

    async def __aenter__(self) -> UnitOfWorkPort:
        """Open a transactional boundary."""

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Rollback on errors and release resources."""

    async def commit(self) -> None:
        """Commit canonical changes."""

    async def coordinate_fact_source_refs(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        source_refs: tuple[SourceRef, ...],
    ) -> None:
        """Coordinate canonical document evidence before locking fact aggregates."""

    async def rollback(self) -> None:
        """Rollback canonical changes."""


class UnitOfWorkFactoryPort(Protocol):
    def __call__(self) -> UnitOfWorkPort:
        """Create a fresh unit of work for one use case execution."""


async def coordinate_fact_source_refs(
    uow: UnitOfWorkPort,
    *,
    space_id: str,
    memory_scope_id: str,
    source_refs: tuple[SourceRef, ...],
) -> None:
    """Invoke document coordination when the persistence adapter provides it."""

    coordinator = getattr(uow, "coordinate_fact_source_refs", None)
    if coordinator is not None:
        await coordinator(
            space_id=space_id,
            memory_scope_id=memory_scope_id,
            source_refs=source_refs,
        )
