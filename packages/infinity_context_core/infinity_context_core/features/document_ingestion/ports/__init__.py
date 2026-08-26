"""Ports owned by the document_ingestion feature."""

from infinity_context_core.features.document_ingestion.ports.indexing import (
    DocumentChunkIndexItem,
    DocumentChunkIndexPort,
    DocumentIndexingResult,
)
from infinity_context_core.features.document_ingestion.ports.projection_ownership import (
    DocumentProjectionOwnershipClaimV1,
    DocumentProjectionOwnershipDecisionV1,
    DocumentRetrievalProjectionOwnershipPortV1,
)
from infinity_context_core.features.document_ingestion.ports.repositories import (
    DocumentChunkRepositoryPort,
    DocumentChunkUpsertResult,
    SourceDocumentRepositoryPort,
)

__all__ = (
    "DocumentChunkIndexItem",
    "DocumentChunkIndexPort",
    "DocumentChunkRepositoryPort",
    "DocumentChunkUpsertResult",
    "DocumentIndexingResult",
    "DocumentProjectionOwnershipClaimV1",
    "DocumentProjectionOwnershipDecisionV1",
    "DocumentRetrievalProjectionOwnershipPortV1",
    "SourceDocumentRepositoryPort",
)
