"""Postgres canonical store seams for document_ingestion.

Postgres owns document and chunk lifecycle. These feature-owned placeholders
implement the document_ingestion repository port shapes without importing
SQLAlchemy or touching legacy layer-first repositories.
"""

from __future__ import annotations

from typing import NoReturn

from infinity_context_core.features.document_ingestion.public import (
    FEATURE_ID,
    DocumentChunk,
    DocumentChunkRepositoryPort,
    DocumentChunkUpsertResult,
    DocumentIngestionScope,
    SourceDocument,
    SourceDocumentRepositoryPort,
)


class PostgresSourceDocumentStore:
    """Placeholder for the future Postgres SourceDocumentRepositoryPort adapter."""

    adapter_name = "postgres"
    feature_id = FEATURE_ID

    async def create(self, _document: SourceDocument) -> SourceDocument:
        _raise_not_implemented("create_source_document")

    async def get(self, _identity: str) -> SourceDocument | None:
        _raise_not_implemented("get_source_document")

    async def find_active_by_content_hash(
        self,
        *,
        scope: DocumentIngestionScope,
        content_hash: str,
    ) -> SourceDocument | None:
        _raise_not_implemented("find_active_by_content_hash")


class PostgresDocumentChunkStore:
    """Placeholder for the future Postgres DocumentChunkRepositoryPort adapter."""

    adapter_name = "postgres"
    feature_id = FEATURE_ID

    async def upsert(self, _chunk: DocumentChunk) -> DocumentChunkUpsertResult:
        _raise_not_implemented("upsert_document_chunk")

    async def list_for_document(
        self,
        _document_id: str,
        *,
        limit: int | None = None,
    ) -> tuple[DocumentChunk, ...]:
        _raise_not_implemented("list_document_chunks")


class PostgresDocumentIngestionStore:
    """Container seam for canonical document and chunk repositories."""

    adapter_name = "postgres"
    feature_id = FEATURE_ID

    def __init__(
        self,
        *,
        source_documents: SourceDocumentRepositoryPort | None = None,
        chunks: DocumentChunkRepositoryPort | None = None,
    ) -> None:
        self.source_documents = source_documents or PostgresSourceDocumentStore()
        self.chunks = chunks or PostgresDocumentChunkStore()


def create_postgres_source_document_store() -> SourceDocumentRepositoryPort:
    """Create the feature-owned Postgres source document store placeholder."""

    return PostgresSourceDocumentStore()


def create_postgres_document_chunk_store() -> DocumentChunkRepositoryPort:
    """Create the feature-owned Postgres document chunk store placeholder."""

    return PostgresDocumentChunkStore()


def create_postgres_document_ingestion_store() -> PostgresDocumentIngestionStore:
    """Create the feature-owned canonical document ingestion store seam."""

    return PostgresDocumentIngestionStore()


def _raise_not_implemented(operation: str) -> NoReturn:
    raise NotImplementedError(
        f"document_ingestion Postgres document store {operation} is a placeholder seam; "
        "real canonical document persistence wiring is deferred."
    )


__all__ = (
    "PostgresDocumentChunkStore",
    "PostgresDocumentIngestionStore",
    "PostgresSourceDocumentStore",
    "create_postgres_document_chunk_store",
    "create_postgres_document_ingestion_store",
    "create_postgres_source_document_store",
)
