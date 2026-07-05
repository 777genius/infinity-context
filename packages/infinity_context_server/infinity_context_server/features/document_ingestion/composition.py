"""Composition helpers for the document_ingestion server feature."""

from __future__ import annotations

from dataclasses import dataclass

import infinity_context_core.features.document_ingestion.public as document_ingestion
from fastapi import APIRouter

from infinity_context_server.features.document_ingestion.routes import (
    create_document_ingestion_router,
)


@dataclass(frozen=True, slots=True)
class DocumentIngestionServerFeature:
    """Server-side assembly for document_ingestion routes and use cases."""

    use_cases: document_ingestion.DocumentIngestionUseCases
    route_prefix: str = ""

    @property
    def feature_id(self) -> str:
        return document_ingestion.FEATURE_ID

    def create_router(self) -> APIRouter:
        return create_document_ingestion_router(
            self.use_cases,
            prefix=self.route_prefix,
        )


def build_document_ingestion_server_feature(
    use_cases: document_ingestion.DocumentIngestionUseCases,
    *,
    route_prefix: str = "",
) -> DocumentIngestionServerFeature:
    """Create the server seam without constructing feature business logic."""

    return DocumentIngestionServerFeature(
        use_cases=use_cases,
        route_prefix=route_prefix,
    )


__all__ = (
    "DocumentIngestionServerFeature",
    "build_document_ingestion_server_feature",
)
