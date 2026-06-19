"""Source-side evidence enrichment for context-link suggestions."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.application.asset_extraction_mapping import ASSET_EXTRACTION_SOURCE_TYPE
from infinity_context_core.application.context_link_candidate_policy import (
    source_text_risk_metadata_from_mapping,
)
from infinity_context_core.application.document_text import document_chunk_retrieval_text
from infinity_context_core.application.dto import SuggestContextLinksCommand
from infinity_context_core.ports.unit_of_work import UnitOfWorkPort

_MAX_SOURCE_EXTRACTION_DOCUMENTS = 5
_MAX_SOURCE_EXTRACTION_CHUNKS_PER_DOCUMENT = 20
_MAX_SOURCE_EXTRACTION_TEXT_CHARS = 12_000


@dataclass(frozen=True)
class SourceExtractionEnrichment:
    text: str
    risk_metadata: dict[str, object]
    diagnostics: dict[str, object]


async def source_extraction_enrichment(
    uow: UnitOfWorkPort,
    *,
    command: SuggestContextLinksCommand,
    document_ids: tuple[str, ...],
) -> SourceExtractionEnrichment:
    diagnostics: dict[str, object] = {
        "source_extraction_result_document_count": len(document_ids),
        "source_extraction_documents_considered": 0,
        "source_extraction_chunks_considered": 0,
        "source_extraction_chunks_used": 0,
        "source_extraction_text_enriched": False,
        "source_extraction_text_chars": 0,
    }
    parts: list[str] = []
    risk_metadata: dict[str, object] = {}
    current_text_chars = 0
    for document_id in document_ids[:_MAX_SOURCE_EXTRACTION_DOCUMENTS]:
        diagnostics["source_extraction_documents_considered"] = (
            int(diagnostics["source_extraction_documents_considered"]) + 1
        )
        chunks = await uow.documents.list_chunks(
            str(document_id),
            limit=_MAX_SOURCE_EXTRACTION_CHUNKS_PER_DOCUMENT,
        )
        diagnostics["source_extraction_chunks_considered"] = (
            int(diagnostics["source_extraction_chunks_considered"]) + len(chunks)
        )
        for chunk in chunks:
            if not _same_scope(chunk, command):
                continue
            text = document_chunk_retrieval_text(
                text=chunk.text,
                metadata=chunk.metadata,
            ).strip()
            if not text:
                continue
            parts.append(text)
            current_text_chars += len(text)
            diagnostics["source_extraction_chunks_used"] = (
                int(diagnostics["source_extraction_chunks_used"]) + 1
            )
            risk_metadata.update(source_text_risk_metadata_from_mapping(chunk.metadata))
            if current_text_chars >= _MAX_SOURCE_EXTRACTION_TEXT_CHARS:
                break
        if current_text_chars >= _MAX_SOURCE_EXTRACTION_TEXT_CHARS:
            break
    text = _bounded_source_extraction_text(parts)
    diagnostics["source_extraction_text_enriched"] = bool(text)
    diagnostics["source_extraction_text_chars"] = len(text)
    if len(document_ids) > _MAX_SOURCE_EXTRACTION_DOCUMENTS:
        diagnostics["source_extraction_documents_truncated"] = True
    return SourceExtractionEnrichment(
        text=text,
        risk_metadata=risk_metadata,
        diagnostics=diagnostics,
    )


def is_self_extraction_document(
    document: object,
    command: SuggestContextLinksCommand,
) -> bool:
    return (
        command.source_type == ASSET_EXTRACTION_SOURCE_TYPE
        and command.source_id is not None
        and str(getattr(document, "source_type", "")) == ASSET_EXTRACTION_SOURCE_TYPE
        and str(getattr(document, "source_external_id", "")) == command.source_id
    )


def is_self_extraction_chunk(
    chunk: object,
    command: SuggestContextLinksCommand,
) -> bool:
    return (
        command.source_type == ASSET_EXTRACTION_SOURCE_TYPE
        and command.source_id is not None
        and str(getattr(chunk, "source_type", "")) == ASSET_EXTRACTION_SOURCE_TYPE
        and str(getattr(chunk, "source_external_id", "")) == command.source_id
    )


def _bounded_source_extraction_text(parts: list[str]) -> str:
    text = "\n\n".join(parts).strip()
    if len(text) <= _MAX_SOURCE_EXTRACTION_TEXT_CHARS:
        return text
    return text[:_MAX_SOURCE_EXTRACTION_TEXT_CHARS].rsplit("\n", 1)[0].strip()


def _same_scope(entity: object, command: SuggestContextLinksCommand) -> bool:
    return str(entity.space_id) == str(command.space_id) and str(entity.memory_scope_id) == str(
        command.memory_scope_id
    )
