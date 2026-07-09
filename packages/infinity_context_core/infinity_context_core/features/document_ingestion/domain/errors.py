"""Domain errors owned by the document_ingestion feature."""

from __future__ import annotations


class DocumentIngestionError(Exception):
    """Base error for document ingestion domain/application failures."""


class DocumentIngestionValidationError(DocumentIngestionError, ValueError):
    """Raised when a document ingestion value object is invalid."""


class DocumentIngestionInvariantError(DocumentIngestionError):
    """Raised when document ingestion invariants are violated."""


__all__ = (
    "DocumentIngestionError",
    "DocumentIngestionInvariantError",
    "DocumentIngestionValidationError",
)
