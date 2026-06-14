"""Repository ports for future canonical persistence adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from memo_stack_core.domain.entities import (
    MemoryAnchor,
    MemoryChunk,
    MemoryDocument,
    MemoryEpisode,
    MemoryFact,
    MemoryFactRelation,
    MemoryScope,
    MemorySpace,
    MemorySuggestion,
    MemoryThread,
)
from memo_stack_core.domain.idempotency import IdempotencyRecord


@dataclass(frozen=True)
class ResolvedScope:
    space_id: str
    memory_scope_id: str
    thread_id: str | None = None


@dataclass(frozen=True)
class UpsertChunkResult:
    chunk_id: str
    duplicate: bool


@dataclass(frozen=True)
class SessionDeleteResult:
    deleted_chunks: int
    deleted_facts: int
    deleted_jobs: int
    deleted_chunk_ids: tuple[str, ...] = ()
    deleted_fact_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SessionStatus:
    chunks: int
    facts: int
    jobs: int
    pending_jobs: int


class ScopeRepositoryPort(Protocol):
    async def create_space(self, space: MemorySpace) -> MemorySpace:
        """Persist or return an existing active space by slug."""

    async def list_spaces(self, *, limit: int) -> list[MemorySpace]:
        """List active spaces."""

    async def create_memory_scope(self, memory_scope: MemoryScope) -> MemoryScope:
        """Persist or return an existing active memory_scope by external ref within a space."""

    async def list_memory_scopes(self, *, space_id: str, limit: int) -> list[MemoryScope]:
        """List active memory_scopes in a space."""

    async def get_memory_scope(self, memory_scope_id: str) -> MemoryScope | None:
        """Load a memory_scope by canonical id."""

    async def get_thread(self, thread_id: str) -> MemoryThread | None:
        """Load a thread by canonical id."""

    async def list_threads(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        status: str | None,
        limit: int,
    ) -> list[MemoryThread]:
        """List threads in a memory_scope."""

    async def save_memory_scope(self, memory_scope: MemoryScope) -> MemoryScope:
        """Persist a changed memory_scope aggregate."""

    async def ensure_scope(
        self,
        *,
        space_slug: str,
        memory_scope_external_ref: str,
        thread_external_ref: str | None,
        now: datetime,
    ) -> ResolvedScope:
        """Resolve or create a space/memory_scope/thread scope."""

    async def delete_thread_memory(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str,
    ) -> SessionDeleteResult:
        """Soft-delete all canonical memory attached to a thread."""

    async def thread_status(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str,
    ) -> SessionStatus:
        """Return safe thread memory counts."""


class FactRepositoryPort(Protocol):
    async def create(self, fact: MemoryFact) -> MemoryFact:
        """Persist a new fact aggregate."""

    async def get_by_id(self, fact_id: str) -> MemoryFact | None:
        """Load a fact by canonical id."""

    async def get_for_update(self, fact_id: str) -> MemoryFact | None:
        """Load a fact with write lock when supported by the adapter."""

    async def save(self, fact: MemoryFact) -> MemoryFact:
        """Persist a changed fact aggregate."""

    async def list_versions(self, fact_id: str) -> list[MemoryFact]:
        """Return fact version history."""

    async def find_active(
        self,
        *,
        space_id: str,
        memory_scope_ids: tuple[str, ...],
        thread_id: str | None,
        query: str,
        limit: int,
        category: str | None = None,
        tags_any: tuple[str, ...] = (),
        tags_all: tuple[str, ...] = (),
        tags_none: tuple[str, ...] = (),
    ) -> list[MemoryFact]:
        """Find active facts for prompt context."""

    async def list_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
        status: str | None,
        limit: int,
        cursor_updated_at: datetime | None = None,
        cursor_id: str | None = None,
        category: str | None = None,
        tag: str | None = None,
    ) -> list[MemoryFact]:
        """List facts for a single scope."""

    async def delete_facts_sourced_only_by_chunks(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        document_id: str,
        chunk_ids: tuple[str, ...],
        now: datetime,
    ) -> tuple[tuple[str, int], ...]:
        """Delete active facts whose current evidence only points to a deleted document."""


class AnchorRepositoryPort(Protocol):
    async def create(self, anchor: MemoryAnchor) -> MemoryAnchor:
        """Persist a semantic anchor."""

    async def get_by_id(self, anchor_id: str) -> MemoryAnchor | None:
        """Load a semantic anchor by canonical id."""

    async def find_active_by_key(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        kind: str,
        normalized_key: str,
    ) -> MemoryAnchor | None:
        """Find an active anchor by scoped normalized key."""

    async def list_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        kind: str | None,
        status: str | None,
        limit: int,
    ) -> list[MemoryAnchor]:
        """List semantic anchors in a memory_scope."""

    async def save(self, anchor: MemoryAnchor) -> MemoryAnchor:
        """Persist changed anchor details."""


class FactRelationRepositoryPort(Protocol):
    async def create(self, relation: MemoryFactRelation) -> MemoryFactRelation:
        """Persist a typed fact relation."""

    async def get_by_id(self, relation_id: str) -> MemoryFactRelation | None:
        """Load one fact relation."""

    async def save(self, relation: MemoryFactRelation) -> MemoryFactRelation:
        """Persist a changed fact relation."""

    async def find_active(
        self,
        *,
        source_fact_id: str,
        target_fact_id: str,
        relation_type: str,
    ) -> MemoryFactRelation | None:
        """Find an active relation for idempotent link creation."""

    async def list_for_fact(
        self,
        *,
        fact_id: str,
        status: str | None,
        limit: int,
    ) -> list[MemoryFactRelation]:
        """List incoming and outgoing relations for a fact."""


class EpisodeRepositoryPort(Protocol):
    async def create(self, episode: MemoryEpisode) -> MemoryEpisode:
        """Persist a canonical transcript/interview episode."""


class DocumentRepositoryPort(Protocol):
    async def create(self, document: MemoryDocument) -> MemoryDocument:
        """Persist a canonical document."""

    async def get_by_id(self, document_id: str) -> MemoryDocument | None:
        """Load a canonical document."""

    async def find_active_by_content_hash(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
        content_hash: str,
    ) -> MemoryDocument | None:
        """Find an active document by scoped content hash and thread visibility."""

    async def list_chunks(
        self,
        document_id: str,
        *,
        limit: int | None = None,
        cursor_sequence: int | None = None,
        cursor_id: str | None = None,
    ) -> list[MemoryChunk]:
        """List active chunks for a document."""

    async def list_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        thread_id: str | None,
        status: str | None,
        limit: int,
    ) -> list[MemoryDocument]:
        """List documents for a single scope."""

    async def soft_delete_with_chunks(
        self,
        *,
        document_id: str,
        now: datetime,
    ) -> tuple[MemoryDocument, tuple[str, ...]] | None:
        """Soft-delete a document and its active chunks, returning deleted chunk ids."""


class ChunkRepositoryPort(Protocol):
    async def get_by_id(self, chunk_id: str) -> MemoryChunk | None:
        """Load a chunk by canonical id."""

    async def upsert(self, chunk: MemoryChunk) -> UpsertChunkResult:
        """Persist a chunk, returning duplicate=true on same source hash."""

    async def hydrate_visible_chunks(
        self,
        *,
        chunk_ids: tuple[str, ...],
        space_id: str,
        memory_scope_ids: tuple[str, ...],
        thread_id: str | None,
    ) -> list[MemoryChunk]:
        """Load visible active chunks after derived-index candidate retrieval."""

    async def keyword_search(
        self,
        *,
        space_id: str,
        memory_scope_ids: tuple[str, ...],
        thread_id: str | None,
        query: str,
        limit: int,
    ) -> list[MemoryChunk]:
        """Fallback canonical keyword search when vector retrieval is disabled."""


class SuggestionRepositoryPort(Protocol):
    async def create(self, suggestion: MemorySuggestion) -> MemorySuggestion:
        """Persist a suggestion candidate."""

    async def get_by_id(self, suggestion_id: str) -> MemorySuggestion | None:
        """Load a suggestion by id."""

    async def get_for_update(self, suggestion_id: str) -> MemorySuggestion | None:
        """Load a suggestion with write lock when supported."""

    async def save(self, suggestion: MemorySuggestion) -> MemorySuggestion:
        """Persist suggestion lifecycle change."""

    async def list_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        status: str | None,
        operation: str | None,
        category: str | None,
        tag: str | None,
        limit: int,
    ) -> list[MemorySuggestion]:
        """List safe suggestion rows for review."""

    async def find_pending_duplicate(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        candidate_fingerprint: str,
        operation: str,
        target_fact_id: str | None,
    ) -> MemorySuggestion | None:
        """Find an equivalent pending suggestion created by auto-memory."""

    async def list_expired_pending(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> list[MemorySuggestion]:
        """List pending suggestions whose expiry timestamp has passed."""

    async def list_pending_for_capture(
        self,
        *,
        capture_id: str,
        limit: int,
    ) -> list[MemorySuggestion]:
        """List pending suggestions derived from a capture."""

    async def count_for_scope(
        self,
        *,
        space_id: str,
        memory_scope_id: str,
        status: str | None,
    ) -> int:
        """Count suggestions for review queue ingress limits."""


class IdempotencyRepositoryPort(Protocol):
    async def find(self, *, space_id: str, key: str) -> IdempotencyRecord | None:
        """Find an idempotency record by scoped key."""

    async def save(self, record: IdempotencyRecord) -> None:
        """Persist an idempotency record."""
