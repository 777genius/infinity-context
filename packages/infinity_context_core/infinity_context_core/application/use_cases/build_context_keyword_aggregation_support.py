"""Focused projection and provenance helpers for keyword aggregation."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from infinity_context_core.application.context_count_cardinality import (
    keyword_aggregation_query_kind,
)
from infinity_context_core.application.context_query_expansion import QueryExpansionPlan
from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.application.context_ranking import best_query_relevance
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    is_query_relevance_sufficient,
    score_query_relevance,
)
from infinity_context_core.application.context_source_siblings import (
    _ObligationEvidenceProjection,
    project_source_sibling_obligation_evidence,
    source_turn_marker,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.application.source_refs import chunk_source_refs
from infinity_context_core.application.use_cases.build_context_item_projection import (
    _best_query_relevance_cached,
)
from infinity_context_core.domain.aggregation_admission import AggregationAdmissionCandidate
from infinity_context_core.domain.entities import MemoryChunk

_MAX_DISTINCT_MEMBER_SOURCE_REFS = 8
_SOURCE_GROUP_SUFFIXES = frozenset({"events", "observation", "summary"})


class _KeywordAggregationProvenanceCandidate(Protocol):
    admission: AggregationAdmissionCandidate
    chunk: MemoryChunk
    member_ids: tuple[str, ...]
    member_evidence_text: str


def _with_duplicate_member_source_refs(
    item: ContextItem,
    *,
    candidate: _KeywordAggregationProvenanceCandidate,
    candidates: tuple[_KeywordAggregationProvenanceCandidate, ...],
    provenance_admitted_ids: frozenset[str],
) -> ContextItem:
    """Merge bounded refs from admitted, non-conflicting duplicate members."""

    refs = list(dict.fromkeys(item.source_refs))[:_MAX_DISTINCT_MEMBER_SOURCE_REFS]
    if len(refs) >= _MAX_DISTINCT_MEMBER_SOURCE_REFS:
        return replace(item, source_refs=tuple(refs))
    selected_members = set(candidate.member_ids)
    for other in candidates:
        if (
            other is candidate
            or other.admission.candidate_id not in provenance_admitted_ids
            or not other.member_ids
            or not set(other.member_ids).issubset(selected_members)
        ):
            continue
        for ref in chunk_source_refs(other.chunk, text_preview=other.member_evidence_text):
            if ref in refs:
                continue
            refs.append(ref)
            if len(refs) >= _MAX_DISTINCT_MEMBER_SOURCE_REFS:
                return replace(item, source_refs=tuple(refs))
    return replace(item, source_refs=tuple(refs))


def _opaque_document_obligation_evidence_projection(
    *,
    query_text: str,
    semantic_query_text: str,
    relevance: QueryRelevance,
    chunk: MemoryChunk,
) -> _ObligationEvidenceProjection:
    if chunk.document_id is None:
        return _ObligationEvidenceProjection(rank=1, text=chunk.text)
    source_id = " ".join(str(chunk.source_external_id or "").split())
    if not source_id or source_turn_marker(source_id) is not None:
        return _ObligationEvidenceProjection(rank=1, text=chunk.text)
    return project_source_sibling_obligation_evidence(
        query_text=query_text,
        semantic_query_text=semantic_query_text,
        relevance=relevance,
        text=chunk.text,
    )


def _aggregation_identity_terms(query: str) -> frozenset[str]:
    intent = build_query_anchor_intent(query)
    terms: set[str] = set()
    for hint in intent.hints:
        if hint.kind.value != "person":
            continue
        terms.update(term for term in hint.canonical_key.split() if term)
    return frozenset(terms)


def _keyword_aggregation_query_kind(
    query: str,
    *,
    query_plan: QueryExpansionPlan | None = None,
) -> str:
    """Compatibility projection retained for focused aggregation tests."""

    return keyword_aggregation_query_kind(query, query_plan=query_plan)


def _aggregation_query_relevance(
    *,
    query: str,
    query_plan: QueryExpansionPlan | None,
    text: str,
    query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]] | None = None,
) -> tuple[str, str, QueryRelevance]:
    if query_plan is None:
        return query, "original_query", score_query_relevance(query=query, text=text)
    if query_relevance_cache is None:
        return best_query_relevance(query_plan, text=text)
    return _best_query_relevance_cached(query_plan, text=text, cache=query_relevance_cache)


def _is_keyword_aggregation_relevance_acceptable(
    relevance: QueryRelevance,
    *,
    aggregation_kind: str,
    strict_hits: int,
) -> bool:
    if is_query_relevance_sufficient(relevance):
        return True
    return (
        aggregation_kind in {"count", "list", "sequence"}
        and strict_hits > 0
        and relevance.unique_term_hits > 0
    )


def _aggregation_source_group(chunk: MemoryChunk) -> str:
    marker = source_turn_marker(chunk.source_external_id)
    if marker is not None:
        return marker[0]
    source_id = " ".join(str(chunk.source_external_id).split())
    parts = source_id.split(":")
    if len(parts) >= 4 and parts[-1] in _SOURCE_GROUP_SUFFIXES:
        return ":".join(parts[:-1])
    return source_id or str(chunk.document_id or chunk.id)


def _aggregation_source_kind_rank(chunk: MemoryChunk) -> int:
    if source_turn_marker(chunk.source_external_id) is not None:
        return 1
    parts = " ".join(str(chunk.source_external_id).split()).split(":")
    if parts and parts[-1] == "observation":
        return 0
    if parts and parts[-1] in {"events", "summary"}:
        return 3
    return 2
