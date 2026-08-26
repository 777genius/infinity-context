"""Derived indexing ports owned by the document_ingestion feature."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from infinity_context_core.features.document_ingestion.domain import (
    DocumentIngestionScope,
    SourceDocumentOrigin,
)


@dataclass(frozen=True, slots=True)
class DocumentChunkIndexItem:
    """Chunk payload for a derived retrieval index."""

    chunk_id: str
    document_id: str
    scope: DocumentIngestionScope
    origin: SourceDocumentOrigin
    text: str
    content_hash: str
    sequence: int


@dataclass(frozen=True, slots=True)
class DocumentIndexingResult:
    """Best-effort derived index write result."""

    accepted_chunk_ids: tuple[str, ...] = ()
    failed_chunk_ids: tuple[str, ...] = ()
    retryable: bool = False


class DocumentChunkIndexPort(Protocol):
    async def upsert_chunks(
        self,
        items: tuple[DocumentChunkIndexItem, ...],
    ) -> DocumentIndexingResult:
        """Upsert chunk payloads into a derived retrieval index."""

    async def delete_chunks_if_version(
        self,
        chunk_ids: tuple[str, ...],
        *,
        canonical_version: int,
    ) -> DocumentIndexingResult:
        """Delete only chunk payloads carrying the exact canonical version."""


__all__ = (
    "DocumentChunkIndexItem",
    "DocumentChunkIndexPort",
    "DocumentIndexingResult",
)
