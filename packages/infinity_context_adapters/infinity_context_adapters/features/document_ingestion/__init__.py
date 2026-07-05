"""Adapter seams for the document_ingestion feature.

These classes mark feature-owned infrastructure boundaries for canonical
documents, derived chunk indexes, and extraction-to-ingestion handoff. Runtime
construction that can reach provider-capable adapters is kept behind lazy
factories.
"""

from infinity_context_core.features.document_ingestion.public import FEATURE_ID

from infinity_context_adapters.features.document_ingestion.composition import (
    DocumentIngestionExtractionComponents,
    create_document_ingestion_extraction_components,
)
from infinity_context_adapters.features.document_ingestion.extraction_adapter import (
    DocumentExtractionIngestionAdapter,
    ExtractedDocumentText,
    create_document_extraction_ingestion_adapter,
)
from infinity_context_adapters.features.document_ingestion.in_memory_document_store import (
    InMemoryDocumentChunkStore,
    InMemoryDocumentIngestionStore,
    InMemorySourceDocumentStore,
    create_in_memory_document_chunk_store,
    create_in_memory_document_ingestion_store,
    create_in_memory_source_document_store,
)
from infinity_context_adapters.features.document_ingestion.postgres_document_store import (
    PostgresDocumentChunkStore,
    PostgresDocumentIngestionStore,
    PostgresSourceDocumentStore,
    create_postgres_document_chunk_store,
    create_postgres_document_ingestion_store,
    create_postgres_source_document_store,
)
from infinity_context_adapters.features.document_ingestion.qdrant_chunk_index import (
    QdrantDocumentChunkIndex,
    create_qdrant_document_chunk_index,
)
from infinity_context_adapters.features.document_ingestion.records import (
    DocumentChunkIndexProjection,
    document_chunk_index_projection_from_chunk,
)

__all__ = (
    "FEATURE_ID",
    "DocumentChunkIndexProjection",
    "DocumentIngestionExtractionComponents",
    "DocumentExtractionIngestionAdapter",
    "ExtractedDocumentText",
    "InMemoryDocumentChunkStore",
    "InMemoryDocumentIngestionStore",
    "InMemorySourceDocumentStore",
    "PostgresDocumentChunkStore",
    "PostgresDocumentIngestionStore",
    "PostgresSourceDocumentStore",
    "QdrantDocumentChunkIndex",
    "create_document_extraction_ingestion_adapter",
    "create_document_ingestion_extraction_components",
    "create_in_memory_document_chunk_store",
    "create_in_memory_document_ingestion_store",
    "create_in_memory_source_document_store",
    "create_postgres_document_chunk_store",
    "create_postgres_document_ingestion_store",
    "create_postgres_source_document_store",
    "create_qdrant_document_chunk_index",
    "document_chunk_index_projection_from_chunk",
)
