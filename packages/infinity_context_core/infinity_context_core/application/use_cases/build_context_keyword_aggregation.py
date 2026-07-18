"""Keyword aggregation and relevance-cache policies for build-context."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from infinity_context_core.application.context_aggregation_evidence_text import (
    _aggregation_evidence_text,
    _strict_query_window_match_counts,
    _strict_token_variants,
    _weighted_aggregation_query_variant_sets,
)
from infinity_context_core.application.context_count_cardinality import (
    has_exact_count_cardinality_evidence,
    keyword_aggregation_query_kind,
    requests_list_aggregation,
)
from infinity_context_core.application.context_count_cardinality import (
    keyword_aggregation_intent as _keyword_aggregation_intent,
)
from infinity_context_core.application.context_lexical import query_terms
from infinity_context_core.application.context_query_expansion import QueryExpansionPlan
from infinity_context_core.application.context_query_intent import (
    build_query_anchor_intent,
    query_anchor_intent_text_conflicts,
)
from infinity_context_core.application.context_ranking import (
    best_query_relevance,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    ACTIVITY_OBSERVATION_SOURCE_REASONS as _ACTIVITY_OBSERVATION_SOURCE_REASONS,
)
from infinity_context_core.application.context_relationship_status_evidence import (
    is_relationship_status_reason as _is_relationship_status_reason,
)
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    is_query_relevance_sufficient,
    score_query_relevance,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_answer_evidence as _source_sibling_answer_evidence,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_group_limit as _source_sibling_group_limit,
)
from infinity_context_core.application.context_source_siblings import (
    source_sibling_related_turn_anchor_evidence as _related_turn_anchor_evidence,
)
from infinity_context_core.application.context_source_siblings import (
    source_turn_marker as _source_turn_marker,
)
from infinity_context_core.application.context_travel_place_evidence import (
    has_travel_place_inventory_evidence,
)
from infinity_context_core.application.document_text import document_chunk_retrieval_text
from infinity_context_core.application.dto import BuildContextQuery, ContextItem
from infinity_context_core.application.use_cases.build_context_item_projection import (
    _best_query_relevance_cached,
    _chunk_context_item,
    _with_keyword_aggregation_score_signals,
)
from infinity_context_core.domain.aggregation_admission import (
    AggregationAdmissionCandidate,
    AggregationAdmissionPolicy,
    AggregationAdmissionSignals,
    AggregationIntent,
)
from infinity_context_core.domain.entities import MemoryChunk
from infinity_context_core.ports.unit_of_work import UnitOfWorkFactoryPort

_MAX_AGGREGATION_KEYWORD_ITEMS = 20
_MAX_AGGREGATION_ADMISSION_SEARCH_RESULTS = 72
_AGGREGATION_CONTINUITY_LIMITS = {
    AggregationIntent.COUNT: 16,
    AggregationIntent.LIST: 8,
    AggregationIntent.SEQUENCE: 32,
}
_STRICT_QUERY_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_EN_PLACE_LIST_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:cities|city|countries|country|states?|places?|locations?|"
    r"destinations?|areas?)\b",
    re.IGNORECASE,
)
_EN_NAMED_PREFERENCE_SOURCE_SIBLING_QUERY_RE = re.compile(
    r"\b(?:would|enjoy|enjoys?|prefer|prefers?|favorite|favourite|"
    r"related|recommend|interested)\b",
    re.IGNORECASE,
)
_EN_NAMED_ENTITY_PHRASE_RE = re.compile(r"\b[A-Z][A-Za-z0-9'-]+(?:[-\s]+[A-Z][A-Za-z0-9'-]+)+\b")
_MAX_EXTRA_ACTIVITY_PROMPT_KEYWORD_ITEMS = 80
_MAX_EXTRA_INVENTORY_PROMPT_KEYWORD_ITEMS = 16
_MIN_CHUNK_LIMIT_FOR_EXTRA_ACTIVITY_PROMPT_ITEMS = 8
_MIN_CHUNK_LIMIT_FOR_EXTRA_INVENTORY_PROMPT_ITEMS = 8
_MIN_EXTRA_INVENTORY_PROMPT_DISTINCTIVE_HITS = 4
_EXTRA_INVENTORY_PROMPT_REASONS = frozenset(
    {
        "decomposition_inventory_list",
        "friend_place_inventory_bridge",
        "friend_place_shelter_inventory_bridge",
        "friend_place_gym_inventory_bridge",
        "friend_place_church_inventory_bridge",
        "travel_country_inventory_bridge",
        "cause_education_infrastructure_inventory_bridge",
        "cause_veterans_inventory_bridge",
        "volunteering_people_inventory_bridge",
        "volunteering_inventory_bridge",
    }
)
_LIST_SOURCE_SIBLING_DEEP_REASONS = _EXTRA_INVENTORY_PROMPT_REASONS | frozenset(
    {
        "activity_aggregation_bridge",
        "book_reading_list_bridge",
        "children_preference_bridge",
        "church_friend_activity_inventory_bridge",
        "decomposition_activity_participation",
        "event_participation_bridge",
        "exercise_activity_inventory_bridge",
        "music_artist_answer_bridge",
        "music_artist_band_bridge",
        "outdoor_activity_inventory_bridge",
    }
)
_LIST_SOURCE_SIBLING_GROUP_LIMIT = 32
_LIST_SOURCE_SIBLING_GROUP_BACKFILL_LIMIT = 96
_ScoredKeywordPromptItem = tuple[int, int, int, float, float, int, str, ContextItem]
_StrictQueryTermVariants = tuple[frozenset[str], ...]
_WeightedAggregationQueryVariants = tuple[tuple[frozenset[str], float], ...]
_SOURCE_GROUP_SUFFIXES = frozenset({"events", "observation", "summary"})


@dataclass(frozen=True)
class _KeywordAggregationCandidate:
    rank_key: tuple[int, int, int, float, int]
    group: str
    chunk: MemoryChunk
    chunk_text: str
    relevance: QueryRelevance
    strict_hits: int
    aggregation_query: str
    aggregation_reason: str
    query_variant_sets: _WeightedAggregationQueryVariants
    admission: AggregationAdmissionCandidate
    numeric_corroboration: bool


def _ranked_keyword_chunk_scores(
    scored_keyword_chunks: list[tuple[int, int, int, float, float, int, MemoryChunk]],
) -> tuple[tuple[int, int, int, float, float, int, MemoryChunk], ...]:
    return tuple(
        sorted(
            scored_keyword_chunks,
            key=lambda item: (
                -item[0],
                -item[1],
                -item[2],
                -item[3],
                -item[4],
                item[5],
            ),
        )
    )


def _context_item_aggregation_source_groups(items: tuple[ContextItem, ...]) -> tuple[str, ...]:
    groups: list[str] = []
    seen: set[str] = set()
    for item in items:
        diagnostics = item.diagnostics or {}
        provenance = diagnostics.get("provenance")
        raw_group = (
            provenance.get("keyword_aggregation_source_group")
            if isinstance(provenance, dict)
            else None
        )
        group = str(raw_group or "").strip()
        if group and group not in seen:
            seen.add(group)
            groups.append(group)
    return tuple(groups)


def _prioritized_chunks_for_source_groups(
    chunks: tuple[MemoryChunk, ...],
    *,
    source_groups: tuple[str, ...],
) -> tuple[MemoryChunk, ...]:
    if not chunks or not source_groups:
        return ()
    source_group_set = set(source_groups)
    return tuple(chunk for chunk in chunks if _aggregation_source_group(chunk) in source_group_set)


def _prioritized_source_sibling_seed_groups(
    *,
    source_groups: dict[str, object],
    seed_chunks: tuple[MemoryChunk, ...],
    query_plan: QueryExpansionPlan,
    query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]],
    limit: int,
) -> dict[str, object]:
    if limit <= 0:
        return {}
    if len(source_groups) <= limit:
        return dict(source_groups)
    group_rank: dict[str, tuple[int, int, int, float]] = {}
    for chunk in seed_chunks:
        group = _aggregation_source_group(chunk)
        if not group or group not in source_groups:
            continue
        chunk_text = document_chunk_retrieval_text(text=chunk.text, metadata=chunk.metadata)
        expansion_query, expansion_reason, relevance = _best_query_relevance_cached(
            query_plan,
            text=chunk_text,
            cache=query_relevance_cache,
        )
        answer_evidence = _source_sibling_answer_evidence(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
            text=chunk_text,
        )
        related_anchor = _related_turn_anchor_evidence(relevance=relevance, text=chunk_text)
        if answer_evidence or related_anchor:
            rank = (
                int(answer_evidence),
                relevance.distinctive_term_hits,
                relevance.unique_term_hits,
                relevance.hit_ratio,
            )
            group_rank[group] = max(rank, group_rank.get(group, (0, 0, 0, 0.0)))
    ordered_groups = tuple(source_groups.items())
    prioritized = sorted(
        (entry for entry in ordered_groups if entry[0] in group_rank),
        key=lambda entry: tuple(-value for value in group_rank[entry[0]]),
    )
    prioritized.extend(entry for entry in ordered_groups if entry[0] not in group_rank)
    return dict(prioritized[:limit])


def _prioritize_source_sibling_answer_evidence_seed_chunks(
    *,
    seed_chunks: tuple[MemoryChunk, ...],
    query_plan: QueryExpansionPlan,
    query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]],
) -> tuple[MemoryChunk, ...]:
    ranked: list[tuple[int, int, int, float, int, str, MemoryChunk]] = []
    remaining: list[tuple[int, MemoryChunk]] = []
    for index, chunk in enumerate(seed_chunks):
        chunk_text = document_chunk_retrieval_text(text=chunk.text, metadata=chunk.metadata)
        expansion_query, expansion_reason, relevance = _best_query_relevance_cached(
            query_plan,
            text=chunk_text,
            cache=query_relevance_cache,
        )
        answer_evidence = _source_sibling_answer_evidence_query_match(
            query_plan=query_plan,
            text=chunk_text,
            preferred_query=expansion_query,
            preferred_reason=expansion_reason,
        )
        related_anchor = _related_turn_anchor_evidence(relevance=relevance, text=chunk_text)
        if answer_evidence or related_anchor:
            ranked.append(
                (
                    int(bool(answer_evidence)),
                    relevance.distinctive_term_hits,
                    relevance.unique_term_hits,
                    relevance.hit_ratio,
                    index,
                    _aggregation_source_group(chunk),
                    chunk,
                )
            )
        else:
            remaining.append((index, chunk))
    if not ranked:
        return seed_chunks
    answer_chunks = sorted(
        (entry for entry in ranked if entry[0] > 0),
        key=lambda entry: (-entry[1], -entry[2], -entry[3], entry[4]),
    )
    anchor_chunks = sorted(
        (entry for entry in ranked if entry[0] <= 0),
        key=lambda entry: (-entry[1], -entry[2], -entry[3], entry[4]),
    )
    prioritized = (
        *_source_group_diverse_answer_evidence_chunks(answer_chunks),
        *_source_group_diverse_answer_evidence_chunks(anchor_chunks),
    )
    return (
        *(entry[-1] for entry in prioritized),
        *(chunk for _, chunk in remaining),
    )


def _source_group_diverse_answer_evidence_chunks(
    chunks: list[tuple[int, int, int, float, int, str, MemoryChunk]],
) -> tuple[tuple[int, int, int, float, int, str, MemoryChunk], ...]:
    primary: list[tuple[int, int, int, float, int, str, MemoryChunk]] = []
    extra: list[tuple[int, int, int, float, int, str, MemoryChunk]] = []
    seen_groups: set[str] = set()
    for chunk in chunks:
        target = primary if chunk[5] and chunk[5] not in seen_groups else extra
        target.append(chunk)
        seen_groups.add(chunk[5])
    return (*primary, *extra)


def _source_sibling_answer_evidence_query_match(
    *,
    query_plan: QueryExpansionPlan,
    text: str,
    preferred_query: str,
    preferred_reason: str,
) -> tuple[str, str] | None:
    expansions = query_plan.retrieval_queries
    for expansion_query, expansion_reason in (
        (preferred_query, preferred_reason),
        *((item.query, item.reason) for item in expansions),
    ):
        if _source_sibling_answer_evidence(
            expansion_query=expansion_query,
            expansion_reason=expansion_reason,
            text=text,
        ):
            return expansion_query, expansion_reason
    return None


def _query_plan_requests_list_source_sibling_depth(
    *,
    query_text: str,
    query_plan: QueryExpansionPlan,
) -> bool:
    return bool(
        requests_list_aggregation(query_text)
        or any(
            item.reason in _LIST_SOURCE_SIBLING_DEEP_REASONS
            for item in query_plan.retrieval_queries
        )
    )


def _query_plan_requests_place_source_sibling_diversity(
    *,
    query_text: str,
    query_plan: QueryExpansionPlan,
) -> bool:
    place_reasons = {
        "friend_place_inventory_bridge",
        "friend_place_shelter_inventory_bridge",
        "friend_place_gym_inventory_bridge",
        "friend_place_church_inventory_bridge",
        "place_area_inventory_bridge",
        "travel_country_inventory_bridge",
        "trip_destination_bridge",
    }
    return bool(
        _EN_PLACE_LIST_SOURCE_SIBLING_QUERY_RE.search(query_text)
        or any(item.reason in place_reasons for item in query_plan.retrieval_queries)
    )


def _query_plan_requests_named_preference_source_sibling_diversity(
    *,
    query_text: str,
    query_plan: QueryExpansionPlan,
) -> bool:
    return bool(
        _EN_NAMED_PREFERENCE_SOURCE_SIBLING_QUERY_RE.search(query_text)
        and _EN_NAMED_ENTITY_PHRASE_RE.search(query_text)
        and any(
            item.reason == "decomposition_inference_support"
            for item in query_plan.retrieval_queries
        )
    )


def _query_plan_requests_relationship_status_source_sibling_diversity(
    *,
    query_text: str,
    query_plan: QueryExpansionPlan,
) -> bool:
    del query_text
    return any(_is_relationship_status_reason(item.reason) for item in query_plan.retrieval_queries)


def _source_sibling_group_limit_for_request(
    *,
    source_group_count: int,
    deep_list_coverage: bool,
    answer_evidence_group_diversity: bool,
) -> int:
    default_limit = _source_sibling_group_limit()
    if deep_list_coverage or answer_evidence_group_diversity:
        return max(default_limit, min(source_group_count, _LIST_SOURCE_SIBLING_GROUP_LIMIT))
    return default_limit


def _source_sibling_group_backfill_plan(
    *,
    deep_list_coverage: bool,
    source_groups: Mapping[str, object],
) -> tuple[tuple[str, ...], int]:
    if not deep_list_coverage or not source_groups:
        return (), 0
    return tuple(source_groups), _LIST_SOURCE_SIBLING_GROUP_BACKFILL_LIMIT


def _source_sibling_answer_evidence_extra_key(
    chunk: MemoryChunk,
    *,
    deep_list_coverage: bool,
) -> str:
    source_id = str(chunk.source_external_id or "")
    return _aggregation_source_group(chunk) or source_id if deep_list_coverage else source_id


def _dedupe_chunks_by_id(chunks: tuple[MemoryChunk, ...]) -> tuple[MemoryChunk, ...]:
    selected: list[MemoryChunk] = []
    seen: set[str] = set()
    for chunk in chunks:
        chunk_id = str(chunk.id)
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        selected.append(chunk)
    return tuple(selected)


async def _aggregation_admission_seed_chunks(
    *,
    uow_factory: UnitOfWorkFactoryPort,
    query: BuildContextQuery,
    query_plan: QueryExpansionPlan,
    canonical_chunks: tuple[MemoryChunk, ...],
) -> tuple[tuple[MemoryChunk, ...], dict[str, object]]:
    """Recover a bounded tail from the explicit request without replaying its plan."""

    diagnostics = {
        "keyword_aggregation_admission_queries": 0,
        "keyword_aggregation_admission_seed_chunks": len(canonical_chunks),
        "keyword_aggregation_admission_seed_chunks_added": 0,
    }
    if (
        query.max_chunks <= 0
        or _keyword_aggregation_intent(query.query, query_plan=query_plan) is None
    ):
        return canonical_chunks, diagnostics
    async with uow_factory() as uow:
        matches = await uow.chunks.keyword_search(
            space_id=str(query.space_id),
            memory_scope_ids=tuple(str(value) for value in query.memory_scope_ids),
            thread_id=str(query.thread_id) if query.thread_id else None,
            query=query.query,
            limit=_MAX_AGGREGATION_ADMISSION_SEARCH_RESULTS,
        )
    chunks = _dedupe_chunks_by_id((*canonical_chunks, *matches))
    diagnostics["keyword_aggregation_admission_queries"] = 1
    diagnostics["keyword_aggregation_admission_seed_chunks"] = len(chunks)
    diagnostics["keyword_aggregation_admission_seed_chunks_added"] = len(chunks) - len(
        canonical_chunks
    )
    return chunks, diagnostics


def _strict_query_term_hits(*, query: str, text: str) -> int:
    return _strict_query_variant_hits(
        query_term_variants=_strict_query_term_variant_sets(query=query),
        text=text,
    )


def _strict_query_term_variant_sets(*, query: str) -> _StrictQueryTermVariants:
    return tuple(frozenset(_strict_token_variants(term.raw)) for term in query_terms(query))


def _strict_query_variant_hits(
    *,
    query_term_variants: _StrictQueryTermVariants,
    text: str,
) -> int:
    if not query_term_variants:
        return 0
    text_variants: set[str] = set()
    for match in _STRICT_QUERY_TOKEN_RE.finditer(text):
        text_variants.update(_strict_token_variants(match.group(0)))
    return sum(
        1 for term_variants in query_term_variants if text_variants.intersection(term_variants)
    )


def _keyword_anchor_conflict_allowed(
    *,
    expansion_reason: str,
    relevance: QueryRelevance,
    text: str,
) -> bool:
    if expansion_reason != "travel_country_inventory_bridge":
        return False
    if relevance.distinctive_term_hits < 3 or relevance.unique_term_hits < 3:
        return False
    return has_travel_place_inventory_evidence(text)


def _selected_keyword_prompt_items(
    scored_items: list[_ScoredKeywordPromptItem],
    *,
    limit: int,
) -> tuple[ContextItem, ...]:
    if limit <= 0 or not scored_items:
        return ()
    ordered = tuple(
        sorted(
            scored_items,
            key=lambda item: (
                -item[0],
                -item[1],
                -item[2],
                -item[3],
                -item[4],
                item[5],
            ),
        )
    )
    selected: list[ContextItem] = []
    selected_keys: set[tuple[str, str]] = set()
    for scored_item in _source_diverse_keyword_prompt_items(ordered, limit=limit):
        item = scored_item[7]
        selected.append(item)
        selected_keys.add((item.item_type, item.item_id))
    if (
        limit < _MIN_CHUNK_LIMIT_FOR_EXTRA_ACTIVITY_PROMPT_ITEMS
        and limit < _MIN_CHUNK_LIMIT_FOR_EXTRA_INVENTORY_PROMPT_ITEMS
    ):
        return tuple(selected)
    if limit >= _MIN_CHUNK_LIMIT_FOR_EXTRA_INVENTORY_PROMPT_ITEMS:
        inventory_extra_count = 0
        inventory_extra_limit = min(limit, _MAX_EXTRA_INVENTORY_PROMPT_KEYWORD_ITEMS)
        for scored_item in ordered[limit:]:
            reason = scored_item[6]
            if reason not in _EXTRA_INVENTORY_PROMPT_REASONS:
                continue
            if scored_item[1] < _MIN_EXTRA_INVENTORY_PROMPT_DISTINCTIVE_HITS:
                continue
            item = scored_item[7]
            key = (item.item_type, item.item_id)
            if key in selected_keys:
                continue
            selected.append(item)
            selected_keys.add(key)
            inventory_extra_count += 1
            if inventory_extra_count >= inventory_extra_limit:
                break
    if limit < _MIN_CHUNK_LIMIT_FOR_EXTRA_ACTIVITY_PROMPT_ITEMS:
        return tuple(selected)
    extra_count = 0
    extra_limit = limit
    if limit >= 32:
        extra_limit = _MAX_EXTRA_ACTIVITY_PROMPT_KEYWORD_ITEMS
    for scored_item in ordered[limit:]:
        reason = scored_item[6]
        if reason not in _ACTIVITY_OBSERVATION_SOURCE_REASONS:
            continue
        item = scored_item[7]
        key = (item.item_type, item.item_id)
        if key in selected_keys:
            continue
        selected.append(item)
        selected_keys.add(key)
        extra_count += 1
        if extra_count >= extra_limit:
            break
    return tuple(selected)


def _source_diverse_keyword_prompt_items(
    ordered: tuple[_ScoredKeywordPromptItem, ...],
    *,
    limit: int,
) -> tuple[_ScoredKeywordPromptItem, ...]:
    selected: list[_ScoredKeywordPromptItem] = []
    used_sources: set[str] = set()
    for scored_item in ordered:
        source_key = _keyword_prompt_item_source_key(scored_item[7])
        if source_key in used_sources:
            continue
        selected.append(scored_item)
        used_sources.add(source_key)
        if len(selected) >= limit:
            return tuple(selected)
    selected_keys = {(item[7].item_type, item[7].item_id) for item in selected}
    for scored_item in ordered:
        item = scored_item[7]
        key = (item.item_type, item.item_id)
        if key in selected_keys:
            continue
        selected.append(scored_item)
        selected_keys.add(key)
        if len(selected) >= limit:
            break
    return tuple(selected)


def _keyword_prompt_item_source_key(item: ContextItem) -> str:
    if item.source_refs:
        ref = item.source_refs[0]
        return f"{ref.source_type}:{ref.source_id}"
    return f"{item.item_type}:{item.item_id}"


def _keyword_aggregation_chunk_items(
    *,
    query: BuildContextQuery,
    seed_chunks: tuple[MemoryChunk, ...],
    ordinary_seed_ids: frozenset[str] | None = None,
    query_plan: QueryExpansionPlan | None = None,
    query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]] | None = None,
) -> tuple[tuple[ContextItem, ...], dict[str, object]]:
    diagnostics = {
        "keyword_aggregation_chunks_considered": 0,
        "keyword_aggregation_chunks_used": 0,
        "keyword_aggregation_chunks_skipped": 0,
        "keyword_aggregation_query_kind": "",
        "keyword_aggregation_relaxed_relevance_used": 0,
        "keyword_aggregation_slot_reservations_used": 0,
        "keyword_aggregation_source_families_used": 0,
        "keyword_aggregation_numeric_corroborations": 0,
        "keyword_aggregation_admission_reasons": {},
        "keyword_aggregation_chunks_deduplicated": 0,
        "keyword_aggregation_admitted_not_selected": 0,
        "keyword_aggregation_continuity_items_used": 0,
        "keyword_aggregation_continuity_limit": 0,
    }
    intent = _keyword_aggregation_intent(query.query, query_plan=query_plan)
    diagnostics["keyword_aggregation_query_kind"] = intent.value if intent else ""
    diagnostics["keyword_aggregation_continuity_limit"] = _AGGREGATION_CONTINUITY_LIMITS.get(
        intent, 0
    )
    if query.max_chunks <= 0 or not seed_chunks or intent is None:
        return (), diagnostics

    query_identity_terms = _aggregation_identity_terms(query.query)
    max_items = min(
        _MAX_AGGREGATION_KEYWORD_ITEMS,
        max(4, query.max_chunks // 2),
    )
    if intent is AggregationIntent.SEQUENCE:
        max_items = min(max_items, 4)
    anchor_intent = build_query_anchor_intent(query.query)
    candidates: list[_KeywordAggregationCandidate] = []
    skipped = 0
    unique_seed_chunks = _dedupe_chunks_by_id(seed_chunks)
    ordinary_ids = ordinary_seed_ids or frozenset(str(chunk.id) for chunk in unique_seed_chunks)
    diagnostics["keyword_aggregation_chunks_deduplicated"] = len(seed_chunks) - len(
        unique_seed_chunks
    )
    for order, chunk in enumerate(unique_seed_chunks):
        diagnostics["keyword_aggregation_chunks_considered"] = (
            int(diagnostics["keyword_aggregation_chunks_considered"]) + 1
        )
        chunk_text = document_chunk_retrieval_text(
            text=chunk.text,
            metadata=chunk.metadata,
        )
        aggregation_query, aggregation_reason, relevance = _aggregation_query_relevance(
            query=query.query,
            query_plan=query_plan,
            text=chunk_text,
            query_relevance_cache=query_relevance_cache,
        )
        weighted_query_terms = _weighted_aggregation_query_variant_sets(
            aggregation_query,
            identity_terms=query_identity_terms,
        )
        weighted_hits, _ = _strict_query_window_match_counts(
            text=chunk_text,
            query_variant_sets=weighted_query_terms,
        )
        strict_hits = int(weighted_hits)
        group = _aggregation_source_group(chunk)
        numeric_corroboration = has_exact_count_cardinality_evidence(chunk_text)
        anchor_conflict = query_anchor_intent_text_conflicts(anchor_intent, chunk_text)
        admission = AggregationAdmissionCandidate(
            candidate_id=str(chunk.id),
            signals=AggregationAdmissionSignals(
                intent=intent,
                relevance_sufficient=is_query_relevance_sufficient(relevance),
                distinctive_hits=strict_hits,
                unique_hits=relevance.unique_term_hits,
                query_plan_slot=aggregation_reason,
                source_family=group,
                anchor_conflict=anchor_conflict,
                temporal_conflict=False,
                numeric_corroboration=numeric_corroboration,
            ),
        )
        rank_key = (
            -strict_hits,
            _aggregation_source_kind_rank(chunk),
            -relevance.distinctive_term_hits,
            -relevance.hit_ratio,
            order,
        )
        candidates.append(
            _KeywordAggregationCandidate(
                rank_key=rank_key,
                group=group,
                chunk=chunk,
                chunk_text=chunk_text,
                relevance=relevance,
                strict_hits=strict_hits,
                aggregation_query=aggregation_query,
                aggregation_reason=aggregation_reason,
                query_variant_sets=weighted_query_terms,
                admission=admission,
                numeric_corroboration=numeric_corroboration,
            )
        )

    ordered_candidates = tuple(sorted(candidates, key=lambda item: item.rank_key))
    policy = AggregationAdmissionPolicy()
    decisions = tuple(policy.decide(candidate.admission) for candidate in ordered_candidates)
    decision_by_id = {decision.candidate_id: decision for decision in decisions}
    ordinary_candidates = tuple(
        candidate.admission
        for candidate in ordered_candidates
        if candidate.admission.candidate_id in ordinary_ids
        and decision_by_id[candidate.admission.candidate_id].admitted
    )
    ordinary_selection = policy.select(
        ordinary_candidates,
        limit=max_items,
        source_family_cap=3,
    )
    ordinary_selected_ids = set(ordinary_selection.selected_ids)
    ordinary_supported_slots = {
        (candidate.aggregation_reason, candidate.group)
        for candidate in ordered_candidates
        if candidate.admission.candidate_id in ordinary_selected_ids
    }
    continuity_candidates = tuple(
        candidate.admission
        for candidate in ordered_candidates
        if (candidate.aggregation_reason, candidate.group) not in ordinary_supported_slots
    )
    continuity_selection = policy.select(
        continuity_candidates,
        limit=_AGGREGATION_CONTINUITY_LIMITS[intent],
        source_family_cap=3,
        selected_source_families=tuple(
            candidate.group
            for candidate in ordered_candidates
            if candidate.admission.candidate_id in ordinary_selected_ids
        ),
    )
    continuity_ids = set(continuity_selection.selected_ids)
    selected_ids = ordinary_selected_ids | continuity_ids
    reason_counts: dict[str, int] = {}
    for decision in decisions:
        reason_counts[decision.reason.value] = reason_counts.get(decision.reason.value, 0) + 1
        if not decision.admitted:
            skipped += 1
    diagnostics["keyword_aggregation_admission_reasons"] = reason_counts
    diagnostics["keyword_aggregation_slot_reservations_used"] = len(ordinary_supported_slots) + len(
        continuity_selection.reserved_ids
    )
    admitted_count = sum(decision.admitted for decision in decisions)
    admitted_not_selected = admitted_count - len(selected_ids)
    diagnostics["keyword_aggregation_admitted_not_selected"] = admitted_not_selected
    skipped += admitted_not_selected
    items: list[ContextItem] = []
    used_families: set[str] = set()
    continuity_item_count = 0
    for candidate in ordered_candidates:
        if candidate.admission.candidate_id not in selected_ids:
            continue
        decision = decision_by_id[candidate.admission.candidate_id]
        continuity_only = candidate.admission.candidate_id in continuity_ids
        if continuity_only:
            continuity_item_count += 1
        if decision.relaxed:
            diagnostics["keyword_aggregation_relaxed_relevance_used"] = (
                int(diagnostics["keyword_aggregation_relaxed_relevance_used"]) + 1
            )
        if candidate.numeric_corroboration:
            diagnostics["keyword_aggregation_numeric_corroborations"] = (
                int(diagnostics["keyword_aggregation_numeric_corroborations"]) + 1
            )
        used_families.add(candidate.group)
        item = _chunk_context_item(
            chunk=candidate.chunk,
            text=_aggregation_evidence_text(
                query=candidate.aggregation_query,
                text=candidate.chunk_text,
                identity_terms=query_identity_terms,
                query_variant_sets=candidate.query_variant_sets,
            ),
            retrieval_source="keyword_aggregation_chunks",
            base_score=0.78,
            score=0.05 if continuity_only else 0.985,
            relevance=None if continuity_only else candidate.relevance,
            query_text=candidate.aggregation_query,
            query_expansion_reason=(
                "original_query" if continuity_only else candidate.aggregation_reason
            ),
            use_query_snippet=False,
        )
        items.append(
            _with_keyword_aggregation_score_signals(
                item,
                strict_hits=candidate.strict_hits,
                source_group=candidate.group,
                query_plan_slot=candidate.aggregation_reason,
                admission_reason=decision.reason.value,
                relaxed_admission=decision.relaxed,
                numeric_corroboration=candidate.numeric_corroboration,
                continuity_only=continuity_only,
            )
        )

    diagnostics["keyword_aggregation_chunks_used"] = len(items)
    diagnostics["keyword_aggregation_chunks_skipped"] = skipped
    diagnostics["keyword_aggregation_source_families_used"] = len(used_families)
    diagnostics["keyword_aggregation_continuity_items_used"] = continuity_item_count
    return tuple(items), diagnostics


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
    marker = _source_turn_marker(chunk.source_external_id)
    if marker is not None:
        return marker[0]
    source_id = " ".join(str(chunk.source_external_id).split())
    parts = source_id.split(":")
    if len(parts) >= 4 and parts[-1] in _SOURCE_GROUP_SUFFIXES:
        return ":".join(parts[:-1])
    return source_id or str(chunk.document_id or chunk.id)


def _aggregation_source_kind_rank(chunk: MemoryChunk) -> int:
    if _source_turn_marker(chunk.source_external_id) is not None:
        return 1
    parts = " ".join(str(chunk.source_external_id).split()).split(":")
    if parts and parts[-1] == "observation":
        return 0
    if parts and parts[-1] in {"events", "summary"}:
        return 3
    return 2
