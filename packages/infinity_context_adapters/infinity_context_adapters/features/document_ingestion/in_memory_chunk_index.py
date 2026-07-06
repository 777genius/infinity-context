"""In-memory derived chunk index seam for document_ingestion adapters."""

from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar

from infinity_context_core.features.document_ingestion.public import (
    FEATURE_ID,
    DocumentChunkIndexItem,
    DocumentChunkIndexPort,
    DocumentIndexingResult,
)


class InMemoryDocumentChunkIndex(DocumentChunkIndexPort):
    """Stdlib-only implementation of DocumentChunkIndexPort for tests and local wiring."""

    adapter_name: ClassVar[str] = "in_memory"
    feature_id: ClassVar[str] = FEATURE_ID

    def __init__(self, items: Iterable[DocumentChunkIndexItem] = ()) -> None:
        self._items_by_chunk_id: dict[str, DocumentChunkIndexItem] = {}
        for item in items:
            self._items_by_chunk_id[item.chunk_id] = item

    async def upsert_chunks(
        self,
        items: tuple[DocumentChunkIndexItem, ...],
    ) -> DocumentIndexingResult:
        accepted_chunk_ids: list[str] = []
        for item in items:
            self._items_by_chunk_id[item.chunk_id] = item
            accepted_chunk_ids.append(item.chunk_id)
        return DocumentIndexingResult(accepted_chunk_ids=tuple(accepted_chunk_ids))

    async def delete_chunks(self, chunk_ids: tuple[str, ...]) -> DocumentIndexingResult:
        for chunk_id in chunk_ids:
            self._items_by_chunk_id.pop(chunk_id, None)
        return DocumentIndexingResult(accepted_chunk_ids=chunk_ids)

    def get(self, chunk_id: str) -> DocumentChunkIndexItem | None:
        """Return the latest indexed item for a chunk id."""

        return self._items_by_chunk_id.get(chunk_id)

    def list_items(self) -> tuple[DocumentChunkIndexItem, ...]:
        """Return indexed items in deterministic chunk-id order."""

        return tuple(
            self._items_by_chunk_id[chunk_id]
            for chunk_id in sorted(self._items_by_chunk_id)
        )


def create_in_memory_document_chunk_index(
    items: Iterable[DocumentChunkIndexItem] = (),
) -> InMemoryDocumentChunkIndex:
    """Create an injectable in-memory document chunk index seam."""

    return InMemoryDocumentChunkIndex(items=items)


__all__ = (
    "InMemoryDocumentChunkIndex",
    "create_in_memory_document_chunk_index",
)
