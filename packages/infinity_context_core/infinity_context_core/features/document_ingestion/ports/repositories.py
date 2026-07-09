"""Repository ports owned by the document_ingestion feature."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from infinity_context_core.features.document_ingestion.domain import (
    DocumentChunk,
    DocumentIngestionScope,
    SourceDocument,
)


@dataclass(frozen=True, slots=True)
class DocumentChunkUpsertResult:
    """Result of writing one canonical chunk."""

    chunk: DocumentChunk
    duplicate: bool = False


class SourceDocumentRepositoryPort(Protocol):
    async def create(self, document: SourceDocument) -> SourceDocument:
        """Persist a new canonical source document."""

    async def get(self, identity: str) -> SourceDocument | None:
        """Load a canonical source document by document id."""

    async def find_active_by_content_hash(
        self,
        *,
        scope: DocumentIngestionScope,
        content_hash: str,
    ) -> SourceDocument | None:
        """Find an active document with the same canonical content hash."""


class DocumentChunkRepositoryPort(Protocol):
    async def upsert(self, chunk: DocumentChunk) -> DocumentChunkUpsertResult:
        """Persist a canonical chunk, reporting duplicate source hashes."""

    async def list_for_document(
        self,
        document_id: str,
        *,
        limit: int | None = None,
    ) -> tuple[DocumentChunk, ...]:
        """List active chunks for a canonical source document."""


__all__ = (
    "DocumentChunkRepositoryPort",
    "DocumentChunkUpsertResult",
    "SourceDocumentRepositoryPort",
)
