"""Qdrant derived chunk index seam for document_ingestion.

Qdrant is a derived retrieval index for canonical document chunks. This module
establishes the feature-owned adapter boundary without importing qdrant_client
or writing vectors.
"""

from __future__ import annotations

from typing import NoReturn

from infinity_context_core.features.document_ingestion.public import (
    FEATURE_ID,
    DocumentChunkIndexItem,
    DocumentChunkIndexPort,
    DocumentIndexingResult,
)


class QdrantDocumentChunkIndex:
    """Placeholder for the future feature-owned Qdrant chunk index."""

    adapter_name = "qdrant"
    feature_id = FEATURE_ID

    async def upsert_chunks(
        self,
        _items: tuple[DocumentChunkIndexItem, ...],
    ) -> DocumentIndexingResult:
        _raise_not_implemented("upsert_chunks")

    async def delete_chunks(self, _chunk_ids: tuple[str, ...]) -> DocumentIndexingResult:
        _raise_not_implemented("delete_chunks")


def create_qdrant_document_chunk_index() -> DocumentChunkIndexPort:
    """Create the feature-owned Qdrant chunk index placeholder."""

    return QdrantDocumentChunkIndex()


def _raise_not_implemented(operation: str) -> NoReturn:
    raise NotImplementedError(
        f"document_ingestion Qdrant chunk index {operation} is a placeholder seam; "
        "real derived chunk index wiring is deferred."
    )


__all__ = ("QdrantDocumentChunkIndex", "create_qdrant_document_chunk_index")
