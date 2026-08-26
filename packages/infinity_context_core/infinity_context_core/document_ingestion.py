"""Public compatibility seam for legacy document ingestion."""

from __future__ import annotations

from infinity_context_core.application.document_fragments import fragment_document_text


def validate_projected_document_text(text: str) -> None:
    """Require text that the canonical legacy ingestor stores as one chunk."""

    if len(fragment_document_text(text)) != 1:
        raise ValueError("projected ingestion requires exactly one canonical chunk")


__all__ = ("validate_projected_document_text",)
