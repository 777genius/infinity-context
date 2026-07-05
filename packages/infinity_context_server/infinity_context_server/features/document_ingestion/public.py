"""Public server seam for the document_ingestion feature mirror."""

from __future__ import annotations

import infinity_context_core.features.document_ingestion.public as document_ingestion

from infinity_context_server.features.document_ingestion.asset_responses import (
    asset_extraction_error_to_response,
    asset_extraction_to_response,
    asset_to_response,
    deduplication_to_response,
    extraction_artifact_to_response,
)
from infinity_context_server.features.document_ingestion.composition import (
    DocumentIngestionServerFeature,
    build_document_ingestion_server_feature,
)
from infinity_context_server.features.document_ingestion.contracts import (
    IngestDocumentHttpRequest,
    LegacyDocumentSourceRefRequest,
    LegacyIngestDocumentRequest,
)
from infinity_context_server.features.document_ingestion.mappers import (
    chunk_to_response,
    document_to_response,
    ingest_document_command_from_contract,
    ingest_document_result_to_contract,
    legacy_ingest_document_command_from_request,
)
from infinity_context_server.features.document_ingestion.routes import (
    create_document_ingestion_router,
)

FEATURE_ID = document_ingestion.FEATURE_ID

__all__ = (
    "DocumentIngestionServerFeature",
    "FEATURE_ID",
    "IngestDocumentHttpRequest",
    "LegacyDocumentSourceRefRequest",
    "LegacyIngestDocumentRequest",
    "asset_extraction_error_to_response",
    "asset_extraction_to_response",
    "asset_to_response",
    "build_document_ingestion_server_feature",
    "chunk_to_response",
    "create_document_ingestion_router",
    "deduplication_to_response",
    "document_to_response",
    "extraction_artifact_to_response",
    "ingest_document_command_from_contract",
    "ingest_document_result_to_contract",
    "legacy_ingest_document_command_from_request",
)
