"""Bounded context diagnostics policy."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from infinity_context_core.application.context_item_evidence import (
    with_context_item_evidence_diagnostics,
)
from infinity_context_core.application.context_quality import retrieval_quality_summary
from infinity_context_core.application.context_requirement_coverage import (
    sanitize_context_requirement_coverage,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.application.safe_payload import safe_metadata, safe_metadata_text

_MAX_RETRIEVAL_SOURCES = 8
_MAX_RETRIEVAL_SOURCE_CANDIDATES = 64
_MAX_RETRIEVAL_TRACE_ENTRIES = 8
_MAX_DIAGNOSTIC_MAPPING_ITEMS = 24
_MAX_BUNDLE_DIAGNOSTIC_MAPPING_ITEMS = 64
_MAX_DIAGNOSTIC_LIST_ITEMS = 8
_MAX_DIAGNOSTIC_KEY_CHARS = 80
_MAX_DIAGNOSTIC_STRING_CHARS = 240
_MAX_RANKING_REASON_CHARS = 240
_MAX_EVIDENCE_LOCATION_GAPS = 8
_SAFE_RECALL_DIAGNOSTIC_KEYS = (
    "provider",
    "adapter_name",
    "projection_version",
    "collection",
    "dataset_id",
)
_SAFE_CONTEXT_LINK_DIAGNOSTIC_KEYS = (
    "context_link_id",
    "context_link_relation_type",
    "context_link_confidence",
    "temporal_relation_id",
    "temporal_replacement_for_fact_id",
)
_SAFE_REVIEW_TEXT_DIAGNOSTIC_KEYS = (
    "review_recommended_action",
    "review_recommended_resolution_action",
    "review_default_resolution",
    "review_risk",
    "review_recommendation_confidence",
    "review_policy_version",
)
_SAFE_REVIEW_BOOL_DIAGNOSTIC_KEYS = (
    "review_requires_review",
    "review_auto_merge_eligible",
)
_SAFE_REVIEW_LIST_DIAGNOSTIC_KEYS = (
    "review_recommendation_reason_codes",
)
_SAFE_ANCHOR_TEXT_DIAGNOSTIC_KEYS = (
    "anchor_kind",
    "normalized_key",
    "identity_scope",
    "identity_key",
    "canonical_key",
    "person_canonical_key",
    "project_canonical_key",
    "organization_canonical_key",
    "event_type",
    "event_type_canonical",
    "event_participant_label",
    "event_participant_relation",
    "event_participant_canonical_key",
    "event_project_label",
    "event_project_relation",
    "event_project_canonical_key",
    "event_temporal_phrase",
    "event_temporal_hint_code",
    "event_temporal_quantity",
    "event_temporal_unit",
)
_SAFE_ANCHOR_LIST_DIAGNOSTIC_KEYS = (
    "event_identity_terms",
    "alias_identity_terms",
)
_CONTEXT_REQUIREMENT_SCORE_SIGNAL_KEYS = (
    "context_requirement_boost",
    "context_requirement_matched_anchor_kind_count",
    "context_requirement_matched_modality_count",
    "context_requirement_matched_feature_count",
)
_DETERMINISTIC_RERANK_SCORE_SIGNAL_KEYS = (
    "book_author_preference_world_evidence",
    "cause_awareness_answer_evidence",
    "choice_reason_answer_evidence",
    "future_plan_timing_answer_evidence",
    "item_purchase_object_evidence",
    "symbol_importance_visual_evidence",
    "friend_place_shelter_anchor_evidence",
    "deterministic_rerank_boost",
    "deterministic_rerank_penalty",
    "deterministic_rerank_net_adjustment",
    "deterministic_rerank_source_count",
    "deterministic_rerank_strong_source_count",
    "deterministic_rerank_requirement_coverage",
    "deterministic_rerank_query_reason",
    "source_quote_answer_support",
    "source_quote_answer_boost",
    "source_quote_answer_relevance",
    "source_quote_answer_distinctive_hits",
)
_SOURCE_SIBLING_SCORE_SIGNAL_KEYS = (
    "exact_source_repair",
    "exact_source_repair_date_anchor",
    "source_sibling_answer_evidence",
    "source_sibling_dialogue_visual_reference",
    "source_sibling_group_level_seed",
    "source_sibling_visual_continuation",
    "source_sibling_score_cap_applied",
    "source_sibling_group_boost",
    "source_sibling_after_seed",
    "source_sibling_closeness",
    "source_sibling_turn_distance",
    "source_sibling_group_priority",
)
_CONTEXT_REQUIREMENT_PROVENANCE_LIST_KEYS = (
    "context_requirement_matched_anchor_kinds",
    "context_requirement_matched_modalities",
    "context_requirement_matched_evidence_features",
)
_DETERMINISTIC_RERANK_PROVENANCE_LIST_KEYS = (
    "deterministic_rerank_reasons",
)
_SOURCE_SIBLING_PROVENANCE_BOOL_KEYS = (
    "source_sibling_answer_evidence",
    "source_sibling_dialogue_visual_reference",
    "source_sibling_group_level_seed",
    "source_sibling_visual_continuation",
    "source_sibling_score_cap_applied",
)
_SOURCE_SIBLING_PROVENANCE_NUMBER_KEYS = (
    "source_sibling_turn_delta",
    "source_sibling_turn_distance",
    "source_sibling_group_priority",
)
_BUNDLE_COUNTER_KEYS = (
    "facts_considered",
    "anchors_considered",
    "anchor_lookup_keys_considered",
    "anchors_loaded_by_lookup",
    "anchors_used",
    "anchors_used_by_query_intent",
    "anchors_dropped_by_query_intent_conflict",
    "anchor_relation_candidates_considered",
    "anchor_relation_items_used",
    "query_anchor_hint_count",
    "query_anchor_person_hint_count",
    "query_anchor_event_hint_count",
    "query_anchor_project_hint_count",
    "query_anchor_organization_hint_count",
    "query_anchor_temporal_hint_count",
    "query_anchor_event_type_hint_count",
    "keyword_chunks_considered",
    "keyword_query_count",
    "keyword_chunks_dropped_by_relevance",
    "keyword_neighbor_chunks_considered",
    "keyword_neighbor_chunks_used",
    "keyword_neighbor_chunks_skipped",
    "keyword_source_sibling_chunks_considered",
    "keyword_source_sibling_chunks_used",
    "keyword_source_sibling_chunks_skipped",
    "keyword_source_sibling_group_count",
    "keyword_source_sibling_candidate_limit",
    "keyword_source_sibling_companion_extra_used",
    "keyword_source_sibling_answer_evidence_extra_used",
    "keyword_source_sibling_precise_support_extra_used",
    "exact_source_sibling_answer_evidence_repair_candidates",
    "exact_source_sibling_answer_evidence_repair_existing",
    "exact_source_sibling_answer_evidence_repair_added",
    "keyword_aggregation_chunks_considered",
    "keyword_aggregation_chunks_used",
    "keyword_aggregation_chunks_skipped",
    "vector_query_count",
    "vector_embedding_vector_count",
    "vector_search_count",
    "vector_query_limit",
    "vector_query_degraded_count",
    "vector_candidate_count",
    "vector_hydrated_count",
    "graph_query_count",
    "graph_query_limit",
    "graph_query_degraded_count",
    "graph_candidate_count",
    "graph_hydrated_count",
    "rag_query_count",
    "rag_query_limit",
    "rag_candidate_count",
    "rag_hydrated_count",
    "rag_query_degraded_count",
    "artifact_evidence_jobs_considered",
    "artifact_evidence_manifests_considered",
    "artifact_evidence_manifests_used",
    "artifact_evidence_items_considered",
    "artifact_evidence_items_used",
    "artifact_evidence_ranked_candidate_count",
    "artifact_evidence_candidate_cap_reached_count",
    "artifact_evidence_confidence_signal_count",
    "artifact_evidence_coordinate_signal_count",
    "artifact_evidence_time_query_count",
    "artifact_evidence_time_query_match_count",
    "artifact_evidence_time_query_drop_count",
    "artifact_evidence_invalid_time_range_count",
    "artifact_evidence_invalid_bbox_count",
    "artifact_evidence_visual_region_query_drop_count",
    "artifact_evidence_document_location_query_drop_count",
    "artifact_evidence_extracted_text_query_drop_count",
    "artifact_evidence_query_drop_count",
    "artifact_evidence_sensitive_drop_count",
    "artifact_evidence_prompt_injection_drop_count",
    "artifact_evidence_manifest_too_large_count",
    "artifact_evidence_read_error_count",
    "artifact_evidence_parse_error_count",
    "artifact_evidence_schema_skip_count",
    "artifact_evidence_stale_asset_drop_count",
    "stale_vector_drop_count",
    "stale_graph_drop_count",
    "stale_rag_drop_count",
    "stale_facts_considered",
    "stale_facts_used",
    "superseded_facts_considered",
    "superseded_facts_used",
    "temporal_relations_considered",
    "temporal_replacements_applied",
    "temporal_contradictions_considered",
    "temporal_relations_skipped_by_validity",
    "linked_temporal_relations_considered",
    "linked_temporal_replacements_applied",
    "linked_temporal_contradictions_considered",
    "linked_temporal_relations_skipped_by_validity",
    "pending_conflict_suggestions_considered",
    "pending_duplicate_merge_suggestions_considered",
    "approved_context_links_considered",
    "approved_context_links_used",
    "approved_context_linked_chunks_used",
    "approved_context_linked_facts_used",
    "approved_context_linked_anchors_used",
    "approved_context_linked_assets_used",
    "approved_context_linked_asset_manifest_jobs_considered",
    "approved_context_linked_asset_manifest_artifacts_considered",
    "approved_context_linked_asset_manifest_items_used",
    "approved_context_linked_asset_manifest_blob_storage_disabled_count",
    "approved_context_linked_asset_manifest_too_large_count",
    "approved_context_linked_asset_manifest_read_error_count",
    "approved_context_linked_asset_manifest_parse_error_count",
    "approved_context_linked_asset_manifest_schema_skip_count",
    "approved_context_linked_extraction_artifacts_used",
    "approved_context_linked_extraction_artifact_manifest_items_used",
    "approved_context_linked_extraction_artifact_blob_storage_disabled_count",
    "approved_context_linked_extraction_artifact_manifest_too_large_count",
    "approved_context_linked_extraction_artifact_read_error_count",
    "approved_context_linked_extraction_artifact_parse_error_count",
    "approved_context_linked_extraction_artifact_schema_skip_count",
    "stale_context_linked_chunk_drop_count",
    "stale_context_linked_fact_drop_count",
    "stale_context_linked_anchor_drop_count",
    "stale_context_linked_asset_drop_count",
    "stale_context_linked_extraction_artifact_drop_count",
    "final_rank_source_item_count",
    "final_rank_candidate_item_count",
    "hybrid_items_used",
    "items_considered",
    "items_used",
    "diversity_families_considered",
    "diversity_families_used",
    "diversity_items_used",
    "answer_support_families_considered",
    "answer_support_families_used",
    "answer_support_items_used",
    "exact_query_object_turn_items_used",
    "chunk_sources_considered",
    "chunk_sources_used",
    "max_chunks_used_per_source",
    "source_capped_sources_considered",
    "source_capped_sources_used",
    "max_source_capped_items_used_per_source",
    "source_diversity_chunks_reordered",
    "dropped_by_instruction_flag",
    "dropped_by_budget",
    "dropped_by_source_cap",
    "dropped_by_source_group_cap",
    "dropped_by_char_cap",
    "citations_rendered",
    "citation_quote_previews_rendered",
    "sensitive_citation_quote_previews_skipped",
    "sensitive_source_identity_parts_redacted",
    "unsafe_source_identity_parts_sanitized",
    "sensitive_item_text_redacted",
    "multimodal_source_ref_count",
    "items_with_multimodal_source_refs",
    "source_refs_with_page_count",
    "source_refs_with_bbox_count",
    "source_refs_with_time_range_count",
    "source_refs_with_char_range_count",
    "query_snippet_items_used",
    "query_snippet_source_refs_enriched",
    "media_time_query_items_used",
    "media_time_query_matched_items_used",
    "requirement_guard_items_considered",
    "requirement_guard_items_dropped",
    "rendered_chars",
    "max_rendered_chars",
)
_BUNDLE_COUNTER_DEFAULTS = {
    "facts_considered": 0,
    "anchors_considered": 0,
    "anchor_lookup_keys_considered": 0,
    "anchors_loaded_by_lookup": 0,
    "anchors_used": 0,
    "anchors_used_by_query_intent": 0,
    "anchors_dropped_by_query_intent_conflict": 0,
    "anchor_relation_candidates_considered": 0,
    "anchor_relation_items_used": 0,
    "query_anchor_hint_count": 0,
    "query_anchor_person_hint_count": 0,
    "query_anchor_event_hint_count": 0,
    "query_anchor_project_hint_count": 0,
    "query_anchor_organization_hint_count": 0,
    "query_anchor_temporal_hint_count": 0,
    "query_anchor_event_type_hint_count": 0,
    "keyword_chunks_considered": 0,
    "keyword_query_count": 0,
    "keyword_chunks_dropped_by_relevance": 0,
    "keyword_neighbor_chunks_considered": 0,
    "keyword_neighbor_chunks_used": 0,
    "keyword_neighbor_chunks_skipped": 0,
    "keyword_source_sibling_chunks_considered": 0,
    "keyword_source_sibling_chunks_used": 0,
    "keyword_source_sibling_chunks_skipped": 0,
    "keyword_source_sibling_group_count": 0,
    "keyword_source_sibling_candidate_limit": 0,
    "keyword_source_sibling_companion_extra_used": 0,
    "keyword_source_sibling_answer_evidence_extra_used": 0,
    "keyword_source_sibling_precise_support_extra_used": 0,
    "keyword_aggregation_chunks_considered": 0,
    "keyword_aggregation_chunks_used": 0,
    "keyword_aggregation_chunks_skipped": 0,
    "vector_query_count": 0,
    "vector_embedding_vector_count": 0,
    "vector_search_count": 0,
    "vector_query_limit": 0,
    "vector_query_degraded_count": 0,
    "vector_candidate_count": 0,
    "vector_hydrated_count": 0,
    "graph_query_count": 0,
    "graph_query_limit": 0,
    "graph_query_degraded_count": 0,
    "graph_candidate_count": 0,
    "graph_hydrated_count": 0,
    "rag_query_count": 0,
    "rag_query_limit": 0,
    "rag_candidate_count": 0,
    "rag_hydrated_count": 0,
    "rag_query_degraded_count": 0,
    "artifact_evidence_jobs_considered": 0,
    "artifact_evidence_manifests_considered": 0,
    "artifact_evidence_manifests_used": 0,
    "artifact_evidence_items_considered": 0,
    "artifact_evidence_items_used": 0,
    "artifact_evidence_ranked_candidate_count": 0,
    "artifact_evidence_candidate_cap_reached_count": 0,
    "artifact_evidence_confidence_signal_count": 0,
    "artifact_evidence_coordinate_signal_count": 0,
    "artifact_evidence_time_query_count": 0,
    "artifact_evidence_time_query_match_count": 0,
    "artifact_evidence_time_query_drop_count": 0,
    "artifact_evidence_invalid_time_range_count": 0,
    "artifact_evidence_invalid_bbox_count": 0,
    "artifact_evidence_visual_region_query_drop_count": 0,
    "artifact_evidence_document_location_query_drop_count": 0,
    "artifact_evidence_extracted_text_query_drop_count": 0,
    "artifact_evidence_query_drop_count": 0,
    "artifact_evidence_sensitive_drop_count": 0,
    "artifact_evidence_prompt_injection_drop_count": 0,
    "artifact_evidence_manifest_too_large_count": 0,
    "artifact_evidence_read_error_count": 0,
    "artifact_evidence_parse_error_count": 0,
    "artifact_evidence_schema_skip_count": 0,
    "artifact_evidence_stale_asset_drop_count": 0,
    "stale_vector_drop_count": 0,
    "stale_graph_drop_count": 0,
    "stale_rag_drop_count": 0,
    "temporal_relations_considered": 0,
    "temporal_replacements_applied": 0,
    "temporal_contradictions_considered": 0,
    "temporal_relations_skipped_by_validity": 0,
    "linked_temporal_relations_considered": 0,
    "linked_temporal_replacements_applied": 0,
    "linked_temporal_contradictions_considered": 0,
    "linked_temporal_relations_skipped_by_validity": 0,
    "stale_facts_considered": 0,
    "stale_facts_used": 0,
    "superseded_facts_considered": 0,
    "superseded_facts_used": 0,
    "pending_conflict_suggestions_considered": 0,
    "pending_duplicate_merge_suggestions_considered": 0,
    "approved_context_links_considered": 0,
    "approved_context_links_used": 0,
    "approved_context_linked_chunks_used": 0,
    "approved_context_linked_facts_used": 0,
    "approved_context_linked_anchors_used": 0,
    "approved_context_linked_assets_used": 0,
    "approved_context_linked_asset_manifest_jobs_considered": 0,
    "approved_context_linked_asset_manifest_artifacts_considered": 0,
    "approved_context_linked_asset_manifest_items_used": 0,
    "approved_context_linked_asset_manifest_blob_storage_disabled_count": 0,
    "approved_context_linked_asset_manifest_too_large_count": 0,
    "approved_context_linked_asset_manifest_read_error_count": 0,
    "approved_context_linked_asset_manifest_parse_error_count": 0,
    "approved_context_linked_asset_manifest_schema_skip_count": 0,
    "approved_context_linked_extraction_artifacts_used": 0,
    "approved_context_linked_extraction_artifact_manifest_items_used": 0,
    "approved_context_linked_extraction_artifact_blob_storage_disabled_count": 0,
    "approved_context_linked_extraction_artifact_manifest_too_large_count": 0,
    "approved_context_linked_extraction_artifact_read_error_count": 0,
    "approved_context_linked_extraction_artifact_parse_error_count": 0,
    "approved_context_linked_extraction_artifact_schema_skip_count": 0,
    "stale_context_linked_chunk_drop_count": 0,
    "stale_context_linked_fact_drop_count": 0,
    "stale_context_linked_anchor_drop_count": 0,
    "stale_context_linked_asset_drop_count": 0,
    "stale_context_linked_extraction_artifact_drop_count": 0,
    "hybrid_items_used": 0,
    "items_considered": 0,
    "items_used": 0,
    "diversity_families_considered": 0,
    "diversity_families_used": 0,
    "diversity_items_used": 0,
    "answer_support_families_considered": 0,
    "answer_support_families_used": 0,
    "answer_support_items_used": 0,
    "exact_query_object_turn_items_used": 0,
    "chunk_sources_considered": 0,
    "chunk_sources_used": 0,
    "max_chunks_used_per_source": 0,
    "source_capped_sources_considered": 0,
    "source_capped_sources_used": 0,
    "max_source_capped_items_used_per_source": 0,
    "source_diversity_chunks_reordered": 0,
    "dropped_by_instruction_flag": 0,
    "dropped_by_budget": 0,
    "dropped_by_source_cap": 0,
    "dropped_by_source_group_cap": 0,
    "dropped_by_char_cap": 0,
    "citations_rendered": 0,
    "citation_quote_previews_rendered": 0,
    "sensitive_citation_quote_previews_skipped": 0,
    "sensitive_source_identity_parts_redacted": 0,
    "unsafe_source_identity_parts_sanitized": 0,
    "sensitive_item_text_redacted": 0,
    "multimodal_source_ref_count": 0,
    "items_with_multimodal_source_refs": 0,
    "source_refs_with_page_count": 0,
    "source_refs_with_bbox_count": 0,
    "source_refs_with_time_range_count": 0,
    "source_refs_with_char_range_count": 0,
    "query_snippet_items_used": 0,
    "query_snippet_source_refs_enriched": 0,
    "media_time_query_items_used": 0,
    "media_time_query_matched_items_used": 0,
    "requirement_guard_items_considered": 0,
    "requirement_guard_items_dropped": 0,
    "rendered_chars": 0,
    "max_rendered_chars": 0,
}
_BUNDLE_STATUS_DEFAULTS = {
    "vector_status": "unknown",
    "graph_status": "unknown",
    "rag_status": "unknown",
    "artifact_evidence_status": "unknown",
    "requirement_guard_status": "not_triggered",
}
_BUNDLE_PROVIDER_STATUS_TEXT_KEYS = (
    "vector_degraded_reason",
    "vector_degraded_step",
    "vector_skip_reason",
    "graph_degraded_reason",
    "graph_degraded_step",
    "graph_skip_reason",
    "rag_degraded_reason",
    "rag_degraded_step",
    "rag_skip_reason",
)
_BUNDLE_PROVIDER_STATUS_FLOAT_KEYS = (
    "vector_deadline_seconds",
    "graph_deadline_seconds",
    "rag_deadline_seconds",
)
_BUNDLE_QUERY_ANCHOR_TEXT_KEYS = (
    "query_anchor_intent_status",
)
_BUNDLE_QUERY_ANCHOR_LIST_KEYS = (
    "query_anchor_hint_reasons",
)
_BUNDLE_KEYWORD_AGGREGATION_TEXT_KEYS = (
    "keyword_aggregation_query_kind",
)
_BUNDLE_QUERY_PLAN_TEXT_KEYS = (
    "query_expansion_status",
    "query_decomposition_status",
)
_BUNDLE_QUERY_PLAN_COUNTER_KEYS = (
    "query_expansion_count",
    "query_decomposition_count",
)
_BUNDLE_QUERY_PLAN_LIST_KEYS = (
    "keyword_query_reasons",
    "query_expansion_reasons",
    "query_decomposition_reasons",
)
_BUNDLE_TEMPORAL_QUERY_TEXT_KEYS = (
    "temporal_query_intent_status",
)
_BUNDLE_TEMPORAL_QUERY_BOOL_KEYS = (
    "temporal_query_prefers_current",
    "temporal_query_requests_previous",
    "temporal_query_requests_change",
    "temporal_query_after_event",
    "temporal_query_before_event",
    "temporal_query_excludes_stale",
    "temporal_query_include_superseded_review",
)
_BUNDLE_TEMPORAL_QUERY_LIST_KEYS = (
    "temporal_query_intent_reasons",
    "temporal_query_relative_time_hints",
)
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
        -_score_signal_float(item, "source_sibling_answer_evidence"),
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


def normalize_context_item_diagnostics(item: ContextItem) -> ContextItem:
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    return replace(
        item,
        diagnostics=with_context_item_evidence_diagnostics(item, diagnostics),
    )


def normalize_context_diagnostics(diagnostics: object) -> dict[str, object]:
    raw = _as_dict(diagnostics)
    listed_retrieval_sources = diagnostic_retrieval_sources(
        raw,
        limit=_MAX_RETRIEVAL_SOURCE_CANDIDATES,
    )
    selected_source = _safe_retrieval_source(raw.get("retrieval_source"))
    all_retrieval_sources = (
        _ordered_unique(
            (selected_source, *listed_retrieval_sources),
            limit=_MAX_RETRIEVAL_SOURCE_CANDIDATES,
        )
        if selected_source
        else listed_retrieval_sources
    )
    retrieval_sources = all_retrieval_sources[:_MAX_RETRIEVAL_SOURCES]
    normalized = safe_diagnostic_mapping(raw)
    normalized.update(_safe_query_snippet_diagnostics(raw))
    normalized.update(_safe_recall_diagnostics(raw))
    normalized.update(_safe_context_link_diagnostics(raw))
    normalized.update(_safe_review_diagnostics(raw))
    normalized.update(_safe_anchor_diagnostics(raw))
    normalized["retrieval_sources"] = list(retrieval_sources)
    normalized["retrieval_sources_total"] = len(all_retrieval_sources)
    normalized["retrieval_sources_returned"] = len(retrieval_sources)
    normalized["retrieval_sources_truncated"] = len(all_retrieval_sources) > len(retrieval_sources)
    if retrieval_sources and not selected_source:
        selected_source = retrieval_sources[0]
    if selected_source:
        normalized["retrieval_source"] = selected_source
    else:
        normalized.pop("retrieval_source", None)
    ranking_reason = _safe_optional_text(raw.get("ranking_reason"), limit=_MAX_RANKING_REASON_CHARS)
    normalized["ranking_reason"] = ranking_reason or ranking_reason_for(retrieval_sources)
    normalized["score_signals"] = safe_score_signals(raw.get("score_signals"))
    provenance = safe_diagnostic_mapping(raw.get("provenance"))
    provenance.update(_safe_context_link_diagnostics(_as_dict(raw.get("provenance"))))
    provenance.update(_safe_context_link_diagnostics(raw))
    provenance.update(_safe_context_requirement_provenance(raw.get("provenance")))
    provenance.update(_safe_deterministic_rerank_provenance(raw.get("provenance")))
    provenance.update(_safe_source_sibling_provenance(raw.get("provenance")))
    if retrieval_sources:
        provenance["retrieval_sources"] = list(retrieval_sources)
    normalized["provenance"] = provenance
    return normalized


def normalize_context_bundle_diagnostics(
    diagnostics: object,
    *,
    items: tuple[ContextItem, ...],
) -> dict[str, object]:
    raw = _as_dict(diagnostics)
    normalized = _bounded_mapping(
        safe_metadata(raw, max_items=_MAX_BUNDLE_DIAGNOSTIC_MAPPING_ITEMS),
        max_items=_MAX_BUNDLE_DIAGNOSTIC_MAPPING_ITEMS,
    )
    normalized["context_assembly_version"] = (
        _safe_optional_text(
            raw.get("context_assembly_version"),
            limit=_MAX_DIAGNOSTIC_KEY_CHARS,
        )
        or "unknown"
    )
    normalized["consistency_mode"] = (
        _safe_optional_text(
            raw.get("consistency_mode"),
            limit=_MAX_DIAGNOSTIC_KEY_CHARS,
        )
        or "unknown"
    )
    for key, default in _BUNDLE_STATUS_DEFAULTS.items():
        normalized[key] = (
            _safe_optional_text(raw.get(key), limit=_MAX_DIAGNOSTIC_KEY_CHARS) or default
        )
    normalized.update(_safe_bundle_provider_status_diagnostics(raw))
    normalized.update(_safe_bundle_query_anchor_diagnostics(raw))
    normalized.update(_safe_bundle_keyword_aggregation_diagnostics(raw))
    normalized.update(_safe_bundle_query_plan_diagnostics(raw))
    normalized.update(_safe_bundle_temporal_query_diagnostics(raw))
    all_retrieval_sources = _bundle_retrieval_sources(
        items,
        limit=_MAX_RETRIEVAL_SOURCE_CANDIDATES,
    )
    retrieval_sources = all_retrieval_sources[:_MAX_RETRIEVAL_SOURCES]
    normalized["retrieval_sources_used"] = list(retrieval_sources)
    normalized["retrieval_sources_total"] = len(all_retrieval_sources)
    normalized["retrieval_sources_returned"] = len(retrieval_sources)
    normalized["retrieval_sources_truncated"] = len(all_retrieval_sources) > len(retrieval_sources)
    normalized["diagnostics_truncated"] = len(raw) > _MAX_BUNDLE_DIAGNOSTIC_MAPPING_ITEMS
    for key in _BUNDLE_COUNTER_KEYS:
        if key in raw or key in _BUNDLE_COUNTER_DEFAULTS:
            normalized[key] = _non_negative_int(
                raw.get(key),
                default=_BUNDLE_COUNTER_DEFAULTS.get(key, 0),
            )
    normalized["keyword_source_sibling_groups_sample"] = _safe_text_list(
        raw.get("keyword_source_sibling_groups_sample"),
        limit=40,
    )
    normalized["keyword_source_sibling_selected_sources_sample"] = _safe_text_list(
        raw.get("keyword_source_sibling_selected_sources_sample"),
        limit=80,
    )
    normalized["keyword_source_sibling_answer_evidence_selected_sources_sample"] = (
        _safe_text_list(
            raw.get("keyword_source_sibling_answer_evidence_selected_sources_sample"),
            limit=40,
        )
    )
    normalized["answer_support_candidate_source_ref_ids_sample"] = _safe_text_list(
        raw.get("answer_support_candidate_source_ref_ids_sample"),
        limit=40,
    )
    normalized["answer_support_candidate_families_sample"] = _safe_text_list(
        raw.get("answer_support_candidate_families_sample"),
        limit=40,
    )
    normalized["answer_support_selected_families_sample"] = _safe_text_list(
        raw.get("answer_support_selected_families_sample"),
        limit=40,
    )
    normalized["answer_support_selected_source_ref_ids_sample"] = _safe_text_list(
        raw.get("answer_support_selected_source_ref_ids_sample"),
        limit=40,
    )
    normalized["pre_pack_source_ref_ids_sample"] = _safe_text_list(
        raw.get("pre_pack_source_ref_ids_sample"),
        limit=200,
    )
    normalized["pre_pack_dialogue_markers_sample"] = _safe_text_list(
        raw.get("pre_pack_dialogue_markers_sample"),
        limit=200,
    )
    normalized["pre_pack_source_sibling_answer_evidence_source_ref_ids_sample"] = (
        _safe_text_list(
            raw.get("pre_pack_source_sibling_answer_evidence_source_ref_ids_sample"),
            limit=40,
        )
    )
    normalized["pre_pack_source_sibling_answer_evidence_dialogue_markers_sample"] = (
        _safe_text_list(
            raw.get("pre_pack_source_sibling_answer_evidence_dialogue_markers_sample"),
            limit=40,
        )
    )
    for stage in ("post_dedupe_hydrate", "final_source", "final_candidate", "guarded"):
        normalized[f"{stage}_source_sibling_item_count"] = _non_negative_int(
            raw.get(f"{stage}_source_sibling_item_count"),
            default=0,
        )
        normalized[f"{stage}_source_sibling_source_ref_ids_sample"] = _safe_text_list(
            raw.get(f"{stage}_source_sibling_source_ref_ids_sample"),
            limit=200,
        )
        normalized[f"{stage}_source_sibling_dialogue_markers_sample"] = _safe_text_list(
            raw.get(f"{stage}_source_sibling_dialogue_markers_sample"),
            limit=200,
        )
        normalized[f"{stage}_source_sibling_answer_evidence_item_count"] = _non_negative_int(
            raw.get(f"{stage}_source_sibling_answer_evidence_item_count"),
            default=0,
        )
        normalized[f"{stage}_source_sibling_answer_evidence_source_ref_ids_sample"] = (
            _safe_text_list(
                raw.get(f"{stage}_source_sibling_answer_evidence_source_ref_ids_sample"),
                limit=200,
            )
        )
        normalized[f"{stage}_source_sibling_answer_evidence_dialogue_markers_sample"] = (
            _safe_text_list(
                raw.get(f"{stage}_source_sibling_answer_evidence_dialogue_markers_sample"),
                limit=200,
            )
        )
    normalized["item_type_counts"] = _item_type_counts(items)
    normalized.update(_source_ref_counts(items))
    normalized.update(_multimodal_source_ref_counts(items))
    normalized.update(_evidence_kind_modality_counts(items))
    normalized["evidence_coverage_profile"] = _evidence_coverage_profile(items)
    normalized["context_requirement_coverage"] = sanitize_context_requirement_coverage(
        raw.get("context_requirement_coverage")
    )
    normalized.update(_query_snippet_counts(items))
    normalized.update(_media_time_query_counts(items))
    normalized["retrieval_trace"] = _retrieval_trace(
        items,
        retrieval_sources=retrieval_sources,
    )
    normalized["provenance_summary"] = _provenance_summary(normalized, items)
    normalized["retrieval_quality_summary"] = retrieval_quality_summary(
        normalized,
        items,
    )
    return normalized


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


def merge_context_diagnostics(
    *,
    primary: object,
    secondary: object,
    retrieval_sources: tuple[str, ...],
    source_ref_count: int,
    primary_score: float,
    secondary_score: float,
    hybrid_boost: float,
) -> dict[str, object]:
    primary_raw = _as_dict(primary)
    secondary_raw = _as_dict(secondary)
    merged = safe_diagnostic_mapping({**secondary_raw, **primary_raw})
    merged.update(_safe_recall_diagnostics(secondary_raw))
    merged.update(_safe_recall_diagnostics(primary_raw))
    merged.update(_safe_context_link_diagnostics(secondary_raw))
    merged.update(_safe_context_link_diagnostics(primary_raw))
    prioritized_sources = _prioritized_retrieval_sources(retrieval_sources)
    selected_source = prioritized_sources[0] if prioritized_sources else None
    if selected_source:
        merged["retrieval_source"] = selected_source
    merged["retrieval_sources"] = list(prioritized_sources)
    merged["merged_candidate_count"] = _candidate_count(primary_raw) + _candidate_count(
        secondary_raw
    )
    merged["ranking_reason"] = ranking_reason_for(prioritized_sources)
    primary_score_signals = safe_score_signals(primary_raw.get("score_signals"))
    secondary_score_signals = safe_score_signals(secondary_raw.get("score_signals"))
    merged["score_signals"] = {
        "dedupe_primary_score": round(primary_score, 4),
        "dedupe_secondary_score": round(secondary_score, 4),
        "hybrid_source_count": len(prioritized_sources),
        "hybrid_boost": round(hybrid_boost, 4),
        "source_ref_count": source_ref_count,
        **secondary_score_signals,
        **primary_score_signals,
    }
    _preserve_positive_score_signals(
        merged["score_signals"],
        primary_score_signals,
        secondary_score_signals,
        keys=(
            "source_sibling_dialogue_visual_reference",
            "source_sibling_answer_evidence",
            "source_sibling_group_level_seed",
            "source_sibling_visual_continuation",
        ),
    )
    primary_provenance = safe_diagnostic_mapping(primary_raw.get("provenance"))
    secondary_provenance = safe_diagnostic_mapping(secondary_raw.get("provenance"))
    merged["provenance"] = {
        **secondary_provenance,
        **primary_provenance,
        "retrieval_sources": list(prioritized_sources),
        "source_ref_count": source_ref_count,
        "selected_retrieval_source": selected_source or "unknown",
    }
    _preserve_positive_provenance_flags(
        merged["provenance"],
        primary_provenance,
        secondary_provenance,
        keys=(
            "source_sibling_dialogue_visual_reference",
            "source_sibling_answer_evidence",
            "source_sibling_group_level_seed",
            "source_sibling_visual_continuation",
        ),
    )
    return normalize_context_diagnostics(merged)


def safe_score_signals(value: object) -> dict[str, object]:
    safe = safe_diagnostic_mapping(value)
    signals = {
        key: item
        for key, item in safe.items()
        if isinstance(item, int | float | str | bool) or item is None
    }
    signals.update(_safe_context_requirement_score_signals(value))
    signals.update(_safe_deterministic_rerank_score_signals(value))
    signals.update(_safe_source_sibling_score_signals(value))
    raw = _as_dict(value)
    raw_same_script_boost = raw.get("same_script_query_boost")
    if isinstance(raw_same_script_boost, int | float) and not isinstance(
        raw_same_script_boost,
        bool,
    ):
        signals["same_script_query_boost"] = round(max(0.0, raw_same_script_boost), 4)
    return signals


def _preserve_positive_score_signals(
    merged: dict[str, object],
    primary: dict[str, object],
    secondary: dict[str, object],
    *,
    keys: tuple[str, ...],
) -> None:
    for key in keys:
        if _positive_numeric_signal(primary.get(key)) or _positive_numeric_signal(
            secondary.get(key)
        ):
            merged[key] = 1


def _preserve_positive_provenance_flags(
    merged: dict[str, object],
    primary: dict[str, object],
    secondary: dict[str, object],
    *,
    keys: tuple[str, ...],
) -> None:
    for key in keys:
        if primary.get(key) is True or secondary.get(key) is True:
            merged[key] = True


def _positive_numeric_signal(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        return value > 0
    return False


def safe_diagnostic_mapping(value: object) -> dict[str, object]:
    return _bounded_mapping(
        safe_metadata(value, max_items=_MAX_DIAGNOSTIC_MAPPING_ITEMS),
        max_items=_MAX_DIAGNOSTIC_MAPPING_ITEMS,
    )


def _safe_context_requirement_score_signals(value: object) -> dict[str, object]:
    raw = _as_dict(value)
    signals: dict[str, object] = {}
    for key in _CONTEXT_REQUIREMENT_SCORE_SIGNAL_KEYS:
        raw_value = raw.get(key)
        if isinstance(raw_value, bool):
            continue
        if isinstance(raw_value, int):
            signals[key] = max(0, raw_value)
        elif isinstance(raw_value, float):
            signals[key] = round(max(0.0, raw_value), 4)
    return signals


def _safe_deterministic_rerank_score_signals(value: object) -> dict[str, object]:
    raw = _as_dict(value)
    signals: dict[str, object] = {}
    for key in _DETERMINISTIC_RERANK_SCORE_SIGNAL_KEYS:
        raw_value = raw.get(key)
        if key == "deterministic_rerank_query_reason":
            reason = _safe_optional_text(raw_value, limit=_MAX_DIAGNOSTIC_KEY_CHARS)
            if reason:
                signals[key] = reason
            continue
        if isinstance(raw_value, bool):
            continue
        if isinstance(raw_value, int):
            signals[key] = (
                raw_value
                if key == "deterministic_rerank_net_adjustment"
                else max(0, raw_value)
            )
        elif isinstance(raw_value, float):
            numeric = round(raw_value, 4)
            signals[key] = (
                numeric
                if key == "deterministic_rerank_net_adjustment"
                else round(max(0.0, numeric), 4)
            )
    return signals


def _safe_source_sibling_score_signals(value: object) -> dict[str, object]:
    raw = _as_dict(value)
    signals: dict[str, object] = {}
    for key in _SOURCE_SIBLING_SCORE_SIGNAL_KEYS:
        raw_value = raw.get(key)
        if isinstance(raw_value, bool):
            continue
        if isinstance(raw_value, int):
            signals[key] = max(0, raw_value)
        elif isinstance(raw_value, float):
            signals[key] = round(max(0.0, raw_value), 4)
    return signals


def _safe_context_requirement_provenance(value: object) -> dict[str, object]:
    raw = _as_dict(value)
    provenance: dict[str, object] = {}
    if raw.get("context_requirement_boost_applied") is True:
        provenance["context_requirement_boost_applied"] = True
    for key in _CONTEXT_REQUIREMENT_PROVENANCE_LIST_KEYS:
        safe_values = [
            safe_value
            for item in _safe_context_requirement_list(raw.get(key))
            if (safe_value := _safe_optional_text(item, limit=_MAX_DIAGNOSTIC_KEY_CHARS))
        ]
        if safe_values or key in raw:
            provenance[key] = safe_values[:_MAX_DIAGNOSTIC_LIST_ITEMS]
    return provenance


def _safe_deterministic_rerank_provenance(value: object) -> dict[str, object]:
    raw = _as_dict(value)
    provenance: dict[str, object] = {}
    if raw.get("deterministic_rerank_applied") is True:
        provenance["deterministic_rerank_applied"] = True
    if raw.get("deterministic_rerank_anchor_conflict") is True:
        provenance["deterministic_rerank_anchor_conflict"] = True
    for key in _DETERMINISTIC_RERANK_PROVENANCE_LIST_KEYS:
        safe_values = [
            safe_value
            for item in _safe_context_requirement_list(raw.get(key))
            if (safe_value := _safe_optional_text(item, limit=_MAX_DIAGNOSTIC_KEY_CHARS))
        ]
        if safe_values or key in raw:
            provenance[key] = safe_values[:_MAX_DIAGNOSTIC_LIST_ITEMS]
    return provenance


def _safe_source_sibling_provenance(value: object) -> dict[str, object]:
    raw = _as_dict(value)
    provenance: dict[str, object] = {}
    for key in _SOURCE_SIBLING_PROVENANCE_BOOL_KEYS:
        if raw.get(key) is True:
            provenance[key] = True
    for key in _SOURCE_SIBLING_PROVENANCE_NUMBER_KEYS:
        raw_value = raw.get(key)
        if isinstance(raw_value, bool):
            continue
        if isinstance(raw_value, int):
            provenance[key] = raw_value
        elif isinstance(raw_value, float):
            provenance[key] = round(raw_value, 4)
    return provenance


def _safe_context_requirement_list(value: object) -> tuple[object, ...]:
    if isinstance(value, list | tuple):
        return tuple(value[:_MAX_DIAGNOSTIC_LIST_ITEMS])
    return ()


def _safe_text_list(value: object, *, limit: int) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    safe_items: list[str] = []
    for item in value:
        text = _safe_optional_text(item, limit=_MAX_DIAGNOSTIC_STRING_CHARS)
        if text is not None:
            safe_items.append(text)
        if len(safe_items) >= limit:
            break
    return safe_items


def _safe_query_snippet_diagnostics(raw: dict[str, Any]) -> dict[str, object]:
    snippet = _safe_optional_text(
        raw.get("query_snippet"),
        limit=_MAX_DIAGNOSTIC_STRING_CHARS,
    )
    if not snippet:
        return {}
    diagnostics: dict[str, object] = {"query_snippet": snippet}
    for key in ("query_snippet_char_start", "query_snippet_char_end"):
        value = _optional_non_negative_int(raw.get(key))
        if value is not None:
            diagnostics[key] = value
    unique_hits = _optional_non_negative_int(raw.get("query_snippet_unique_term_hits"))
    if unique_hits is not None:
        diagnostics["query_snippet_unique_term_hits"] = unique_hits
    terms = raw.get("query_snippet_matched_terms")
    if isinstance(terms, list | tuple):
        diagnostics["query_snippet_matched_terms"] = [
            term
            for raw_term in terms[:_MAX_DIAGNOSTIC_LIST_ITEMS]
            if (term := _safe_optional_text(raw_term, limit=_MAX_DIAGNOSTIC_KEY_CHARS))
        ]
    return diagnostics


def _safe_recall_diagnostics(raw: dict[str, Any]) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    for key in _SAFE_RECALL_DIAGNOSTIC_KEYS:
        value = _safe_optional_text(raw.get(key), limit=_MAX_DIAGNOSTIC_STRING_CHARS)
        if value:
            diagnostics[key] = value
    return diagnostics


def _safe_context_link_diagnostics(raw: dict[str, Any]) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    for key in _SAFE_CONTEXT_LINK_DIAGNOSTIC_KEYS:
        value = _safe_optional_text(raw.get(key), limit=_MAX_DIAGNOSTIC_STRING_CHARS)
        if value:
            diagnostics[key] = value
    return diagnostics


def _safe_review_diagnostics(raw: dict[str, Any]) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    for key in _SAFE_REVIEW_TEXT_DIAGNOSTIC_KEYS:
        value = _safe_optional_text(raw.get(key), limit=_MAX_DIAGNOSTIC_STRING_CHARS)
        if value:
            diagnostics[key] = value
    for key in _SAFE_REVIEW_BOOL_DIAGNOSTIC_KEYS:
        value = raw.get(key)
        if isinstance(value, bool):
            diagnostics[key] = value
    for key in _SAFE_REVIEW_LIST_DIAGNOSTIC_KEYS:
        value = raw.get(key)
        if not isinstance(value, list | tuple):
            continue
        safe_values = [
            text
            for raw_text in value[:_MAX_DIAGNOSTIC_LIST_ITEMS]
            if (text := _safe_optional_text(raw_text, limit=_MAX_DIAGNOSTIC_KEY_CHARS))
        ]
        if safe_values:
            diagnostics[key] = safe_values
    options = raw.get("review_resolution_options")
    if isinstance(options, list | tuple):
        safe_options: list[dict[str, str]] = []
        for option in options[:_MAX_DIAGNOSTIC_LIST_ITEMS]:
            if not isinstance(option, dict):
                continue
            safe_option = {
                key: value
                for key, value in (
                    ("id", _safe_optional_text(option.get("id"), limit=_MAX_DIAGNOSTIC_KEY_CHARS)),
                    (
                        "review_action",
                        _safe_optional_text(
                            option.get("review_action"),
                            limit=_MAX_DIAGNOSTIC_KEY_CHARS,
                        ),
                    ),
                    (
                        "effect",
                        _safe_optional_text(
                            option.get("effect"),
                            limit=_MAX_DIAGNOSTIC_STRING_CHARS,
                        ),
                    ),
                    (
                        "availability",
                        _safe_optional_text(
                            option.get("availability"),
                            limit=_MAX_DIAGNOSTIC_KEY_CHARS,
                        ),
                    ),
                )
                if value
            }
            if safe_option:
                safe_options.append(safe_option)
        if safe_options:
            diagnostics["review_resolution_options"] = safe_options
    return diagnostics


def _safe_anchor_diagnostics(raw: dict[str, Any]) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    for key in _SAFE_ANCHOR_TEXT_DIAGNOSTIC_KEYS:
        value = _safe_optional_text(raw.get(key), limit=_MAX_DIAGNOSTIC_STRING_CHARS)
        if value:
            diagnostics[key] = value
    for key in _SAFE_ANCHOR_LIST_DIAGNOSTIC_KEYS:
        value = raw.get(key)
        if not isinstance(value, list | tuple):
            continue
        safe_values = [
            text
            for raw_text in value[:_MAX_DIAGNOSTIC_LIST_ITEMS]
            if (text := _safe_optional_text(raw_text, limit=_MAX_DIAGNOSTIC_KEY_CHARS))
        ]
        if safe_values:
            diagnostics[key] = safe_values
    profile = safe_diagnostic_mapping(raw.get("anchor_identity_profile"))
    if profile:
        diagnostics["anchor_identity_profile"] = profile
    identity_metadata = safe_diagnostic_mapping(raw.get("identity_metadata"))
    if identity_metadata:
        diagnostics["identity_metadata"] = identity_metadata
    return diagnostics


def _safe_bundle_query_plan_diagnostics(raw: dict[str, Any]) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    for key in _BUNDLE_QUERY_PLAN_TEXT_KEYS:
        value = _safe_optional_text(raw.get(key), limit=_MAX_DIAGNOSTIC_KEY_CHARS)
        if value:
            diagnostics[key] = value
    for key in _BUNDLE_QUERY_PLAN_COUNTER_KEYS:
        if key in raw:
            diagnostics[key] = _non_negative_int(raw.get(key), default=0)
    for key in _BUNDLE_QUERY_PLAN_LIST_KEYS:
        value = raw.get(key)
        if not isinstance(value, list | tuple):
            continue
        safe_values = [
            text
            for raw_text in value[:_MAX_DIAGNOSTIC_LIST_ITEMS]
            if (text := _safe_optional_text(raw_text, limit=_MAX_DIAGNOSTIC_KEY_CHARS))
        ]
        if safe_values:
            diagnostics[key] = safe_values
    return diagnostics


def _safe_bundle_provider_status_diagnostics(raw: dict[str, Any]) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    for key in _BUNDLE_PROVIDER_STATUS_TEXT_KEYS:
        value = _safe_optional_text(raw.get(key), limit=_MAX_DIAGNOSTIC_KEY_CHARS)
        if value:
            diagnostics[key] = value
    for key in _BUNDLE_PROVIDER_STATUS_FLOAT_KEYS:
        value = _optional_non_negative_float(raw.get(key))
        if value is not None:
            diagnostics[key] = value
    return diagnostics


def _safe_bundle_query_anchor_diagnostics(raw: dict[str, Any]) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    for key in _BUNDLE_QUERY_ANCHOR_TEXT_KEYS:
        value = _safe_optional_text(raw.get(key), limit=_MAX_DIAGNOSTIC_KEY_CHARS)
        if value:
            diagnostics[key] = value
    for key in _BUNDLE_QUERY_ANCHOR_LIST_KEYS:
        value = raw.get(key)
        if not isinstance(value, list | tuple):
            continue
        safe_values = [
            text
            for raw_text in value[:_MAX_DIAGNOSTIC_LIST_ITEMS]
            if (text := _safe_optional_text(raw_text, limit=_MAX_DIAGNOSTIC_KEY_CHARS))
        ]
        if safe_values:
            diagnostics[key] = safe_values
    return diagnostics


def _safe_bundle_keyword_aggregation_diagnostics(raw: dict[str, Any]) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    for key in _BUNDLE_KEYWORD_AGGREGATION_TEXT_KEYS:
        value = _safe_optional_text(raw.get(key), limit=_MAX_DIAGNOSTIC_KEY_CHARS)
        if value is not None:
            diagnostics[key] = value
    return diagnostics


def _safe_bundle_temporal_query_diagnostics(raw: dict[str, Any]) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    for key in _BUNDLE_TEMPORAL_QUERY_TEXT_KEYS:
        value = _safe_optional_text(raw.get(key), limit=_MAX_DIAGNOSTIC_KEY_CHARS)
        if value:
            diagnostics[key] = value
    for key in _BUNDLE_TEMPORAL_QUERY_BOOL_KEYS:
        value = raw.get(key)
        if isinstance(value, bool):
            diagnostics[key] = value
    for key in _BUNDLE_TEMPORAL_QUERY_LIST_KEYS:
        value = raw.get(key)
        if not isinstance(value, list | tuple):
            continue
        safe_values = [
            text
            for raw_text in value[:_MAX_DIAGNOSTIC_LIST_ITEMS]
            if (text := _safe_optional_text(raw_text, limit=_MAX_DIAGNOSTIC_KEY_CHARS))
        ]
        if safe_values:
            diagnostics[key] = safe_values
    return diagnostics


def ranking_reason_for(retrieval_sources: tuple[str, ...]) -> str:
    if len(retrieval_sources) > 1:
        reason = f"hybrid match via {', '.join(retrieval_sources)}"
    elif retrieval_sources:
        reason = f"matched via {retrieval_sources[0]}"
    else:
        reason = "matched without retrieval channel diagnostics"
    return safe_metadata_text(reason, limit=_MAX_RANKING_REASON_CHARS)


def _bounded_mapping(
    value: object,
    *,
    depth: int = 0,
    max_items: int = _MAX_DIAGNOSTIC_MAPPING_ITEMS,
) -> dict[str, object]:
    if not isinstance(value, dict) or depth > 2:
        return {}
    bounded: dict[str, object] = {}
    for raw_key, raw_value in list(value.items())[:max_items]:
        key = safe_metadata_text(str(raw_key), limit=_MAX_DIAGNOSTIC_KEY_CHARS).strip()
        if not key or "[redacted]" in key:
            continue
        item = _bounded_value(raw_value, depth=depth, max_items=max_items)
        if _is_safe_diagnostic_value(item):
            bounded[key] = item
    return bounded


def _bounded_value(
    value: object,
    *,
    depth: int,
    max_items: int,
) -> object:
    if isinstance(value, str):
        return safe_metadata_text(value, limit=_MAX_DIAGNOSTIC_STRING_CHARS)
    if isinstance(value, int | float | bool) or value is None:
        return value
    if isinstance(value, dict):
        return _bounded_mapping(value, depth=depth + 1, max_items=max_items)
    if isinstance(value, list):
        safe_items: list[object] = []
        for raw_item in value[:_MAX_DIAGNOSTIC_LIST_ITEMS]:
            item = _bounded_value(raw_item, depth=depth + 1, max_items=max_items)
            if _is_safe_diagnostic_value(item):
                safe_items.append(item)
        return safe_items
    return None


def _is_safe_diagnostic_value(value: object) -> bool:
    return isinstance(value, str | int | float | bool | dict | list) or value is None


def _safe_retrieval_source(value: object) -> str | None:
    if value is None:
        return None
    text = safe_metadata_text(str(value), limit=_MAX_DIAGNOSTIC_KEY_CHARS).strip()
    if "[redacted]" in text:
        return None
    return text or None


def _safe_optional_text(value: object, *, limit: int) -> str | None:
    if value is None:
        return None
    text = safe_metadata_text(str(value), limit=limit).strip()
    return text or None


def _candidate_count(diagnostics: dict[str, Any]) -> int:
    value = diagnostics.get("merged_candidate_count")
    return value if isinstance(value, int) and value > 0 else 1


def _bundle_retrieval_sources(
    items: tuple[ContextItem, ...],
    *,
    limit: int = _MAX_RETRIEVAL_SOURCES,
) -> tuple[str, ...]:
    sources = _ordered_unique(
        tuple(
            source
            for item in items
            for source in diagnostic_retrieval_sources(item.diagnostics, limit=limit)
        ),
        limit=limit,
    )
    return _prioritized_retrieval_sources(sources)


def _source_ref_counts(items: tuple[ContextItem, ...]) -> dict[str, int | bool]:
    returned = sum(len(item.source_refs) for item in items)
    total = sum(max(len(item.source_refs), _diagnostic_source_ref_count(item)) for item in items)
    return {
        "source_refs_total": total,
        "source_refs_returned": returned,
        "source_refs_truncated": total > returned,
        "citations_total": total,
        "citations_returned": returned,
        "citations_truncated": total > returned,
        "items_with_citations": sum(1 for item in items if item.source_refs),
    }


def _provenance_summary(
    diagnostics: dict[str, object],
    items: tuple[ContextItem, ...],
) -> dict[str, object]:
    item_count = len(items)
    refs = tuple(ref for item in items for ref in item.source_refs)
    items_with_citations = _non_negative_int(
        diagnostics.get("items_with_citations"),
        default=0,
    )
    items_with_quote_previews = sum(
        1
        for item in items
        if any(ref.quote_preview and ref.quote_preview.strip() for ref in item.source_refs)
    )
    items_with_precise_locations = sum(
        1
        for item in items
        if any(_source_ref_has_precise_location(ref) for ref in item.source_refs)
    )
    review_only_items = sum(
        1 for item in items if bool(_as_dict(item.diagnostics).get("review_only"))
    )
    pending_review_items = sum(
        1
        for item in items
        if any(
            source
            in {
                "pending_conflict_suggestion",
                "pending_duplicate_merge_suggestion",
            }
            for source in diagnostic_retrieval_sources(item.diagnostics)
        )
    )
    stale_items = sum(
        1
        for item in items
        if _safe_optional_text(
            _as_dict(item.diagnostics).get("stale_reason"),
            limit=_MAX_DIAGNOSTIC_KEY_CHARS,
        )
    )
    quote_preview_refs = sum(
        1 for ref in refs if ref.quote_preview is not None and ref.quote_preview.strip()
    )
    precise_location_refs = sum(1 for ref in refs if _source_ref_has_precise_location(ref))
    return {
        "items_total": item_count,
        "items_with_citations": items_with_citations,
        "uncited_items": max(0, item_count - items_with_citations),
        "citation_coverage_ratio": _ratio(items_with_citations, item_count),
        "citation_density": _ratio(
            _non_negative_int(diagnostics.get("citations_returned"), default=0),
            item_count,
        ),
        "items_with_quote_previews": items_with_quote_previews,
        "quote_preview_coverage_ratio": _ratio(items_with_quote_previews, item_count),
        "items_with_precise_locations": items_with_precise_locations,
        "precise_location_coverage_ratio": _ratio(items_with_precise_locations, item_count),
        "source_refs_total": _non_negative_int(
            diagnostics.get("source_refs_total"),
            default=0,
        ),
        "source_refs_returned": _non_negative_int(
            diagnostics.get("source_refs_returned"),
            default=0,
        ),
        "source_refs_with_quote_preview_count": quote_preview_refs,
        "source_refs_with_precise_location_count": precise_location_refs,
        "review_only_items": review_only_items,
        "pending_review_items": pending_review_items,
        "stale_items": stale_items,
        "active_default_items": max(0, item_count - review_only_items),
    }


def _source_ref_has_precise_location(ref: object) -> bool:
    return (
        getattr(ref, "char_start", None) is not None
        or getattr(ref, "char_end", None) is not None
        or getattr(ref, "page_number", None) is not None
        or getattr(ref, "time_start_ms", None) is not None
        or getattr(ref, "time_end_ms", None) is not None
        or getattr(ref, "bbox", None) is not None
    )


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


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


def _item_type_counts(items: tuple[ContextItem, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = _safe_optional_text(item.item_type, limit=_MAX_DIAGNOSTIC_KEY_CHARS)
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return counts


def _evidence_kind_modality_counts(items: tuple[ContextItem, ...]) -> dict[str, object]:
    kind_counts: dict[str, int] = {}
    modality_counts: dict[str, int] = {}
    for item in items:
        kind = _diagnostic_text(item, "evidence_kind")
        if kind:
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
        modality = _diagnostic_text(item, "evidence_modality")
        if modality:
            modality_counts[modality] = modality_counts.get(modality, 0) + 1
    return {
        "evidence_kind_counts": dict(sorted(kind_counts.items())),
        "evidence_modality_counts": dict(sorted(modality_counts.items())),
        "items_with_evidence_kind": sum(kind_counts.values()),
        "items_with_evidence_modality": sum(modality_counts.values()),
    }


def _evidence_coverage_profile(items: tuple[ContextItem, ...]) -> dict[str, object]:
    evidence_items = tuple(item for item in items if _has_evidence_identity(item))
    precise_evidence_items = sum(1 for item in evidence_items if _item_has_precise_location(item))
    transcript_items = tuple(item for item in evidence_items if _is_transcript_evidence(item))
    image_region_items = tuple(item for item in evidence_items if _is_image_region_evidence(item))
    video_frame_items = tuple(item for item in evidence_items if _is_video_frame_evidence(item))
    document_items = tuple(item for item in evidence_items if _is_document_evidence(item))
    gaps = _evidence_location_gaps(
        transcript_items=transcript_items,
        image_region_items=image_region_items,
        video_frame_items=video_frame_items,
        document_items=document_items,
    )
    return {
        "schema_version": "evidence-coverage-v1",
        "items_total": len(items),
        "evidence_items_total": len(evidence_items),
        "precise_evidence_items": precise_evidence_items,
        "precise_evidence_location_coverage_ratio": _ratio(
            precise_evidence_items,
            len(evidence_items),
        ),
        "transcript_items_total": len(transcript_items),
        "transcript_time_range_coverage_ratio": _ratio(
            sum(1 for item in transcript_items if _item_has_time_range(item)),
            len(transcript_items),
        ),
        "image_region_items_total": len(image_region_items),
        "image_bbox_coverage_ratio": _ratio(
            sum(1 for item in image_region_items if _item_has_bbox(item)),
            len(image_region_items),
        ),
        "video_frame_items_total": len(video_frame_items),
        "video_time_range_coverage_ratio": _ratio(
            sum(1 for item in video_frame_items if _item_has_time_range(item)),
            len(video_frame_items),
        ),
        "document_items_total": len(document_items),
        "document_page_or_char_coverage_ratio": _ratio(
            sum(1 for item in document_items if _item_has_page_or_char_range(item)),
            len(document_items),
        ),
        "evidence_location_gap_count": len(gaps),
        "evidence_location_gaps": list(gaps[:_MAX_EVIDENCE_LOCATION_GAPS]),
        "prompt_ready_multimodal_evidence": len(gaps) == 0,
    }


def _has_evidence_identity(item: ContextItem) -> bool:
    return bool(
        _diagnostic_text(item, "evidence_kind")
        or _diagnostic_text(item, "evidence_modality")
    )


def _is_transcript_evidence(item: ContextItem) -> bool:
    kind = _diagnostic_text(item, "evidence_kind").casefold()
    modality = _diagnostic_text(item, "evidence_modality").casefold()
    return modality == "audio" or any(marker in kind for marker in ("transcript", "speech", "word"))


def _is_image_region_evidence(item: ContextItem) -> bool:
    kind = _diagnostic_text(item, "evidence_kind").casefold()
    modality = _diagnostic_text(item, "evidence_modality").casefold()
    return modality == "image" and any(
        marker in kind for marker in ("ocr", "region", "bbox", "vision")
    )


def _is_video_frame_evidence(item: ContextItem) -> bool:
    kind = _diagnostic_text(item, "evidence_kind").casefold()
    modality = _diagnostic_text(item, "evidence_modality").casefold()
    return modality == "video" and any(marker in kind for marker in ("keyframe", "frame"))


def _is_document_evidence(item: ContextItem) -> bool:
    kind = _diagnostic_text(item, "evidence_kind").casefold()
    modality = _diagnostic_text(item, "evidence_modality").casefold()
    return modality in {"document", "pdf"} or any(
        marker in kind for marker in ("document", "pdf", "page")
    )


def _evidence_location_gaps(
    *,
    transcript_items: tuple[ContextItem, ...],
    image_region_items: tuple[ContextItem, ...],
    video_frame_items: tuple[ContextItem, ...],
    document_items: tuple[ContextItem, ...],
) -> tuple[str, ...]:
    gaps: list[str] = []
    if any(not _item_has_time_range(item) for item in transcript_items):
        gaps.append("transcript_without_time_range")
    if any(not _item_has_bbox(item) for item in image_region_items):
        gaps.append("image_region_without_bbox")
    if any(not _item_has_time_range(item) for item in video_frame_items):
        gaps.append("video_frame_without_time_range")
    if any(not _item_has_page_or_char_range(item) for item in document_items):
        gaps.append("document_without_page_or_char_range")
    return tuple(gaps)


def _item_has_precise_location(item: ContextItem) -> bool:
    return any(_source_ref_has_precise_location(ref) for ref in item.source_refs)


def _item_has_time_range(item: ContextItem) -> bool:
    return any(
        ref.time_start_ms is not None or ref.time_end_ms is not None
        for ref in item.source_refs
    )


def _item_has_bbox(item: ContextItem) -> bool:
    return any(ref.bbox is not None for ref in item.source_refs)


def _item_has_page_or_char_range(item: ContextItem) -> bool:
    return any(
        ref.page_number is not None
        or ref.char_start is not None
        or ref.char_end is not None
        for ref in item.source_refs
    )


def _diagnostic_text(item: ContextItem, key: str) -> str:
    diagnostics = _as_dict(item.diagnostics)
    provenance = _as_dict(diagnostics.get("provenance"))
    value = diagnostics.get(key) or provenance.get(key)
    text = _safe_optional_text(value, limit=_MAX_DIAGNOSTIC_KEY_CHARS)
    if not text or "[redacted]" in text:
        return ""
    return text


def _diagnostic_source_ref_count(item: ContextItem) -> int:
    diagnostics = _as_dict(item.diagnostics)
    provenance = _as_dict(diagnostics.get("provenance"))
    score_signals = _as_dict(diagnostics.get("score_signals"))
    for value in (
        diagnostics.get("source_ref_count"),
        provenance.get("source_ref_count"),
        score_signals.get("source_ref_count"),
    ):
        count = _optional_non_negative_int(value)
        if count is not None:
            return count
    return len(item.source_refs)


def _multimodal_source_ref_counts(items: tuple[ContextItem, ...]) -> dict[str, int]:
    refs = tuple(ref for item in items for ref in item.source_refs)
    page_count = sum(1 for ref in refs if ref.page_number is not None)
    bbox_count = sum(1 for ref in refs if ref.bbox is not None)
    time_count = sum(
        1 for ref in refs if ref.time_start_ms is not None or ref.time_end_ms is not None
    )
    char_range_count = sum(
        1 for ref in refs if ref.char_start is not None or ref.char_end is not None
    )
    return {
        "multimodal_source_ref_count": sum(1 for ref in refs if _is_multimodal_source_ref(ref)),
        "items_with_multimodal_source_refs": sum(
            1 for item in items if any(_is_multimodal_source_ref(ref) for ref in item.source_refs)
        ),
        "source_refs_with_page_count": page_count,
        "source_refs_with_bbox_count": bbox_count,
        "source_refs_with_time_range_count": time_count,
        "source_refs_with_char_range_count": char_range_count,
    }


def _query_snippet_counts(items: tuple[ContextItem, ...]) -> dict[str, int]:
    items_with_snippets = 0
    enriched_refs = 0
    for item in items:
        diagnostics = _as_dict(item.diagnostics)
        snippet = diagnostics.get("query_snippet")
        if not isinstance(snippet, str) or not snippet.strip():
            continue
        items_with_snippets += 1
        enriched_refs += sum(
            1
            for ref in item.source_refs
            if ref.quote_preview
            and (snippet in ref.quote_preview or ref.quote_preview in snippet)
        )
    return {
        "query_snippet_items_used": items_with_snippets,
        "query_snippet_source_refs_enriched": enriched_refs,
    }


def _media_time_query_counts(items: tuple[ContextItem, ...]) -> dict[str, int]:
    query_items = 0
    matched_items = 0
    for item in items:
        diagnostics = _as_dict(item.diagnostics)
        score_signals = _as_dict(diagnostics.get("score_signals"))
        if _optional_non_negative_int(diagnostics.get("media_time_query_count")):
            query_items += 1
        if _optional_non_negative_int(score_signals.get("media_time_matched_window_count")):
            matched_items += 1
    return {
        "media_time_query_items_used": query_items,
        "media_time_query_matched_items_used": matched_items,
    }


def _retrieval_trace(
    items: tuple[ContextItem, ...],
    *,
    retrieval_sources: tuple[str, ...],
) -> list[dict[str, object]]:
    by_source: dict[str, dict[str, object]] = {}
    source_order = retrieval_sources or ("unknown",)
    for source in source_order:
        by_source[source] = _empty_retrieval_trace_entry(source)

    for item in items:
        item_sources = diagnostic_retrieval_sources(item.diagnostics)
        if not item_sources:
            item_sources = ("unknown",)
            by_source.setdefault("unknown", _empty_retrieval_trace_entry("unknown"))
        for source in item_sources:
            entry = by_source.setdefault(source, _empty_retrieval_trace_entry(source))
            _add_item_to_retrieval_trace_entry(entry, item)

    return [
        _finalize_retrieval_trace_entry(entry)
        for source in source_order[:_MAX_RETRIEVAL_TRACE_ENTRIES]
        if (entry := by_source.get(source)) and entry["item_count"] > 0
    ]


def _empty_retrieval_trace_entry(source: str) -> dict[str, object]:
    return {
        "retrieval_source": _safe_optional_text(
            source,
            limit=_MAX_DIAGNOSTIC_KEY_CHARS,
        )
        or "unknown",
        "item_count": 0,
        "item_types": {},
        "source_ref_count": 0,
        "multimodal_source_ref_count": 0,
        "source_refs_with_char_range_count": 0,
        "source_refs_with_page_count": 0,
        "source_refs_with_bbox_count": 0,
        "source_refs_with_time_range_count": 0,
        "media_time_query_match_count": 0,
        "evidence_kind_counts": {},
        "evidence_modality_counts": {},
        "max_score": 0.0,
        "review_only_count": 0,
        "stale_count": 0,
    }


def _add_item_to_retrieval_trace_entry(
    entry: dict[str, object],
    item: ContextItem,
) -> None:
    diagnostics = _as_dict(item.diagnostics)
    entry["item_count"] = int(entry["item_count"]) + 1
    entry["source_ref_count"] = int(entry["source_ref_count"]) + len(item.source_refs)
    entry["multimodal_source_ref_count"] = int(entry["multimodal_source_ref_count"]) + sum(
        1 for ref in item.source_refs if _is_multimodal_source_ref(ref)
    )
    entry["source_refs_with_char_range_count"] = int(
        entry["source_refs_with_char_range_count"]
    ) + sum(
        1
        for ref in item.source_refs
        if ref.char_start is not None or ref.char_end is not None
    )
    entry["source_refs_with_page_count"] = int(entry["source_refs_with_page_count"]) + sum(
        1 for ref in item.source_refs if ref.page_number is not None
    )
    entry["source_refs_with_bbox_count"] = int(entry["source_refs_with_bbox_count"]) + sum(
        1 for ref in item.source_refs if ref.bbox is not None
    )
    entry["source_refs_with_time_range_count"] = int(
        entry["source_refs_with_time_range_count"]
    ) + sum(
        1
        for ref in item.source_refs
        if ref.time_start_ms is not None or ref.time_end_ms is not None
    )
    entry["media_time_query_match_count"] = int(entry["media_time_query_match_count"]) + int(
        _optional_non_negative_int(
            _as_dict(diagnostics.get("score_signals")).get("media_time_matched_window_count")
        )
        or 0
    )
    entry["max_score"] = max(float(entry["max_score"]), round(float(item.score), 4))
    if diagnostics.get("review_only") is True:
        entry["review_only_count"] = int(entry["review_only_count"]) + 1
    if _safe_optional_text(diagnostics.get("stale_reason"), limit=_MAX_DIAGNOSTIC_KEY_CHARS):
        entry["stale_count"] = int(entry["stale_count"]) + 1
    _increment_count_mapping(entry, "item_types", item.item_type)
    _increment_count_mapping(entry, "evidence_kind_counts", _diagnostic_text(item, "evidence_kind"))
    _increment_count_mapping(
        entry,
        "evidence_modality_counts",
        _diagnostic_text(item, "evidence_modality"),
    )


def _increment_count_mapping(
    entry: dict[str, object],
    key: str,
    raw_value: object,
) -> None:
    value = _safe_optional_text(raw_value, limit=_MAX_DIAGNOSTIC_KEY_CHARS)
    if not value or "[redacted]" in value:
        return
    counts = entry[key]
    if not isinstance(counts, dict):
        counts = {}
        entry[key] = counts
    counts[value] = int(counts.get(value, 0)) + 1


def _finalize_retrieval_trace_entry(entry: dict[str, object]) -> dict[str, object]:
    finalized = dict(entry)
    for key in ("item_types", "evidence_kind_counts", "evidence_modality_counts"):
        counts = finalized.get(key)
        finalized[key] = dict(sorted(counts.items())) if isinstance(counts, dict) else {}
    finalized["max_score"] = round(float(finalized.get("max_score") or 0.0), 4)
    return finalized


def _is_multimodal_source_ref(ref: Any) -> bool:
    return (
        ref.page_number is not None
        or ref.bbox is not None
        or ref.time_start_ms is not None
        or ref.time_end_ms is not None
    )


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


def _non_negative_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value))
    return default


def _optional_non_negative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value))
    return None


def _optional_non_negative_float(value: object) -> float | None:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, int | float):
        return max(0.0, round(float(value), 4))
    return None


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


def _as_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _ordered_unique(
    values: tuple[str, ...],
    *,
    limit: int = _MAX_RETRIEVAL_SOURCES,
) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
        if len(result) >= limit:
            break
    return tuple(result)
