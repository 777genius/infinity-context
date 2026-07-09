"""Reciprocal rank fusion policy for context ranking."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace

from infinity_context_core.application.context_diagnostics import (
    context_rank_key,
    diagnostic_retrieval_sources,
    normalize_context_diagnostics,
    safe_diagnostic_mapping,
    safe_score_signals,
)
from infinity_context_core.application.dto import ContextItem

_RRF_RANK_CONSTANT = 60.0
_RRF_MAX_RANK_PER_SOURCE = 50
_RRF_MAX_BOOST = 0.045
_DEFAULT_RRF_SOURCE_WEIGHTS = {
    "approved_context_linked_anchors": 1.18,
    "approved_context_linked_asset_manifest_evidence": 1.14,
    "approved_context_linked_assets": 1.08,
    "approved_context_linked_chunks": 1.12,
    "approved_context_linked_extraction_artifacts": 1.2,
    "approved_context_linked_facts": 1.14,
    "artifact_evidence": 1.2,
    "canonical_anchor_relations": 1.12,
    "canonical_anchors": 1.15,
    "graph_hydrated": 1.08,
    "keyword_aggregation_chunks": 1.12,
    "keyword_chunks": 1.04,
    "keyword_neighbor_chunks": 1.04,
    "keyword_source_sibling_chunks": 1.08,
    "postgres_facts": 1.06,
    "rag_recall": 1.06,
    "temporal_supersedes_relation": 1.12,
    "vector_chunks": 1.08,
}


def apply_rank_fusion_boosts(
    items: tuple[ContextItem, ...],
    *,
    rank_constant: float = _RRF_RANK_CONSTANT,
    max_rank_per_source: int = _RRF_MAX_RANK_PER_SOURCE,
    max_boost: float = _RRF_MAX_BOOST,
    source_weights: Mapping[str, float] | None = None,
) -> tuple[ContextItem, ...]:
    if len(items) <= 1 or rank_constant <= 0 or max_rank_per_source <= 0 or max_boost <= 0:
        return items
    rankings = _ranked_items_by_retrieval_source(items)
    if len(rankings) <= 1:
        return items
    effective_source_weights = (
        _DEFAULT_RRF_SOURCE_WEIGHTS if source_weights is None else source_weights
    )
    fusion_scores = reciprocal_rank_fusion_scores(
        rankings,
        rank_constant=rank_constant,
        max_rank_per_source=max_rank_per_source,
        source_weights=effective_source_weights,
    )
    max_fusion_score = max(fusion_scores.values(), default=0.0)
    if max_fusion_score <= 0:
        return items
    return tuple(
        _with_rank_fusion_boost(
            item,
            fusion_score=fusion_scores.get((item.item_type, item.item_id), 0.0),
            max_fusion_score=max_fusion_score,
            max_boost=max_boost,
            source_count=len(rankings),
            source_weighted=bool(effective_source_weights),
        )
        for item in items
    )


def reciprocal_rank_fusion_scores(
    rankings: Mapping[str, Sequence[ContextItem]],
    *,
    rank_constant: float = _RRF_RANK_CONSTANT,
    max_rank_per_source: int = _RRF_MAX_RANK_PER_SOURCE,
    source_weights: Mapping[str, float] | None = None,
) -> dict[tuple[str, str], float]:
    if rank_constant <= 0:
        raise ValueError("rank_constant must be positive")
    if max_rank_per_source <= 0:
        raise ValueError("max_rank_per_source must be positive")
    scores: dict[tuple[str, str], float] = {}
    for source, ranked_items in rankings.items():
        weight = _bounded_source_weight(source_weights.get(source, 1.0) if source_weights else 1.0)
        if weight <= 0:
            continue
        seen: set[tuple[str, str]] = set()
        for rank, item in enumerate(ranked_items, start=1):
            if rank > max_rank_per_source:
                break
            key = (item.item_type, item.item_id)
            if key in seen:
                continue
            seen.add(key)
            scores[key] = round(
                scores.get(key, 0.0) + weight / (rank_constant + rank),
                8,
            )
    return scores


def _ranked_items_by_retrieval_source(
    items: tuple[ContextItem, ...],
) -> dict[str, tuple[ContextItem, ...]]:
    by_source: dict[str, list[ContextItem]] = {}
    for item in items:
        sources = diagnostic_retrieval_sources(item.diagnostics)
        for source in sources:
            by_source.setdefault(source, []).append(item)
    return {
        source: tuple(sorted(source_items, key=context_rank_key))
        for source, source_items in by_source.items()
    }


def _bounded_source_weight(value: float) -> float:
    if value <= 0:
        return 0.0
    return min(5.0, float(value))


def _with_rank_fusion_boost(
    item: ContextItem,
    *,
    fusion_score: float,
    max_fusion_score: float,
    max_boost: float,
    source_count: int,
    source_weighted: bool = False,
) -> ContextItem:
    if _rank_fusion_already_applied(item):
        return item
    if fusion_score <= 0 or max_fusion_score <= 0:
        return item
    normalized_score = min(1.0, fusion_score / max_fusion_score)
    boost = round(max_boost * normalized_score, 4)
    if boost <= 0:
        return item
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    diagnostics["ranking_reason"] = diagnostics.get(
        "ranking_reason",
        "ranked by retrieval score",
    )
    diagnostics["rank_fusion_reason"] = f"RRF over {source_count} retrieval sources"
    diagnostics["score_signals"] = {
        **safe_score_signals(diagnostics.get("score_signals")),
        "rank_fusion_score": round(fusion_score, 6),
        "rank_fusion_normalized_score": round(normalized_score, 4),
        "rank_fusion_boost": boost,
        "rank_fusion_source_count": source_count,
        "rank_fusion_source_weighted": source_weighted,
    }
    diagnostics["provenance"] = {
        **safe_diagnostic_mapping(diagnostics.get("provenance")),
        "rank_fusion_applied": True,
        "rank_fusion_source_count": source_count,
        "rank_fusion_source_weighted": source_weighted,
    }
    return replace(
        item,
        score=min(0.99, round(item.score + boost, 4)),
        diagnostics=normalize_context_diagnostics(diagnostics),
    )


def _rank_fusion_already_applied(item: ContextItem) -> bool:
    return _provenance_flag_is_true(item.diagnostics, "rank_fusion_applied")


def _provenance_flag_is_true(
    diagnostics: object,
    flag: str,
    *,
    normalized: bool = False,
) -> bool:
    diagnostics = (
        safe_diagnostic_mapping(diagnostics)
        if normalized
        else normalize_context_diagnostics(diagnostics)
    )
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    return provenance.get(flag) is True
