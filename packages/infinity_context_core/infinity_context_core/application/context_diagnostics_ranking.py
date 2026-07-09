"""Ranking keys for normalized context diagnostics."""

from __future__ import annotations

from infinity_context_core.application.context_diagnostics_primitives import _as_dict
from infinity_context_core.application.context_diagnostics_sources import (
    _RETRIEVAL_SOURCE_PRIORITY,
    _prioritized_retrieval_sources,
    diagnostic_retrieval_sources,
)
from infinity_context_core.application.dto import ContextItem


def context_rank_key(
    item: ContextItem,
) -> tuple[float | int | str, ...]:
    return (
        -round(item.score, 8),
        -_score_signal_float(item, "same_script_query_boost"),
        -_score_signal_float(item, "deterministic_rerank_net_adjustment"),
        -_score_signal_float(item, "deterministic_rerank_requirement_coverage"),
        -_score_signal_float(item, "deterministic_rerank_boost"),
        -_score_signal_float(item, "query_expansion_reason_priority"),
        -_score_signal_float(item, "source_sibling_group_level_seed"),
        -_score_signal_float(item, "source_sibling_dialogue_visual_reference"),
        -_score_signal_float(item, "source_sibling_visual_continuation"),
        -_score_signal_float(item, "book_author_preference_world_evidence"),
        -_score_signal_float(item, "cause_awareness_answer_evidence"),
        -_score_signal_float(item, "item_purchase_object_evidence"),
        -_score_signal_float(item, "symbol_importance_visual_evidence"),
        -_score_signal_float(item, "friend_place_shelter_anchor_evidence"),
        -_score_signal_float(item, "phrase_bigram_hits"),
        -_score_signal_float(item, "phrase_boost"),
        -_score_signal_float(item, "distinctive_term_hits"),
        -_score_signal_float(item, "unique_term_hits"),
        -_score_signal_float(item, "keyword_aggregation_group_match"),
        -_score_signal_float(item, "keyword_aggregation_strict_term_hits"),
        -_score_signal_float(item, "source_sibling_group_boost"),
        -_score_signal_float(item, "source_sibling_after_seed"),
        -_score_signal_float(item, "source_sibling_closeness"),
        -_source_ref_quality_score(item),
        item.item_type,
        _memory_scope_id(item),
        _source_key(item),
        _chunk_sequence(item),
        _char_start(item),
        _updated_at(item),
        item.item_id,
    )


def context_duplicate_primary_key(
    item: ContextItem,
) -> tuple[int, tuple[float, str, str, str, int, int, str, str], str]:
    sources = _prioritized_retrieval_sources(diagnostic_retrieval_sources(item.diagnostics))
    selected_source = sources[0] if sources else ""
    return (
        _RETRIEVAL_SOURCE_PRIORITY.get(selected_source, 10_000),
        context_rank_key(item),
        item.text,
    )

def _source_ref_quality_score(item: ContextItem) -> int:
    refs = item.source_refs[:3]
    if not refs:
        return 0
    score = min(3, len(refs))
    for ref in refs:
        if ref.source_type and ref.source_id:
            score += 1
        if ref.chunk_id:
            score += 2
        if ref.quote_preview and ref.quote_preview.strip():
            score += 3
        if ref.char_start is not None or ref.char_end is not None:
            score += 4
        if ref.page_number is not None:
            score += 4
        if ref.time_start_ms is not None or ref.time_end_ms is not None:
            score += 4
        if ref.bbox is not None:
            score += 5
    return min(99, score)


def _score_signal_float(item: ContextItem, key: str) -> float:
    diagnostics = _as_dict(item.diagnostics)
    score_signals = _as_dict(diagnostics.get("score_signals"))
    value = score_signals.get(key)
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0

def _updated_at(item: ContextItem) -> str:
    diagnostics = item.diagnostics or {}
    if not isinstance(diagnostics, dict):
        return ""
    value = diagnostics.get("updated_at") or diagnostics.get("created_at") or ""
    return str(value)


def _memory_scope_id(item: ContextItem) -> str:
    diagnostics = _as_dict(item.diagnostics)
    return str(diagnostics.get("memory_scope_id") or "")


def _source_key(item: ContextItem) -> str:
    diagnostics = _as_dict(item.diagnostics)
    provenance = _as_dict(diagnostics.get("provenance"))
    source_type = diagnostics.get("source_type") or provenance.get("source_type")
    source_id = diagnostics.get("source_id") or provenance.get("source_id")
    if (source_type is None or source_id is None) and item.source_refs:
        ref = item.source_refs[0]
        source_type = source_type or ref.source_type
        source_id = source_id or ref.source_id
    return f"{source_type or ''}:{source_id or ''}"


def _chunk_sequence(item: ContextItem) -> int:
    diagnostics = _as_dict(item.diagnostics)
    provenance = _as_dict(diagnostics.get("provenance"))
    return _rank_int(diagnostics.get("chunk_sequence") or provenance.get("sequence"))


def _char_start(item: ContextItem) -> int:
    diagnostics = _as_dict(item.diagnostics)
    provenance = _as_dict(diagnostics.get("provenance"))
    value = diagnostics.get("char_start") or provenance.get("char_start")
    if value is None and item.source_refs:
        value = item.source_refs[0].char_start
    return _rank_int(value)


def _rank_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value))
    return 2_147_483_647
