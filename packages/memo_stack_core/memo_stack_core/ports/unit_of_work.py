"""Unit of work port."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol

from memo_stack_core.domain.events import OutboxEvent
from memo_stack_core.ports.assets import (
    AssetRepositoryPort,
    ContextLinkRepositoryPort,
    ContextLinkSuggestionRepositoryPort,
)
from memo_stack_core.ports.captures import CaptureRepositoryPort
from memo_stack_core.ports.extraction import AssetExtractionRepositoryPort
from memo_stack_core.ports.repositories import (
    AnchorRepositoryPort,
    ChunkRepositoryPort,
    DocumentRepositoryPort,
    EpisodeRepositoryPort,
    FactRelationRepositoryPort,
    FactRepositoryPort,
    IdempotencyRepositoryPort,
    ScopeRepositoryPort,
    SuggestionRepositoryPort,
)
from memo_stack_core.ports.usage import UsageRepositoryPort


class OutboxPort(Protocol):
    async def enqueue(self, event: OutboxEvent) -> None:
        """Persist an outbox event in the current transaction."""


class UnitOfWorkPort(Protocol):
    scope: ScopeRepositoryPort
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

    async def rollback(self) -> None:
        """Rollback canonical changes."""


class UnitOfWorkFactoryPort(Protocol):
    def __call__(self) -> UnitOfWorkPort:
        """Create a fresh unit of work for one use case execution."""
