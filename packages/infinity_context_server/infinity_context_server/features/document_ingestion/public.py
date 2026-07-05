"""Public server seam for the document_ingestion feature mirror."""

from __future__ import annotations

import infinity_context_core.features.document_ingestion.public as document_ingestion

from infinity_context_server.features.document_ingestion.composition import (
    DocumentIngestionServerFeature,
    build_document_ingestion_server_feature,
)
from infinity_context_server.features.document_ingestion.contracts import (
    IngestDocumentHttpRequest,
)
from infinity_context_server.features.document_ingestion.mappers import (
    chunk_to_response,
    document_to_response,
    ingest_document_command_from_contract,
    ingest_document_result_to_contract,
)
from infinity_context_server.features.document_ingestion.routes import (
    create_document_ingestion_router,
)

FEATURE_ID = document_ingestion.FEATURE_ID

__all__ = (
    "DocumentIngestionServerFeature",
    "FEATURE_ID",
    "IngestDocumentHttpRequest",
    "build_document_ingestion_server_feature",
    "chunk_to_response",
    "create_document_ingestion_router",
    "document_to_response",
    "ingest_document_command_from_contract",
    "ingest_document_result_to_contract",
)
