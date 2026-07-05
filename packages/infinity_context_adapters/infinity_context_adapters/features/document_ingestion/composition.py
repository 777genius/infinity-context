"""Composition helpers for document_ingestion infrastructure adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from infinity_context_core.features.document_ingestion.public import FEATURE_ID


@dataclass(frozen=True, slots=True)
class DocumentIngestionExtractionComponents:
    """Provider-neutral extraction components used by document_ingestion workflows."""

    detector: object
    extractor: object

    adapter_name: ClassVar[str] = "standard_asset_extraction"
    feature_id: ClassVar[str] = FEATURE_ID


def create_document_ingestion_extraction_components(
    *,
    openai_api_key: str | None = None,
    vision_model: str | None = None,
    vision_detail: str | None = None,
    provider_timeout_seconds: int | None = None,
    transcription_provider: str | None = None,
    transcription_model: str | None = None,
    transcription_max_upload_bytes: int | None = None,
    asr_model: str | None = None,
    asr_device: str | None = None,
    asr_compute_type: str | None = None,
) -> DocumentIngestionExtractionComponents:
    """Create the standard asset extraction adapters for document_ingestion.

    Imports of provider-capable extraction modules stay inside this factory so
    importing the document_ingestion adapter package remains SDK-free.
    """

    from infinity_context_adapters.extraction.content import SimpleFileTypeDetector
    from infinity_context_adapters.extraction.factory import build_standard_extractor

    extractor_options = _configured_options(
        openai_api_key=openai_api_key,
        vision_model=vision_model,
        vision_detail=vision_detail,
        provider_timeout_seconds=provider_timeout_seconds,
        transcription_provider=transcription_provider,
        transcription_model=transcription_model,
        transcription_max_upload_bytes=transcription_max_upload_bytes,
        asr_model=asr_model,
        asr_device=asr_device,
        asr_compute_type=asr_compute_type,
    )
    return DocumentIngestionExtractionComponents(
        detector=SimpleFileTypeDetector(),
        extractor=build_standard_extractor(**extractor_options),
    )


def _configured_options(**options: object) -> dict[str, object]:
    return {name: value for name, value in options.items() if value is not None}


__all__ = (
    "DocumentIngestionExtractionComponents",
    "create_document_ingestion_extraction_components",
)
