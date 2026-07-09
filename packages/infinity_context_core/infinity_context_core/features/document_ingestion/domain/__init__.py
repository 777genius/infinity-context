"""Domain model owned by the document_ingestion feature."""

from infinity_context_core.features.document_ingestion.domain.chunking import (
    CHUNKING_POLICY_VERSION,
    ChunkingPolicy,
    DocumentChunk,
    DocumentChunkDraft,
    DocumentChunkIdentity,
    DocumentChunkKind,
    DocumentChunkStatus,
    DocumentTextRange,
    estimate_token_count,
)
from infinity_context_core.features.document_ingestion.domain.errors import (
    DocumentIngestionError,
    DocumentIngestionInvariantError,
    DocumentIngestionValidationError,
)
from infinity_context_core.features.document_ingestion.domain.feature import (
    FEATURE_ID,
    DocumentIngestionFeature,
)
from infinity_context_core.features.document_ingestion.domain.source_document import (
    DocumentIngestionScope,
    SourceDocument,
    SourceDocumentClassification,
    SourceDocumentContent,
    SourceDocumentDraft,
    SourceDocumentIdentity,
    SourceDocumentOrigin,
    SourceDocumentStatus,
    content_hash_for_text,
    normalize_document_text,
)

__all__ = (
    "CHUNKING_POLICY_VERSION",
    "ChunkingPolicy",
    "DocumentChunk",
    "DocumentChunkDraft",
    "DocumentChunkIdentity",
    "DocumentChunkKind",
    "DocumentChunkStatus",
    "DocumentIngestionError",
    "DocumentIngestionFeature",
    "DocumentIngestionInvariantError",
    "DocumentIngestionScope",
    "DocumentIngestionValidationError",
    "DocumentTextRange",
    "FEATURE_ID",
    "SourceDocument",
    "SourceDocumentClassification",
    "SourceDocumentContent",
    "SourceDocumentDraft",
    "SourceDocumentIdentity",
    "SourceDocumentOrigin",
    "SourceDocumentStatus",
    "content_hash_for_text",
    "estimate_token_count",
    "normalize_document_text",
)
