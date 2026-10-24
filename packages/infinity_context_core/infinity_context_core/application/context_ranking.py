"""Compatibility entrypoints and batch orchestration for context ranking.

Policies have one bounded owner. Explicit callbacks preserve the supported legacy
lexical/relevance/normalization seams without mutable global forwarding.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache

from infinity_context_core.application.context_anchor_intent_ranking import (
    _QUERY_ANCHOR_INTENT_MAX_BOOST as _QUERY_ANCHOR_INTENT_MAX_BOOST,
)
from infinity_context_core.application.context_anchor_intent_ranking import (
    _query_anchor_intent_already_applied as _query_anchor_intent_already_applied,
)
from infinity_context_core.application.context_anchor_intent_ranking import (
    _with_query_anchor_intent_boost as _with_query_anchor_intent_boost,
)
from infinity_context_core.application.context_anchor_intent_ranking import (
    apply_query_anchor_intent_boosts as apply_query_anchor_intent_boosts,
)
from infinity_context_core.application.context_bm25_ranking import (
    _BM25_B as _BM25_B,
)
from infinity_context_core.application.context_bm25_ranking import (
    _BM25_K1 as _BM25_K1,
)
from infinity_context_core.application.context_bm25_ranking import (
    _BM25_MAX_BOOST as _BM25_MAX_BOOST,
)
from infinity_context_core.application.context_bm25_ranking import (
    _best_bm25_query_matches as _owner_best_bm25_query_matches,
)
from infinity_context_core.application.context_bm25_ranking import (
    _bm25_document as _owner_bm25_document,
)
from infinity_context_core.application.context_bm25_ranking import (
    _bm25_lexical_already_applied as _bm25_lexical_already_applied,
)
from infinity_context_core.application.context_bm25_ranking import (
    _bm25_prepared_item as _bm25_prepared_item,
)
from infinity_context_core.application.context_bm25_ranking import (
    _bm25_query_coverage as _bm25_query_coverage,
)
from infinity_context_core.application.context_bm25_ranking import (
    _bm25_raw_scores as _owner_bm25_raw_scores,
)
from infinity_context_core.application.context_bm25_ranking import (
    _bm25_raw_scores_for_prepared as _owner_bm25_raw_scores_for_prepared,
)
from infinity_context_core.application.context_bm25_ranking import (
    _bm25_score as _bm25_score,
)
from infinity_context_core.application.context_bm25_ranking import (
    _bm25_term_frequency as _owner_bm25_term_frequency,
)
from infinity_context_core.application.context_bm25_ranking import (
    _Bm25Document as _Bm25Document,
)
from infinity_context_core.application.context_bm25_ranking import (
    _Bm25PreparedItem as _Bm25PreparedItem,
)
from infinity_context_core.application.context_bm25_ranking import (
    _Bm25QueryMatch as _Bm25QueryMatch,
)
from infinity_context_core.application.context_bm25_ranking import (
    _Bm25TermFrequencyCache as _Bm25TermFrequencyCache,
)
from infinity_context_core.application.context_bm25_ranking import (
    _query_expansion_terms_for_signature as _bm25_expansion_terms_for_signature,
)
from infinity_context_core.application.context_bm25_ranking import (
    _QueryExpansionTerms as _QueryExpansionTerms,
)
from infinity_context_core.application.context_bm25_ranking import (
    _select_bm25_query_match as _select_bm25_query_match,
)
from infinity_context_core.application.context_bm25_ranking import (
    _with_bm25_lexical_boost as _with_bm25_lexical_boost,
)
from infinity_context_core.application.context_bm25_ranking import (
    apply_bm25_lexical_boosts as _owner_apply_bm25_lexical_boosts,
)
from infinity_context_core.application.context_bm25_ranking import (
    apply_query_plan_bm25_lexical_boosts as _owner_apply_query_plan_bm25_lexical_boosts,
)
from infinity_context_core.application.context_conflicting_evidence_rerank import (
    apply_conflicting_evidence_currentness_rerank,
)
from infinity_context_core.application.context_deterministic_rerank import (
    _DETERMINISTIC_RERANK_MAX_BOOST as _DETERMINISTIC_RERANK_MAX_BOOST,
)
from infinity_context_core.application.context_deterministic_rerank import (
    _DETERMINISTIC_RERANK_MAX_PENALTY as _DETERMINISTIC_RERANK_MAX_PENALTY,
)
from infinity_context_core.application.context_deterministic_rerank import (
    _deterministic_rerank_already_applied as _deterministic_rerank_already_applied,
)
from infinity_context_core.application.context_deterministic_rerank import (
    _deterministic_rerank_already_applied_in_diagnostics as _rerank_applied_in_diagnostics,
)
from infinity_context_core.application.context_deterministic_rerank import (
    _strong_artifact_evidence_score_floor as _strong_artifact_evidence_score_floor,
)
from infinity_context_core.application.context_deterministic_rerank import (
    _with_deterministic_rerank_adjustment as _owner_with_deterministic_rerank_adjustment,
)
from infinity_context_core.application.context_deterministic_rerank_policy import (
    _STRONG_EVIDENCE_RERANK_SOURCES as _STRONG_EVIDENCE_RERANK_SOURCES,
)
from infinity_context_core.application.context_deterministic_rerank_policy import (
    _deterministic_rerank_signals as _owner_deterministic_rerank_signals,
)
from infinity_context_core.application.context_deterministic_rerank_policy import (
    _DeterministicRerankSignals as _DeterministicRerankSignals,
)
from infinity_context_core.application.context_diagnostics import normalize_context_diagnostics
from infinity_context_core.application.context_domain_rerank_signals import (
    has_multi_evidence_aggregation_candidate,
)
from infinity_context_core.application.context_internal_diagnostics import provenance_flag_is_true
from infinity_context_core.application.context_keyword_ranking import (
    _ACTIVITY_DERIVED_SUMMARY_SOURCE_BOOST as _ACTIVITY_DERIVED_SUMMARY_SOURCE_BOOST,
)
from infinity_context_core.application.context_keyword_ranking import (
    _ACTIVITY_DERIVED_SUMMARY_SOURCE_CAP as _ACTIVITY_DERIVED_SUMMARY_SOURCE_CAP,
)
from infinity_context_core.application.context_keyword_ranking import (
    _ACTIVITY_DERIVED_SUMMARY_STRONG_HITS as _ACTIVITY_DERIVED_SUMMARY_STRONG_HITS,
)
from infinity_context_core.application.context_keyword_ranking import (
    _ACTIVITY_EVIDENCE_SOURCE_SUFFIXES as _ACTIVITY_EVIDENCE_SOURCE_SUFFIXES,
)
from infinity_context_core.application.context_keyword_ranking import (
    _ACTIVITY_OBSERVATION_MIN_DISTINCTIVE_HITS as _ACTIVITY_OBSERVATION_MIN_DISTINCTIVE_HITS,
)
from infinity_context_core.application.context_keyword_ranking import (
    _ATTRIBUTE_EVIDENCE_SOURCE_SUFFIXES as _ATTRIBUTE_EVIDENCE_SOURCE_SUFFIXES,
)
from infinity_context_core.application.context_keyword_ranking import (
    _DERIVED_SUMMARY_SOURCE_BOOST as _DERIVED_SUMMARY_SOURCE_BOOST,
)
from infinity_context_core.application.context_keyword_ranking import (
    _DERIVED_SUMMARY_SOURCE_CAP as _DERIVED_SUMMARY_SOURCE_CAP,
)
from infinity_context_core.application.context_keyword_ranking import (
    _DERIVED_SUMMARY_SOURCE_SUFFIXES as _DERIVED_SUMMARY_SOURCE_SUFFIXES,
)
from infinity_context_core.application.context_keyword_ranking import (
    _PRECISE_EVIDENCE_SOURCE_REASONS as _PRECISE_EVIDENCE_SOURCE_REASONS,
)
from infinity_context_core.application.context_keyword_ranking import (
    _TURN_ONLY_EVIDENCE_SOURCE_REASONS as _TURN_ONLY_EVIDENCE_SOURCE_REASONS,
)
from infinity_context_core.application.context_keyword_ranking import (
    apply_keyword_chunk_source_score_boost as apply_keyword_chunk_source_score_boost,
)
from infinity_context_core.application.context_keyword_ranking import (
    keyword_chunk_score as keyword_chunk_score,
)
from infinity_context_core.application.context_keyword_ranking import (
    keyword_chunk_source_score_boost as keyword_chunk_source_score_boost,
)
from infinity_context_core.application.context_keyword_ranking import (
    query_expansion_reason_priority as query_expansion_reason_priority,
)
from infinity_context_core.application.context_lexical import (
    LexicalQueryTerm,
    query_term_frequency,
    query_terms,
    text_variant_profile,
)
from infinity_context_core.application.context_query_expansion import QueryExpansionPlan
from infinity_context_core.application.context_query_intent import QueryAnchorIntent
from infinity_context_core.application.context_query_relevance_ranking import (
    _ARTIFACT_CONTEXT_COMPOSITE_QUERY_RE as _ARTIFACT_CONTEXT_COMPOSITE_QUERY_RE,
)
from infinity_context_core.application.context_query_relevance_ranking import (
    _BOOK_SUGGESTION_EVIDENCE_CUE_RE as _BOOK_SUGGESTION_EVIDENCE_CUE_RE,
)
from infinity_context_core.application.context_query_relevance_ranking import (
    _BOOK_SUGGESTION_PROJECT_FALSE_FRIEND_RE as _BOOK_SUGGESTION_PROJECT_FALSE_FRIEND_RE,
)
from infinity_context_core.application.context_query_relevance_ranking import (
    _DIRECT_VISUAL_TEXT_QUERY_RE as _DIRECT_VISUAL_TEXT_QUERY_RE,
)
from infinity_context_core.application.context_query_relevance_ranking import (
    _STRICT_QUERY_REASON_MIN_DISTINCTIVE_HITS as _STRICT_QUERY_REASON_MIN_DISTINCTIVE_HITS,
)
from infinity_context_core.application.context_query_relevance_ranking import (
    _is_direct_quantity_query as _is_direct_quantity_query,
)
from infinity_context_core.application.context_query_relevance_ranking import (
    _is_direct_visual_text_query as _is_direct_visual_text_query,
)
from infinity_context_core.application.context_query_relevance_ranking import (
    _query_reason_priority_for_relevance as _query_reason_priority_for_relevance,
)
from infinity_context_core.application.context_query_relevance_ranking import (
    _query_relevance_false_friend as _query_relevance_false_friend,
)
from infinity_context_core.application.context_query_relevance_ranking import (
    _query_relevance_rank_key_for_plan as _query_relevance_rank_key_for_plan,
)
from infinity_context_core.application.context_query_relevance_ranking import (
    _strict_query_reason_below_minimum as _strict_query_reason_below_minimum,
)
from infinity_context_core.application.context_query_relevance_ranking import (
    best_query_relevance_for_plan as _owner_best_query_relevance,
)
from infinity_context_core.application.context_query_relevance_ranking import (
    query_relevance_rank_key as query_relevance_rank_key,
)
from infinity_context_core.application.context_rank_dedupe import (
    _DIALOGUE_MARKER_RE as _DIALOGUE_MARKER_RE,
)
from infinity_context_core.application.context_rank_dedupe import (
    _DUPLICATE_SOURCE_SCORE_TOLERANCE as _DUPLICATE_SOURCE_SCORE_TOLERANCE,
)
from infinity_context_core.application.context_rank_dedupe import (
    _context_item_reason_priority as _context_item_reason_priority,
)
from infinity_context_core.application.context_rank_dedupe import (
    _exact_source_sibling_answer_body_rank as _exact_source_sibling_answer_body_rank,
)
from infinity_context_core.application.context_rank_dedupe import (
    _has_dialogue_turn_body_for_source_ref as _has_dialogue_turn_body_for_source_ref,
)
from infinity_context_core.application.context_rank_dedupe import (
    _hybrid_boost as _hybrid_boost,
)
from infinity_context_core.application.context_rank_dedupe import (
    _is_strong_exact_source_sibling_turn as _is_strong_exact_source_sibling_turn,
)
from infinity_context_core.application.context_rank_dedupe import (
    _merge_context_items as _merge_context_items,
)
from infinity_context_core.application.context_rank_dedupe import (
    _merge_source_refs as _merge_source_refs,
)
from infinity_context_core.application.context_rank_dedupe import (
    _preferred_merge_body_item as _preferred_merge_body_item,
)
from infinity_context_core.application.context_rank_dedupe import (
    _should_replace_context_item as _should_replace_context_item,
)
from infinity_context_core.application.context_rank_dedupe import (
    _source_ref_dialogue_marker as _source_ref_dialogue_marker,
)
from infinity_context_core.application.context_rank_dedupe import (
    _source_ref_is_turn as _source_ref_is_turn,
)
from infinity_context_core.application.context_rank_dedupe import (
    _text_has_dialogue_turn_body as _text_has_dialogue_turn_body,
)
from infinity_context_core.application.context_rank_dedupe import (
    dedupe_rank_items as dedupe_rank_items,
)
from infinity_context_core.application.context_rank_fusion import (
    _DEFAULT_RRF_SOURCE_WEIGHTS as _DEFAULT_RRF_SOURCE_WEIGHTS,
)
from infinity_context_core.application.context_rank_fusion import (
    _RRF_MAX_BOOST as _RRF_MAX_BOOST,
)
from infinity_context_core.application.context_rank_fusion import (
    _RRF_MAX_RANK_PER_SOURCE as _RRF_MAX_RANK_PER_SOURCE,
)
from infinity_context_core.application.context_rank_fusion import (
    _RRF_RANK_CONSTANT as _RRF_RANK_CONSTANT,
)
from infinity_context_core.application.context_rank_fusion import (
    _bounded_source_weight as _bounded_source_weight,
)
from infinity_context_core.application.context_rank_fusion import (
    _rank_fusion_already_applied as _rank_fusion_already_applied,
)
from infinity_context_core.application.context_rank_fusion import (
    _ranked_items_by_retrieval_source as _ranked_items_by_retrieval_source,
)
from infinity_context_core.application.context_rank_fusion import (
    _with_rank_fusion_boost as _with_rank_fusion_boost,
)
from infinity_context_core.application.context_rank_fusion import (
    apply_rank_fusion_boosts as apply_rank_fusion_boosts,
)
from infinity_context_core.application.context_rank_fusion import (
    reciprocal_rank_fusion_scores as reciprocal_rank_fusion_scores,
)
from infinity_context_core.application.context_relevance import QueryRelevance
from infinity_context_core.application.context_requirement_coverage import (
    context_requirement_coverage,
)
from infinity_context_core.application.context_requirement_ranking import (
    _CONTEXT_REQUIREMENT_ANCHOR_BOOST as _CONTEXT_REQUIREMENT_ANCHOR_BOOST,
)
from infinity_context_core.application.context_requirement_ranking import (
    _CONTEXT_REQUIREMENT_ANSWER_SHAPE_BOOST as _CONTEXT_REQUIREMENT_ANSWER_SHAPE_BOOST,
)
from infinity_context_core.application.context_requirement_ranking import (
    _CONTEXT_REQUIREMENT_EXACT_COUNT_CARDINALITY_BOOST as _requirement_exact_count_boost,
)
from infinity_context_core.application.context_requirement_ranking import (
    _CONTEXT_REQUIREMENT_FEATURE_BOOST as _CONTEXT_REQUIREMENT_FEATURE_BOOST,
)
from infinity_context_core.application.context_requirement_ranking import (
    _CONTEXT_REQUIREMENT_MAX_BOOST as _CONTEXT_REQUIREMENT_MAX_BOOST,
)
from infinity_context_core.application.context_requirement_ranking import (
    _CONTEXT_REQUIREMENT_MODALITY_BOOST as _CONTEXT_REQUIREMENT_MODALITY_BOOST,
)
from infinity_context_core.application.context_requirement_ranking import (
    _CONTEXT_REQUIREMENT_TYPED_ANSWER_UNIT_BOOST as _CONTEXT_REQUIREMENT_TYPED_ANSWER_UNIT_BOOST,
)
from infinity_context_core.application.context_requirement_ranking import (
    _CONTEXT_REQUIREMENT_TYPED_ANSWER_UNIT_MISMATCH_PENALTY as _typed_answer_unit_mismatch_penalty,
)
from infinity_context_core.application.context_requirement_ranking import (
    _GENERIC_BOOSTABLE_ANSWER_SHAPES as _GENERIC_BOOSTABLE_ANSWER_SHAPES,
)
from infinity_context_core.application.context_requirement_ranking import (
    _context_requirement_boost_already_applied as _context_requirement_boost_already_applied,
)
from infinity_context_core.application.context_requirement_ranking import (
    _sorted_coverage_matches as _sorted_coverage_matches,
)
from infinity_context_core.application.context_requirement_ranking import (
    _typed_answer_unit_mismatch_shapes as _typed_answer_unit_mismatch_shapes,
)
from infinity_context_core.application.context_requirement_ranking import (
    _with_context_requirement_boost as _with_context_requirement_boost,
)
from infinity_context_core.application.context_requirement_ranking import (
    apply_context_requirement_boosts as apply_context_requirement_boosts,
)
from infinity_context_core.application.context_requirement_signals import (
    RequirementCoverageSignals as _coverage_signal_type,
)
from infinity_context_core.application.context_requirement_signals import (
    _coverage_int as _coverage_int,
)
from infinity_context_core.application.context_requirement_signals import (
    _coverage_ratio as _coverage_ratio,
)
from infinity_context_core.application.context_requirement_signals import (
    _coverage_value_set as _coverage_value_set,
)
from infinity_context_core.application.context_requirement_signals import (
    _item_requirement_coverage_signals as _item_requirement_coverage_signals,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _ACTIVITY_OWNER_MATCH_BOOST as _ACTIVITY_OWNER_MATCH_BOOST,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _ACTIVITY_OWNER_MISMATCH_PENALTY as _ACTIVITY_OWNER_MISMATCH_PENALTY,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _DIALOGUE_SPEAKER_RE as _DIALOGUE_SPEAKER_RE,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _EVENT_PARTICIPATION_QUERY_RE as _EVENT_PARTICIPATION_QUERY_RE,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _EVENT_TERM_QUERY_RE as _EVENT_TERM_QUERY_RE,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _MISSED_EVENT_TEXT_RE as _MISSED_EVENT_TEXT_RE,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _POSITIVE_ACTIVITY_TEXT_RE as _POSITIVE_ACTIVITY_TEXT_RE,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _POSITIVE_EVENT_PARTICIPATION_TEXT_RE as _POSITIVE_EVENT_PARTICIPATION_TEXT_RE,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _POSITIVE_EVENT_TEXT_RE as _POSITIVE_EVENT_TEXT_RE,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _POST_EVENT_ACTIVITY_TIMING_CONTEXT_RE as _POST_EVENT_ACTIVITY_TIMING_CONTEXT_RE,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _SELF_MISSED_EVENT_TEXT_RE as _SELF_MISSED_EVENT_TEXT_RE,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _SHOE_USAGE_CONTEXT_RE as _SHOE_USAGE_CONTEXT_RE,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _SPEAKER_LABEL_RE as _SPEAKER_LABEL_RE,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _VOLUNTEER_CAREER_CONTEXT_RE as _VOLUNTEER_CAREER_CONTEXT_RE,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _VOLUNTEER_CAREER_EVIDENCE_RE as _VOLUNTEER_CAREER_EVIDENCE_RE,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _VOLUNTEER_CAREER_STRONG_NON_TURN_EVIDENCE_RE as _VOLUNTEER_CAREER_STRONG_NON_TURN_EVIDENCE_RE,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _action_role_confirms_requested_relation as _action_role_confirms_requested_relation,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _activity_owner_signal as _activity_owner_signal,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _activity_source_sibling_noise as _activity_source_sibling_noise,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _allergy_condition_weak_evidence as _allergy_condition_weak_evidence,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _capped_source_sibling_low_signal as _capped_source_sibling_low_signal,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _dialogue_speaker_confirms_query_anchor as _dialogue_speaker_confirms_query_anchor,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _dialogue_speaker_labels as _dialogue_speaker_labels,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _event_participation_mismatch as _event_participation_mismatch,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _event_participation_positive_match as _event_participation_positive_match,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _event_participation_source_sibling_noise as _event_participation_source_sibling_noise,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _is_item_purchase_temporal_answer_evidence as _is_item_purchase_temporal_answer_evidence,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _is_post_event_activity_timing_candidate as _is_post_event_activity_timing_candidate,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _is_shoe_usage_candidate as _is_shoe_usage_candidate,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _item_source_is_turn as _item_source_is_turn,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _item_temporal_hint_code as _item_temporal_hint_code,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _matches_query_or_score_signal_reason as _matches_query_or_score_signal_reason,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _normalized_dialogue_label as _normalized_dialogue_label,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _patriotic_service_weak_evidence as _patriotic_service_weak_evidence,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _positive_signal as _positive_signal,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _post_event_activity_timing_exact_evidence as _post_event_activity_timing_exact_evidence,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _post_event_activity_timing_weak_evidence as _post_event_activity_timing_weak_evidence,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _query_person_labels as _query_person_labels,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _running_reason_weak_evidence as _running_reason_weak_evidence,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _shoe_usage_exact_evidence as _shoe_usage_exact_evidence,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _shoe_usage_weak_evidence as _shoe_usage_weak_evidence,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _temporal_answer_signal as _temporal_answer_signal,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _temporal_query_signal_already_applied as _temporal_query_signal_already_applied,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _volunteer_career_broad_evidence as _volunteer_career_broad_evidence,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _volunteer_career_exact_turn_evidence as _volunteer_career_exact_turn_evidence,
)
from infinity_context_core.application.context_rerank_domain_heuristics import (
    _volunteer_career_weak_evidence as _volunteer_career_weak_evidence,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _ARTIFACT_INVENTORY_EVIDENCE_RERANK_MAX_BOOST as _ARTIFACT_INVENTORY_EVIDENCE_RERANK_MAX_BOOST,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _ARTIFACT_INVENTORY_RERANK_SOURCES as _ARTIFACT_INVENTORY_RERANK_SOURCES,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _ARTIFACT_INVENTORY_SOURCE_REF_TYPES as _ARTIFACT_INVENTORY_SOURCE_REF_TYPES,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _BROAD_DECOMPOSITION_COVERAGE_REASONS as _BROAD_DECOMPOSITION_COVERAGE_REASONS,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _CANONICAL_ANCHOR_SUMMARY_RERANK_MAX_BOOST as _CANONICAL_ANCHOR_SUMMARY_RERANK_MAX_BOOST,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _CITATION_EVIDENCE_RERANK_MAX_BOOST as _CITATION_EVIDENCE_RERANK_MAX_BOOST,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _DECOMPOSITION_COVERAGE_RERANK_MAX_BOOST as _DECOMPOSITION_COVERAGE_RERANK_MAX_BOOST,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _LOCALIZED_EVIDENCE_RERANK_MAX_BOOST as _LOCALIZED_EVIDENCE_RERANK_MAX_BOOST,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _SOURCE_QUOTE_ANSWER_RERANK_MAX_BOOST as _SOURCE_QUOTE_ANSWER_RERANK_MAX_BOOST,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _artifact_inventory_evidence_support_signal as _artifact_inventory_evidence_support_signal,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _canonical_anchor_summary_support_signal as _canonical_anchor_summary_support_signal,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _citation_evidence_support_signal as _owner_citation_evidence_support_signal,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _decomposition_coverage_support_signal as _decomposition_coverage_support_signal,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _has_canonical_anchor_profile_evidence as _has_canonical_anchor_profile_evidence,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _is_canonical_anchor_source as _is_canonical_anchor_source,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _localized_evidence_support_signal as _localized_evidence_support_signal,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _safe_evidence_kind_or_modality as _safe_evidence_kind_or_modality,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _source_quote_anchor_matches_query as _owner_source_quote_anchor_matches_query,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _source_quote_answer_support_signal as _owner_source_quote_answer_support_signal,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _source_quote_relevance_supports_answer as _source_quote_relevance_supports_answer,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _source_ref_has_precise_location as _source_ref_has_precise_location,
)
from infinity_context_core.application.context_rerank_evidence_signals import (
    _source_ref_location_features as _source_ref_location_features,
)
from infinity_context_core.application.context_rerank_relevance import (
    _best_query_relevance_for_rerank as _owner_best_query_relevance_for_rerank,
)
from infinity_context_core.application.context_rerank_relevance import (
    _is_long_query_weak_overlap as _is_long_query_weak_overlap,
)
from infinity_context_core.application.context_rerank_relevance import (
    _non_negative_float_signal as _non_negative_float_signal,
)
from infinity_context_core.application.context_rerank_relevance import (
    _non_negative_int_signal as _non_negative_int_signal,
)
from infinity_context_core.application.context_rerank_relevance import (
    _numeric_signal as _numeric_signal,
)
from infinity_context_core.application.context_rerank_relevance import (
    _query_relevance_from_item_diagnostics as _query_relevance_from_item_diagnostics,
)
from infinity_context_core.application.context_rerank_relevance import (
    _query_relevance_from_score_signals as _query_relevance_from_score_signals,
)
from infinity_context_core.application.context_rerank_relevance import (
    _query_text_for_expansion_reason as _query_text_for_expansion_reason,
)
from infinity_context_core.application.context_same_person_disambiguation import (
    _SAME_PERSON_TOPIC_DECOY_TEXT_RE as _SAME_PERSON_TOPIC_DECOY_TEXT_RE,
)
from infinity_context_core.application.context_same_person_disambiguation import (
    _SAME_PERSON_TOPIC_DISAMBIGUATION_MAX_PENALTY as _SAME_PERSON_TOPIC_DISAMBIGUATION_MAX_PENALTY,
)
from infinity_context_core.application.context_same_person_disambiguation import (
    _SAME_PERSON_TOPIC_DISAMBIGUATION_QUERY_RE as _SAME_PERSON_TOPIC_DISAMBIGUATION_QUERY_RE,
)
from infinity_context_core.application.context_same_person_disambiguation import (
    _SAME_PERSON_TOPIC_QUERY_STOP_TERMS as _SAME_PERSON_TOPIC_QUERY_STOP_TERMS,
)
from infinity_context_core.application.context_same_person_disambiguation import (
    _apply_same_person_topic_disambiguation_penalties as _same_person_disambiguation,
)
from infinity_context_core.application.context_same_person_disambiguation import (
    _same_person_topic_profile as _same_person_topic_profile,
)
from infinity_context_core.application.context_same_person_disambiguation import (
    _same_person_topic_terms as _same_person_topic_terms,
)
from infinity_context_core.application.context_same_person_disambiguation import (
    _same_person_topic_variant_is_specific as _same_person_topic_variant_is_specific,
)
from infinity_context_core.application.context_same_person_disambiguation import (
    _SamePersonTopicProfile as _SamePersonTopicProfile,
)
from infinity_context_core.application.context_same_person_disambiguation import (
    _with_same_person_topic_disambiguation_penalty as _same_person_topic_penalty,
)
from infinity_context_core.application.context_speaker_disambiguation import (
    apply_attributed_speaker_exact_name_disambiguation,
)
from infinity_context_core.application.context_temporal_query import (
    TemporalQueryIntent,
    build_temporal_query_intent,
)
from infinity_context_core.application.dto import ContextItem


def apply_bm25_lexical_boosts(
    items: tuple[ContextItem, ...],
    *,
    query: str,
    k1: float = _BM25_K1,
    b: float = _BM25_B,
    max_boost: float = _BM25_MAX_BOOST,
) -> tuple[ContextItem, ...]:
    return _owner_apply_bm25_lexical_boosts(
        items,
        query=query,
        k1=k1,
        b=b,
        max_boost=max_boost,
        query_terms_fn=query_terms,
        query_term_frequency_fn=query_term_frequency,
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
    return _owner_apply_query_plan_bm25_lexical_boosts(
        items,
        plan=plan,
        bm25_text_stats_cache=bm25_text_stats_cache,
        k1=k1,
        b=b,
        max_boost=max_boost,
        query_expansion_terms_fn=_query_expansion_terms,
        query_term_frequency_fn=query_term_frequency,
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
    adjusted = _apply_same_person_topic_disambiguation_penalties(
        adjusted,
        query=query,
        query_anchor_intent=query_anchor_intent,
        max_penalty=max_penalty,
    )
    return apply_conflicting_evidence_currentness_rerank(
        adjusted,
        query=query,
        max_boost=max_boost,
        max_penalty=max_penalty,
    )


# Explicit aliases preserve long historical names without indirection.
_deterministic_rerank_already_applied_in_diagnostics = _rerank_applied_in_diagnostics
_CONTEXT_REQUIREMENT_EXACT_COUNT_CARDINALITY_BOOST = _requirement_exact_count_boost
_CONTEXT_REQUIREMENT_TYPED_ANSWER_UNIT_MISMATCH_PENALTY = _typed_answer_unit_mismatch_penalty
_apply_same_person_topic_disambiguation_penalties = _same_person_disambiguation
_with_same_person_topic_disambiguation_penalty = _same_person_topic_penalty


@lru_cache(maxsize=512)
def _query_expansion_terms_for_signature(
    signature: tuple[tuple[str, str], ...],
) -> _QueryExpansionTerms:
    return _bm25_expansion_terms_for_signature(signature, query_terms_fn=query_terms)


def _query_expansion_terms(plan: QueryExpansionPlan) -> _QueryExpansionTerms:
    return _query_expansion_terms_for_signature(
        tuple((expansion.query, expansion.reason) for expansion in plan.retrieval_queries)
    )


def best_query_relevance(plan: QueryExpansionPlan, *, text: str) -> tuple[str, str, QueryRelevance]:
    return _owner_best_query_relevance(
        plan,
        text=text,
        query_expansion_terms_fn=_query_expansion_terms,
        text_variant_profile_fn=text_variant_profile,
    )


def _best_bm25_query_matches(
    *,
    items: tuple[ContextItem, ...],
    plan: QueryExpansionPlan,
    k1: float,
    b: float,
    bm25_text_stats_cache: dict[str, tuple[Mapping[str, int], int]] | None = None,
) -> tuple[_Bm25QueryMatch, ...]:
    return _owner_best_bm25_query_matches(
        items=items,
        plan=plan,
        k1=k1,
        b=b,
        bm25_text_stats_cache=bm25_text_stats_cache,
        query_expansion_terms_fn=_query_expansion_terms,
        query_term_frequency_fn=query_term_frequency,
    )


def _bm25_raw_scores(
    *, items: tuple[ContextItem, ...], terms: tuple[LexicalQueryTerm, ...], k1: float, b: float
) -> tuple[tuple[_Bm25Document, ...], tuple[float, ...]]:
    return _owner_bm25_raw_scores(
        items=items, terms=terms, k1=k1, b=b, query_term_frequency_fn=query_term_frequency
    )


def _bm25_raw_scores_for_prepared(
    *,
    prepared_items: tuple[_Bm25PreparedItem, ...],
    terms: tuple[LexicalQueryTerm, ...],
    k1: float,
    b: float,
    term_frequency_cache: _Bm25TermFrequencyCache | None = None,
) -> tuple[tuple[_Bm25Document, ...], tuple[float, ...]]:
    return _owner_bm25_raw_scores_for_prepared(
        prepared_items=prepared_items,
        terms=terms,
        k1=k1,
        b=b,
        term_frequency_cache=term_frequency_cache,
        query_term_frequency_fn=query_term_frequency,
    )


def _bm25_document(
    *,
    prepared: _Bm25PreparedItem,
    prepared_index: int,
    terms: tuple[LexicalQueryTerm, ...],
    term_frequency_cache: _Bm25TermFrequencyCache | None = None,
) -> _Bm25Document:
    return _owner_bm25_document(
        prepared=prepared,
        prepared_index=prepared_index,
        terms=terms,
        term_frequency_cache=term_frequency_cache,
        query_term_frequency_fn=query_term_frequency,
    )


def _bm25_term_frequency(
    *,
    prepared: _Bm25PreparedItem,
    prepared_index: int,
    term: LexicalQueryTerm,
    term_frequency_cache: _Bm25TermFrequencyCache | None,
) -> int:
    return _owner_bm25_term_frequency(
        prepared=prepared,
        prepared_index=prepared_index,
        term=term,
        term_frequency_cache=term_frequency_cache,
        query_term_frequency_fn=query_term_frequency,
    )


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
    return _owner_with_deterministic_rerank_adjustment(
        item,
        query=query,
        plan=plan,
        query_anchor_intent=query_anchor_intent,
        temporal_query_intent=temporal_query_intent,
        requested_total=requested_total,
        has_multi_evidence_aggregation_candidate=has_multi_evidence_aggregation_candidate,
        query_relevance_cache=query_relevance_cache,
        max_boost=max_boost,
        max_penalty=max_penalty,
        best_query_relevance_fn=best_query_relevance,
        normalize_context_diagnostics_fn=normalize_context_diagnostics,
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
    return _owner_deterministic_rerank_signals(
        item,
        query=query,
        plan=plan,
        query_anchor_intent=query_anchor_intent,
        temporal_query_intent=temporal_query_intent,
        requested_total=requested_total,
        has_multi_evidence_aggregation_candidate=has_multi_evidence_aggregation_candidate,
        query_relevance_cache=query_relevance_cache,
        max_boost=max_boost,
        max_penalty=max_penalty,
        best_query_relevance_fn=best_query_relevance,
    )


def _best_query_relevance_for_rerank(
    plan: QueryExpansionPlan,
    *,
    item: ContextItem,
    cache: dict[str, tuple[str, str, QueryRelevance]] | None,
) -> tuple[str, str, QueryRelevance]:
    return _owner_best_query_relevance_for_rerank(
        plan, item=item, cache=cache, best_query_relevance_fn=best_query_relevance
    )


def _provenance_flag_is_true(
    diagnostics: object,
    flag: str,
    *,
    normalized: bool = False,
) -> bool:
    del normalized
    return provenance_flag_is_true(diagnostics, flag)


def _source_quote_anchor_matches_query(
    *, item: ContextItem, plan: QueryExpansionPlan, query_anchor_intent: QueryAnchorIntent
) -> bool:
    return _owner_source_quote_anchor_matches_query(
        item=item,
        plan=plan,
        query_anchor_intent=query_anchor_intent,
        best_query_relevance_fn=best_query_relevance,
    )


def _citation_evidence_support_signal(
    *,
    item: ContextItem,
    plan: QueryExpansionPlan,
    coverage: _RequirementCoverageSignals,
    relevance: QueryRelevance,
    anchor_matched: bool,
    strong_source_count: int,
) -> tuple[float, str, dict[str, float]]:
    return _owner_citation_evidence_support_signal(
        item=item,
        plan=plan,
        coverage=coverage,
        relevance=relevance,
        anchor_matched=anchor_matched,
        strong_source_count=strong_source_count,
        best_query_relevance_fn=best_query_relevance,
    )


def _source_quote_answer_support_signal(
    *, item: ContextItem, plan: QueryExpansionPlan
) -> tuple[float, dict[str, float]]:
    return _owner_source_quote_answer_support_signal(
        item=item, plan=plan, best_query_relevance_fn=best_query_relevance
    )


_RequirementCoverageSignals = _coverage_signal_type
