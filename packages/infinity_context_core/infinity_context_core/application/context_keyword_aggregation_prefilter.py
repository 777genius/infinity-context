"""Bound large aggregation pools without dropping recognized quantity members."""

from __future__ import annotations

from infinity_context_core.application.context_quantity_evidence_slots import (
    QuantityEvidenceTargetKind,
    extract_quantity_evidence_request,
    project_quantity_evidence_slots,
)
from infinity_context_core.application.document_text import document_chunk_retrieval_text
from infinity_context_core.domain.entities import MemoryChunk

_PREFILTER_THRESHOLD = 145
_PREFILTER_MIN_TARGET = 125
_PREFILTER_MAX_TARGET = 180


def prefilter_keyword_aggregation_seed_chunks(
    *,
    query: str,
    max_chunks: int,
    chunks: tuple[MemoryChunk, ...],
) -> tuple[tuple[MemoryChunk, ...], dict[str, int]]:
    """Preserve bounded project members before expensive aggregation scoring."""

    diagnostics = {
        "keyword_aggregation_prefilter_candidates_selected": len(chunks),
        "keyword_aggregation_prefilter_candidates_skipped": 0,
        "keyword_aggregation_prefilter_distinct_member_preserved": 0,
    }
    request = extract_quantity_evidence_request(query)
    if (
        len(chunks) <= _PREFILTER_THRESHOLD
        or request is None
        or request.target_kind is not QuantityEvidenceTargetKind.PROJECT_LEADERSHIP_COUNT
    ):
        return chunks, diagnostics

    target = min(
        len(chunks),
        _PREFILTER_MAX_TARGET,
        max(_PREFILTER_MIN_TARGET, max_chunks),
    )
    protected_ids: set[str] = set()
    protected_member_count = 0
    for chunk in chunks:
        text = document_chunk_retrieval_text(text=chunk.text, metadata=chunk.metadata)
        projection = project_quantity_evidence_slots(query=query, text=text)
        if not projection.present:
            continue
        protected_ids.add(str(chunk.id))
        protected_member_count += len(projection.member_ids)

    selected_ids = set(protected_ids)
    for chunk in chunks:
        if len(selected_ids) >= target:
            break
        selected_ids.add(str(chunk.id))
    selected = tuple(chunk for chunk in chunks if str(chunk.id) in selected_ids)
    diagnostics["keyword_aggregation_prefilter_candidates_selected"] = len(selected)
    diagnostics["keyword_aggregation_prefilter_candidates_skipped"] = len(chunks) - len(selected)
    diagnostics["keyword_aggregation_prefilter_distinct_member_preserved"] = protected_member_count
    return selected, diagnostics
