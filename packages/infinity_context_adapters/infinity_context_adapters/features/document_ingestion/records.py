"""Provider-neutral projection records for document_ingestion adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from infinity_context_core.features.document_ingestion.public import (
    FEATURE_ID,
    DocumentChunk,
    DocumentChunkIndexItem,
    DocumentIngestionScope,
    DocumentIngestionValidationError,
    SourceDocument,
    SourceDocumentOrigin,
)


@dataclass(frozen=True, slots=True)
class DocumentChunkIndexProjection:
    """Feature-owned chunk payload before a provider-specific index write."""

    feature_id: ClassVar[str] = FEATURE_ID

    chunk_id: str
    document_id: str
    scope: DocumentIngestionScope
    origin: SourceDocumentOrigin
    text: str
    content_hash: str
    sequence: int

    @classmethod
    def from_document_chunk(
        cls,
        *,
        document: SourceDocument,
        chunk: DocumentChunk,
    ) -> DocumentChunkIndexProjection:
        if document.identity.document_id != chunk.identity.document_id:
            raise DocumentIngestionValidationError(
                "Document chunk projection requires a chunk from the same document"
            )
        if document.identity.scope != chunk.identity.scope:
            raise DocumentIngestionValidationError(
                "Document chunk projection requires matching document and chunk scopes"
            )
        return cls(
            chunk_id=chunk.identity.chunk_id,
            document_id=chunk.identity.document_id,
            scope=chunk.identity.scope,
            origin=document.origin,
            text=chunk.text,
            content_hash=chunk.content_hash,
            sequence=chunk.sequence,
        )

    def to_index_item(self) -> DocumentChunkIndexItem:
        """Convert to the document_ingestion public index port DTO."""

        return DocumentChunkIndexItem(
            chunk_id=self.chunk_id,
            document_id=self.document_id,
            scope=self.scope,
            origin=self.origin,
            text=self.text,
            content_hash=self.content_hash,
            sequence=self.sequence,
        )


def document_chunk_index_projection_from_chunk(
    *,
    document: SourceDocument,
    chunk: DocumentChunk,
) -> DocumentChunkIndexProjection:
    """Create a provider-neutral chunk projection from canonical document state."""

    return DocumentChunkIndexProjection.from_document_chunk(
        document=document,
        chunk=chunk,
    )


__all__ = (
    "DocumentChunkIndexProjection",
    "document_chunk_index_projection_from_chunk",
)
