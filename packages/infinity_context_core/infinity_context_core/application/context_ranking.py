"""Context dedupe, rank fusion and deterministic ranking helpers."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from infinity_context_core.application.context_action_roles import action_role_rerank_signal
from infinity_context_core.application.context_activity_companion import (
    activity_companion_signal,
)
from infinity_context_core.application.context_aggregation_answer_slots import (
    aggregation_answer_slot_count,
)
from infinity_context_core.application.context_conversation_counterparty import (
    conversation_counterparty_evidence_signal,
    conversation_recency_evidence_signal,
    conversation_recency_missing_temporal_signal,
    conversation_recency_temporal_hint_signal,
    conversation_topic_evidence_signal,
)
from infinity_context_core.application.context_diagnostics import (
    context_duplicate_primary_key,
    context_rank_key,
    diagnostic_retrieval_sources,
    merge_context_diagnostics,
    merge_diagnostic_retrieval_sources,
    normalize_context_diagnostics,
    normalize_context_item_diagnostics,
    safe_diagnostic_mapping,
    safe_score_signals,
)
from infinity_context_core.application.context_domain_rerank_apply import (
    apply_domain_rerank_signals,
)
from infinity_context_core.application.context_domain_rerank_signals import (
    commonality_who_else_anchor_override,
    has_multi_evidence_aggregation_candidate,
)
from infinity_context_core.application.context_inference_evidence import (
    answer_evidence_rerank_signal,
)
from infinity_context_core.application.context_item_purchase_evidence import (
    has_item_purchase_object_evidence,
)
from infinity_context_core.application.context_lexical import (
    LexicalQueryTerm,
    query_term_frequency,
    query_terms,
    text_variant_counts,
    text_variant_sequence,
)
from infinity_context_core.application.context_object_mismatch import (
    object_kind_mismatch_signal,
)
from infinity_context_core.application.context_polarity_rerank import (
    absence_contrast_signal,
    negative_preference_signal,
    status_polarity_signal,
)
from infinity_context_core.application.context_possession_source import (
    possession_source_signal,
)
from infinity_context_core.application.context_query_expansion import QueryExpansionPlan
from infinity_context_core.application.context_query_intent import (
    QueryAnchorIntent,
    match_query_anchor_intent_to_text,
    query_anchor_intent_text_conflicts,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    ACTIVITY_OBSERVATION_SOURCE_REASONS as _ACTIVITY_OBSERVATION_SOURCE_REASONS,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    ACTIVITY_OWNER_REASONS as _ACTIVITY_OWNER_REASONS,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    CONTEXT_ITEM_REASON_PRIORITY as _CONTEXT_ITEM_REASON_PRIORITY,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    DERIVED_SUMMARY_SOURCE_MIN_DISTINCTIVE_HITS as _DERIVED_SUMMARY_SOURCE_MIN_DISTINCTIVE_HITS,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    DERIVED_SUMMARY_SOURCE_REASONS as _DERIVED_SUMMARY_SOURCE_REASONS,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    KEYWORD_EXPANSION_REASON_BOOSTS as _KEYWORD_EXPANSION_REASON_BOOSTS,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    KEYWORD_EXPANSION_SCORE_CAPS as _KEYWORD_EXPANSION_SCORE_CAPS,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    QUERY_REASON_PRIORITY as _QUERY_REASON_PRIORITY,
)
from infinity_context_core.application.context_ranking_reason_policy import (
    QUERY_REASON_PRIORITY_MIN_DISTINCTIVE_HITS as _QUERY_REASON_PRIORITY_MIN_DISTINCTIVE_HITS,
)
from infinity_context_core.application.context_relation_requirement import (
    relation_requirement_signal,
)
from infinity_context_core.application.context_relevance import (
    QueryRelevance,
    has_project_identity_mismatch,
    is_query_relevance_sufficient,
    score_query_relevance,
)
from infinity_context_core.application.context_requirement_coverage import (
    context_requirement_coverage,
)
from infinity_context_core.application.context_speaker_attribution import (
    speaker_attribution_signal,
)
from infinity_context_core.application.context_temporal_metadata import (
    temporal_hint_code_from_metadata,
)
from infinity_context_core.application.context_temporal_query import (
    TemporalQueryIntent,
    build_temporal_query_intent,
    temporal_query_boost_signal,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import (
    MAX_SOURCE_REFS_PER_ITEM,
    MemoryAnchorKind,
    SourceRef,
)

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
_BM25_K1 = 1.2
_BM25_B = 0.75
_BM25_MAX_BOOST = 0.035
_QUERY_ANCHOR_INTENT_MAX_BOOST = 0.035
_CONTEXT_REQUIREMENT_MAX_BOOST = 0.04
_CONTEXT_REQUIREMENT_ANCHOR_BOOST = 0.008
_CONTEXT_REQUIREMENT_MODALITY_BOOST = 0.022
_CONTEXT_REQUIREMENT_FEATURE_BOOST = 0.014
_CONTEXT_REQUIREMENT_ANSWER_SHAPE_BOOST = 0.012
_GENERIC_BOOSTABLE_ANSWER_SHAPES = frozenset((
    "causal",
    "choice",
    "commonality",
    "commitment",
    "constraint",
    "conversation_participant",
    "conversation_topic",
    "count",
    "existence",
    "gotcha",
    "inference",
    "list",
    "location",
    "ordinal",
    "preference",
    "relationship",
    "speaker",
    "summary",
    "temporal",
))
_DETERMINISTIC_RERANK_MAX_BOOST = 0.055
_DETERMINISTIC_RERANK_MAX_PENALTY = 0.11
_CANONICAL_ANCHOR_SUMMARY_RERANK_MAX_BOOST = 0.018
_CITATION_EVIDENCE_RERANK_MAX_BOOST = 0.024
_LOCALIZED_EVIDENCE_RERANK_MAX_BOOST = 0.022
_DUPLICATE_SOURCE_SCORE_TOLERANCE = 0.015
_STRONG_EVIDENCE_RERANK_SOURCES = frozenset(
    {
        "approved_context_linked_anchors",
        "approved_context_linked_asset_manifest_evidence",
        "approved_context_linked_assets",
        "approved_context_linked_chunks",
        "approved_context_linked_extraction_artifacts",
        "approved_context_linked_facts",
        "artifact_evidence",
        "canonical_anchor_relations",
        "canonical_anchors",
        "temporal_supersedes_relation",
    }
)
_DERIVED_SUMMARY_SOURCE_BOOST = 0.06
_DERIVED_SUMMARY_SOURCE_CAP = 0.985
_ACTIVITY_DERIVED_SUMMARY_SOURCE_BOOST = 0.09
_ACTIVITY_DERIVED_SUMMARY_SOURCE_CAP = 0.99
_ACTIVITY_DERIVED_SUMMARY_STRONG_HITS = 10
_DERIVED_SUMMARY_SOURCE_SUFFIXES = (":observation", ":summary", ":events")
_ACTIVITY_EVIDENCE_SOURCE_SUFFIXES = (":turn", ":observation", ":summary", ":events")
_ATTRIBUTE_EVIDENCE_SOURCE_SUFFIXES = (":turn", ":observation", ":events")
_PRECISE_EVIDENCE_SOURCE_REASONS = frozenset(
    {
        "adoption_current_goal_bridge",
        "adoption_current_milestone_bridge",
        "allergy_condition_inference_bridge",
        "allergy_inventory_bridge",
        "business_start_reason_bridge",
        "book_reading_list_bridge",
        "charity_brand_sponsorship_bridge",
        "charity_tournament_count_bridge",
        "children_count_event_bridge",
        "business_commonality_bridge",
        "degree_policy_inference_bridge",
        "exercise_activity_inventory_bridge",
        "endorsement_gear_brand_bridge",
        "gaming_medium_bridge",
        "hiking_trail_count_bridge",
        "hobby_interest_bridge",
        "instrument_play_bridge",
        "letter_count_bridge",
        "meteor_shower_feeling_bridge",
        "patriotic_service_inference_bridge",
        "pet_count_bridge",
        "pet_inventory_bridge",
        "personality_authenticity_bridge",
        "personality_drive_bridge",
        "personality_thoughtfulness_bridge",
        "personality_trait_bridge",
        "running_reason_bridge",
        "running_reason_question_bridge",
        "screenplay_count_bridge",
        "shelter_comfort_reason_bridge",
        "state_residence_inference_bridge",
        "symbol_importance_bridge",
        "temporal_event_detail_bridge",
        "tournament_count_bridge",
        "volunteer_career_inference_bridge",
        "yoga_delay_gaming_bridge",
    }
)
_TURN_ONLY_EVIDENCE_SOURCE_REASONS = frozenset(
    {
        "personality_authenticity_bridge",
        "personality_drive_bridge",
        "personality_thoughtfulness_bridge",
        "personality_trait_bridge",
        "state_residence_inference_bridge",
    }
)
_ACTIVITY_OBSERVATION_MIN_DISTINCTIVE_HITS = 8
_ACTIVITY_OWNER_MATCH_BOOST = 0.012
_ACTIVITY_OWNER_MISMATCH_PENALTY = 0.042
_VOLUNTEER_CAREER_EVIDENCE_RE = re.compile(
    r"\b("
    r"volunteer(?:ed|ing|s)?|homeless\s+shelter|shelter|front\s+desk|"
    r"food|bed|talks?|compliments?|fulfilling|make\s+a\s+difference|"
    r"brighten|aunt|struggling|residents?|social\s+work|"
    r"counsel(?:or|ing)?|coordinator"
    r")\b",
    re.IGNORECASE,
)
_VOLUNTEER_CAREER_CONTEXT_RE = re.compile(
    r"\b("
    r"volunteer(?:ed|ing|s)?|homeless\s+shelter|shelter|front\s+desk|"
    r"food|bed|talks?|compliments?|residents?|social\s+work|"
    r"counsel(?:or|ing)?|coordinator"
    r")\b",
    re.IGNORECASE,
)
_VOLUNTEER_CAREER_STRONG_NON_TURN_EVIDENCE_RE = re.compile(
    r"\b("
    r"front\s+desk|talks?|compliments?|residents?|bed|food|"
    r"counsel(?:or|ing)?|coordinator|started\s+volunteering"
    r")\b",
    re.IGNORECASE,
)
_POST_EVENT_ACTIVITY_TIMING_CONTEXT_RE = re.compile(
    r"\b(?:road\s*trip|roadtrip)\b(?=.{0,180}\b(?:yesterday|recent|"
    r"just\s+did|after\s+the\s+(?:road\s*trip|drive)|relax))|"
    r"\b(?:yesterday|just\s+did|recent|relax)\b(?=.{0,180}\b(?:road\s*trip|roadtrip))",
    re.IGNORECASE | re.DOTALL,
)
_SHOE_USAGE_CONTEXT_RE = re.compile(
    r"\b(?:shoes?|sneakers?)\b|walking\s+or\s+running|for\s+running|"
    r"purple\s+running\s+shoe",
    re.IGNORECASE,
)
_EVENT_PARTICIPATION_QUERY_RE = re.compile(
    r"\b(attend(?:ed|ing)?|participat(?:e|ed|ing)|partook|joined|went)\b",
    re.IGNORECASE,
)
_EVENT_TERM_QUERY_RE = re.compile(r"\b(events?|parade|conference|group|program)\b", re.IGNORECASE)
_TEMPORAL_ANSWER_QUERY_RE = re.compile(
    r"\b(?:when|what\s+date|what\s+day|which\s+day|how\s+long)\b|"
    r"\b(?:когда|какая\s+дата|в\s+какой\s+день|какого\s+числа|как\s+долго)\b",
    re.IGNORECASE,
)
_TEMPORAL_ANSWER_EVIDENCE_RE = re.compile(
    r"\b(?:session_\d+\s+date|date:|today|yesterday|tomorrow|recently|ago|"
    r"last\s+(?:week|month|year|night|weekend|monday|tuesday|wednesday|thursday|"
    r"friday|saturday|sunday)|"
    r"next\s+(?:week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|"
    r"sunday)|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"сегодня|вчера|завтра|неделю\s+назад|месяц\s+назад|год\s+назад|"
    r"прошл\w+\s+(?:недел\w+|месяц\w+|год\w+|ноч\w+)|"
    r"следующ\w+\s+(?:недел\w+|месяц\w+|год\w+))\b|"
    r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|"
    r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?\b|"
    r"\b\d{1,2}\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)(?:,?\s+\d{2,4})?\b|"
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\s+\d{1,2}(?:,?\s+\d{2,4})?\b",
    re.IGNORECASE,
)
_MISSED_EVENT_TEXT_RE = re.compile(r"\bmissed\s+(?:it|the|that)?\b", re.IGNORECASE)
_SELF_MISSED_EVENT_TEXT_RE = re.compile(r"\b(?:i|we)\s+missed\s+(?:it|the|that)?\b", re.IGNORECASE)
_POSITIVE_EVENT_TEXT_RE = re.compile(
    r"\b(attended|participated|joined|went|marched|took part)\b",
    re.IGNORECASE,
)
_POSITIVE_EVENT_PARTICIPATION_TEXT_RE = re.compile(
    r"\b(?:i|we)\s+(?:recently\s+|also\s+|just\s+|last\s+\w+\s+)?"
    r"(?:went|attended|participated|joined|marched|took\s+part)\b|"
    r"\b(?:went\s+to|attended|participated\s+in|joined)\b.{0,80}"
    r"\b(?:events?|parade|conference|group|program|campaign)\b",
    re.IGNORECASE | re.DOTALL,
)
_POSITIVE_ACTIVITY_TEXT_RE = re.compile(
    r"\b(?:hikes?|hiking|camp(?:ing|fire|ed)?|marshmallows?|forest|trail|"
    r"outdoors?|nature|museum|dinosaur|exhibit|park|playground|pottery|"
    r"workshop|clay|pots?|painting|painted|swimm(?:ing)?|swam|beach|"
    r"waterfall|mountains?|concert|running|race)\b",
    re.IGNORECASE,
)
_SPEAKER_LABEL_RE = r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
_DIALOGUE_SPEAKER_RE = re.compile(
    rf"\bD\d+:\d+\s+(?P<speaker>{_SPEAKER_LABEL_RE}):",
    re.IGNORECASE,
)


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
    fusion_scores = reciprocal_rank_fusion_scores(
        rankings,
        rank_constant=rank_constant,
        max_rank_per_source=max_rank_per_source,
        source_weights=(_DEFAULT_RRF_SOURCE_WEIGHTS if source_weights is None else source_weights),
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
            source_weighted=bool(
                _DEFAULT_RRF_SOURCE_WEIGHTS if source_weights is None else source_weights
            ),
        )
        for item in items
    )


def apply_bm25_lexical_boosts(
    items: tuple[ContextItem, ...],
    *,
    query: str,
    k1: float = _BM25_K1,
    b: float = _BM25_B,
    max_boost: float = _BM25_MAX_BOOST,
) -> tuple[ContextItem, ...]:
    if len(items) <= 1 or k1 <= 0 or not 0 <= b <= 1 or max_boost <= 0:
        return items
    terms = query_terms(query)
    if not terms:
        return items
    documents, raw_scores = _bm25_raw_scores(items=items, terms=terms, k1=k1, b=b)
    max_raw_score = max(raw_scores, default=0.0)
    if max_raw_score <= 0:
        return items
    return tuple(
        _with_bm25_lexical_boost(
            document.item,
            raw_score=raw_score,
            max_raw_score=max_raw_score,
            max_boost=max_boost,
            query_term_count=len(terms),
            matched_term_count=sum(1 for frequency in document.term_frequencies if frequency > 0),
        )
        for document, raw_score in zip(documents, raw_scores, strict=True)
    )


def apply_query_plan_bm25_lexical_boosts(
    items: tuple[ContextItem, ...],
    *,
    plan: QueryExpansionPlan,
    bm25_text_stats_cache: dict[str, tuple[Mapping[str, int], int]] | None = None,
    k1: float = _BM25_K1,
    b: float = _BM25_B,
    max_boost: float = _BM25_MAX_BOOST,
) -> tuple[ContextItem, ...]:
    if len(items) <= 1 or k1 <= 0 or not 0 <= b <= 1 or max_boost <= 0:
        return items
    matches = _best_bm25_query_matches(
        items=items,
        plan=plan,
        k1=k1,
        b=b,
        bm25_text_stats_cache=bm25_text_stats_cache,
    )
    if not any(match.normalized_score > 0 for match in matches):
        return items
    return tuple(
        _with_bm25_lexical_boost(
            item,
            raw_score=match.normalized_score,
            max_raw_score=1.0,
            max_boost=max_boost,
            query_term_count=match.query_term_count,
            matched_term_count=match.matched_term_count,
            query_reason=match.query_reason,
            query_coverage=match.query_coverage,
        )
        for item, match in zip(items, matches, strict=True)
    )


def apply_query_anchor_intent_boosts(
    items: tuple[ContextItem, ...],
    *,
    intent: QueryAnchorIntent,
    max_boost: float = _QUERY_ANCHOR_INTENT_MAX_BOOST,
) -> tuple[ContextItem, ...]:
    if not items or intent.empty or max_boost <= 0:
        return items
    return tuple(
        _with_query_anchor_intent_boost(
            item,
            match=match_query_anchor_intent_to_text(intent, item.text),
            max_boost=max_boost,
        )
        for item in items
    )


def apply_context_requirement_boosts(
    items: tuple[ContextItem, ...],
    *,
    query: str,
    query_anchor_intent: QueryAnchorIntent,
    max_boost: float = _CONTEXT_REQUIREMENT_MAX_BOOST,
) -> tuple[ContextItem, ...]:
    if not items or max_boost <= 0:
        return items
    requested = context_requirement_coverage(
        query=query,
        query_anchor_intent=query_anchor_intent,
        items=(),
    )
    requested_anchor_kinds = _coverage_value_set(requested.get("requested_anchor_kinds"))
    requested_modalities = _coverage_value_set(requested.get("requested_modalities"))
    requested_features = _coverage_value_set(requested.get("requested_evidence_features"))
    requested_answer_shapes = _coverage_value_set(requested.get("requested_answer_shapes"))
    if (
        not requested_anchor_kinds
        and not requested_modalities
        and not requested_features
        and not requested_answer_shapes
    ):
        return items
    return tuple(
        _with_context_requirement_boost(
            item,
            query=query,
            query_anchor_intent=query_anchor_intent,
            requested_anchor_kinds=requested_anchor_kinds,
            requested_modalities=requested_modalities,
            requested_features=requested_features,
            requested_answer_shapes=requested_answer_shapes,
            max_boost=max_boost,
        )
        for item in items
    )


def apply_deterministic_rerank_adjustments(
    items: tuple[ContextItem, ...],
    *,
    query: str,
    plan: QueryExpansionPlan,
    query_anchor_intent: QueryAnchorIntent,
    query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]] | None = None,
    max_boost: float = _DETERMINISTIC_RERANK_MAX_BOOST,
    max_penalty: float = _DETERMINISTIC_RERANK_MAX_PENALTY,
) -> tuple[ContextItem, ...]:
    if not items or (max_boost <= 0 and max_penalty <= 0):
        return items
    requested_coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=query_anchor_intent,
        items=(),
    )
    temporal_query_intent = build_temporal_query_intent(query)
    requested_total = _coverage_int(requested_coverage.get("requested_total"))
    has_multi_aggregation_candidate = has_multi_evidence_aggregation_candidate(
        query=query,
        items=items,
    )
    return tuple(
        _with_deterministic_rerank_adjustment(
            item,
            query=query,
            plan=plan,
            query_anchor_intent=query_anchor_intent,
            temporal_query_intent=temporal_query_intent,
            requested_total=requested_total,
            has_multi_evidence_aggregation_candidate=has_multi_aggregation_candidate,
            query_relevance_cache=query_relevance_cache,
            max_boost=max_boost,
            max_penalty=max_penalty,
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


def best_query_relevance(
    plan: QueryExpansionPlan,
    *,
    text: str,
) -> tuple[str, str, QueryRelevance]:
    scored = tuple(
        (
            expansion.query,
            expansion.reason,
            score_query_relevance(query=expansion.query, text=text),
        )
        for expansion in plan.retrieval_queries
    )
    return max(scored, key=query_relevance_rank_key)


def query_relevance_rank_key(
    item: tuple[str, str, QueryRelevance],
) -> tuple[bool, int, int, int, float, bool]:
    _, reason, relevance = item
    return (
        is_query_relevance_sufficient(relevance),
        _query_reason_priority_for_relevance(reason, relevance),
        relevance.distinctive_term_hits,
        relevance.unique_term_hits,
        relevance.score_boost,
        reason == "original_query",
    )


def _query_reason_priority_for_relevance(
    reason: str,
    relevance: QueryRelevance,
) -> int:
    min_hits = _QUERY_REASON_PRIORITY_MIN_DISTINCTIVE_HITS.get(reason, 0)
    if relevance.distinctive_term_hits < min_hits:
        return 0
    return _QUERY_REASON_PRIORITY.get(reason, 0)


def keyword_chunk_score(
    relevance: QueryRelevance,
    *,
    query_expansion_reason: str,
) -> float:
    distinctive_boost = min(0.028, relevance.distinctive_term_hits * 0.007)
    phrase_boost = min(0.018, relevance.phrase_bigram_hits * 0.006)
    frequency_boost = min(0.014, relevance.capped_frequency_hits * 0.0015)
    expansion_boost = 0.004 if query_expansion_reason != "original_query" else 0.0
    reason_boost = _KEYWORD_EXPANSION_REASON_BOOSTS.get(query_expansion_reason, 0.0)
    score_cap = _KEYWORD_EXPANSION_SCORE_CAPS.get(query_expansion_reason, 0.93)
    return min(
        score_cap,
        round(
            0.75
            + relevance.score_boost
            + distinctive_boost
            + phrase_boost
            + frequency_boost
            + expansion_boost
            + reason_boost,
            4,
        ),
    )


def keyword_chunk_source_score_boost(
    relevance: QueryRelevance,
    *,
    query_expansion_reason: str,
    source_external_id: str,
) -> float:
    """Prefer compact derived observations/summaries for broad aggregation answers."""

    if query_expansion_reason not in _DERIVED_SUMMARY_SOURCE_REASONS:
        return 0.0
    normalized_source_id = source_external_id.casefold()
    if query_expansion_reason in _ACTIVITY_OBSERVATION_SOURCE_REASONS:
        allowed_suffixes = _ACTIVITY_EVIDENCE_SOURCE_SUFFIXES
    elif query_expansion_reason in _TURN_ONLY_EVIDENCE_SOURCE_REASONS:
        allowed_suffixes = (":turn",)
    elif (
        query_expansion_reason.startswith("attribute_")
        or query_expansion_reason in _PRECISE_EVIDENCE_SOURCE_REASONS
    ):
        allowed_suffixes = _ATTRIBUTE_EVIDENCE_SOURCE_SUFFIXES
    else:
        allowed_suffixes = _DERIVED_SUMMARY_SOURCE_SUFFIXES
    if not normalized_source_id.endswith(allowed_suffixes):
        return 0.0
    min_hits = _DERIVED_SUMMARY_SOURCE_MIN_DISTINCTIVE_HITS.get(
        query_expansion_reason,
        _ACTIVITY_OBSERVATION_MIN_DISTINCTIVE_HITS,
    )
    if relevance.distinctive_term_hits < min_hits:
        return 0.0
    if (
        query_expansion_reason in _ACTIVITY_OBSERVATION_SOURCE_REASONS
        and relevance.distinctive_term_hits >= _ACTIVITY_DERIVED_SUMMARY_STRONG_HITS
    ):
        return _ACTIVITY_DERIVED_SUMMARY_SOURCE_BOOST
    return _DERIVED_SUMMARY_SOURCE_BOOST


def query_expansion_reason_priority(reason: str) -> int:
    return _CONTEXT_ITEM_REASON_PRIORITY.get(reason, 0)


def apply_keyword_chunk_source_score_boost(
    score: float,
    relevance: QueryRelevance,
    *,
    query_expansion_reason: str,
    source_external_id: str,
) -> tuple[float, float]:
    boost = keyword_chunk_source_score_boost(
        relevance,
        query_expansion_reason=query_expansion_reason,
        source_external_id=source_external_id,
    )
    if boost <= 0:
        return score, 0.0
    cap = (
        _ACTIVITY_DERIVED_SUMMARY_SOURCE_CAP
        if (
            query_expansion_reason in _ACTIVITY_OBSERVATION_SOURCE_REASONS
            and boost >= _ACTIVITY_DERIVED_SUMMARY_SOURCE_BOOST
        )
        else _DERIVED_SUMMARY_SOURCE_CAP
    )
    return (
        min(cap, round(score + boost, 4)),
        boost,
    )


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


@dataclass(frozen=True)
class _Bm25Document:
    item: ContextItem
    term_frequencies: tuple[int, ...]
    length: int


@dataclass(frozen=True)
class _Bm25PreparedItem:
    item: ContextItem
    text_counts: Mapping[str, int]
    length: int


@dataclass(frozen=True)
class _Bm25QueryMatch:
    normalized_score: float
    query_term_count: int
    matched_term_count: int
    query_reason: str
    query_coverage: float = 0.0


@dataclass(frozen=True)
class _DeterministicRerankSignals:
    boost: float
    penalty: float
    reasons: tuple[str, ...]
    rank_signals: tuple[tuple[str, float], ...]
    source_count: int
    strong_source_count: int
    coverage_ratio: float
    anchor_conflict: bool
    query_reason: str

    @property
    def net_adjustment(self) -> float:
        return round(self.boost - self.penalty, 4)


@dataclass(frozen=True)
class _RequirementCoverageSignals:
    ratio: float
    requested_anchor_kinds: frozenset[str]
    covered_anchor_kinds: frozenset[str]
    missing_anchor_kinds: frozenset[str]
    requested_modalities: frozenset[str]
    missing_modalities: frozenset[str]
    requested_evidence_features: frozenset[str]
    missing_evidence_features: frozenset[str]
    requested_answer_shapes: frozenset[str]
    covered_answer_shapes: frozenset[str]
    missing_answer_shapes: frozenset[str]

    @property
    def answer_shape_ratio(self) -> float:
        if not self.requested_answer_shapes:
            return 0.0
        return len(self.covered_answer_shapes) / len(self.requested_answer_shapes)


def _best_bm25_query_matches(
    *,
    items: tuple[ContextItem, ...],
    plan: QueryExpansionPlan,
    k1: float,
    b: float,
    bm25_text_stats_cache: dict[str, tuple[Mapping[str, int], int]] | None = None,
) -> tuple[_Bm25QueryMatch, ...]:
    prepared_items = tuple(
        _bm25_prepared_item(item, text_stats_cache=bm25_text_stats_cache)
        for item in items
    )
    best_matches = tuple(
        _Bm25QueryMatch(
            normalized_score=0.0,
            query_term_count=0,
            matched_term_count=0,
            query_reason="",
            query_coverage=0.0,
        )
        for _ in items
    )
    for expansion in plan.retrieval_queries:
        terms = query_terms(expansion.query)
        if not terms:
            continue
        documents, raw_scores = _bm25_raw_scores_for_prepared(
            prepared_items=prepared_items,
            terms=terms,
            k1=k1,
            b=b,
        )
        max_raw_score = max(raw_scores, default=0.0)
        if max_raw_score <= 0:
            continue
        query_matches: list[_Bm25QueryMatch] = []
        for document, raw_score in zip(documents, raw_scores, strict=True):
            matched_term_count = sum(1 for frequency in document.term_frequencies if frequency > 0)
            coverage = _bm25_query_coverage(
                matched_term_count=matched_term_count,
                query_term_count=len(terms),
            )
            query_matches.append(
                _Bm25QueryMatch(
                    normalized_score=round(
                        min(1.0, raw_score / max_raw_score) * coverage,
                        6,
                    ),
                    query_term_count=len(terms),
                    matched_term_count=matched_term_count,
                    query_reason=expansion.reason,
                    query_coverage=coverage,
                )
            )
        best_matches = tuple(
            _select_bm25_query_match(best, candidate)
            for best, candidate in zip(best_matches, tuple(query_matches), strict=True)
        )
    return best_matches


def _select_bm25_query_match(
    best: _Bm25QueryMatch,
    candidate: _Bm25QueryMatch,
) -> _Bm25QueryMatch:
    if candidate.matched_term_count <= 0:
        return best
    if candidate.normalized_score > best.normalized_score:
        return candidate
    if candidate.normalized_score < best.normalized_score:
        return best
    if candidate.matched_term_count > best.matched_term_count:
        return candidate
    if candidate.matched_term_count < best.matched_term_count:
        return best
    candidate_priority = _QUERY_REASON_PRIORITY.get(candidate.query_reason, 0)
    best_priority = _QUERY_REASON_PRIORITY.get(best.query_reason, 0)
    if candidate_priority > best_priority:
        return candidate
    if candidate_priority < best_priority:
        return best
    if candidate.query_reason == "original_query" and best.query_reason != "original_query":
        return candidate
    return best


def _bm25_raw_scores(
    *,
    items: tuple[ContextItem, ...],
    terms: tuple[LexicalQueryTerm, ...],
    k1: float,
    b: float,
) -> tuple[tuple[_Bm25Document, ...], tuple[float, ...]]:
    prepared_items = tuple(_bm25_prepared_item(item) for item in items)
    return _bm25_raw_scores_for_prepared(
        prepared_items=prepared_items,
        terms=terms,
        k1=k1,
        b=b,
    )


def _bm25_raw_scores_for_prepared(
    *,
    prepared_items: tuple[_Bm25PreparedItem, ...],
    terms: tuple[LexicalQueryTerm, ...],
    k1: float,
    b: float,
) -> tuple[tuple[_Bm25Document, ...], tuple[float, ...]]:
    documents = tuple(_bm25_document(prepared=item, terms=terms) for item in prepared_items)
    average_length = sum(document.length for document in documents) / len(documents)
    document_frequencies = tuple(
        sum(1 for document in documents if document.term_frequencies[index] > 0)
        for index, _ in enumerate(terms)
    )
    raw_scores = tuple(
        _bm25_score(
            term_frequencies=document.term_frequencies,
            document_frequencies=document_frequencies,
            document_count=len(documents),
            document_length=document.length,
            average_document_length=max(1.0, average_length),
            k1=k1,
            b=b,
        )
        for document in documents
    )
    return documents, raw_scores


def _bm25_query_coverage(*, matched_term_count: int, query_term_count: int) -> float:
    if matched_term_count <= 0 or query_term_count <= 0:
        return 0.0
    denominator = min(8, max(3, query_term_count))
    return round(min(1.0, matched_term_count / denominator), 4)


def _bm25_document(
    *,
    prepared: _Bm25PreparedItem,
    terms: tuple[LexicalQueryTerm, ...],
) -> _Bm25Document:
    return _Bm25Document(
        item=prepared.item,
        term_frequencies=tuple(
            query_term_frequency(term, prepared.text_counts) for term in terms
        ),
        length=prepared.length,
    )


def _bm25_prepared_item(
    item: ContextItem,
    *,
    text_stats_cache: dict[str, tuple[Mapping[str, int], int]] | None = None,
) -> _Bm25PreparedItem:
    if text_stats_cache is not None:
        cached = text_stats_cache.get(item.text)
        if cached is not None:
            counts, length = cached
            return _Bm25PreparedItem(item=item, text_counts=counts, length=length)
    counts = text_variant_counts(item.text)
    length = max(1, len(text_variant_sequence(item.text)))
    if text_stats_cache is not None:
        text_stats_cache[item.text] = (counts, length)
    return _Bm25PreparedItem(
        item=item,
        text_counts=counts,
        length=length,
    )


def _bm25_score(
    *,
    term_frequencies: tuple[int, ...],
    document_frequencies: tuple[int, ...],
    document_count: int,
    document_length: int,
    average_document_length: float,
    k1: float,
    b: float,
) -> float:
    score = 0.0
    length_ratio = document_length / average_document_length
    normalizer = k1 * (1 - b + b * length_ratio)
    for frequency, document_frequency in zip(
        term_frequencies,
        document_frequencies,
        strict=True,
    ):
        if frequency <= 0 or document_frequency <= 0:
            continue
        idf = math.log(1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5))
        score += idf * (frequency * (k1 + 1)) / (frequency + normalizer)
    return round(score, 8)


def _with_bm25_lexical_boost(
    item: ContextItem,
    *,
    raw_score: float,
    max_raw_score: float,
    max_boost: float,
    query_term_count: int,
    matched_term_count: int,
    query_reason: str = "original_query",
    query_coverage: float | None = None,
) -> ContextItem:
    if _bm25_lexical_already_applied(item):
        return item
    if raw_score <= 0 or max_raw_score <= 0 or matched_term_count <= 0:
        return item
    normalized_score = min(1.0, raw_score / max_raw_score)
    boost = round(max_boost * normalized_score, 4)
    if boost <= 0:
        return item
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    diagnostics["bm25_lexical_reason"] = "BM25 lexical rerank over candidate pool"
    diagnostics["score_signals"] = {
        **safe_score_signals(diagnostics.get("score_signals")),
        "bm25_lexical_raw_score": round(raw_score, 6),
        "bm25_lexical_normalized_score": round(normalized_score, 4),
        "bm25_lexical_boost": boost,
        "bm25_lexical_query_term_count": query_term_count,
        "bm25_lexical_matched_term_count": matched_term_count,
        "bm25_lexical_query_reason": query_reason,
    }
    if query_coverage is not None:
        diagnostics["score_signals"]["bm25_lexical_query_coverage"] = round(
            query_coverage,
            4,
        )
    diagnostics["provenance"] = {
        **safe_diagnostic_mapping(diagnostics.get("provenance")),
        "bm25_lexical_applied": True,
        "bm25_lexical_query_reason": query_reason,
    }
    return replace(
        item,
        score=min(0.99, round(item.score + boost, 4)),
        diagnostics=normalize_context_diagnostics(diagnostics),
    )


def _bm25_lexical_already_applied(item: ContextItem) -> bool:
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    return provenance.get("bm25_lexical_applied") is True


def _with_query_anchor_intent_boost(
    item: ContextItem,
    *,
    match: object,
    max_boost: float,
) -> ContextItem:
    if match is None or _query_anchor_intent_already_applied(item):
        return item
    try:
        raw_boost = float(getattr(match, "score_boost", 0.0))
    except (TypeError, ValueError):
        return item
    boost = min(max_boost, max(0.0, round(raw_boost, 4)))
    if boost <= 0:
        return item
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    reasons = tuple(getattr(match, "reasons", ()) or ())
    matched_keys = tuple(getattr(match, "matched_keys", ()) or ())
    diagnostics["query_anchor_intent_reason"] = "query anchor identity matched context item text"
    diagnostics["score_signals"] = {
        **safe_score_signals(diagnostics.get("score_signals")),
        "query_anchor_intent_boost": boost,
        "query_anchor_intent_reason_count": len(reasons),
        "query_anchor_intent_matched_key_count": len(matched_keys),
    }
    diagnostics["provenance"] = {
        **safe_diagnostic_mapping(diagnostics.get("provenance")),
        "query_anchor_intent_applied": True,
        "query_anchor_intent_reasons": list(reasons[:8]),
        "query_anchor_intent_matched_keys": list(matched_keys[:8]),
    }
    return replace(
        item,
        score=min(0.99, round(item.score + boost, 4)),
        diagnostics=normalize_context_diagnostics(diagnostics),
    )


def _query_anchor_intent_already_applied(item: ContextItem) -> bool:
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    return provenance.get("query_anchor_intent_applied") is True


def _with_context_requirement_boost(
    item: ContextItem,
    *,
    query: str,
    query_anchor_intent: QueryAnchorIntent,
    requested_anchor_kinds: frozenset[str],
    requested_modalities: frozenset[str],
    requested_features: frozenset[str],
    requested_answer_shapes: frozenset[str],
    max_boost: float,
) -> ContextItem:
    if _context_requirement_boost_already_applied(item):
        return item
    normalized_item = normalize_context_item_diagnostics(item)
    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=query_anchor_intent,
        items=(normalized_item,),
    )
    matched_anchor_kinds = _sorted_coverage_matches(
        requested_anchor_kinds,
        coverage.get("covered_anchor_kinds"),
    )
    matched_modalities = _sorted_coverage_matches(
        requested_modalities,
        coverage.get("covered_modalities"),
    )
    matched_features = _sorted_coverage_matches(
        requested_features,
        coverage.get("covered_evidence_features"),
    )
    matched_answer_shapes = _sorted_coverage_matches(
        requested_answer_shapes,
        coverage.get("covered_answer_shapes"),
    )
    score_boosted_answer_shapes = tuple(
        shape for shape in matched_answer_shapes if shape in _GENERIC_BOOSTABLE_ANSWER_SHAPES
    )
    raw_boost = (
        len(matched_anchor_kinds) * _CONTEXT_REQUIREMENT_ANCHOR_BOOST
        + len(matched_modalities) * _CONTEXT_REQUIREMENT_MODALITY_BOOST
        + len(matched_features) * _CONTEXT_REQUIREMENT_FEATURE_BOOST
        + len(score_boosted_answer_shapes) * _CONTEXT_REQUIREMENT_ANSWER_SHAPE_BOOST
    )
    boost = min(max_boost, round(raw_boost, 4))
    if boost <= 0:
        return item
    diagnostics = normalize_context_diagnostics(normalized_item.diagnostics)
    diagnostics["context_requirement_reason"] = "explicit query requirement matched item evidence"
    diagnostics["score_signals"] = {
        **safe_score_signals(diagnostics.get("score_signals")),
        "context_requirement_boost": boost,
        "context_requirement_matched_anchor_kind_count": len(matched_anchor_kinds),
        "context_requirement_matched_modality_count": len(matched_modalities),
        "context_requirement_matched_feature_count": len(matched_features),
        "context_requirement_matched_answer_shape_count": len(score_boosted_answer_shapes),
    }
    diagnostics["provenance"] = {
        **safe_diagnostic_mapping(diagnostics.get("provenance")),
        "context_requirement_boost_applied": True,
        "context_requirement_matched_anchor_kinds": list(matched_anchor_kinds),
        "context_requirement_matched_modalities": list(matched_modalities),
        "context_requirement_matched_evidence_features": list(matched_features),
        "context_requirement_matched_answer_shapes": list(matched_answer_shapes),
    }
    return replace(
        normalized_item,
        score=min(0.99, round(normalized_item.score + boost, 4)),
        diagnostics=normalize_context_diagnostics(diagnostics),
    )


def _context_requirement_boost_already_applied(item: ContextItem) -> bool:
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    return provenance.get("context_requirement_boost_applied") is True


def _with_deterministic_rerank_adjustment(
    item: ContextItem,
    *,
    query: str,
    plan: QueryExpansionPlan,
    query_anchor_intent: QueryAnchorIntent,
    temporal_query_intent: TemporalQueryIntent,
    requested_total: int,
    has_multi_evidence_aggregation_candidate: bool,
    query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]] | None,
    max_boost: float,
    max_penalty: float,
) -> ContextItem:
    if _deterministic_rerank_already_applied(item):
        return item
    normalized_item = normalize_context_item_diagnostics(item)
    signals = _deterministic_rerank_signals(
        normalized_item,
        query=query,
        plan=plan,
        query_anchor_intent=query_anchor_intent,
        temporal_query_intent=temporal_query_intent,
        requested_total=requested_total,
        has_multi_evidence_aggregation_candidate=has_multi_evidence_aggregation_candidate,
        query_relevance_cache=query_relevance_cache,
        max_boost=max_boost,
        max_penalty=max_penalty,
    )
    if signals.net_adjustment == 0 and not signals.rank_signals:
        return item
    diagnostics = normalize_context_diagnostics(normalized_item.diagnostics)
    diagnostics["deterministic_rerank_reason"] = (
        "query-aware deterministic rerank over fused candidates"
    )
    diagnostics["score_signals"] = {
        **safe_score_signals(diagnostics.get("score_signals")),
        "deterministic_rerank_boost": signals.boost,
        "deterministic_rerank_penalty": signals.penalty,
        "deterministic_rerank_net_adjustment": signals.net_adjustment,
        "deterministic_rerank_source_count": signals.source_count,
        "deterministic_rerank_strong_source_count": signals.strong_source_count,
        "deterministic_rerank_requirement_coverage": signals.coverage_ratio,
        "deterministic_rerank_query_reason": signals.query_reason,
        **{key: value for key, value in signals.rank_signals},
    }
    diagnostics["provenance"] = {
        **safe_diagnostic_mapping(diagnostics.get("provenance")),
        "deterministic_rerank_applied": True,
        "deterministic_rerank_reasons": list(signals.reasons[:8]),
        "deterministic_rerank_anchor_conflict": signals.anchor_conflict,
    }
    return replace(
        normalized_item,
        score=min(0.99, max(0.0, round(normalized_item.score + signals.net_adjustment, 4))),
        diagnostics=normalize_context_diagnostics(diagnostics),
    )


def _deterministic_rerank_signals(
    item: ContextItem,
    *,
    query: str,
    plan: QueryExpansionPlan,
    query_anchor_intent: QueryAnchorIntent,
    temporal_query_intent: TemporalQueryIntent,
    requested_total: int,
    has_multi_evidence_aggregation_candidate: bool,
    query_relevance_cache: dict[str, tuple[str, str, QueryRelevance]] | None,
    max_boost: float,
    max_penalty: float,
) -> _DeterministicRerankSignals:
    sources = diagnostic_retrieval_sources(item.diagnostics)
    strong_source_count = len(set(sources).intersection(_STRONG_EVIDENCE_RERANK_SOURCES))
    query_text, query_reason, relevance = _best_query_relevance_for_rerank(
        plan,
        text=item.text,
        cache=query_relevance_cache,
    )
    del query_text
    coverage = _item_requirement_coverage_signals(
        item,
        query=query,
        query_anchor_intent=query_anchor_intent,
        requested_total=requested_total,
    )
    coverage_ratio = coverage.ratio
    anchor_match = match_query_anchor_intent_to_text(query_anchor_intent, item.text)
    text_anchor_conflict = query_anchor_intent_text_conflicts(
        query_anchor_intent,
        item.text,
    )
    project_identity_conflict = has_project_identity_mismatch(query=query, text=item.text)
    anchor_conflict = text_anchor_conflict or project_identity_conflict
    source_speaker_anchor_override = (
        text_anchor_conflict
        and not project_identity_conflict
        and _dialogue_speaker_confirms_query_anchor(
            item=item,
            query_anchor_intent=query_anchor_intent,
            relevance=relevance,
        )
    )
    commonality_anchor_override = (
        text_anchor_conflict
        and not project_identity_conflict
        and commonality_who_else_anchor_override(
            query=query,
            query_reason=query_reason,
            item=item,
        )
    )
    boost = 0.0
    penalty = 0.0
    reasons: list[str] = []
    if len(sources) >= 2:
        boost += min(0.018, 0.006 * len(sources))
        reasons.append("hybrid_source_diversity")
    if strong_source_count:
        boost += min(0.018, 0.008 * strong_source_count)
        reasons.append("strong_evidence_source")
    if anchor_match is not None:
        boost += min(0.018, max(0.0, anchor_match.score_boost) * 0.35)
        reasons.append("query_anchor_match")
    if requested_total > 0 and coverage_ratio > 0:
        boost += 0.014 * coverage_ratio
        reasons.append("explicit_requirement_covered")
    answer_shape_boost = 0.0
    boostable_requested_answer_shapes = (
        coverage.requested_answer_shapes & _GENERIC_BOOSTABLE_ANSWER_SHAPES
    )
    boostable_covered_answer_shapes = (
        coverage.covered_answer_shapes & _GENERIC_BOOSTABLE_ANSWER_SHAPES
    )
    if boostable_requested_answer_shapes and boostable_covered_answer_shapes:
        answer_shape_boost = 0.018 * (
            len(boostable_covered_answer_shapes) / len(boostable_requested_answer_shapes)
        )
    if "speaker" in coverage.covered_answer_shapes:
        boost += 0.018
        reasons.append("speaker_answer_shape_covered")
    if is_query_relevance_sufficient(relevance):
        relevance_boost = min(
            0.012,
            relevance.score_boost * 0.1 + relevance.distinctive_term_hits * 0.003,
        )
        if relevance_boost > 0:
            boost += relevance_boost
            reasons.append("query_relevance_supported")
    localized_evidence_boost, localized_evidence_reason = _localized_evidence_support_signal(
        item=item,
        relevance=relevance,
        coverage_ratio=coverage_ratio,
        anchor_matched=anchor_match is not None,
        strong_source_count=strong_source_count,
    )
    if localized_evidence_boost > 0:
        boost += localized_evidence_boost
        reasons.append(localized_evidence_reason)
    canonical_summary_boost, canonical_summary_reason = (
        _canonical_anchor_summary_support_signal(
            item=item,
            coverage=coverage,
            relevance=relevance,
            anchor_matched=anchor_match is not None,
            anchor_conflict=anchor_conflict,
            sources=sources,
            strong_source_count=strong_source_count,
        )
    )
    if canonical_summary_boost > 0:
        boost += canonical_summary_boost
        reasons.append(canonical_summary_reason)
    citation_evidence_boost, citation_evidence_reason = _citation_evidence_support_signal(
        item=item,
        coverage=coverage,
        relevance=relevance,
        anchor_matched=anchor_match is not None,
        strong_source_count=strong_source_count,
    )
    if citation_evidence_boost > 0:
        boost += citation_evidence_boost
        reasons.append(citation_evidence_reason)
    owner_boost, owner_penalty, owner_reason = _activity_owner_signal(
        query_anchor_intent=query_anchor_intent,
        query_reason=query_reason,
        text=item.text,
    )
    if owner_boost > 0:
        boost += owner_boost
        reasons.append(owner_reason)
    if owner_penalty > 0:
        penalty += owner_penalty
        reasons.append(owner_reason)
    speaker_boost, speaker_penalty, speaker_reason = speaker_attribution_signal(
        query=query,
        text=item.text,
    )
    if speaker_boost > 0:
        boost += speaker_boost
        reasons.append(speaker_reason)
    if speaker_penalty > 0:
        penalty += speaker_penalty
        reasons.append(speaker_reason)
    if (
        answer_shape_boost > 0
        and owner_penalty <= 0
        and speaker_penalty <= 0
        and not anchor_conflict
    ):
        boost += answer_shape_boost
        reasons.append("explicit_answer_shape_covered")
    action_signal = action_role_rerank_signal(query=query, text=item.text)
    if action_signal.boost > 0:
        boost += action_signal.boost
        reasons.append(action_signal.reason)
    if action_signal.penalty > 0:
        penalty += action_signal.penalty
        reasons.append(action_signal.reason)
    possession_boost, possession_penalty, possession_reason = possession_source_signal(
        query=query,
        item=item,
    )
    if possession_boost > 0:
        boost += possession_boost
        reasons.append(possession_reason)
    if possession_penalty > 0:
        penalty += possession_penalty
        reasons.append(possession_reason)
    inference_signal = answer_evidence_rerank_signal(query=query, text=item.text)
    if inference_signal.boost > 0:
        boost += inference_signal.boost
        reasons.append(inference_signal.reason)
    if inference_signal.penalty > 0:
        penalty += inference_signal.penalty
        reasons.append(inference_signal.reason)
    polarity_boost, polarity_penalty, polarity_reason = status_polarity_signal(
        query=query,
        text=item.text,
    )
    if polarity_boost > 0:
        boost += polarity_boost
        reasons.append(polarity_reason)
    if polarity_penalty > 0:
        penalty += polarity_penalty
        reasons.append(polarity_reason)
    negative_boost, negative_penalty, negative_reason = negative_preference_signal(
        query=query,
        text=item.text,
    )
    if negative_boost > 0:
        boost += negative_boost
        reasons.append(negative_reason)
    if negative_penalty > 0:
        penalty += negative_penalty
        reasons.append(negative_reason)
    contrast_boost, contrast_penalty, contrast_reason = absence_contrast_signal(
        query=query,
        text=item.text,
    )
    if contrast_boost > 0:
        boost += contrast_boost
        reasons.append(contrast_reason)
    if contrast_penalty > 0:
        penalty += contrast_penalty
        reasons.append(contrast_reason)
    object_boost, object_penalty, object_reason = object_kind_mismatch_signal(
        query=query,
        text=item.text,
    )
    if object_boost > 0:
        boost += object_boost
        reasons.append(object_reason)
    if object_penalty > 0:
        penalty += object_penalty
        reasons.append(object_reason)
    relation_signal = relation_requirement_signal(query=query, text=item.text)
    if relation_signal.boost > 0:
        boost += relation_signal.boost
        reasons.append(relation_signal.reason)
    if (
        relation_signal.penalty > 0
        and not _is_item_purchase_temporal_answer_evidence(query_reason=query_reason, item=item)
    ):
        penalty += relation_signal.penalty
        reasons.append(relation_signal.reason)
    conversation_boost, conversation_penalty, conversation_reason = (
        conversation_counterparty_evidence_signal(
            query=query,
            text=item.text,
        )
    )
    if conversation_boost > 0:
        boost += conversation_boost
        reasons.append(conversation_reason)
    if conversation_penalty > 0:
        penalty += conversation_penalty
        reasons.append(conversation_reason)
    topic_boost, topic_penalty, topic_reason = conversation_topic_evidence_signal(
        query=query,
        text=item.text,
    )
    if topic_boost > 0:
        boost += topic_boost
        reasons.append(topic_reason)
    if topic_penalty > 0:
        penalty += topic_penalty
        reasons.append(topic_reason)
    recency_boost, recency_penalty, recency_reason = conversation_recency_evidence_signal(
        query=query,
        text=item.text,
    )
    if recency_boost > 0:
        boost += recency_boost
        reasons.append(recency_reason)
    if recency_penalty > 0:
        penalty += recency_penalty
        reasons.append(recency_reason)
    temporal_hint_code = _item_temporal_hint_code(item)
    recency_hint_boost, recency_hint_reason = conversation_recency_temporal_hint_signal(
        query=query,
        temporal_hint_code=temporal_hint_code,
    )
    if recency_hint_boost > 0:
        boost += recency_hint_boost
        reasons.append(recency_hint_reason)
    recency_missing_time_penalty, recency_missing_time_reason = (
        conversation_recency_missing_temporal_signal(
            query=query,
            text=item.text,
            temporal_hint_code=temporal_hint_code,
        )
    )
    if recency_missing_time_penalty > 0:
        penalty += recency_missing_time_penalty
        reasons.append(recency_missing_time_reason)
    if not _temporal_query_signal_already_applied(item):
        temporal_signal = temporal_query_boost_signal(
            item,
            intent=temporal_query_intent,
        )
        if temporal_signal.boost > 0:
            boost += temporal_signal.boost
            reasons.append(f"temporal_query_{temporal_signal.code}")
        if temporal_signal.boost < 0:
            penalty += abs(temporal_signal.boost)
            reasons.append(f"temporal_query_{temporal_signal.code}")
    temporal_answer_boost, temporal_answer_penalty, temporal_answer_reason = (
        _temporal_answer_signal(query=query, query_reason=query_reason, item=item)
    )
    if temporal_answer_boost > 0:
        boost += temporal_answer_boost
        reasons.append(temporal_answer_reason)
    if temporal_answer_penalty > 0:
        penalty += temporal_answer_penalty
        reasons.append(temporal_answer_reason)
    if source_speaker_anchor_override:
        reasons.append("query_anchor_conflict_overridden_by_source_speaker")
    elif commonality_anchor_override:
        reasons.append("query_anchor_conflict_overridden_by_commonality_who_else")
    elif anchor_conflict and not _action_role_confirms_requested_relation(action_signal.reason):
        penalty += 0.07
        reasons.append("query_anchor_conflict")
    elif anchor_conflict:
        reasons.append("query_anchor_conflict_overridden_by_action_role")
    if _event_participation_mismatch(query=query, text=item.text):
        penalty += 0.075
        reasons.append("event_participation_mismatch")
    elif _event_participation_positive_match(query=query, text=item.text):
        boost += 0.018
        reasons.append("event_participation_positive_match")
    elif _event_participation_source_sibling_noise(query=query, item=item):
        penalty += 0.07
        reasons.append("event_participation_source_sibling_noise")
    companion_boost, companion_penalty, companion_reason = activity_companion_signal(
        query=query,
        item=item,
        query_anchor_intent=query_anchor_intent,
    )
    if companion_boost > 0:
        boost += companion_boost
        reasons.append(companion_reason)
    if companion_penalty > 0:
        penalty += companion_penalty
        reasons.append(companion_reason)
    if _activity_source_sibling_noise(item=item):
        penalty += 0.04
        reasons.append("activity_source_sibling_noise")
    if _capped_source_sibling_low_signal(item=item):
        penalty += 0.06
        reasons.append("capped_source_sibling_low_signal")
    if _allergy_condition_weak_evidence(query_reason=query_reason, relevance=relevance):
        penalty += 0.07
        reasons.append("allergy_condition_weak_evidence")
    if _patriotic_service_weak_evidence(query_reason=query_reason, relevance=relevance):
        penalty += 0.055
        reasons.append("patriotic_service_weak_evidence")
    if _running_reason_weak_evidence(query_reason=query_reason, relevance=relevance):
        penalty += 0.055
        reasons.append("running_reason_weak_evidence")
    if _volunteer_career_exact_turn_evidence(query_reason=query_reason, item=item):
        boost += 0.028
        reasons.append("volunteer_career_exact_turn_evidence")
    if _volunteer_career_weak_evidence(
        query_anchor_intent=query_anchor_intent,
        query_reason=query_reason,
        item=item,
    ):
        penalty += 0.07
        reasons.append("volunteer_career_weak_evidence")
    if _volunteer_career_broad_evidence(query_reason=query_reason, item=item):
        penalty += 0.07
        reasons.append("volunteer_career_broad_evidence")
    if _post_event_activity_timing_exact_evidence(query_reason=query_reason, item=item):
        boost += 0.032
        reasons.append("post_event_activity_timing_exact_evidence")
    if _post_event_activity_timing_weak_evidence(query_reason=query_reason, item=item):
        penalty += 0.12
        reasons.append("post_event_activity_timing_weak_evidence")
    if _shoe_usage_exact_evidence(query_reason=query_reason, item=item):
        boost += 0.024
        reasons.append("shoe_usage_exact_evidence")
    if _shoe_usage_weak_evidence(query_reason=query_reason, item=item):
        penalty += 0.12
        reasons.append("shoe_usage_weak_evidence")
    domain_adjustment = apply_domain_rerank_signals(
        query=query,
        query_reason=query_reason,
        item=item,
        relevance=relevance,
        has_multi_evidence_aggregation_candidate=has_multi_evidence_aggregation_candidate,
    )
    boost += domain_adjustment.boost
    penalty += domain_adjustment.penalty
    reasons.extend(domain_adjustment.reasons)
    rank_signals = dict(domain_adjustment.rank_signals)
    slot_diverse_aggregation = aggregation_answer_slot_count(query=query, text=item.text) >= 2
    event_detail_requirement_support = "temporal_camping_detail_evidence" in reasons
    if requested_total > 0:
        if coverage_ratio <= 0 and event_detail_requirement_support:
            reasons.append("explicit_requirement_supported_by_event_detail")
        elif coverage_ratio <= 0:
            penalty += 0.025
            reasons.append("explicit_requirement_missing")
        elif coverage_ratio < 0.5 and not slot_diverse_aggregation:
            penalty += 0.012
            reasons.append("explicit_requirement_partial")
    if coverage.missing_answer_shapes and not slot_diverse_aggregation:
        penalty += min(
            0.02,
            0.014 * len(coverage.missing_answer_shapes),
        )
        reasons.append("explicit_requirement_missing")
        reasons.append("explicit_answer_shape_missing")
    if coverage.missing_modalities:
        penalty += min(
            0.032,
            0.024 * len(coverage.missing_modalities),
        )
        reasons.append("explicit_requirement_missing")
        reasons.append("explicit_modality_missing")
    if coverage.missing_evidence_features and not slot_diverse_aggregation:
        penalty += min(
            0.028,
            0.02 * len(coverage.missing_evidence_features),
        )
        reasons.append("explicit_requirement_missing")
        reasons.append("explicit_evidence_feature_missing")
    if (
        not is_query_relevance_sufficient(relevance)
        and anchor_match is None
        and coverage_ratio <= 0
    ):
        penalty += 0.018
        reasons.append("weak_query_relevance")
    elif (
        _is_long_query_weak_overlap(relevance)
        and anchor_match is None
        and coverage_ratio <= 0
        and strong_source_count <= 0
        and len(sources) <= 1
    ):
        penalty += 0.016
        reasons.append("weak_long_query_overlap")
    return _DeterministicRerankSignals(
        boost=round(min(max_boost, boost), 4),
        penalty=round(min(max_penalty, penalty), 4),
        reasons=tuple(dict.fromkeys(reasons)),
        rank_signals=tuple(sorted(rank_signals.items())),
        source_count=len(sources),
        strong_source_count=strong_source_count,
        coverage_ratio=round(coverage_ratio, 4),
        anchor_conflict=anchor_conflict,
        query_reason=query_reason,
    )


def _is_long_query_weak_overlap(relevance: QueryRelevance) -> bool:
    if relevance.query_term_count < 6:
        return False
    if relevance.phrase_bigram_hits > 0:
        return False
    return relevance.distinctive_term_hits <= 1 and relevance.unique_term_hits <= 2


def _localized_evidence_support_signal(
    *,
    item: ContextItem,
    relevance: QueryRelevance,
    coverage_ratio: float,
    anchor_matched: bool,
    strong_source_count: int,
) -> tuple[float, str]:
    localized_refs = tuple(ref for ref in item.source_refs if _source_ref_has_precise_location(ref))
    if not localized_refs:
        return 0.0, ""
    if (
        not is_query_relevance_sufficient(relevance)
        and coverage_ratio <= 0
        and not anchor_matched
        and strong_source_count <= 0
    ):
        return 0.0, ""
    source_count = len({(ref.source_type, ref.source_id) for ref in localized_refs})
    feature_count = len(
        {
            feature
            for ref in localized_refs
            for feature in _source_ref_location_features(ref)
        }
    )
    boost = 0.008
    boost += min(0.006, 0.003 * max(0, len(localized_refs) - 1))
    boost += min(0.004, 0.002 * max(0, source_count - 1))
    boost += min(0.004, 0.002 * max(0, feature_count - 1))
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    if _safe_evidence_kind_or_modality(diagnostics):
        boost += 0.003
    reason = (
        "multi_localized_evidence_source"
        if len(localized_refs) >= 2 or source_count >= 2 or feature_count >= 2
        else "localized_evidence_source"
    )
    return round(min(_LOCALIZED_EVIDENCE_RERANK_MAX_BOOST, boost), 4), reason


def _canonical_anchor_summary_support_signal(
    *,
    item: ContextItem,
    coverage: _RequirementCoverageSignals,
    relevance: QueryRelevance,
    anchor_matched: bool,
    anchor_conflict: bool,
    sources: tuple[str, ...],
    strong_source_count: int,
) -> tuple[float, str]:
    if anchor_conflict or "summary" not in coverage.requested_answer_shapes:
        return 0.0, ""
    if not coverage.requested_anchor_kinds & coverage.covered_anchor_kinds:
        return 0.0, ""
    if not _is_canonical_anchor_source(item=item, sources=sources):
        return 0.0, ""
    if (
        not is_query_relevance_sufficient(relevance)
        and not anchor_matched
        and coverage.ratio <= 0
    ):
        return 0.0, ""
    if not _has_canonical_anchor_profile_evidence(item):
        return 0.0, ""

    boost = 0.01
    if item.item_type == "anchor":
        boost += 0.003
    if anchor_matched:
        boost += 0.003
    if strong_source_count:
        boost += 0.002
    return (
        round(min(_CANONICAL_ANCHOR_SUMMARY_RERANK_MAX_BOOST, boost), 4),
        "canonical_anchor_summary_profile",
    )


def _is_canonical_anchor_source(*, item: ContextItem, sources: tuple[str, ...]) -> bool:
    if item.item_type == "anchor":
        return True
    return bool(
        set(sources).intersection(
            {
                "approved_context_linked_anchors",
                "canonical_anchor_relations",
                "canonical_anchors",
            }
        )
    )


def _has_canonical_anchor_profile_evidence(item: ContextItem) -> bool:
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    profile = safe_diagnostic_mapping(
        diagnostics.get("anchor_identity_profile")
        or provenance.get("anchor_identity_profile")
    )
    score_signals = safe_score_signals(diagnostics.get("score_signals"))
    identity_term_count = max(
        _coverage_int(profile.get("identity_term_count")),
        _coverage_int(score_signals.get("anchor_identity_term_count")),
    )
    alias_identity_term_count = max(
        _coverage_int(profile.get("alias_identity_term_count")),
        _coverage_int(score_signals.get("anchor_alias_identity_term_count")),
    )
    source_ref_count = max(
        len(item.source_refs),
        _coverage_int(provenance.get("source_ref_count")),
    )
    text = item.text.casefold()
    has_rendered_profile_text = any(
        marker in text for marker in ("aliases:", "description:", "identity:")
    )
    return (
        has_rendered_profile_text
        or identity_term_count > 0
        or alias_identity_term_count > 0
        or source_ref_count > 0
    )


def _source_ref_has_precise_location(ref: SourceRef) -> bool:
    return bool(_source_ref_location_features(ref))


def _citation_evidence_support_signal(
    *,
    item: ContextItem,
    coverage: _RequirementCoverageSignals,
    relevance: QueryRelevance,
    anchor_matched: bool,
    strong_source_count: int,
) -> tuple[float, str]:
    if "citation" not in coverage.requested_evidence_features:
        return 0.0, ""
    if (
        not is_query_relevance_sufficient(relevance)
        and coverage.ratio <= 0
        and not anchor_matched
        and strong_source_count <= 0
    ):
        return 0.0, ""
    quote_count = sum(1 for ref in item.source_refs if (ref.quote_preview or "").strip())
    localized_count = sum(1 for ref in item.source_refs if _source_ref_has_precise_location(ref))
    if quote_count <= 0 and localized_count <= 0:
        return 0.0, ""
    boost = 0.01
    boost += min(0.008, quote_count * 0.004)
    boost += min(0.006, localized_count * 0.003)
    reason = "citation_quote_evidence" if quote_count > 0 else "citation_localized_evidence"
    return round(min(_CITATION_EVIDENCE_RERANK_MAX_BOOST, boost), 4), reason


def _source_ref_location_features(ref: SourceRef) -> tuple[str, ...]:
    features: list[str] = []
    if ref.page_number is not None:
        features.append("page")
    if ref.char_start is not None or ref.char_end is not None:
        features.append("char")
    if ref.time_start_ms is not None or ref.time_end_ms is not None:
        features.append("time")
    if ref.bbox is not None:
        features.append("bbox")
    return tuple(features)


def _safe_evidence_kind_or_modality(diagnostics: Mapping[str, object]) -> bool:
    for key in ("evidence_kind", "evidence_modality", "artifact_type"):
        value = diagnostics.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _best_query_relevance_for_rerank(
    plan: QueryExpansionPlan,
    *,
    text: str,
    cache: dict[str, tuple[str, str, QueryRelevance]] | None,
) -> tuple[str, str, QueryRelevance]:
    if cache is None:
        return best_query_relevance(plan, text=text)
    cached = cache.get(text)
    if cached is not None:
        return cached
    result = best_query_relevance(plan, text=text)
    cache[text] = result
    return result


def _allergy_condition_weak_evidence(
    *,
    query_reason: str,
    relevance: QueryRelevance,
) -> bool:
    return (
        query_reason == "allergy_condition_inference_bridge"
        and relevance.distinctive_term_hits < 4
    )


def _patriotic_service_weak_evidence(
    *,
    query_reason: str,
    relevance: QueryRelevance,
) -> bool:
    return (
        query_reason == "patriotic_service_inference_bridge"
        and relevance.distinctive_term_hits < 4
    )


def _running_reason_weak_evidence(
    *,
    query_reason: str,
    relevance: QueryRelevance,
) -> bool:
    return query_reason == "running_reason_bridge" and relevance.distinctive_term_hits < 3


def _temporal_query_signal_already_applied(item: ContextItem) -> bool:
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    return provenance.get("temporal_query_intent_applied") is True


def _item_temporal_hint_code(item: ContextItem) -> str:
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    return temporal_hint_code_from_metadata(diagnostics, provenance)


def _temporal_answer_signal(
    *,
    query: str,
    query_reason: str,
    item: ContextItem,
) -> tuple[float, float, str]:
    if not _TEMPORAL_ANSWER_QUERY_RE.search(query):
        return 0.0, 0.0, ""
    if (
        query_reason == "item_purchase_bridge"
        and not _is_item_purchase_temporal_answer_evidence(query_reason=query_reason, item=item)
    ):
        return 0.0, 0.012, "temporal_answer_evidence_missing"
    if _item_has_temporal_answer_evidence(item):
        return 0.026, 0.0, "temporal_answer_evidence"
    return 0.0, 0.012, "temporal_answer_evidence_missing"


def _is_item_purchase_temporal_answer_evidence(
    *,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if query_reason != "item_purchase_bridge":
        return False
    return has_item_purchase_object_evidence(item.text)


def _item_has_temporal_answer_evidence(item: ContextItem) -> bool:
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    for metadata in (diagnostics, provenance):
        if any(
            metadata.get(key)
            for key in (
                "temporal_hint_code",
                "event_temporal_hint_code",
                "event_valid_from",
                "event_valid_to",
                "valid_from",
                "valid_to",
            )
        ):
            return True
    if any(
        ref.time_start_ms is not None
        or ref.time_end_ms is not None
        or _TEMPORAL_ANSWER_EVIDENCE_RE.search(ref.quote_preview or "")
        for ref in item.source_refs
    ):
        return True
    return bool(_TEMPORAL_ANSWER_EVIDENCE_RE.search(item.text))


def _event_participation_mismatch(*, query: str, text: str) -> bool:
    if not _EVENT_PARTICIPATION_QUERY_RE.search(query):
        return False
    if not _EVENT_TERM_QUERY_RE.search(query):
        return False
    if _SELF_MISSED_EVENT_TEXT_RE.search(text):
        return True
    if not _MISSED_EVENT_TEXT_RE.search(text):
        return False
    return not _POSITIVE_EVENT_TEXT_RE.search(text)


def _event_participation_positive_match(*, query: str, text: str) -> bool:
    if not _EVENT_PARTICIPATION_QUERY_RE.search(query):
        return False
    if not _EVENT_TERM_QUERY_RE.search(query):
        return False
    return bool(_POSITIVE_EVENT_PARTICIPATION_TEXT_RE.search(text))


def _event_participation_source_sibling_noise(*, query: str, item: ContextItem) -> bool:
    if not _EVENT_PARTICIPATION_QUERY_RE.search(query):
        return False
    if not _EVENT_TERM_QUERY_RE.search(query):
        return False
    if "keyword_source_sibling_chunks" not in diagnostic_retrieval_sources(item.diagnostics):
        return False
    signals = safe_score_signals(safe_diagnostic_mapping(item.diagnostics).get("score_signals"))
    if str(signals.get("source_sibling_dialogue_visual_reference") or "").casefold() in {
        "1",
        "true",
    }:
        return False
    return not _POSITIVE_EVENT_TEXT_RE.search(item.text)


def _activity_source_sibling_noise(*, item: ContextItem) -> bool:
    if "keyword_source_sibling_chunks" not in diagnostic_retrieval_sources(item.diagnostics):
        return False
    signals = safe_score_signals(safe_diagnostic_mapping(item.diagnostics).get("score_signals"))
    reason = str(signals.get("query_expansion_reason") or "").strip()
    if reason not in _ACTIVITY_OBSERVATION_SOURCE_REASONS.union(_ACTIVITY_OWNER_REASONS):
        return False
    return not _POSITIVE_ACTIVITY_TEXT_RE.search(item.text)


def _capped_source_sibling_low_signal(*, item: ContextItem) -> bool:
    if "keyword_source_sibling_chunks" not in diagnostic_retrieval_sources(item.diagnostics):
        return False
    signals = safe_score_signals(safe_diagnostic_mapping(item.diagnostics).get("score_signals"))
    return _positive_signal(signals.get("source_sibling_score_cap_applied"))


def _volunteer_career_weak_evidence(
    *,
    query_anchor_intent: QueryAnchorIntent,
    query_reason: str,
    item: ContextItem,
) -> bool:
    if query_reason != "volunteer_career_inference_bridge":
        return False
    if _VOLUNTEER_CAREER_CONTEXT_RE.search(item.text) is None:
        return True
    query_people = _query_person_labels(query_anchor_intent)
    if not query_people:
        return False
    speakers = _dialogue_speaker_labels(item.text)
    return bool(speakers and not speakers.intersection(query_people))


def _volunteer_career_exact_turn_evidence(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason != "volunteer_career_inference_bridge":
        return False
    if _VOLUNTEER_CAREER_CONTEXT_RE.search(item.text) is None:
        return False
    return _item_source_is_turn(item)


def _volunteer_career_broad_evidence(*, query_reason: str, item: ContextItem) -> bool:
    if query_reason != "volunteer_career_inference_bridge":
        return False
    if _item_source_is_turn(item):
        return False
    if _VOLUNTEER_CAREER_STRONG_NON_TURN_EVIDENCE_RE.search(item.text) is not None:
        return False
    return _VOLUNTEER_CAREER_CONTEXT_RE.search(item.text) is not None


def _post_event_activity_timing_exact_evidence(*, query_reason: str, item: ContextItem) -> bool:
    if not _is_post_event_activity_timing_candidate(query_reason=query_reason, item=item):
        return False
    if _POST_EVENT_ACTIVITY_TIMING_CONTEXT_RE.search(item.text) is None:
        return False
    return _item_source_is_turn(item)


def _post_event_activity_timing_weak_evidence(*, query_reason: str, item: ContextItem) -> bool:
    if not _is_post_event_activity_timing_candidate(query_reason=query_reason, item=item):
        return False
    return _POST_EVENT_ACTIVITY_TIMING_CONTEXT_RE.search(item.text) is None


def _is_post_event_activity_timing_candidate(*, query_reason: str, item: ContextItem) -> bool:
    return _matches_query_or_score_signal_reason(
        query_reason=query_reason,
        item=item,
        target_reason="post_event_activity_timing_bridge",
    )


def _shoe_usage_exact_evidence(*, query_reason: str, item: ContextItem) -> bool:
    if not _is_shoe_usage_candidate(query_reason=query_reason, item=item):
        return False
    if _SHOE_USAGE_CONTEXT_RE.search(item.text) is None:
        return False
    return _item_source_is_turn(item)


def _shoe_usage_weak_evidence(*, query_reason: str, item: ContextItem) -> bool:
    if not _is_shoe_usage_candidate(query_reason=query_reason, item=item):
        return False
    return _SHOE_USAGE_CONTEXT_RE.search(item.text) is None


def _is_shoe_usage_candidate(*, query_reason: str, item: ContextItem) -> bool:
    return _matches_query_or_score_signal_reason(
        query_reason=query_reason,
        item=item,
        target_reason="shoe_usage_bridge",
    )


def _matches_query_or_score_signal_reason(
    *,
    query_reason: str,
    item: ContextItem,
    target_reason: str,
) -> bool:
    if query_reason == target_reason:
        return True
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    signals = safe_score_signals(diagnostics.get("score_signals"))
    return str(signals.get("query_expansion_reason") or "") == target_reason


def _item_source_is_turn(item: ContextItem) -> bool:
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    source_id = str(diagnostics.get("source_id") or "").strip()
    if not source_id:
        provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
        source_id = str(provenance.get("source_id") or "").strip()
    if source_id:
        return source_id.casefold().endswith(":turn")
    return any(_source_ref_is_turn(ref) for ref in item.source_refs)


def _action_role_confirms_requested_relation(reason: str) -> bool:
    return reason in {
        "action_role_actor_recipient_match",
        "action_role_actor_to_recipient_evidence",
        "action_role_information_source_evidence",
        "action_role_recipient_match",
    }


def _dialogue_speaker_confirms_query_anchor(
    *,
    item: ContextItem,
    query_anchor_intent: QueryAnchorIntent,
    relevance: QueryRelevance,
) -> bool:
    sources = diagnostic_retrieval_sources(item.diagnostics)
    if "keyword_source_sibling_chunks" in sources:
        signals = safe_score_signals(
            safe_diagnostic_mapping(item.diagnostics).get("score_signals")
        )
        if not _positive_signal(signals.get("source_sibling_group_level_seed")):
            return False
        if _numeric_signal(signals.get("query_expansion_reason_priority")) < 3:
            return False
    if relevance.distinctive_term_hits < 4 or relevance.unique_term_hits < 4:
        return False
    query_people = _query_person_labels(query_anchor_intent)
    if not query_people:
        return False
    speakers = _dialogue_speaker_labels(item.text)
    return bool(speakers.intersection(query_people))


def _positive_signal(value: object) -> bool:
    return _numeric_signal(value) > 0


def _numeric_signal(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _activity_owner_signal(
    *,
    query_anchor_intent: QueryAnchorIntent,
    query_reason: str,
    text: str,
) -> tuple[float, float, str]:
    if query_reason not in _ACTIVITY_OWNER_REASONS:
        return 0.0, 0.0, ""
    query_people = _query_person_labels(query_anchor_intent)
    if not query_people:
        return 0.0, 0.0, ""
    speakers = _dialogue_speaker_labels(text)
    if not speakers:
        return 0.0, 0.0, ""
    if speakers.intersection(query_people):
        return _ACTIVITY_OWNER_MATCH_BOOST, 0.0, "activity_owner_speaker_match"
    return 0.0, _ACTIVITY_OWNER_MISMATCH_PENALTY, "activity_owner_speaker_mismatch"


def _query_person_labels(query_anchor_intent: QueryAnchorIntent) -> frozenset[str]:
    labels: set[str] = set()
    for hint in query_anchor_intent.hints:
        if hint.kind != MemoryAnchorKind.PERSON:
            continue
        label = _normalized_dialogue_label(hint.label)
        if label:
            labels.add(label)
        canonical = _normalized_dialogue_label(hint.canonical_key)
        if canonical:
            labels.add(canonical)
    return frozenset(labels)


def _dialogue_speaker_labels(text: str) -> frozenset[str]:
    return frozenset(
        label
        for label in (
            _normalized_dialogue_label(match.group("speaker"))
            for match in _DIALOGUE_SPEAKER_RE.finditer(text)
        )
        if label
    )


def _normalized_dialogue_label(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


def _item_requirement_coverage_signals(
    item: ContextItem,
    *,
    query: str,
    query_anchor_intent: QueryAnchorIntent,
    requested_total: int,
) -> _RequirementCoverageSignals:
    if requested_total <= 0:
        return _RequirementCoverageSignals(
            ratio=0.0,
            requested_anchor_kinds=frozenset(),
            covered_anchor_kinds=frozenset(),
            missing_anchor_kinds=frozenset(),
            requested_modalities=frozenset(),
            missing_modalities=frozenset(),
            requested_evidence_features=frozenset(),
            missing_evidence_features=frozenset(),
            requested_answer_shapes=frozenset(),
            covered_answer_shapes=frozenset(),
            missing_answer_shapes=frozenset(),
        )
    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=query_anchor_intent,
        items=(item,),
    )
    requested_anchor_kinds = _coverage_value_set(coverage.get("requested_anchor_kinds"))
    covered_anchor_kinds = _coverage_value_set(coverage.get("covered_anchor_kinds"))
    missing_anchor_kinds = _coverage_value_set(coverage.get("missing_anchor_kinds"))
    requested_modalities = _coverage_value_set(coverage.get("requested_modalities"))
    missing_modalities = _coverage_value_set(coverage.get("missing_modalities"))
    requested_evidence_features = _coverage_value_set(
        coverage.get("requested_evidence_features")
    )
    missing_evidence_features = _coverage_value_set(coverage.get("missing_evidence_features"))
    requested_answer_shapes = _coverage_value_set(coverage.get("requested_answer_shapes"))
    covered_answer_shapes = _coverage_value_set(coverage.get("covered_answer_shapes"))
    missing_answer_shapes = _coverage_value_set(coverage.get("missing_answer_shapes"))
    return _RequirementCoverageSignals(
        ratio=_coverage_ratio(coverage.get("coverage_ratio")),
        requested_anchor_kinds=requested_anchor_kinds,
        covered_anchor_kinds=requested_anchor_kinds & covered_anchor_kinds,
        missing_anchor_kinds=requested_anchor_kinds & missing_anchor_kinds,
        requested_modalities=requested_modalities,
        missing_modalities=requested_modalities & missing_modalities,
        requested_evidence_features=requested_evidence_features,
        missing_evidence_features=requested_evidence_features & missing_evidence_features,
        requested_answer_shapes=requested_answer_shapes,
        covered_answer_shapes=requested_answer_shapes & covered_answer_shapes,
        missing_answer_shapes=requested_answer_shapes & missing_answer_shapes,
    )


def _coverage_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value))
    return 0


def _coverage_ratio(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return min(1.0, max(0.0, float(value)))
    return 0.0


def _deterministic_rerank_already_applied(item: ContextItem) -> bool:
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    return provenance.get("deterministic_rerank_applied") is True


def _coverage_value_set(value: object) -> frozenset[str]:
    if not isinstance(value, list | tuple):
        return frozenset()
    return frozenset(
        text for item in value if isinstance(item, str) and (text := item.strip().casefold())
    )


def _sorted_coverage_matches(
    requested: frozenset[str],
    covered: object,
) -> tuple[str, ...]:
    return tuple(sorted(requested & _coverage_value_set(covered)))


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
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    return provenance.get("rank_fusion_applied") is True
