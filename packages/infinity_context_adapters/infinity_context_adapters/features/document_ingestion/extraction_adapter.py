"""Extraction-to-ingestion seam for document_ingestion.

Provider extraction remains outside this slice. This adapter maps already
extracted text into the document_ingestion public command shape without loading
Docling, OpenAI, or other provider runtimes.
"""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.features.document_ingestion.public import (
    FEATURE_ID,
    DocumentIngestionScope,
    DocumentIngestionValidationError,
    IngestDocumentCommand,
    SourceDocumentClassification,
    SourceDocumentOrigin,
    normalize_document_text,
)


@dataclass(frozen=True, slots=True)
class ExtractedDocumentText:
    """Provider-neutral extracted text ready for document_ingestion handoff."""

    text: str
    source_external_id: str
    title: str | None = None
    source_type: str = "extraction"
    uri: str | None = None
    classification: SourceDocumentClassification = "unknown"
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        normalized_text = normalize_document_text(self.text)
        if not normalized_text:
            raise DocumentIngestionValidationError("ExtractedDocumentText.text is required")
        object.__setattr__(self, "text", normalized_text)
        object.__setattr__(
            self,
            "source_external_id",
            _required_text(self.source_external_id, "source_external_id"),
        )
        object.__setattr__(
            self,
            "source_type",
            _required_text(self.source_type, "source_type"),
        )
        object.__setattr__(
            self,
            "title",
            _optional_text(self.title) or self.source_external_id,
        )
        object.__setattr__(self, "uri", _optional_text(self.uri))
        object.__setattr__(
            self,
            "classification",
            _required_text(self.classification, "classification"),
        )
        object.__setattr__(self, "idempotency_key", _optional_text(self.idempotency_key))


class DocumentExtractionIngestionAdapter:
    """Build document_ingestion commands from provider-neutral extracted text."""

    adapter_name = "extraction"
    feature_id = FEATURE_ID

    def build_command(
        self,
        *,
        scope: DocumentIngestionScope,
        extracted: ExtractedDocumentText,
    ) -> IngestDocumentCommand:
        return IngestDocumentCommand(
            scope=scope,
            title=extracted.title or extracted.source_external_id,
            origin=SourceDocumentOrigin(
                source_type=extracted.source_type,
                source_external_id=extracted.source_external_id,
                uri=extracted.uri,
            ),
            text=extracted.text,
            classification=extracted.classification,
            idempotency_key=extracted.idempotency_key,
        )


def create_document_extraction_ingestion_adapter() -> DocumentExtractionIngestionAdapter:
    """Create the feature-owned extraction-to-ingestion handoff adapter."""

    return DocumentExtractionIngestionAdapter()


def _required_text(value: str, field_name: str) -> str:
    cleaned = str(value).strip()
    if not cleaned:
        raise DocumentIngestionValidationError(f"{field_name} is required")
    return cleaned


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


__all__ = (
    "DocumentExtractionIngestionAdapter",
    "ExtractedDocumentText",
    "create_document_extraction_ingestion_adapter",
)
