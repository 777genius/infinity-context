"""Retrieval source normalization for context diagnostics."""

from __future__ import annotations

from infinity_context_core.application.context_diagnostics_primitives import (
    _MAX_RANKING_REASON_CHARS,
    _MAX_RETRIEVAL_SOURCES,
    _as_dict,
    _ordered_unique,
    _safe_retrieval_source,
)
from infinity_context_core.application.safe_payload import safe_metadata_text

_RETRIEVAL_SOURCE_PRIORITY = {
    "vector_chunks": 0,
    "rag_recall": 1,
    "approved_context_linked_chunks": 2,
    "approved_context_linked_facts": 3,
    "approved_context_linked_anchors": 4,
    "approved_context_linked_assets": 5,
    "approved_context_linked_extraction_artifacts": 6,
    "artifact_evidence": 7,
    "canonical_anchors": 8,
    "keyword_aggregation_chunks": 9,
    "keyword_chunks": 10,
    "keyword_neighbor_chunks": 11,
    "keyword_source_sibling_chunks": 12,
    "graph_hydrated": 13,
    "temporal_supersedes_relation": 14,
    "pending_conflict_suggestion": 15,
    "pending_duplicate_merge_suggestion": 16,
    "superseded_review": 17,
    "disputed_review": 18,
    "stale_review": 19,
    "postgres_facts": 19,
}

def diagnostic_retrieval_sources(
    diagnostics: object,
    *,
    limit: int = _MAX_RETRIEVAL_SOURCES,
) -> tuple[str, ...]:
    raw = _as_dict(diagnostics)
    raw_sources = raw.get("retrieval_sources")
    if isinstance(raw_sources, list | tuple):
        return _ordered_unique(
            tuple(source for value in raw_sources if (source := _safe_retrieval_source(value))),
            limit=limit,
        )
    raw_source = _safe_retrieval_source(raw.get("retrieval_source"))
    return (raw_source,) if raw_source else ()


def merge_diagnostic_retrieval_sources(*diagnostics: object) -> tuple[str, ...]:
    return _ordered_unique(
        tuple(
            source
            for diagnostic in diagnostics
            for source in diagnostic_retrieval_sources(diagnostic)
        )
    )

def ranking_reason_for(retrieval_sources: tuple[str, ...]) -> str:
    if len(retrieval_sources) > 1:
        reason = f"hybrid match via {', '.join(retrieval_sources)}"
    elif retrieval_sources:
        reason = f"matched via {retrieval_sources[0]}"
    else:
        reason = "matched without retrieval channel diagnostics"
    return safe_metadata_text(reason, limit=_MAX_RANKING_REASON_CHARS)

def _prioritized_retrieval_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    indexed = {source: index for index, source in enumerate(sources)}
    return tuple(
        sorted(
            sources,
            key=lambda source: (
                _RETRIEVAL_SOURCE_PRIORITY.get(source, 10_000),
                indexed[source],
            ),
        )
    )
