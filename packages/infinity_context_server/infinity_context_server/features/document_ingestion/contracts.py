"""HTTP request models for the document_ingestion server feature."""

from __future__ import annotations

from typing import Any

from infinity_context_contracts.features.document_ingestion import (
    IngestDocumentRequestDto,
)
from pydantic import BaseModel, ConfigDict, Field


class IngestDocumentHttpRequest(BaseModel):
    """HTTP request accepted by the feature-owned document ingestion seam."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=500_000)
    title: str = Field(min_length=1, max_length=300)
    source_type: str = Field(default="document", min_length=1, max_length=80)
    source_external_id: str = Field(min_length=1, max_length=240)
    source_uri: str | None = Field(default=None, max_length=2000)
    media_type: str = Field(default="text/plain", min_length=1, max_length=120)
    classification: str = Field(default="unknown", min_length=1, max_length=80)
    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    memory_scope_id: str | None = Field(default=None, min_length=1, max_length=80)
    thread_id: str | None = Field(default=None, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    memory_scope_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    thread_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    content_hash: str | None = Field(default=None, min_length=1, max_length=160)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_contract(self) -> IngestDocumentRequestDto:
        metadata = dict(self.metadata)
        metadata.update(
            {
                "classification": self.classification,
                "source_external_id": self.source_external_id,
                "source_type": self.source_type,
            }
        )
        return IngestDocumentRequestDto(
            text=self.text,
            title=self.title,
            source_uri=self.source_uri,
            media_type=self.media_type,
            space_id=self.space_id,
            memory_scope_id=self.memory_scope_id,
            thread_id=self.thread_id,
            space_slug=self.space_slug,
            memory_scope_external_ref=self.memory_scope_external_ref,
            thread_external_ref=self.thread_external_ref,
            content_hash=self.content_hash,
            idempotency_key=self.idempotency_key,
            metadata=metadata,
        )


class LegacyDocumentSourceRefRequest(BaseModel):
    """Source reference shape accepted by the legacy /v1/documents route."""

    model_config = ConfigDict(extra="forbid")

    source_type: str = Field(min_length=1, max_length=80)
    source_id: str = Field(min_length=1, max_length=160)
    chunk_id: str | None = Field(default=None, max_length=160)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    quote_preview: str | None = Field(default=None, max_length=240)
    page_number: int | None = Field(default=None, ge=1)
    time_start_ms: int | None = Field(default=None, ge=0)
    time_end_ms: int | None = Field(default=None, ge=0)
    bbox: tuple[float, float, float, float] | None = None


class LegacyIngestDocumentRequest(BaseModel):
    """Compatibility request model for the legacy /v1/documents ingest route."""

    model_config = ConfigDict(extra="forbid")

    space_id: str | None = Field(default=None, min_length=1, max_length=80)
    memory_scope_id: str | None = Field(default=None, min_length=1, max_length=80)
    thread_id: str | None = Field(default=None, max_length=80)
    space_slug: str | None = Field(default=None, min_length=1, max_length=160)
    memory_scope_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    thread_external_ref: str | None = Field(default=None, min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=500_000)
    source_type: str = Field(default="document", min_length=1, max_length=80)
    source_external_id: str = Field(min_length=1, max_length=240)
    classification: str = Field(default="unknown", max_length=40)
    source_refs: list[LegacyDocumentSourceRefRequest] = Field(
        default_factory=list,
        max_length=24,
    )


__all__ = (
    "IngestDocumentHttpRequest",
    "LegacyDocumentSourceRefRequest",
    "LegacyIngestDocumentRequest",
)
