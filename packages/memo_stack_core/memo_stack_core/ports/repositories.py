"""Repository ports for future canonical persistence adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from memo_stack_core.domain.entities import (
    MemoryChunk,
    MemoryDocument,
    MemoryEpisode,
    MemoryFact,
    MemoryProfile,
    MemorySpace,
    MemorySuggestion,
)
from memo_stack_core.domain.idempotency import IdempotencyRecord


@dataclass(frozen=True)
class ResolvedScope:
    space_id: str
    profile_id: str
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

    async def create_profile(self, profile: MemoryProfile) -> MemoryProfile:
        """Persist or return an existing active profile by external ref within a space."""

    async def list_profiles(self, *, space_id: str, limit: int) -> list[MemoryProfile]:
        """List active profiles in a space."""

    async def ensure_scope(
        self,
        *,
        space_slug: str,
        profile_external_ref: str,
        thread_external_ref: str | None,
        now: datetime,
    ) -> ResolvedScope:
        """Resolve or create a space/profile/thread scope."""

    async def delete_thread_memory(
        self,
        *,
        space_id: str,
        profile_id: str,
        thread_id: str,
    ) -> SessionDeleteResult:
        """Soft-delete all canonical memory attached to a thread."""

    async def thread_status(
        self,
        *,
        space_id: str,
        profile_id: str,
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
        profile_ids: tuple[str, ...],
        thread_id: str | None,
        query: str,
        limit: int,
    ) -> list[MemoryFact]:
        """Find active facts for prompt context."""

    async def list_for_scope(
        self,
        *,
        space_id: str,
        profile_id: str,
        thread_id: str | None,
        status: str | None,
        limit: int,
        cursor_updated_at: datetime | None = None,
        cursor_id: str | None = None,
    ) -> list[MemoryFact]:
        """List facts for a single scope."""

    async def delete_facts_sourced_only_by_chunks(
        self,
        *,
        space_id: str,
        profile_id: str,
        document_id: str,
        chunk_ids: tuple[str, ...],
        now: datetime,
    ) -> tuple[tuple[str, int], ...]:
        """Delete active facts whose current evidence only points to a deleted document."""


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
        profile_id: str,
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
        profile_ids: tuple[str, ...],
        thread_id: str | None,
    ) -> list[MemoryChunk]:
        """Load visible active chunks after derived-index candidate retrieval."""

    async def keyword_search(
        self,
        *,
        space_id: str,
        profile_ids: tuple[str, ...],
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
        profile_id: str,
        status: str | None,
        limit: int,
    ) -> list[MemorySuggestion]:
        """List safe suggestion rows for review."""

    async def find_pending_duplicate(
        self,
        *,
        space_id: str,
        profile_id: str,
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
        profile_id: str,
        status: str | None,
    ) -> int:
        """Count suggestions for review queue ingress limits."""


class IdempotencyRepositoryPort(Protocol):
    async def find(self, *, space_id: str, key: str) -> IdempotencyRecord | None:
        """Find an idempotency record by scoped key."""

    async def save(self, record: IdempotencyRecord) -> None:
        """Persist an idempotency record."""
