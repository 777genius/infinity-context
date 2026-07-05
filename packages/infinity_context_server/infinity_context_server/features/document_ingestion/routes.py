"""Feature-owned FastAPI route seam for document_ingestion."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
import infinity_context_core.features.document_ingestion.public as document_ingestion

from infinity_context_server.features.document_ingestion.contracts import (
    IngestDocumentHttpRequest,
)
from infinity_context_server.features.document_ingestion.mappers import (
    ingest_document_command_from_contract,
    ingest_document_result_to_contract,
)


def create_document_ingestion_router(
    use_cases: document_ingestion.DocumentIngestionUseCases,
    *,
    prefix: str = "",
) -> APIRouter:
    """Create routes that only translate HTTP contracts to feature use cases."""

    router = APIRouter(prefix=prefix, tags=["document_ingestion"])

    @router.post("/documents", status_code=status.HTTP_201_CREATED)
    async def ingest_document(request: IngestDocumentHttpRequest) -> dict[str, Any]:
        try:
            command = ingest_document_command_from_contract(request.to_contract())
        except (ValueError, document_ingestion.DocumentIngestionValidationError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        result = await use_cases.ingest_document.execute(command)
        return ingest_document_result_to_contract(result).to_dict()

    return router


__all__ = ("create_document_ingestion_router",)
