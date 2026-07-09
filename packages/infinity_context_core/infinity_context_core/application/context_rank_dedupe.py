"""Context rank dedupe and merge policy."""

from __future__ import annotations

from dataclasses import replace

from infinity_context_core.application.context_diagnostics import (
    context_duplicate_primary_key,
    context_rank_key,
    diagnostic_retrieval_sources,
    merge_context_diagnostics,
    merge_diagnostic_retrieval_sources,
    normalize_context_item_diagnostics,
    safe_diagnostic_mapping,
    safe_score_signals,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import MAX_SOURCE_REFS_PER_ITEM, SourceRef

_DUPLICATE_SOURCE_SCORE_TOLERANCE = 0.015


def dedupe_rank_items(items: tuple[ContextItem, ...]) -> tuple[ContextItem, ...]:
    by_key: dict[tuple[str, str], ContextItem] = {}
    for raw_item in items:
        item = normalize_context_item_diagnostics(raw_item)
        key = (item.item_type, item.item_id)
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = item
        elif _should_replace_context_item(candidate=item, existing=existing):
            by_key[key] = _merge_context_items(primary=item, secondary=existing)
        else:
            by_key[key] = _merge_context_items(primary=existing, secondary=item)
    return tuple(sorted(by_key.values(), key=context_rank_key))


def _should_replace_context_item(*, candidate: ContextItem, existing: ContextItem) -> bool:
    score_delta = round(candidate.score - existing.score, 8)
    if abs(score_delta) <= _DUPLICATE_SOURCE_SCORE_TOLERANCE:
        candidate_priority = _context_item_reason_priority(candidate)
        existing_priority = _context_item_reason_priority(existing)
        if candidate_priority != existing_priority:
            return candidate_priority > existing_priority
        if score_delta != 0:
            return score_delta > 0
        return context_duplicate_primary_key(candidate) < context_duplicate_primary_key(existing)
    return score_delta > 0


def _context_item_reason_priority(item: ContextItem) -> float:
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    signals = safe_score_signals(diagnostics.get("score_signals"))
    value = signals.get("query_expansion_reason_priority")
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _merge_context_items(*, primary: ContextItem, secondary: ContextItem) -> ContextItem:
    source_refs = _merge_source_refs(primary.source_refs, secondary.source_refs)
    retrieval_sources = merge_diagnostic_retrieval_sources(
        primary.diagnostics,
        secondary.diagnostics,
    )
    hybrid_boost = _hybrid_boost(
        retrieval_source_count=len(retrieval_sources),
        source_ref_count=len(source_refs),
    )
    score = min(0.99, round(max(primary.score, secondary.score) + hybrid_boost, 4))
    body_item = _preferred_merge_body_item(primary=primary, secondary=secondary)
    return replace(
        body_item,
        score=score,
        source_refs=source_refs,
        diagnostics=merge_context_diagnostics(
            primary=primary.diagnostics,
            secondary=secondary.diagnostics,
            retrieval_sources=retrieval_sources,
            source_ref_count=len(source_refs),
            primary_score=primary.score,
            secondary_score=secondary.score,
            hybrid_boost=hybrid_boost,
        ),
    )


def _preferred_merge_body_item(*, primary: ContextItem, secondary: ContextItem) -> ContextItem:
    if (primary.item_type, primary.item_id) != (secondary.item_type, secondary.item_id):
        return primary
    primary_exact_source_sibling = _is_strong_exact_source_sibling_turn(primary)
    secondary_exact_source_sibling = _is_strong_exact_source_sibling_turn(secondary)
    if primary_exact_source_sibling and not secondary_exact_source_sibling:
        return primary
    if secondary_exact_source_sibling and not primary_exact_source_sibling:
        return secondary
    primary_sources = set(diagnostic_retrieval_sources(primary.diagnostics))
    secondary_sources = set(diagnostic_retrieval_sources(secondary.diagnostics))
    if (
        "keyword_aggregation_chunks" in secondary_sources
        and "keyword_aggregation_chunks" not in primary_sources
    ):
        return secondary
    if (
        "keyword_aggregation_chunks" in primary_sources
        and "keyword_aggregation_chunks" not in secondary_sources
    ):
        return primary
    return primary


def _is_strong_exact_source_sibling_turn(item: ContextItem) -> bool:
    if "keyword_source_sibling_chunks" not in diagnostic_retrieval_sources(item.diagnostics):
        return False
    if not any(_source_ref_is_turn(ref) for ref in item.source_refs):
        return False
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    signals = safe_score_signals(diagnostics.get("score_signals"))
    if _numeric_signal(signals.get("query_expansion_reason_priority")) < 3:
        return False
    return _numeric_signal(signals.get("distinctive_term_hits")) >= 4


def _source_ref_is_turn(ref: SourceRef) -> bool:
    return str(ref.source_id).casefold().endswith(":turn")


def _merge_source_refs(
    primary: tuple[SourceRef, ...],
    secondary: tuple[SourceRef, ...],
) -> tuple[SourceRef, ...]:
    refs: list[SourceRef] = []
    seen: set[tuple[object, ...]] = set()
    for ref in (*primary, *secondary):
        key = (
            ref.source_type,
            ref.source_id,
            ref.chunk_id,
            ref.char_start,
            ref.char_end,
            ref.quote_preview,
            ref.page_number,
            ref.time_start_ms,
            ref.time_end_ms,
            ref.bbox,
        )
        if key in seen:
            continue
        seen.add(key)
        refs.append(ref)
        if len(refs) >= MAX_SOURCE_REFS_PER_ITEM:
            break
    return tuple(refs)


def _hybrid_boost(*, retrieval_source_count: int, source_ref_count: int) -> float:
    if retrieval_source_count <= 1:
        return 0.0
    source_boost = 0.035 * (retrieval_source_count - 1)
    provenance_boost = 0.01 * min(3, max(0, source_ref_count - 1))
    return min(0.08, source_boost + provenance_boost)


def _numeric_signal(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0
