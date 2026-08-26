"""Application command/result contracts for document ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from infinity_context_core.features.document_ingestion.domain import (
    ChunkingPolicy,
    DocumentChunk,
    DocumentChunkDraft,
    DocumentIngestionScope,
    DocumentRetrievalProjectionV1,
    SourceDocument,
    SourceDocumentClassification,
    SourceDocumentDraft,
    SourceDocumentOrigin,
)
from infinity_context_core.features.document_ingestion.domain.retrieval_projection import (
    copy_document_retrieval_projection,
)

DocumentIndexingStatus: TypeAlias = str


@dataclass(frozen=True, slots=True)
class IngestDocumentCommand:
    """Request to ingest one source document into canonical document memory."""

    scope: DocumentIngestionScope
    title: str
    origin: SourceDocumentOrigin
    text: str
    classification: SourceDocumentClassification = "unknown"
    chunking_policy: ChunkingPolicy | None = None
    idempotency_key: str | None = None
    retrieval_projection: DocumentRetrievalProjectionV1 | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scope, DocumentIngestionScope):
            raise ValueError("ingest scope has an invalid type")
        if not isinstance(self.origin, SourceDocumentOrigin):
            raise ValueError("ingest origin has an invalid type")
        object.__setattr__(
            self,
            "scope",
            DocumentIngestionScope(
                self.scope.space_id, self.scope.memory_scope_id, self.scope.thread_id
            ),
        )
        object.__setattr__(
            self,
            "origin",
            SourceDocumentOrigin(
                self.origin.source_type, self.origin.source_external_id, self.origin.uri
            ),
        )
        if self.retrieval_projection is not None:
            object.__setattr__(
                self,
                "retrieval_projection",
                copy_document_retrieval_projection(self.retrieval_projection),
            )


@dataclass(frozen=True, slots=True)
class PreparedDocumentIngestion:
    """Validated source document and chunk drafts before persistence."""

    document: SourceDocumentDraft
    chunks: tuple[DocumentChunkDraft, ...]
    chunking_policy_version: str
    idempotency_key: str | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IngestDocumentResult:
    """Result returned after a document reaches the ingestion boundary."""

    document: SourceDocument
    chunks: tuple[DocumentChunk, ...]
    duplicate_chunk_count: int = 0
    indexing_status: DocumentIndexingStatus = "pending"
    warnings: tuple[str, ...] = ()


__all__ = (
    "DocumentIndexingStatus",
    "IngestDocumentCommand",
    "IngestDocumentResult",
    "PreparedDocumentIngestion",
)
