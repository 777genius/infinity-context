"""Context item projection helpers for build-context orchestration."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from infinity_context_core.application.context_media_time import enrich_context_item_with_media_time
from infinity_context_core.application.context_ranking import query_expansion_reason_priority
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    query_relevance_score_signals,
    score_query_relevance,
)
from infinity_context_core.application.context_snippets import (
    query_focused_snippet,
    query_snippet_diagnostics,
    query_snippet_score_signals,
    source_refs_with_query_snippet,
)
from infinity_context_core.application.dto import BuildContextQuery, ContextItem
from infinity_context_core.application.source_refs import (
    chunk_source_refs,
    source_ref_location_summary,
)
from infinity_context_core.application.temporal_validity import is_temporal_window_current
from infinity_context_core.domain.entities import (
    DataClassification,
    LifecycleStatus,
    MemoryChunk,
    MemoryFact,
    MemoryFactRelation,
)


def _fact_context_item(
    fact: MemoryFact,
    *,
    now: datetime | None,
    query_text: str,
) -> ContextItem:
    relevance = score_query_relevance(query=query_text, text=fact.text, max_boost=0.03)
    fact_score, fact_signals = _fact_score_signals(
        fact,
        now=now,
        relevance=relevance,
    )
    snippet = query_focused_snippet(query=query_text, text=fact.text)
    source_refs = source_refs_with_query_snippet(fact.source_refs, snippet)
    return enrich_context_item_with_media_time(
        ContextItem(
            item_id=str(fact.id),
            item_type="fact",
            text=fact.text,
            score=fact_score,
            source_refs=source_refs,
            diagnostics={
                "memory_scope_id": str(fact.memory_scope_id),
                "retrieval_source": "postgres_facts",
                "retrieval_sources": ["postgres_facts"],
                "ranking_reason": "canonical active fact matched query and filters",
                "score_signals": {
                    **fact_signals,
                    **query_snippet_score_signals(snippet),
                },
                "provenance": {
                    "retrieval_sources": ["postgres_facts"],
                    "source_ref_count": len(source_refs),
                    "fact_status": fact.status.value,
                    "fact_version": fact.version,
                    **query_snippet_diagnostics(snippet),
                },
                "confidence": fact.confidence.value,
                "trust_level": fact.trust_level.value,
                "updated_at": fact.updated_at.isoformat(),
                **query_snippet_diagnostics(snippet),
            },
        ),
        query_text=query_text,
    )


def _temporal_relation_is_current(
    relation: MemoryFactRelation,
    *,
    now: datetime | None,
) -> bool:
    return is_temporal_window_current(
        valid_from=relation.valid_from,
        valid_to=relation.valid_to,
        now=now,
    )


def _temporal_replacement_item(
    fact: MemoryFact,
    *,
    relation: MemoryFactRelation,
    now: datetime | None,
    query_text: str,
) -> ContextItem:
    item = _fact_context_item(fact, now=now, query_text=query_text)
    diagnostics = dict(item.diagnostics or {})
    diagnostics["retrieval_source"] = "temporal_supersedes_relation"
    diagnostics["retrieval_sources"] = [
        "temporal_supersedes_relation",
        *[
            source
            for source in diagnostics.get("retrieval_sources", [])
            if source != "temporal_supersedes_relation"
        ],
    ]
    diagnostics["ranking_reason"] = "active fact supersedes a matched older fact"
    diagnostics["temporal_replacement_for_fact_id"] = str(relation.target_fact_id)
    diagnostics["temporal_relation_id"] = str(relation.id)
    diagnostics["score_signals"] = {
        **_score_signals(diagnostics),
        "temporal_supersedes_boost": 0.04,
    }
    diagnostics["provenance"] = {
        **_provenance(diagnostics),
        "temporal_relation_id": str(relation.id),
        "supersedes_fact_id": str(relation.target_fact_id),
        "observed_at": relation.observed_at.isoformat(),
        "valid_from": relation.valid_from.isoformat() if relation.valid_from else None,
        "valid_to": relation.valid_to.isoformat() if relation.valid_to else None,
    }
    return replace(
        item,
        score=min(0.99, round(item.score + 0.04, 4)),
        diagnostics=diagnostics,
    )


def _annotate_temporal_relation(
    item: ContextItem,
    *,
    relation: MemoryFactRelation,
    role: str,
    score_delta: float,
) -> ContextItem:
    diagnostics = dict(item.diagnostics or {})
    temporal_relations = list(diagnostics.get("temporal_relations") or [])
    temporal_relations.append(
        {
            "relation_id": str(relation.id),
            "relation_type": relation.relation_type.value,
            "role": role,
            "source_fact_id": str(relation.source_fact_id),
            "target_fact_id": str(relation.target_fact_id),
            "observed_at": relation.observed_at.isoformat(),
            "valid_from": relation.valid_from.isoformat() if relation.valid_from else None,
            "valid_to": relation.valid_to.isoformat() if relation.valid_to else None,
        }
    )
    diagnostics["temporal_relations"] = temporal_relations[-8:]
    diagnostics["score_signals"] = {
        **_score_signals(diagnostics),
        f"temporal_{role}_boost": score_delta,
    }
    diagnostics["provenance"] = {
        **_provenance(diagnostics),
        "temporal_relation_count": len(temporal_relations),
    }
    return replace(
        item,
        score=min(0.99, round(item.score + score_delta, 4)),
        diagnostics=diagnostics,
    )


def _with_keyword_aggregation_score_signals(
    item: ContextItem,
    *,
    strict_hits: int,
    source_group: str,
) -> ContextItem:
    diagnostics = dict(item.diagnostics or {})
    diagnostics["score_signals"] = {
        **_score_signals(diagnostics),
        "keyword_aggregation_strict_term_hits": strict_hits,
        "keyword_aggregation_group_match": 1,
    }
    diagnostics["provenance"] = {
        **_provenance(diagnostics),
        "keyword_aggregation_source_group": source_group,
    }
    return replace(item, diagnostics=diagnostics)


def _chunk_context_item(
    *,
    chunk: MemoryChunk,
    text: str,
    retrieval_source: str,
    base_score: float,
    score: float,
    relevance: QueryRelevance | None,
    query_text: str,
    query_expansion_reason: str = "original_query",
    use_query_snippet: bool = True,
    keyword_source_score_boost: float = 0.0,
) -> ContextItem:
    snippet = query_focused_snippet(query=query_text, text=text) if use_query_snippet else None
    evidence_text = snippet.text if snippet is not None else text
    source_refs = source_refs_with_query_snippet(
        chunk_source_refs(chunk, text_preview=(snippet.text if snippet else text[:200])),
        snippet,
        include_char_range=True,
    )
    score_signals = {
        "base_score": base_score,
        "final_score": score,
        "retrieval_channel": retrieval_source,
        "source_type": chunk.source_type,
        "source_ref_count": len(source_refs),
        **query_snippet_score_signals(snippet),
    }
    if relevance is not None:
        score_signals.update(query_relevance_score_signals(relevance))
    if query_expansion_reason != "original_query":
        score_signals["query_expansion_reason"] = query_expansion_reason
    reason_priority = query_expansion_reason_priority(query_expansion_reason)
    if reason_priority > 0:
        score_signals["query_expansion_reason_priority"] = reason_priority
    if keyword_source_score_boost > 0:
        score_signals["keyword_source_score_boost"] = keyword_source_score_boost
    return enrich_context_item_with_media_time(
        ContextItem(
            item_id=str(chunk.id),
            item_type="chunk",
            text=evidence_text,
            score=score,
            source_refs=source_refs,
            diagnostics={
                "memory_scope_id": str(chunk.memory_scope_id),
                "retrieval_source": retrieval_source,
                "retrieval_sources": [retrieval_source],
                "ranking_reason": f"matched via {retrieval_source}",
                "query_expansion_reason": query_expansion_reason,
                "score_signals": score_signals,
                "provenance": {
                    "retrieval_sources": [retrieval_source],
                    "source_ref_count": len(source_refs),
                    "source_type": chunk.source_type,
                    "source_id": chunk.source_external_id,
                    "chunk_id": str(chunk.id),
                    "sequence": chunk.sequence,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    **source_ref_location_summary(source_refs),
                    **query_snippet_diagnostics(snippet),
                    "query_expansion_reason": query_expansion_reason,
                },
                "source_type": chunk.source_type,
                "source_id": chunk.source_external_id,
                "chunk_sequence": chunk.sequence,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                **source_ref_location_summary(source_refs),
                **query_snippet_diagnostics(snippet),
            },
        ),
        query_text=query_text,
    )


def _is_neighbor_chunk_visible(
    chunk: MemoryChunk,
    *,
    query: BuildContextQuery,
    memory_scope_ids: tuple[str, ...],
) -> bool:
    if chunk.status != LifecycleStatus.ACTIVE:
        return False
    if chunk.classification == DataClassification.RESTRICTED.value:
        return False
    if str(chunk.space_id) != str(query.space_id):
        return False
    if str(chunk.memory_scope_id) not in memory_scope_ids:
        return False
    if query.thread_id is None:
        return chunk.thread_id is None
    return chunk.thread_id is None or str(chunk.thread_id) == str(query.thread_id)




def _score_signals(diagnostics: dict[str, object]) -> dict[str, object]:
    value = diagnostics.get("score_signals")
    return dict(value) if isinstance(value, dict) else {}


def _provenance(diagnostics: dict[str, object]) -> dict[str, object]:
    value = diagnostics.get("provenance")
    return dict(value) if isinstance(value, dict) else {}




def _fact_score_signals(
    fact: MemoryFact,
    *,
    now: datetime | None,
    relevance: QueryRelevance,
) -> tuple[float, dict[str, object]]:
    confidence_boost = _level_boost(fact.confidence.value, low=0.012, medium=0.03, high=0.05)
    trust_boost = _level_boost(fact.trust_level.value, low=0.01, medium=0.03, high=0.045)
    freshness_boost = _freshness_boost(fact.updated_at, now=now)
    ttl_penalty = -0.015 if fact.expires_at is not None else 0.0
    score = min(
        0.99,
        max(
            0.0,
            round(
                0.88
                + confidence_boost
                + trust_boost
                + freshness_boost
                + ttl_penalty
                + relevance.score_boost,
                4,
            ),
        ),
    )
    return score, {
        "base_score": 0.88,
        "confidence_boost": round(confidence_boost, 4),
        "trust_boost": round(trust_boost, 4),
        "freshness_boost": round(freshness_boost, 4),
        "ttl_penalty": round(ttl_penalty, 4),
        **query_relevance_score_signals(relevance),
        "classification": fact.classification,
        "category": fact.category,
    }


def _level_boost(value: str, *, low: float, medium: float, high: float) -> float:
    if value == "high":
        return high
    if value == "low":
        return low
    return medium


def _freshness_boost(updated_at: datetime, *, now: datetime | None) -> float:
    if now is None:
        return 0.0
    comparable_updated_at = updated_at
    comparable_now = now
    if comparable_updated_at.tzinfo is None and comparable_now.tzinfo is not None:
        comparable_updated_at = comparable_updated_at.replace(tzinfo=comparable_now.tzinfo)
    elif comparable_updated_at.tzinfo is not None and comparable_now.tzinfo is None:
        comparable_now = comparable_now.replace(tzinfo=comparable_updated_at.tzinfo)
    age_days = max(0.0, (comparable_now - comparable_updated_at).total_seconds() / 86400)
    if age_days <= 7:
        return 0.02
    if age_days <= 30:
        return 0.012
    if age_days <= 180:
        return 0.006
    return 0.0
