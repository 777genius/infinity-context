"""Application command/result contracts for document ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from infinity_context_core.features.document_ingestion.domain import (
    ChunkingPolicy,
    DocumentChunk,
    DocumentChunkDraft,
    DocumentIngestionScope,
    SourceDocument,
    SourceDocumentClassification,
    SourceDocumentDraft,
    SourceDocumentOrigin,
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
