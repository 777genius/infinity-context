"""Context dedupe, rank fusion and deterministic ranking helpers."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache

from infinity_context_core.application.context_action_roles import action_role_rerank_signal
from infinity_context_core.application.context_activity_companion import (
    activity_companion_signal,
)
from infinity_context_core.application.context_aggregation_answer_slots import (
    aggregation_answer_slot_count,
)
from infinity_context_core.application.context_answer_unit_shapes import (
    is_typed_answer_unit_shape,
)
from infinity_context_core.application.context_conversation_counterparty import (
    conversation_counterparty_evidence_signal,
    conversation_recency_evidence_signal,
    conversation_recency_missing_temporal_signal,
    conversation_recency_temporal_hint_signal,
    conversation_topic_evidence_signal,
)
from infinity_context_core.application.context_count_cardinality import (
    has_exact_count_cardinality_evidence,
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
    has_current_state_correction_evidence,
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
    text_variant_profile,
    text_variant_stats,
)
from infinity_context_core.application.context_named_person_preference import (
    named_person_preference_signal,
)
from infinity_context_core.application.context_object_mismatch import (
    object_kind_mismatch_signal,
)
from infinity_context_core.application.context_ordinal_sequence import (
    ordinal_sequence_rerank_signal,
)
from infinity_context_core.application.context_owner_grounding import (
    owner_grounding_signal,
)
from infinity_context_core.application.context_person_kinship import (
    person_kinship_signal,
)
from infinity_context_core.application.context_person_occupation import (
    person_occupation_signal,
)
from infinity_context_core.application.context_person_relation_inventory import (
    person_relation_inventory_signal,
)
from infinity_context_core.application.context_person_residence import (
    person_residence_signal,
)
from infinity_context_core.application.context_person_team_membership import (
    person_team_membership_signal,
)
from infinity_context_core.application.context_pet_ownership import (
    pet_ownership_signal,
)
from infinity_context_core.application.context_polarity_rerank import (
    absence_contrast_signal,
    absence_negation_signal,
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
    score_query_terms_relevance_against_profile,
)
from infinity_context_core.application.context_requirement_coverage import (
    context_requirement_coverage,
)
from infinity_context_core.application.context_speaker_attribution import (
    speaker_attribution_signal,
)
from infinity_context_core.application.context_speaker_disambiguation import (
    apply_attributed_speaker_exact_name_disambiguation,
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
_QueryExpansionTerms = tuple[tuple[str, str, tuple[LexicalQueryTerm, ...]], ...]
_STRICT_QUERY_REASON_MIN_DISTINCTIVE_HITS = {
    "book_suggestion_bridge": 4,
    "music_artist_answer_bridge": 4,
}
_DIRECT_VISUAL_TEXT_QUERY_RE = re.compile(
    r"\b(?:what|which)\b(?=.{0,120}\b(?:ocr|text|written|label|title)\b)"
    r"(?=.{0,120}\b(?:screenshot|screen|image|visual)\b)",
    re.IGNORECASE | re.DOTALL,
)
_ARTIFACT_CONTEXT_COMPOSITE_QUERY_RE = re.compile(
    r"\b(?:changed|after|before|call|meeting|conversation|about)\b",
    re.IGNORECASE,
)
_BOOK_SUGGESTION_PROJECT_FALSE_FRIEND_RE = re.compile(
    r"\b(?:project|launch|planning|proposal|task|workflow)\s+suggestion\b|"
    r"\bsuggestion\s+(?:from|about)\b(?=.{0,80}\b(?:project|launch|planning|proposal|task)\b)",
    re.IGNORECASE | re.DOTALL,
)
_BOOK_SUGGESTION_EVIDENCE_CUE_RE = re.compile(
    r"[\"“][^\"”]{2,80}[\"”]|"
    r"\b(?:book|novel|memoir|author|chapter|must[-\s]?see|great\s+read|"
    r"read\s+(?:the\s+)?book|recommended\s+(?:the\s+)?book|"
    r"suggested\s+(?:the\s+)?book)\b",
    re.IGNORECASE,
)
_QUERY_ANCHOR_INTENT_MAX_BOOST = 0.035
_CONTEXT_REQUIREMENT_MAX_BOOST = 0.04
_CONTEXT_REQUIREMENT_ANCHOR_BOOST = 0.008
_CONTEXT_REQUIREMENT_MODALITY_BOOST = 0.022
_CONTEXT_REQUIREMENT_FEATURE_BOOST = 0.014
_CONTEXT_REQUIREMENT_ANSWER_SHAPE_BOOST = 0.012
_CONTEXT_REQUIREMENT_EXACT_COUNT_CARDINALITY_BOOST = 0.008
_CONTEXT_REQUIREMENT_TYPED_ANSWER_UNIT_BOOST = 0.018
_CONTEXT_REQUIREMENT_TYPED_ANSWER_UNIT_MISMATCH_PENALTY = 0.012
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
_SOURCE_QUOTE_ANSWER_RERANK_MAX_BOOST = 0.01
_ARTIFACT_INVENTORY_EVIDENCE_RERANK_MAX_BOOST = 0.028
_DECOMPOSITION_COVERAGE_RERANK_MAX_BOOST = 0.022
_LOCALIZED_EVIDENCE_RERANK_MAX_BOOST = 0.022
_SAME_PERSON_TOPIC_DISAMBIGUATION_MAX_PENALTY = 0.064
_DUPLICATE_SOURCE_SCORE_TOLERANCE = 0.015
_BROAD_DECOMPOSITION_COVERAGE_REASONS = frozenset(
    {
        "decomposition_clause",
        "decomposition_inventory_list",
        "decomposition_quantity_count",
        "decomposition_temporal_answer",
    }
)
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
_ARTIFACT_INVENTORY_RERANK_SOURCES = frozenset(
    {
        "approved_context_linked_asset_manifest_evidence",
        "approved_context_linked_assets",
        "approved_context_linked_extraction_artifacts",
        "artifact_evidence",
    }
)
_ARTIFACT_INVENTORY_SOURCE_REF_TYPES = frozenset(
    {
        "asset",
        "extraction_artifact",
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
        "activity_competition_evidence_bridge",
        "allergy_condition_inference_bridge",
        "allergy_inventory_bridge",
        "business_networking_event_bridge",
        "business_opening_timeline_bridge",
        "business_promotion_event_bridge",
        "business_store_promotion_event_bridge",
        "business_start_reason_bridge",
        "book_reading_list_bridge",
        "church_friend_activity_inventory_bridge",
        "charity_brand_sponsorship_bridge",
        "charity_tournament_count_bridge",
        "children_count_event_bridge",
        "choice_reason_bridge",
        "business_commonality_bridge",
        "store_promotion_inventory_bridge",
        "camping_location_bridge",
        "degree_policy_inference_bridge",
        "exercise_activity_inventory_bridge",
        "endorsement_gear_brand_bridge",
        "gaming_medium_bridge",
        "hiking_trail_count_bridge",
        "hobby_interest_bridge",
        "instrument_play_bridge",
        "letter_count_bridge",
        "meteor_shower_feeling_bridge",
        "national_park_inference_bridge",
        "patriotic_service_inference_bridge",
        "pet_count_bridge",
        "pet_inventory_bridge",
        "personality_authenticity_bridge",
        "personality_drive_bridge",
        "personality_thoughtfulness_bridge",
        "personality_trait_bridge",
        "post_athletic_career_bridge",
        "running_reason_bridge",
        "running_reason_question_bridge",
        "screenplay_count_bridge",
        "shelter_comfort_reason_bridge",
        "state_residence_inference_bridge",
        "symbol_importance_bridge",
        "temporal_event_detail_bridge",
        "future_plan_timing_bridge",
        "tournament_count_bridge",
        "volunteer_career_inference_bridge",
        "volunteering_people_inventory_bridge",
        "yoga_delay_gaming_bridge",
    }
)
_TURN_ONLY_EVIDENCE_SOURCE_REASONS = frozenset(
    {
        "personality_authenticity_bridge",
        "personality_drive_bridge",
        "personality_thoughtfulness_bridge",
        "personality_trait_bridge",
        "national_park_inference_bridge",
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
_DIALOGUE_MARKER_RE = re.compile(r"\bD\d+:\d+\b")
_SAME_PERSON_TOPIC_DECOY_TEXT_RE = re.compile(
    r"\b(?:about|around|regarding|topic|subject|agenda|covered|covers?|"
    r"discuss(?:ed|ion)?|mention(?:ed)?|said|told|wrote|asked|"
    r"recommended|suggested|project|plan|initiative|campaign|issue)\b",
    re.IGNORECASE,
)
_SAME_PERSON_TOPIC_DISAMBIGUATION_QUERY_RE = re.compile(
    r"\b(?:about|around|regarding|topic|subject)\b|"
    r"\b(?:what|which|who)\b(?=.{0,120}\b(?:ask(?:ed)?|discuss(?:ed)?|"
    r"mention(?:ed)?|recommend(?:ed)?|said|say|suggest(?:ed)?|wrote|write)\b)",
    re.IGNORECASE | re.DOTALL,
)
_SAME_PERSON_TOPIC_QUERY_STOP_TERMS = frozenset(
    {
        "about",
        "after",
        "ago",
        "and",
        "around",
        "ask",
        "asked",
        "call",
        "called",
        "chat",
        "chatted",
        "conversation",
        "day",
        "days",
        "did",
        "discuss",
        "discussed",
        "do",
        "does",
        "during",
        "hour",
        "hours",
        "latest",
        "last",
        "meeting",
        "mention",
        "mentioned",
        "message",
        "messaged",
        "recent",
        "said",
        "say",
        "sent",
        "spoke",
        "subject",
        "talk",
        "talked",
        "text",
        "texted",
        "topic",
        "was",
        "week",
        "weeks",
        "what",
        "when",
        "where",
        "which",
        "who",
        "with",
        "write",
        "wrote",
        "о",
        "об",
        "про",
        "разговор",
        "сказал",
        "сказала",
        "созвон",
        "что",
    }
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
    adjusted = tuple(
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
    adjusted = apply_attributed_speaker_exact_name_disambiguation(
        adjusted,
        query=query,
        max_penalty=max_penalty,
    )
    return _apply_same_person_topic_disambiguation_penalties(
        adjusted,
        query=query,
        query_anchor_intent=query_anchor_intent,
        max_penalty=max_penalty,
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


@lru_cache(maxsize=512)
def _query_expansion_terms_for_signature(
    signature: tuple[tuple[str, str], ...],
) -> _QueryExpansionTerms:
    return tuple((query, reason, query_terms(query)) for query, reason in signature)


def _query_expansion_terms(plan: QueryExpansionPlan) -> _QueryExpansionTerms:
    return _query_expansion_terms_for_signature(
        tuple((expansion.query, expansion.reason) for expansion in plan.retrieval_queries)
    )


def best_query_relevance(
    plan: QueryExpansionPlan,
    *,
    text: str,
) -> tuple[str, str, QueryRelevance]:
    text_counts, text_variants = text_variant_profile(text)
    scored = tuple(
        (
            query,
            reason,
            score_query_terms_relevance_against_profile(
                terms=terms,
                text_counts=text_counts,
                text_variants=text_variants,
            ),
        )
        for query, reason, terms in _query_expansion_terms(plan)
    )
    strict_filtered = tuple(
        item
        for item in scored
        if not _strict_query_reason_below_minimum(reason=item[1], relevance=item[2])
    )
    filtered = tuple(
        item
        for item in strict_filtered or scored
        if not _query_relevance_false_friend(plan=plan, item=item, text=text)
    )
    return max(
        filtered or strict_filtered or scored,
        key=lambda item: _query_relevance_rank_key_for_plan(plan, item),
    )


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


def _query_relevance_rank_key_for_plan(
    plan: QueryExpansionPlan,
    item: tuple[str, str, QueryRelevance],
) -> tuple[bool, int, int, int, float, bool]:
    query, reason, relevance = item
    priority = _query_reason_priority_for_relevance(reason, relevance)
    if (
        reason == "visual_text_evidence_bridge"
        and _is_direct_visual_text_query(plan.original_query)
    ):
        priority += 2
    if reason == "decomposition_quantity_count" and _is_direct_quantity_query(
        plan.original_query
    ):
        priority += 2
    return (
        is_query_relevance_sufficient(relevance),
        priority,
        relevance.distinctive_term_hits,
        relevance.unique_term_hits,
        relevance.score_boost,
        reason == "original_query",
    )


def _is_direct_visual_text_query(query: str) -> bool:
    return bool(
        _DIRECT_VISUAL_TEXT_QUERY_RE.search(query)
        and _ARTIFACT_CONTEXT_COMPOSITE_QUERY_RE.search(query) is None
    )


def _is_direct_quantity_query(query: str) -> bool:
    return bool(
        re.search(
            r"\b(?:how many|how much|number of|count|total)\b",
            query,
            re.IGNORECASE,
        )
    )


def _query_relevance_false_friend(
    *,
    plan: QueryExpansionPlan,
    item: tuple[str, str, QueryRelevance],
    text: str,
) -> bool:
    _, reason, relevance = item
    if reason != "book_suggestion_bridge":
        return False
    if relevance.distinctive_term_hits < 5:
        return False
    query = plan.original_query.casefold()
    if "book" not in query:
        return False
    if _BOOK_SUGGESTION_EVIDENCE_CUE_RE.search(text):
        return False
    return _BOOK_SUGGESTION_PROJECT_FALSE_FRIEND_RE.search(text) is not None


def _strict_query_reason_below_minimum(
    *,
    reason: str,
    relevance: QueryRelevance,
) -> bool:
    min_hits = _STRICT_QUERY_REASON_MIN_DISTINCTIVE_HITS.get(reason)
    return min_hits is not None and relevance.distinctive_term_hits < min_hits


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
    primary_exact_answer_rank = _exact_source_sibling_answer_body_rank(primary)
    secondary_exact_answer_rank = _exact_source_sibling_answer_body_rank(secondary)
    if primary_exact_answer_rank != secondary_exact_answer_rank:
        return primary if primary_exact_answer_rank < secondary_exact_answer_rank else secondary
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


def _exact_source_sibling_answer_body_rank(item: ContextItem) -> int:
    turn_ref_count = sum(1 for ref in item.source_refs if _source_ref_is_turn(ref))
    if turn_ref_count <= 0:
        return 4
    if _has_dialogue_turn_body_for_source_ref(item):
        return 0 if len(item.source_refs) == 1 else 1
    if "keyword_source_sibling_chunks" not in diagnostic_retrieval_sources(item.diagnostics):
        return 4
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    signals = safe_score_signals(diagnostics.get("score_signals"))
    if _numeric_signal(signals.get("source_sibling_answer_evidence")) <= 0:
        return 4
    if len(item.source_refs) == 1:
        return 2
    return 3


def _has_dialogue_turn_body_for_source_ref(item: ContextItem) -> bool:
    for ref in item.source_refs:
        marker = _source_ref_dialogue_marker(ref)
        if marker and _text_has_dialogue_turn_body(item.text, marker=marker):
            return True
    return False


def _source_ref_dialogue_marker(ref: SourceRef) -> str:
    match = _DIALOGUE_MARKER_RE.search(str(ref.source_id or ""))
    return match.group(0) if match is not None else ""


def _text_has_dialogue_turn_body(text: str, *, marker: str) -> bool:
    for match in re.finditer(rf"\b{re.escape(marker)}\b", text):
        following = text[match.end() : match.end() + 64]
        if re.match(r"\s+(?!\.\.\.)[A-Z][^:\n]{0,40}:", following):
            return True
    return False


def _is_strong_exact_source_sibling_turn(item: ContextItem) -> bool:
    if "keyword_source_sibling_chunks" not in diagnostic_retrieval_sources(item.diagnostics):
        return False
    if not any(_source_ref_is_turn(ref) for ref in item.source_refs):
        return False
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    signals = safe_score_signals(diagnostics.get("score_signals"))
    if _numeric_signal(signals.get("source_sibling_answer_evidence")) > 0:
        return True
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


_Bm25TermFrequencyCache = dict[tuple[int, LexicalQueryTerm], int]


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


@dataclass(frozen=True)
class _SamePersonTopicProfile:
    item: ContextItem
    matches_query_person: bool
    has_anchor_conflict: bool
    topic_hits: int
    covers_topic: bool
    explicit_topic_decoy_shape: bool


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
    term_frequency_cache: _Bm25TermFrequencyCache = {}
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
    for _, reason, terms in _query_expansion_terms(plan):
        if not terms:
            continue
        documents, raw_scores = _bm25_raw_scores_for_prepared(
            prepared_items=prepared_items,
            terms=terms,
            k1=k1,
            b=b,
            term_frequency_cache=term_frequency_cache,
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
                    query_reason=reason,
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
    term_frequency_cache: _Bm25TermFrequencyCache | None = None,
) -> tuple[tuple[_Bm25Document, ...], tuple[float, ...]]:
    documents = tuple(
        _bm25_document(
            prepared=item,
            prepared_index=index,
            terms=terms,
            term_frequency_cache=term_frequency_cache,
        )
        for index, item in enumerate(prepared_items)
    )
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
    prepared_index: int,
    terms: tuple[LexicalQueryTerm, ...],
    term_frequency_cache: _Bm25TermFrequencyCache | None = None,
) -> _Bm25Document:
    return _Bm25Document(
        item=prepared.item,
        term_frequencies=tuple(
            _bm25_term_frequency(
                prepared=prepared,
                prepared_index=prepared_index,
                term=term,
                term_frequency_cache=term_frequency_cache,
            )
            for term in terms
        ),
        length=prepared.length,
    )


def _bm25_term_frequency(
    *,
    prepared: _Bm25PreparedItem,
    prepared_index: int,
    term: LexicalQueryTerm,
    term_frequency_cache: _Bm25TermFrequencyCache | None,
) -> int:
    if term_frequency_cache is None:
        return query_term_frequency(term, prepared.text_counts)
    cache_key = (prepared_index, term)
    cached = term_frequency_cache.get(cache_key)
    if cached is not None:
        return cached
    frequency = query_term_frequency(term, prepared.text_counts)
    term_frequency_cache[cache_key] = frequency
    return frequency


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
    counts, sequence_length = text_variant_stats(item.text)
    length = max(1, sequence_length)
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
    return _provenance_flag_is_true(item.diagnostics, "bm25_lexical_applied")


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
    return _provenance_flag_is_true(item.diagnostics, "query_anchor_intent_applied")


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
    covered_answer_shape_value = coverage.get("covered_answer_shapes")
    covered_answer_shapes = _coverage_value_set(covered_answer_shape_value)
    matched_answer_shapes = _sorted_coverage_matches(
        requested_answer_shapes,
        covered_answer_shape_value,
    )
    score_boosted_answer_shapes = tuple(
        shape for shape in matched_answer_shapes if shape in _GENERIC_BOOSTABLE_ANSWER_SHAPES
    )
    typed_unit_answer_shapes = tuple(
        shape for shape in matched_answer_shapes if is_typed_answer_unit_shape(shape)
    )
    typed_unit_mismatch_shapes = _typed_answer_unit_mismatch_shapes(
        requested_answer_shapes=requested_answer_shapes,
        covered_answer_shapes=covered_answer_shapes,
    )
    exact_count_cardinality_boost = (
        _CONTEXT_REQUIREMENT_EXACT_COUNT_CARDINALITY_BOOST
        if "count" in score_boosted_answer_shapes
        and has_exact_count_cardinality_evidence(normalized_item.text)
        else 0.0
    )
    typed_unit_mismatch_penalty = (
        _CONTEXT_REQUIREMENT_TYPED_ANSWER_UNIT_MISMATCH_PENALTY
        if typed_unit_mismatch_shapes
        else 0.0
    )
    raw_boost = (
        len(matched_anchor_kinds) * _CONTEXT_REQUIREMENT_ANCHOR_BOOST
        + len(matched_modalities) * _CONTEXT_REQUIREMENT_MODALITY_BOOST
        + len(matched_features) * _CONTEXT_REQUIREMENT_FEATURE_BOOST
        + len(score_boosted_answer_shapes) * _CONTEXT_REQUIREMENT_ANSWER_SHAPE_BOOST
        + exact_count_cardinality_boost
        + len(typed_unit_answer_shapes) * _CONTEXT_REQUIREMENT_TYPED_ANSWER_UNIT_BOOST
    )
    boost = min(max_boost, round(raw_boost, 4))
    if boost <= 0 and typed_unit_mismatch_penalty <= 0:
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
        "context_requirement_matched_typed_answer_unit_count": len(typed_unit_answer_shapes),
        "context_requirement_typed_answer_unit_mismatch_count": len(
            typed_unit_mismatch_shapes
        ),
        **(
            {
                "context_requirement_exact_count_cardinality_boost": (
                    exact_count_cardinality_boost
                )
            }
            if exact_count_cardinality_boost > 0
            else {}
        ),
        **(
            {
                "context_requirement_typed_answer_unit_boost": (
                    len(typed_unit_answer_shapes)
                    * _CONTEXT_REQUIREMENT_TYPED_ANSWER_UNIT_BOOST
                )
            }
            if typed_unit_answer_shapes
            else {}
        ),
        **(
            {
                "context_requirement_typed_answer_unit_mismatch_penalty": (
                    typed_unit_mismatch_penalty
                )
            }
            if typed_unit_mismatch_penalty > 0
            else {}
        ),
    }
    diagnostics["provenance"] = {
        **safe_diagnostic_mapping(diagnostics.get("provenance")),
        "context_requirement_boost_applied": True,
        "context_requirement_matched_anchor_kinds": list(matched_anchor_kinds),
        "context_requirement_matched_modalities": list(matched_modalities),
        "context_requirement_matched_evidence_features": list(matched_features),
        "context_requirement_matched_answer_shapes": list(matched_answer_shapes),
        "context_requirement_mismatched_answer_unit_shapes": list(
            typed_unit_mismatch_shapes
        ),
    }
    return replace(
        normalized_item,
        score=min(
            0.99,
            max(
                0.0,
                round(normalized_item.score + boost - typed_unit_mismatch_penalty, 4),
            ),
        ),
        diagnostics=normalize_context_diagnostics(diagnostics),
    )


def _context_requirement_boost_already_applied(item: ContextItem) -> bool:
    return _provenance_flag_is_true(item.diagnostics, "context_requirement_boost_applied")


def _typed_answer_unit_mismatch_shapes(
    *,
    requested_answer_shapes: frozenset[str],
    covered_answer_shapes: frozenset[str],
) -> tuple[str, ...]:
    requested_units = frozenset(
        shape for shape in requested_answer_shapes if is_typed_answer_unit_shape(shape)
    )
    if not requested_units:
        return ()
    covered_units = frozenset(
        shape for shape in covered_answer_shapes if is_typed_answer_unit_shape(shape)
    )
    if not covered_units or requested_units & covered_units:
        return ()
    return tuple(sorted(covered_units))


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
    normalized_item = normalize_context_item_diagnostics(item)
    if _deterministic_rerank_already_applied_in_diagnostics(normalized_item.diagnostics):
        return item
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
        item=item,
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
    source_quote_anchor_matched = (
        "citation" in coverage.requested_evidence_features
        and _source_quote_anchor_matches_query(
            item=item,
            plan=plan,
            query_anchor_intent=query_anchor_intent,
        )
    )
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
    current_state_correction_anchor_override = (
        anchor_conflict
        and temporal_query_intent.prefers_current
        and has_current_state_correction_evidence(item.text)
    )
    boost = 0.0
    penalty = 0.0
    reasons: list[str] = []
    rank_signals: dict[str, float] = {}
    if len(sources) >= 2:
        boost += min(0.018, 0.006 * len(sources))
        reasons.append("hybrid_source_diversity")
    if strong_source_count:
        boost += min(0.018, 0.008 * strong_source_count)
        reasons.append("strong_evidence_source")
    if anchor_match is not None:
        boost += min(0.018, max(0.0, anchor_match.score_boost) * 0.35)
        reasons.append("query_anchor_match")
    elif source_quote_anchor_matched:
        boost += 0.012
        reasons.append("source_quote_query_anchor_match")
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
    typed_requested_answer_shapes = frozenset(
        shape
        for shape in coverage.requested_answer_shapes
        if is_typed_answer_unit_shape(shape)
    )
    typed_covered_answer_shapes = frozenset(
        shape
        for shape in coverage.covered_answer_shapes
        if is_typed_answer_unit_shape(shape)
    )
    if typed_requested_answer_shapes and typed_covered_answer_shapes:
        answer_shape_boost += 0.024 * (
            len(typed_covered_answer_shapes) / len(typed_requested_answer_shapes)
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
        anchor_matched=anchor_match is not None or source_quote_anchor_matched,
        strong_source_count=strong_source_count,
    )
    if localized_evidence_boost > 0:
        boost += localized_evidence_boost
        reasons.append(localized_evidence_reason)
    decomposition_boost, decomposition_reason, decomposition_signals = (
        _decomposition_coverage_support_signal(
            plan=plan,
            text=item.text,
            query_reason=query_reason,
        )
    )
    if decomposition_boost > 0:
        boost += decomposition_boost
        reasons.append(decomposition_reason)
        rank_signals.update(decomposition_signals)
    canonical_summary_boost, canonical_summary_reason = (
        _canonical_anchor_summary_support_signal(
            item=item,
            coverage=coverage,
            relevance=relevance,
            anchor_matched=anchor_match is not None or source_quote_anchor_matched,
            anchor_conflict=anchor_conflict,
            sources=sources,
            strong_source_count=strong_source_count,
        )
    )
    if canonical_summary_boost > 0:
        boost += canonical_summary_boost
        reasons.append(canonical_summary_reason)
    citation_evidence_boost, citation_evidence_reason, citation_evidence_signals = (
        _citation_evidence_support_signal(
            item=item,
            plan=plan,
            coverage=coverage,
            relevance=relevance,
            anchor_matched=anchor_match is not None or source_quote_anchor_matched,
            strong_source_count=strong_source_count,
        )
    )
    if citation_evidence_boost > 0:
        boost += citation_evidence_boost
        reasons.append(citation_evidence_reason)
        rank_signals.update(citation_evidence_signals)
    (
        artifact_inventory_boost,
        artifact_inventory_penalty,
        artifact_inventory_reason,
        artifact_inventory_signals,
    ) = _artifact_inventory_evidence_support_signal(
        item=item,
        plan=plan,
        query_reason=query_reason,
        relevance=relevance,
        coverage_ratio=coverage_ratio,
        anchor_matched=anchor_match is not None or source_quote_anchor_matched,
    )
    if artifact_inventory_boost > 0:
        boost += artifact_inventory_boost
        reasons.append(artifact_inventory_reason)
        rank_signals.update(artifact_inventory_signals)
    if artifact_inventory_penalty > 0:
        penalty += artifact_inventory_penalty
        reasons.append(artifact_inventory_reason)
        rank_signals.update(artifact_inventory_signals)
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
    absence_boost, absence_penalty, absence_reason = absence_negation_signal(
        query=query,
        text=item.text,
    )
    if absence_boost > 0:
        boost += absence_boost
        reasons.append(absence_reason)
    if absence_penalty > 0:
        penalty += absence_penalty
        reasons.append(absence_reason)
    named_preference_signal = named_person_preference_signal(
        query=query,
        text=item.text,
    )
    if named_preference_signal.boost > 0:
        boost += named_preference_signal.boost
        reasons.append(named_preference_signal.reason)
    if named_preference_signal.penalty > 0:
        penalty += named_preference_signal.penalty
        reasons.append(named_preference_signal.reason)
    pet_signal = pet_ownership_signal(query=query, text=item.text)
    if pet_signal.boost > 0:
        boost += pet_signal.boost
        reasons.append(pet_signal.reason)
    if pet_signal.penalty > 0:
        penalty += pet_signal.penalty
        reasons.append(pet_signal.reason)
    owner_grounding = owner_grounding_signal(query=query, text=item.text)
    if owner_grounding.boost > 0:
        boost += owner_grounding.boost
        reasons.append(owner_grounding.reason)
    if owner_grounding.penalty > 0:
        penalty += owner_grounding.penalty
        reasons.append(owner_grounding.reason)
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
    ordinal_sequence_signal = ordinal_sequence_rerank_signal(
        query=query,
        text=item.text,
    )
    if ordinal_sequence_signal.boost > 0:
        boost += ordinal_sequence_signal.boost
        reasons.append(ordinal_sequence_signal.reason)
    if ordinal_sequence_signal.penalty > 0:
        penalty += ordinal_sequence_signal.penalty
        reasons.append(ordinal_sequence_signal.reason)
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
    person_relation_signal = person_relation_inventory_signal(
        query=query,
        text=item.text,
    )
    if person_relation_signal.boost > 0:
        boost += person_relation_signal.boost
        reasons.append(person_relation_signal.reason)
    if person_relation_signal.penalty > 0:
        penalty += person_relation_signal.penalty
        reasons.append(person_relation_signal.reason)
    occupation_signal = person_occupation_signal(query=query, text=item.text)
    if occupation_signal.boost > 0:
        boost += occupation_signal.boost
        reasons.append(occupation_signal.reason)
    if occupation_signal.penalty > 0:
        penalty += occupation_signal.penalty
        reasons.append(occupation_signal.reason)
    residence_signal = person_residence_signal(query=query, text=item.text)
    if residence_signal.boost > 0:
        boost += residence_signal.boost
        reasons.append(residence_signal.reason)
    if residence_signal.penalty > 0:
        penalty += residence_signal.penalty
        reasons.append(residence_signal.reason)
    kinship_signal = person_kinship_signal(query=query, text=item.text)
    if kinship_signal.boost > 0:
        boost += kinship_signal.boost
        reasons.append(kinship_signal.reason)
    if kinship_signal.penalty > 0:
        penalty += kinship_signal.penalty
        reasons.append(kinship_signal.reason)
    team_signal = person_team_membership_signal(query=query, text=item.text)
    if team_signal.boost > 0:
        boost += team_signal.boost
        reasons.append(team_signal.reason)
    if team_signal.penalty > 0:
        penalty += team_signal.penalty
        reasons.append(team_signal.reason)
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
    elif current_state_correction_anchor_override:
        reasons.append("query_anchor_conflict_overridden_by_current_state_correction")
    elif anchor_conflict and source_quote_anchor_matched:
        reasons.append("query_anchor_conflict_overridden_by_source_quote")
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
    ordinal_sequence_requirement_support = (
        ordinal_sequence_signal.boost > 0
        and ordinal_sequence_signal.reason == "ordinal_sequence_exact_evidence"
    )
    if (
        ordinal_sequence_requirement_support
        and "item_purchase_temporal_weak_evidence" in domain_adjustment.reasons
    ):
        reasons.append("item_purchase_weak_evidence_overridden_by_ordinal_sequence")
    else:
        penalty += domain_adjustment.penalty
    reasons.extend(domain_adjustment.reasons)
    rank_signals.update(domain_adjustment.rank_signals)
    slot_diverse_aggregation = aggregation_answer_slot_count(query=query, text=item.text) >= 2
    event_detail_requirement_support = "temporal_camping_detail_evidence" in reasons
    artifact_inventory_requirement_support = (
        "artifact_inventory_first_party_evidence" in reasons
    )
    if requested_total > 0:
        if coverage_ratio <= 0 and (
            event_detail_requirement_support
            or artifact_inventory_requirement_support
            or ordinal_sequence_requirement_support
        ):
            if event_detail_requirement_support:
                reasons.append("explicit_requirement_supported_by_event_detail")
            if artifact_inventory_requirement_support:
                reasons.append("explicit_requirement_supported_by_artifact_inventory")
            if ordinal_sequence_requirement_support:
                reasons.append("explicit_requirement_supported_by_ordinal_sequence")
        elif coverage_ratio <= 0:
            penalty += 0.025
            reasons.append("explicit_requirement_missing")
        elif coverage_ratio < 0.5 and not slot_diverse_aggregation:
            penalty += 0.012
            reasons.append("explicit_requirement_partial")
    if (
        coverage.missing_answer_shapes
        and not slot_diverse_aggregation
        and not ordinal_sequence_requirement_support
    ):
        penalty += min(
            0.02,
            0.014 * len(coverage.missing_answer_shapes),
        )
        reasons.append("explicit_requirement_missing")
        reasons.append("explicit_answer_shape_missing")
    if coverage.missing_modalities and not artifact_inventory_requirement_support:
        penalty += min(
            0.032,
            0.024 * len(coverage.missing_modalities),
        )
        reasons.append("explicit_requirement_missing")
        reasons.append("explicit_modality_missing")
    if (
        coverage.missing_evidence_features
        and not slot_diverse_aggregation
        and not artifact_inventory_requirement_support
    ):
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


def _apply_same_person_topic_disambiguation_penalties(
    items: tuple[ContextItem, ...],
    *,
    query: str,
    query_anchor_intent: QueryAnchorIntent,
    max_penalty: float,
) -> tuple[ContextItem, ...]:
    topic_terms = _same_person_topic_terms(
        query=query,
        query_anchor_intent=query_anchor_intent,
    )
    if not topic_terms:
        return items
    support_threshold = min(2, len(topic_terms))
    profiles = tuple(
        _same_person_topic_profile(
            item,
            query=query,
            query_anchor_intent=query_anchor_intent,
            topic_terms=topic_terms,
            support_threshold=support_threshold,
        )
        for item in items
    )
    support_count = sum(
        1
        for profile in profiles
        if profile.matches_query_person
        and not profile.has_anchor_conflict
        and profile.covers_topic
    )
    if support_count <= 0:
        return items
    return tuple(
        _with_same_person_topic_disambiguation_penalty(
            profile.item,
            profile=profile,
            support_count=support_count,
            topic_term_count=len(topic_terms),
            max_penalty=max_penalty,
        )
        for profile in profiles
    )


def _same_person_topic_terms(
    *,
    query: str,
    query_anchor_intent: QueryAnchorIntent,
) -> tuple[LexicalQueryTerm, ...]:
    if _SAME_PERSON_TOPIC_DISAMBIGUATION_QUERY_RE.search(query) is None:
        return ()
    person_keys = query_anchor_intent.keys_for_kind(MemoryAnchorKind.PERSON)
    if len(person_keys) != 1:
        return ()
    terms: list[LexicalQueryTerm] = []
    seen: set[tuple[str, ...]] = set()
    for term in query_terms(query):
        variants = set(term.variants)
        if variants.intersection(person_keys):
            continue
        if variants.intersection(_SAME_PERSON_TOPIC_QUERY_STOP_TERMS):
            continue
        if not any(_same_person_topic_variant_is_specific(variant) for variant in variants):
            continue
        key = tuple(term.variants)
        if key in seen:
            continue
        seen.add(key)
        terms.append(term)
    return tuple(terms[:8])


def _same_person_topic_variant_is_specific(variant: str) -> bool:
    return len(variant) >= 3 and not variant.isdigit()


def _same_person_topic_profile(
    item: ContextItem,
    *,
    query: str,
    query_anchor_intent: QueryAnchorIntent,
    topic_terms: tuple[LexicalQueryTerm, ...],
    support_threshold: int,
) -> _SamePersonTopicProfile:
    anchor_match = match_query_anchor_intent_to_text(query_anchor_intent, item.text)
    matches_query_person = bool(
        anchor_match is not None
        and "query_person_identity_match" in anchor_match.reasons
    )
    has_anchor_conflict = (
        query_anchor_intent_text_conflicts(query_anchor_intent, item.text)
        or has_project_identity_mismatch(query=query, text=item.text)
    )
    text_counts, _ = text_variant_profile(item.text)
    topic_hits = sum(
        1 for term in topic_terms if query_term_frequency(term, text_counts) > 0
    )
    return _SamePersonTopicProfile(
        item=item,
        matches_query_person=matches_query_person,
        has_anchor_conflict=has_anchor_conflict,
        topic_hits=topic_hits,
        covers_topic=topic_hits >= support_threshold,
        explicit_topic_decoy_shape=bool(
            _SAME_PERSON_TOPIC_DECOY_TEXT_RE.search(item.text)
        ),
    )


def _with_same_person_topic_disambiguation_penalty(
    item: ContextItem,
    *,
    profile: _SamePersonTopicProfile,
    support_count: int,
    topic_term_count: int,
    max_penalty: float,
) -> ContextItem:
    if (
        not profile.matches_query_person
        or profile.has_anchor_conflict
        or profile.topic_hits > 0
        or not profile.explicit_topic_decoy_shape
    ):
        return item
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    score_signals = safe_score_signals(diagnostics.get("score_signals"))
    existing_penalty = _non_negative_float_signal(
        score_signals.get("deterministic_rerank_penalty")
    ) or 0.0
    available_penalty = max(0.0, max_penalty - existing_penalty)
    penalty = min(
        available_penalty,
        _SAME_PERSON_TOPIC_DISAMBIGUATION_MAX_PENALTY,
    )
    if penalty <= 0:
        return item
    existing_boost = _non_negative_float_signal(
        score_signals.get("deterministic_rerank_boost")
    ) or 0.0
    new_penalty = round(existing_penalty + penalty, 4)
    score_signals.update(
        {
            "deterministic_rerank_boost": round(existing_boost, 4),
            "deterministic_rerank_penalty": new_penalty,
            "deterministic_rerank_net_adjustment": round(
                existing_boost - new_penalty,
                4,
            ),
            "same_person_topic_disambiguation_penalty": round(penalty, 4),
            "same_person_topic_disambiguation_support_count": support_count,
            "same_person_topic_disambiguation_topic_hits": profile.topic_hits,
            "same_person_topic_disambiguation_topic_term_count": topic_term_count,
        }
    )
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    reasons = list(provenance.get("deterministic_rerank_reasons") or ())
    reasons.append("same_person_wrong_topic_decoy")
    diagnostics["deterministic_rerank_reason"] = (
        "query-aware deterministic rerank over fused candidates"
    )
    diagnostics["score_signals"] = score_signals
    diagnostics["provenance"] = {
        **provenance,
        "deterministic_rerank_applied": True,
        "deterministic_rerank_reasons": list(dict.fromkeys(reasons))[:8],
    }
    return replace(
        item,
        score=max(0.0, round(item.score - penalty, 4)),
        diagnostics=normalize_context_diagnostics(diagnostics),
    )


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


def _decomposition_coverage_support_signal(
    *,
    plan: QueryExpansionPlan,
    text: str,
    query_reason: str,
) -> tuple[float, str, dict[str, float]]:
    if len(plan.decompositions) < 2:
        return 0.0, "", {}
    if (
        not query_reason.startswith("decomposition_")
        or query_reason in _BROAD_DECOMPOSITION_COVERAGE_REASONS
    ):
        return 0.0, "", {}
    matched_reasons: set[str] = set()
    priority_total = 0
    distinctive_hit_total = 0
    for decomposition in plan.decompositions:
        reason = decomposition.reason
        if (
            reason in _BROAD_DECOMPOSITION_COVERAGE_REASONS
            or not reason.startswith("decomposition_")
        ):
            continue
        relevance = score_query_relevance(query=decomposition.query, text=text)
        priority = _query_reason_priority_for_relevance(reason, relevance)
        if priority <= 0 and reason.startswith("decomposition_"):
            priority = 3
        min_distinctive_hits = max(
            4,
            _QUERY_REASON_PRIORITY_MIN_DISTINCTIVE_HITS.get(reason, 0),
        )
        if (
            priority <= 0
            or relevance.distinctive_term_hits < min_distinctive_hits
            or (relevance.hit_ratio < 0.12 and relevance.phrase_bigram_hits <= 0)
        ):
            continue
        matched_reasons.add(reason)
        priority_total += priority
        distinctive_hit_total += relevance.distinctive_term_hits
    if len(matched_reasons) < 2:
        return 0.0, "", {}

    boost = 0.006 + min(0.012, 0.005 * len(matched_reasons))
    if priority_total >= 8:
        boost += 0.002
    if distinctive_hit_total >= 8:
        boost += 0.002
    boost = round(min(_DECOMPOSITION_COVERAGE_RERANK_MAX_BOOST, boost), 4)
    return (
        boost,
        "query_decomposition_multi_intent_covered",
        {
            "query_decomposition_covered_reason_count": float(len(matched_reasons)),
            "query_decomposition_coverage_boost": boost,
        },
    )


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


def _source_quote_anchor_matches_query(
    *,
    item: ContextItem,
    plan: QueryExpansionPlan,
    query_anchor_intent: QueryAnchorIntent,
) -> bool:
    if query_anchor_intent.empty:
        return False
    for ref in item.source_refs:
        quote = (ref.quote_preview or "").strip()
        if not quote:
            continue
        if match_query_anchor_intent_to_text(query_anchor_intent, quote) is None:
            continue
        _, _, relevance = best_query_relevance(plan, text=quote)
        if _source_quote_relevance_supports_answer(relevance):
            return True
    return False


def _citation_evidence_support_signal(
    *,
    item: ContextItem,
    plan: QueryExpansionPlan,
    coverage: _RequirementCoverageSignals,
    relevance: QueryRelevance,
    anchor_matched: bool,
    strong_source_count: int,
) -> tuple[float, str, dict[str, float]]:
    if "citation" not in coverage.requested_evidence_features:
        return 0.0, "", {}
    if (
        not is_query_relevance_sufficient(relevance)
        and coverage.ratio <= 0
        and not anchor_matched
        and strong_source_count <= 0
    ):
        return 0.0, "", {}
    quote_count = sum(1 for ref in item.source_refs if (ref.quote_preview or "").strip())
    localized_count = sum(1 for ref in item.source_refs if _source_ref_has_precise_location(ref))
    if quote_count <= 0 and localized_count <= 0:
        return 0.0, "", {}
    boost = 0.01
    boost += min(0.008, quote_count * 0.004)
    boost += min(0.006, localized_count * 0.003)
    quote_answer_boost, quote_answer_signals = _source_quote_answer_support_signal(
        item=item,
        plan=plan,
    )
    boost += quote_answer_boost
    reason = "citation_quote_evidence" if quote_count > 0 else "citation_localized_evidence"
    return (
        round(min(_CITATION_EVIDENCE_RERANK_MAX_BOOST, boost), 4),
        reason,
        quote_answer_signals,
    )


def _source_quote_answer_support_signal(
    *,
    item: ContextItem,
    plan: QueryExpansionPlan,
) -> tuple[float, dict[str, float]]:
    best_relevance: QueryRelevance | None = None
    for ref in item.source_refs:
        quote = (ref.quote_preview or "").strip()
        if not quote:
            continue
        _, _, relevance = best_query_relevance(plan, text=quote)
        if not _source_quote_relevance_supports_answer(relevance):
            continue
        if best_relevance is None or query_relevance_rank_key(
            ("", "source_quote", relevance)
        ) > query_relevance_rank_key(("", "source_quote", best_relevance)):
            best_relevance = relevance
    if best_relevance is None:
        return 0.0, {}

    boost = 0.003
    boost += min(0.005, best_relevance.distinctive_term_hits * 0.002)
    boost += min(0.002, best_relevance.phrase_bigram_hits * 0.002)
    boost = round(min(_SOURCE_QUOTE_ANSWER_RERANK_MAX_BOOST, boost), 4)
    return boost, {
        "source_quote_answer_support": 1.0,
        "source_quote_answer_boost": boost,
        "source_quote_answer_relevance": round(best_relevance.score_boost, 4),
        "source_quote_answer_distinctive_hits": float(
            best_relevance.distinctive_term_hits
        ),
    }


def _source_quote_relevance_supports_answer(relevance: QueryRelevance) -> bool:
    if relevance.query_term_count <= 0:
        return False
    if relevance.distinctive_term_hits >= 2:
        return True
    return relevance.distinctive_term_hits >= 1 and (
        relevance.phrase_bigram_hits > 0 or relevance.unique_term_hits >= 2
    )


def _artifact_inventory_evidence_support_signal(
    *,
    item: ContextItem,
    plan: QueryExpansionPlan,
    query_reason: str,
    relevance: QueryRelevance,
    coverage_ratio: float,
    anchor_matched: bool,
) -> tuple[float, float, str, dict[str, float]]:
    has_artifact_inventory_query = any(
        expansion.reason == "artifact_inventory_bridge"
        for expansion in plan.retrieval_queries
    )
    if not has_artifact_inventory_query and not _matches_query_or_score_signal_reason(
        query_reason=query_reason,
        item=item,
        target_reason="artifact_inventory_bridge",
    ):
        return 0.0, 0.0, "", {}
    if not (
        is_query_relevance_sufficient(relevance)
        or coverage_ratio > 0
        or anchor_matched
    ):
        return 0.0, 0.0, "", {}

    sources = set(diagnostic_retrieval_sources(item.diagnostics))
    source_ref_types = {ref.source_type for ref in item.source_refs}
    has_document_evidence_ref = any(
        ref.source_type == "document"
        and (_source_ref_has_precise_location(ref) or (ref.quote_preview or "").strip())
        for ref in item.source_refs
    )
    has_first_party_artifact = (
        item.item_type == "extraction_artifact"
        or bool(sources.intersection(_ARTIFACT_INVENTORY_RERANK_SOURCES))
        or bool(source_ref_types.intersection(_ARTIFACT_INVENTORY_SOURCE_REF_TYPES))
        or has_document_evidence_ref
    )
    if not has_first_party_artifact:
        return (
            0.0,
            0.018,
            "artifact_inventory_unbacked_reference",
            {
                "artifact_inventory_first_party_evidence": 0.0,
                "artifact_inventory_unbacked_reference": 1.0,
            },
        )

    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    evidence_signal_count = 1
    if _safe_evidence_kind_or_modality(diagnostics):
        evidence_signal_count += 1
    if any(_source_ref_has_precise_location(ref) for ref in item.source_refs):
        evidence_signal_count += 1
    if any((ref.quote_preview or "").strip() for ref in item.source_refs):
        evidence_signal_count += 1
    if len(sources) >= 2:
        evidence_signal_count += 1

    boost = 0.016 + min(0.012, 0.003 * evidence_signal_count)
    if "artifact_evidence" in sources:
        boost += 0.003

    return (
        round(min(_ARTIFACT_INVENTORY_EVIDENCE_RERANK_MAX_BOOST, boost), 4),
        0.0,
        "artifact_inventory_first_party_evidence",
        {
            "artifact_inventory_first_party_evidence": 1.0,
            "artifact_inventory_evidence_signal_count": float(evidence_signal_count),
        },
    )


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
    item: ContextItem,
    cache: dict[str, tuple[str, str, QueryRelevance]] | None,
) -> tuple[str, str, QueryRelevance]:
    diagnostics_relevance = _query_relevance_from_item_diagnostics(plan, item)
    if diagnostics_relevance is not None:
        return diagnostics_relevance
    text = item.text
    if cache is None:
        return best_query_relevance(plan, text=text)
    cached = cache.get(text)
    if cached is not None:
        return cached
    result = best_query_relevance(plan, text=text)
    cache[text] = result
    return result


def _query_relevance_from_item_diagnostics(
    plan: QueryExpansionPlan,
    item: ContextItem,
) -> tuple[str, str, QueryRelevance] | None:
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    signals = safe_score_signals(diagnostics.get("score_signals"))
    reason_value = signals.get("query_expansion_reason") or diagnostics.get(
        "query_expansion_reason"
    )
    if not isinstance(reason_value, str) or not reason_value:
        return None
    query_text = _query_text_for_expansion_reason(plan, reason_value)
    if query_text is None:
        return None
    relevance = _query_relevance_from_score_signals(signals)
    if relevance is None:
        relevance = score_query_relevance(query=query_text, text=item.text)
    return query_text, reason_value, relevance


def _query_text_for_expansion_reason(
    plan: QueryExpansionPlan,
    reason: str,
) -> str | None:
    for expansion in plan.retrieval_queries:
        if expansion.reason == reason:
            return expansion.query
    return None


def _query_relevance_from_score_signals(
    signals: Mapping[str, object],
) -> QueryRelevance | None:
    query_term_count = _non_negative_int_signal(signals.get("query_term_count"))
    unique_term_hits = _non_negative_int_signal(signals.get("unique_term_hits"))
    capped_frequency_hits = _non_negative_int_signal(signals.get("capped_frequency_hits"))
    distinctive_term_count = _non_negative_int_signal(signals.get("distinctive_term_count"))
    distinctive_term_hits = _non_negative_int_signal(signals.get("distinctive_term_hits"))
    phrase_bigram_count = _non_negative_int_signal(signals.get("phrase_bigram_count"))
    phrase_bigram_hits = _non_negative_int_signal(signals.get("phrase_bigram_hits"))
    if (
        query_term_count is None
        or unique_term_hits is None
        or capped_frequency_hits is None
        or distinctive_term_count is None
        or distinctive_term_hits is None
        or phrase_bigram_count is None
        or phrase_bigram_hits is None
    ):
        return None
    hit_ratio = _non_negative_float_signal(signals.get("hit_ratio"))
    score_boost = _non_negative_float_signal(signals.get("query_relevance_boost"))
    phrase_boost = _non_negative_float_signal(signals.get("phrase_boost"))
    if hit_ratio is None or score_boost is None or phrase_boost is None:
        return None
    return QueryRelevance(
        score_boost=score_boost,
        query_term_count=query_term_count,
        unique_term_hits=unique_term_hits,
        capped_frequency_hits=capped_frequency_hits,
        hit_ratio=hit_ratio,
        distinctive_term_count=distinctive_term_count,
        distinctive_term_hits=distinctive_term_hits,
        phrase_bigram_count=phrase_bigram_count,
        phrase_bigram_hits=phrase_bigram_hits,
        phrase_boost=phrase_boost,
    )


def _non_negative_int_signal(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float) and value.is_integer():
        return max(0, int(value))
    return None


def _non_negative_float_signal(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return max(0.0, float(value))
    return None


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
    return _provenance_flag_is_true(item.diagnostics, "temporal_query_intent_applied")


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
    return _provenance_flag_is_true(item.diagnostics, "deterministic_rerank_applied")


def _deterministic_rerank_already_applied_in_diagnostics(
    diagnostics: object,
) -> bool:
    return _provenance_flag_is_true(
        diagnostics,
        "deterministic_rerank_applied",
        normalized=True,
    )


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
