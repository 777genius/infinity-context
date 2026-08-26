"""Domain errors owned by the document_ingestion feature."""

from __future__ import annotations


class DocumentIngestionError(Exception):
    """Base error for document ingestion domain/application failures."""


class DocumentIngestionValidationError(DocumentIngestionError, ValueError):
    """Raised when a document ingestion value object is invalid."""


class DocumentIngestionInvariantError(DocumentIngestionError):
    """Raised when document ingestion invariants are violated."""


class DocumentProjectionInvalidError(DocumentIngestionValidationError):
    """Projected ingest descriptor or canonical single-chunk shape is invalid."""

    code = "memory.document_projection_invalid"


class DocumentProjectionConflictError(DocumentIngestionError):
    """Base typed conflict returned by a projection ownership consumer."""

    code = "memory.document_projection_invalid"


class DocumentProjectionLocatorConflictError(DocumentProjectionConflictError):
    code = "memory.document_projection_locator_conflict"


class DocumentProjectionOrdinalConflictError(DocumentProjectionConflictError):
    code = "memory.document_projection_ordinal_conflict"


class DocumentProjectionIdempotencyConflictError(DocumentProjectionConflictError):
    code = "memory.document_projection_idempotency_conflict"


__all__ = (
    "DocumentIngestionError",
    "DocumentIngestionInvariantError",
    "DocumentIngestionValidationError",
    "DocumentProjectionConflictError",
    "DocumentProjectionIdempotencyConflictError",
    "DocumentProjectionInvalidError",
    "DocumentProjectionLocatorConflictError",
    "DocumentProjectionOrdinalConflictError",
)
