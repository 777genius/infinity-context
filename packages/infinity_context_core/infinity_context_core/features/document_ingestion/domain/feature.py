"""Domain identity for the document_ingestion feature capsule."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

FEATURE_ID: Final = "document_ingestion"


@dataclass(frozen=True, slots=True)
class DocumentIngestionFeature:
    """Stable domain identity for the document_ingestion business capability."""

    feature_id: str = FEATURE_ID


__all__ = ("FEATURE_ID", "DocumentIngestionFeature")
