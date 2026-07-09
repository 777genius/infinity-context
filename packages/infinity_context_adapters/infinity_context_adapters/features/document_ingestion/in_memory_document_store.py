"""In-memory document store seam for document_ingestion adapters.

This module provides stdlib-only implementations of the document_ingestion
repository ports so adapter composition can inject persistence/query behavior
without pulling in Postgres, SQLAlchemy, Qdrant, or provider runtimes.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar

from infinity_context_core.features.document_ingestion.public import (
    FEATURE_ID,
    DocumentChunk,
    DocumentChunkRepositoryPort,
    DocumentChunkUpsertResult,
    DocumentIngestionScope,
    SourceDocument,
    SourceDocumentRepositoryPort,
)


class InMemorySourceDocumentStore:
    """Deterministic in-memory implementation of SourceDocumentRepositoryPort."""

    adapter_name: ClassVar[str] = "in_memory"
    feature_id: ClassVar[str] = FEATURE_ID

    def __init__(self, documents: Iterable[SourceDocument] = ()) -> None:
        self._documents_by_id: dict[str, SourceDocument] = {}
        for document in documents:
            self._documents_by_id[document.identity.document_id] = document

    async def create(self, document: SourceDocument) -> SourceDocument:
        self._documents_by_id[document.identity.document_id] = document
        return document

    async def get(self, identity: str) -> SourceDocument | None:
        return self._documents_by_id.get(identity)

    async def find_active_by_content_hash(
        self,
        *,
        scope: DocumentIngestionScope,
        content_hash: str,
    ) -> SourceDocument | None:
        for document in self._documents_by_id.values():
            if document.status != "active":
                continue
            if document.identity.scope != scope:
                continue
            if document.content_hash == content_hash:
                return document
        return None


class InMemoryDocumentChunkStore:
    """Deterministic in-memory implementation of DocumentChunkRepositoryPort."""

    adapter_name: ClassVar[str] = "in_memory"
    feature_id: ClassVar[str] = FEATURE_ID

    def __init__(self, chunks: Iterable[DocumentChunk] = ()) -> None:
        self._chunks_by_id: dict[str, DocumentChunk] = {}
        for chunk in chunks:
            self._chunks_by_id[chunk.identity.chunk_id] = chunk

    async def upsert(self, chunk: DocumentChunk) -> DocumentChunkUpsertResult:
        existing = self._find_duplicate(chunk)
        if existing is not None:
            return DocumentChunkUpsertResult(chunk=existing, duplicate=True)

        self._chunks_by_id[chunk.identity.chunk_id] = chunk
        return DocumentChunkUpsertResult(chunk=chunk)

    async def list_for_document(
        self,
        document_id: str,
        *,
        limit: int | None = None,
    ) -> tuple[DocumentChunk, ...]:
        chunks = tuple(
            sorted(
                (
                    chunk
                    for chunk in self._chunks_by_id.values()
                    if chunk.identity.document_id == document_id
                    and chunk.status == "active"
                ),
                key=lambda chunk: (chunk.sequence, chunk.identity.chunk_id),
            )
        )
        if limit is None:
            return chunks
        if limit <= 0:
            return ()
        return chunks[:limit]

    def _find_duplicate(self, chunk: DocumentChunk) -> DocumentChunk | None:
        existing = self._chunks_by_id.get(chunk.identity.chunk_id)
        if existing is not None:
            return existing
        for stored_chunk in self._chunks_by_id.values():
            if stored_chunk.source_hash == chunk.source_hash:
                return stored_chunk
        return None


class InMemoryDocumentIngestionStore:
    """Container seam for injectable in-memory document/chunk repositories."""

    adapter_name: ClassVar[str] = "in_memory"
    feature_id: ClassVar[str] = FEATURE_ID

    def __init__(
        self,
        *,
        source_documents: SourceDocumentRepositoryPort | None = None,
        chunks: DocumentChunkRepositoryPort | None = None,
        documents: Iterable[SourceDocument] = (),
        document_chunks: Iterable[DocumentChunk] = (),
    ) -> None:
        self.source_documents = (
            source_documents
            if source_documents is not None
            else InMemorySourceDocumentStore(documents=documents)
        )
        self.chunks = (
            chunks
            if chunks is not None
            else InMemoryDocumentChunkStore(chunks=document_chunks)
        )


def create_in_memory_source_document_store(
    documents: Iterable[SourceDocument] = (),
) -> SourceDocumentRepositoryPort:
    """Create an injectable in-memory source document repository."""

    return InMemorySourceDocumentStore(documents=documents)


def create_in_memory_document_chunk_store(
    chunks: Iterable[DocumentChunk] = (),
) -> DocumentChunkRepositoryPort:
    """Create an injectable in-memory document chunk repository."""

    return InMemoryDocumentChunkStore(chunks=chunks)


def create_in_memory_document_ingestion_store(
    *,
    source_documents: SourceDocumentRepositoryPort | None = None,
    chunks: DocumentChunkRepositoryPort | None = None,
    documents: Iterable[SourceDocument] = (),
    document_chunks: Iterable[DocumentChunk] = (),
) -> InMemoryDocumentIngestionStore:
    """Create an injectable in-memory document ingestion store seam."""

    return InMemoryDocumentIngestionStore(
        source_documents=source_documents,
        chunks=chunks,
        documents=documents,
        document_chunks=document_chunks,
    )


__all__ = (
    "InMemoryDocumentChunkStore",
    "InMemoryDocumentIngestionStore",
    "InMemorySourceDocumentStore",
    "create_in_memory_document_chunk_store",
    "create_in_memory_document_ingestion_store",
    "create_in_memory_source_document_store",
)
