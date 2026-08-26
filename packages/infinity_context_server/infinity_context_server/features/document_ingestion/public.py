"""Public server seam for the document_ingestion feature mirror."""

from __future__ import annotations

import infinity_context_core.features.document_ingestion.public as document_ingestion

from infinity_context_server.features.document_ingestion.asset_requests import (
    read_limited_asset_upload_body,
)
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
    ReconcileExactDocumentHttpRequest,
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

# Keep legacy HTTP exception handling behind the server-owned feature seam. These
# aliases intentionally preserve the core exception identities so existing
# projected-ingestion adapters and handlers remain compatible.
DocumentProjectionIdempotencyConflictError = (
    document_ingestion.DocumentProjectionIdempotencyConflictError
)
DocumentProjectionLocatorConflictError = document_ingestion.DocumentProjectionLocatorConflictError
DocumentProjectionOrdinalConflictError = document_ingestion.DocumentProjectionOrdinalConflictError
DocumentIngestionScope = document_ingestion.DocumentIngestionScope
ExactDocumentIdentity = document_ingestion.ExactDocumentIdentity
ExactDocumentReconciliation = document_ingestion.ExactDocumentReconciliation
ReconcileExactDocumentQuery = document_ingestion.ReconcileExactDocumentQuery
SourceDocumentOrigin = document_ingestion.SourceDocumentOrigin

__all__ = (
    "DocumentIngestionServerFeature",
    "DocumentProjectionIdempotencyConflictError",
    "DocumentProjectionLocatorConflictError",
    "DocumentProjectionOrdinalConflictError",
    "DocumentIngestionScope",
    "ExactDocumentIdentity",
    "ExactDocumentReconciliation",
    "FEATURE_ID",
    "IngestDocumentHttpRequest",
    "LegacyDocumentSourceRefRequest",
    "LegacyIngestDocumentRequest",
    "ReconcileExactDocumentHttpRequest",
    "ReconcileExactDocumentQuery",
    "SourceDocumentOrigin",
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
    "read_limited_asset_upload_body",
)
