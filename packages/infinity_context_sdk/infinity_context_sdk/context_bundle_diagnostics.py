"""Typed bundle diagnostics for context SDK responses."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from infinity_context_sdk.context_payload_utils import (
    MAX_BUNDLE_DIAGNOSTIC_ITEMS,
    MAX_KEY_CHARS,
    MAX_LIST_ITEMS,
    MAX_RETRIEVAL_SOURCES,
    MAX_STRING_CHARS,
    _as_list,
    _as_mapping,
    _bounded_mapping,
    _int_mapping,
    _non_negative_int,
    _safe_bool,
    _safe_float,
    _safe_text,
    _safe_text_tuple,
)


@dataclass(frozen=True)
class ContextRetrievalTraceEntry:
    retrieval_source: str
    item_count: int
    item_types: Mapping[str, int]
    source_ref_count: int
    multimodal_source_ref_count: int
    evidence_kind_counts: Mapping[str, int]
    evidence_modality_counts: Mapping[str, int]
    max_score: float
    review_only_count: int = 0
    stale_count: int = 0
    source_refs_with_char_range_count: int = 0
    source_refs_with_page_count: int = 0
    source_refs_with_bbox_count: int = 0
    source_refs_with_time_range_count: int = 0
    media_time_query_match_count: int = 0


@dataclass(frozen=True)
class ContextBundleDiagnostics:
    context_assembly_version: str
    consistency_mode: str
    retrieval_sources_used: tuple[str, ...]
    retrieval_sources_total: int
    retrieval_sources_returned: int
    retrieval_sources_truncated: bool
    hybrid_items_used: int
    temporal_replacements_applied: int
    temporal_relations_skipped_by_validity: int
    items_considered: int
    items_used: int
    dropped_by_instruction_flag: int
    dropped_by_budget: int
    dropped_by_source_cap: int
    dropped_by_char_cap: int
    diagnostics_truncated: bool
    raw: Mapping[str, object]
    vector_status: str = "unknown"
    graph_status: str = "unknown"
    rag_status: str = "unknown"
    artifact_evidence_status: str = "unknown"
    facts_considered: int = 0
    anchors_considered: int = 0
    anchors_used: int = 0
    anchor_relation_candidates_considered: int = 0
    anchor_relation_items_used: int = 0
    keyword_chunks_considered: int = 0
    keyword_chunks_dropped_by_relevance: int = 0
    vector_candidate_count: int = 0
    vector_hydrated_count: int = 0
    graph_candidate_count: int = 0
    graph_hydrated_count: int = 0
    artifact_evidence_jobs_considered: int = 0
    artifact_evidence_manifests_considered: int = 0
    artifact_evidence_manifests_used: int = 0
    artifact_evidence_items_considered: int = 0
    artifact_evidence_items_used: int = 0
    artifact_evidence_ranked_candidate_count: int = 0
    artifact_evidence_candidate_cap_reached_count: int = 0
    artifact_evidence_confidence_signal_count: int = 0
    artifact_evidence_coordinate_signal_count: int = 0
    artifact_evidence_time_query_count: int = 0
    artifact_evidence_time_query_match_count: int = 0
    artifact_evidence_time_query_drop_count: int = 0
    artifact_evidence_invalid_time_range_count: int = 0
    artifact_evidence_invalid_bbox_count: int = 0
    artifact_evidence_visual_region_query_drop_count: int = 0
    artifact_evidence_document_location_query_drop_count: int = 0
    artifact_evidence_extracted_text_query_drop_count: int = 0
    artifact_evidence_query_drop_count: int = 0
    artifact_evidence_sensitive_drop_count: int = 0
    artifact_evidence_prompt_injection_drop_count: int = 0
    artifact_evidence_manifest_too_large_count: int = 0
    artifact_evidence_read_error_count: int = 0
    artifact_evidence_parse_error_count: int = 0
    artifact_evidence_schema_skip_count: int = 0
    artifact_evidence_stale_asset_drop_count: int = 0
    stale_vector_drop_count: int = 0
    stale_graph_drop_count: int = 0
    stale_rag_drop_count: int = 0
    stale_facts_considered: int = 0
    stale_facts_used: int = 0
    superseded_facts_considered: int = 0
    superseded_facts_used: int = 0
    temporal_relations_considered: int = 0
    temporal_contradictions_considered: int = 0
    linked_temporal_relations_considered: int = 0
    linked_temporal_replacements_applied: int = 0
    linked_temporal_contradictions_considered: int = 0
    linked_temporal_relations_skipped_by_validity: int = 0
    pending_conflict_suggestions_considered: int = 0
    pending_duplicate_merge_suggestions_considered: int = 0
    approved_context_links_considered: int = 0
    approved_context_links_used: int = 0
    approved_context_linked_chunks_used: int = 0
    approved_context_linked_facts_used: int = 0
    approved_context_linked_anchors_used: int = 0
    approved_context_linked_assets_used: int = 0
    approved_context_linked_asset_manifest_jobs_considered: int = 0
    approved_context_linked_asset_manifest_artifacts_considered: int = 0
    approved_context_linked_asset_manifest_items_used: int = 0
    approved_context_linked_asset_manifest_blob_storage_disabled_count: int = 0
    approved_context_linked_asset_manifest_too_large_count: int = 0
    approved_context_linked_asset_manifest_read_error_count: int = 0
    approved_context_linked_asset_manifest_parse_error_count: int = 0
    approved_context_linked_asset_manifest_schema_skip_count: int = 0
    approved_context_linked_extraction_artifacts_used: int = 0
    approved_context_linked_extraction_artifact_manifest_items_used: int = 0
    approved_context_linked_extraction_artifact_blob_storage_disabled_count: int = 0
    approved_context_linked_extraction_artifact_manifest_too_large_count: int = 0
    approved_context_linked_extraction_artifact_read_error_count: int = 0
    approved_context_linked_extraction_artifact_parse_error_count: int = 0
    approved_context_linked_extraction_artifact_schema_skip_count: int = 0
    stale_context_linked_chunk_drop_count: int = 0
    stale_context_linked_fact_drop_count: int = 0
    stale_context_linked_anchor_drop_count: int = 0
    stale_context_linked_asset_drop_count: int = 0
    stale_context_linked_extraction_artifact_drop_count: int = 0
    diversity_families_considered: int = 0
    diversity_families_used: int = 0
    diversity_items_used: int = 0
    chunk_sources_considered: int = 0
    chunk_sources_used: int = 0
    max_chunks_used_per_source: int = 0
    source_capped_sources_considered: int = 0
    source_capped_sources_used: int = 0
    max_source_capped_items_used_per_source: int = 0
    source_diversity_chunks_reordered: int = 0
    multimodal_source_ref_count: int = 0
    items_with_multimodal_source_refs: int = 0
    source_refs_with_page_count: int = 0
    source_refs_with_bbox_count: int = 0
    source_refs_with_time_range_count: int = 0
    source_refs_with_char_range_count: int = 0
    query_snippet_items_used: int = 0
    query_snippet_source_refs_enriched: int = 0
    media_time_query_items_used: int = 0
    media_time_query_matched_items_used: int = 0
    requirement_guard_items_considered: int = 0
    requirement_guard_items_dropped: int = 0
    anchor_lookup_keys_considered: int = 0
    anchors_loaded_by_lookup: int = 0
    anchors_used_by_query_intent: int = 0
    anchors_dropped_by_query_intent_conflict: int = 0
    query_anchor_hint_count: int = 0
    query_anchor_person_hint_count: int = 0
    query_anchor_event_hint_count: int = 0
    query_anchor_project_hint_count: int = 0
    query_anchor_organization_hint_count: int = 0
    query_anchor_temporal_hint_count: int = 0
    query_anchor_event_type_hint_count: int = 0
    keyword_query_count: int = 0
    keyword_neighbor_chunks_considered: int = 0
    keyword_neighbor_chunks_used: int = 0
    keyword_neighbor_chunks_skipped: int = 0
    keyword_source_sibling_chunks_considered: int = 0
    keyword_source_sibling_chunks_used: int = 0
    keyword_source_sibling_chunks_skipped: int = 0
    keyword_source_sibling_group_count: int = 0
    keyword_source_sibling_candidate_limit: int = 0
    keyword_aggregation_chunks_considered: int = 0
    keyword_aggregation_chunks_used: int = 0
    keyword_aggregation_chunks_skipped: int = 0
    keyword_aggregation_relaxed_relevance_used: int = 0
    keyword_aggregation_slot_reservations_used: int = 0
    keyword_aggregation_source_families_used: int = 0
    keyword_aggregation_numeric_corroborations: int = 0
    keyword_aggregation_distinct_member_candidates: int = 0
    keyword_aggregation_distinct_member_reservations_used: int = 0
    keyword_aggregation_distinct_member_slots_used: int = 0
    keyword_aggregation_chunks_deduplicated: int = 0
    keyword_aggregation_admitted_not_selected: int = 0
    keyword_aggregation_continuity_items_used: int = 0
    keyword_aggregation_continuity_limit: int = 0
    keyword_aggregation_continuity_items_promoted: int = 0
    keyword_aggregation_continuity_items_suppressed: int = 0
    keyword_aggregation_admission_queries: int = 0
    keyword_aggregation_admission_seed_chunks: int = 0
    keyword_aggregation_admission_seed_chunks_added: int = 0
    pre_rerank_distinct_set_evidence_items_considered: int = 0
    pre_rerank_distinct_set_evidence_bodies_restored: int = 0
    pre_rerank_distinct_set_evidence_items_added_for_rerank: int = 0
    pre_rerank_distinct_set_evidence_items_rejected_before_rerank: int = 0
    distinct_set_evidence_items_considered: int = 0
    distinct_set_evidence_bodies_restored: int = 0
    distinct_set_evidence_items_readded: int = 0
    distinct_set_evidence_items_missing_after_ranking: int = 0
    distinct_set_evidence_items_rejected_by_rerank: int = 0
    distinct_set_candidates_considered: int = 0
    distinct_set_source_candidates: int = 0
    distinct_set_items_selected: int = 0
    distinct_set_member_slots_selected: int = 0
    distinct_set_redundant_items_suppressed: int = 0
    vector_query_count: int = 0
    vector_embedding_vector_count: int = 0
    vector_search_count: int = 0
    vector_query_limit: int = 0
    vector_query_degraded_count: int = 0
    graph_query_count: int = 0
    graph_query_limit: int = 0
    graph_query_degraded_count: int = 0
    rag_query_count: int = 0
    rag_query_limit: int = 0
    rag_candidate_count: int = 0
    rag_hydrated_count: int = 0
    rag_query_degraded_count: int = 0
    final_rank_source_item_count: int = 0
    final_rank_candidate_item_count: int = 0
    answer_support_families_considered: int = 0
    answer_support_families_used: int = 0
    answer_support_items_used: int = 0
    dropped_by_source_group_cap: int = 0
    source_refs_total: int = 0
    source_refs_returned: int = 0
    source_refs_truncated: bool = False
    citations_rendered: int = 0
    citations_total: int = 0
    citations_returned: int = 0
    citations_truncated: bool = False
    items_with_citations: int = 0
    answer_support_status: str = "missing"
    answer_support_items_returned: int = 0
    answer_support_cited_count: int = 0
    answer_support_precise_location_count: int = 0
    answer_support_multimodal_count: int = 0
    answer_support_coverage_ratio: float = 0.0
    answer_support_source_type_count: int = 0
    answer_support_evidence_kind_count: int = 0
    answer_support_evidence_modality_count: int = 0
    answer_support_warnings: tuple[str, ...] = ()
    citation_quote_previews_rendered: int = 0
    sensitive_citation_quote_previews_skipped: int = 0
    sensitive_source_identity_parts_redacted: int = 0
    unsafe_source_identity_parts_sanitized: int = 0
    sensitive_item_text_redacted: int = 0
    rendered_chars: int = 0
    max_rendered_chars: int = 0
    provenance_summary: Mapping[str, object] | None = None
    retrieval_quality_summary: Mapping[str, object] | None = None
    retrieval_trace: tuple[ContextRetrievalTraceEntry, ...] = ()


def bundle_diagnostics_from_payload(value: object) -> ContextBundleDiagnostics:
    payload = _as_mapping(value)
    raw = _bounded_mapping(value, max_items=MAX_BUNDLE_DIAGNOSTIC_ITEMS)
    provenance_summary = _bounded_mapping(
        payload.get("provenance_summary"),
        max_items=MAX_BUNDLE_DIAGNOSTIC_ITEMS,
    )
    retrieval_quality_summary = _bounded_mapping(
        payload.get("retrieval_quality_summary"),
        max_items=MAX_BUNDLE_DIAGNOSTIC_ITEMS,
    )
    retrieval_sources_used = _safe_text_tuple(
        raw.get("retrieval_sources_used"),
        limit=MAX_RETRIEVAL_SOURCES,
    )
    safe_raw = dict(raw)
    safe_raw["retrieval_sources_used"] = list(retrieval_sources_used)
    if provenance_summary:
        safe_raw["provenance_summary"] = provenance_summary
    if retrieval_quality_summary:
        safe_raw["retrieval_quality_summary"] = retrieval_quality_summary
    retrieval_sources_total = _non_negative_int(
        raw.get("retrieval_sources_total"),
        default=len(retrieval_sources_used),
    )
    retrieval_sources_returned = _non_negative_int(
        raw.get("retrieval_sources_returned"),
        default=len(retrieval_sources_used),
    )
    retrieval_sources_truncated = (
        _safe_bool(raw.get("retrieval_sources_truncated"))
        or retrieval_sources_total > retrieval_sources_returned
    )
    safe_raw["retrieval_sources_total"] = retrieval_sources_total
    safe_raw["retrieval_sources_returned"] = retrieval_sources_returned
    safe_raw["retrieval_sources_truncated"] = retrieval_sources_truncated
    retrieval_trace = tuple(
        _retrieval_trace_entry_from_payload(entry)
        for entry in _as_list(payload.get("retrieval_trace"))[:MAX_RETRIEVAL_SOURCES]
        if isinstance(entry, Mapping)
    )
    safe_raw["retrieval_trace"] = [
        _retrieval_trace_entry_to_raw(entry) for entry in retrieval_trace
    ]
    answer_support_status = _safe_text(
        payload.get("answer_support_status"),
        default="missing",
        limit=MAX_KEY_CHARS,
    )
    answer_support_items_returned = _non_negative_int(
        payload.get("answer_support_items_returned")
    )
    answer_support_cited_count = _non_negative_int(payload.get("answer_support_cited_count"))
    answer_support_precise_location_count = _non_negative_int(
        payload.get("answer_support_precise_location_count")
    )
    answer_support_multimodal_count = _non_negative_int(
        payload.get("answer_support_multimodal_count")
    )
    answer_support_coverage_ratio = _safe_float(
        payload.get("answer_support_coverage_ratio")
    )
    answer_support_source_type_count = _non_negative_int(
        payload.get("answer_support_source_type_count")
    )
    answer_support_evidence_kind_count = _non_negative_int(
        payload.get("answer_support_evidence_kind_count")
    )
    answer_support_evidence_modality_count = _non_negative_int(
        payload.get("answer_support_evidence_modality_count")
    )
    answer_support_warnings = tuple(
        warning
        for raw_warning in _as_list(payload.get("answer_support_warnings"))[:MAX_LIST_ITEMS]
        if (warning := _safe_text(raw_warning, default="", limit=MAX_STRING_CHARS))
    )
    safe_raw["answer_support_status"] = answer_support_status
    safe_raw["answer_support_items_returned"] = answer_support_items_returned
    safe_raw["answer_support_cited_count"] = answer_support_cited_count
    safe_raw["answer_support_precise_location_count"] = answer_support_precise_location_count
    safe_raw["answer_support_multimodal_count"] = answer_support_multimodal_count
    safe_raw["answer_support_coverage_ratio"] = answer_support_coverage_ratio
    safe_raw["answer_support_source_type_count"] = answer_support_source_type_count
    safe_raw["answer_support_evidence_kind_count"] = answer_support_evidence_kind_count
    safe_raw["answer_support_evidence_modality_count"] = answer_support_evidence_modality_count
    safe_raw["answer_support_warnings"] = list(answer_support_warnings)
    return ContextBundleDiagnostics(
        context_assembly_version=_safe_text(raw.get("context_assembly_version"), default="unknown"),
        consistency_mode=_safe_text(raw.get("consistency_mode"), default="unknown"),
        retrieval_sources_used=retrieval_sources_used,
        retrieval_sources_total=retrieval_sources_total,
        retrieval_sources_returned=retrieval_sources_returned,
        retrieval_sources_truncated=retrieval_sources_truncated,
        hybrid_items_used=_non_negative_int(payload.get("hybrid_items_used")),
        temporal_replacements_applied=_non_negative_int(payload.get("temporal_replacements_applied")),
        temporal_relations_skipped_by_validity=_non_negative_int(
            payload.get("temporal_relations_skipped_by_validity")
        ),
        items_considered=_non_negative_int(payload.get("items_considered")),
        items_used=_non_negative_int(payload.get("items_used")),
        dropped_by_instruction_flag=_non_negative_int(payload.get("dropped_by_instruction_flag")),
        dropped_by_budget=_non_negative_int(payload.get("dropped_by_budget")),
        dropped_by_source_cap=_non_negative_int(payload.get("dropped_by_source_cap")),
        dropped_by_char_cap=_non_negative_int(payload.get("dropped_by_char_cap")),
        diagnostics_truncated=bool(raw.get("diagnostics_truncated")),
        raw=safe_raw,
        vector_status=_safe_text(raw.get("vector_status"), default="unknown"),
        graph_status=_safe_text(raw.get("graph_status"), default="unknown"),
        rag_status=_safe_text(raw.get("rag_status"), default="unknown"),
        artifact_evidence_status=_safe_text(
            raw.get("artifact_evidence_status"),
            default="unknown",
        ),
        facts_considered=_non_negative_int(payload.get("facts_considered")),
        anchors_considered=_non_negative_int(payload.get("anchors_considered")),
        anchors_used=_non_negative_int(payload.get("anchors_used")),
        anchor_relation_candidates_considered=_non_negative_int(
            payload.get("anchor_relation_candidates_considered")
        ),
        anchor_relation_items_used=_non_negative_int(payload.get("anchor_relation_items_used")),
        keyword_chunks_considered=_non_negative_int(payload.get("keyword_chunks_considered")),
        keyword_chunks_dropped_by_relevance=_non_negative_int(
            payload.get("keyword_chunks_dropped_by_relevance")
        ),
        vector_candidate_count=_non_negative_int(payload.get("vector_candidate_count")),
        vector_hydrated_count=_non_negative_int(payload.get("vector_hydrated_count")),
        graph_candidate_count=_non_negative_int(payload.get("graph_candidate_count")),
        graph_hydrated_count=_non_negative_int(payload.get("graph_hydrated_count")),
        artifact_evidence_jobs_considered=_non_negative_int(
            payload.get("artifact_evidence_jobs_considered")
        ),
        artifact_evidence_manifests_considered=_non_negative_int(
            payload.get("artifact_evidence_manifests_considered")
        ),
        artifact_evidence_manifests_used=_non_negative_int(
            payload.get("artifact_evidence_manifests_used")
        ),
        artifact_evidence_items_considered=_non_negative_int(
            payload.get("artifact_evidence_items_considered")
        ),
        artifact_evidence_items_used=_non_negative_int(payload.get("artifact_evidence_items_used")),
        artifact_evidence_ranked_candidate_count=_non_negative_int(
            payload.get("artifact_evidence_ranked_candidate_count")
        ),
        artifact_evidence_candidate_cap_reached_count=_non_negative_int(
            payload.get("artifact_evidence_candidate_cap_reached_count")
        ),
        artifact_evidence_confidence_signal_count=_non_negative_int(
            payload.get("artifact_evidence_confidence_signal_count")
        ),
        artifact_evidence_coordinate_signal_count=_non_negative_int(
            payload.get("artifact_evidence_coordinate_signal_count")
        ),
        artifact_evidence_time_query_count=_non_negative_int(
            payload.get("artifact_evidence_time_query_count")
        ),
        artifact_evidence_time_query_match_count=_non_negative_int(
            payload.get("artifact_evidence_time_query_match_count")
        ),
        artifact_evidence_time_query_drop_count=_non_negative_int(
            payload.get("artifact_evidence_time_query_drop_count")
        ),
        artifact_evidence_invalid_time_range_count=_non_negative_int(
            payload.get("artifact_evidence_invalid_time_range_count")
        ),
        artifact_evidence_invalid_bbox_count=_non_negative_int(
            payload.get("artifact_evidence_invalid_bbox_count")
        ),
        artifact_evidence_visual_region_query_drop_count=_non_negative_int(
            payload.get("artifact_evidence_visual_region_query_drop_count")
        ),
        artifact_evidence_document_location_query_drop_count=_non_negative_int(
            payload.get("artifact_evidence_document_location_query_drop_count")
        ),
        artifact_evidence_extracted_text_query_drop_count=_non_negative_int(
            payload.get("artifact_evidence_extracted_text_query_drop_count")
        ),
        artifact_evidence_query_drop_count=_non_negative_int(
            payload.get("artifact_evidence_query_drop_count")
        ),
        artifact_evidence_sensitive_drop_count=_non_negative_int(
            payload.get("artifact_evidence_sensitive_drop_count")
        ),
        artifact_evidence_prompt_injection_drop_count=_non_negative_int(
            payload.get("artifact_evidence_prompt_injection_drop_count")
        ),
        artifact_evidence_manifest_too_large_count=_non_negative_int(
            payload.get("artifact_evidence_manifest_too_large_count")
        ),
        artifact_evidence_read_error_count=_non_negative_int(
            payload.get("artifact_evidence_read_error_count")
        ),
        artifact_evidence_parse_error_count=_non_negative_int(
            payload.get("artifact_evidence_parse_error_count")
        ),
        artifact_evidence_schema_skip_count=_non_negative_int(
            payload.get("artifact_evidence_schema_skip_count")
        ),
        artifact_evidence_stale_asset_drop_count=_non_negative_int(
            payload.get("artifact_evidence_stale_asset_drop_count")
        ),
        stale_vector_drop_count=_non_negative_int(payload.get("stale_vector_drop_count")),
        stale_graph_drop_count=_non_negative_int(payload.get("stale_graph_drop_count")),
        stale_rag_drop_count=_non_negative_int(payload.get("stale_rag_drop_count")),
        stale_facts_considered=_non_negative_int(payload.get("stale_facts_considered")),
        stale_facts_used=_non_negative_int(payload.get("stale_facts_used")),
        superseded_facts_considered=_non_negative_int(payload.get("superseded_facts_considered")),
        superseded_facts_used=_non_negative_int(payload.get("superseded_facts_used")),
        temporal_relations_considered=_non_negative_int(payload.get("temporal_relations_considered")),
        temporal_contradictions_considered=_non_negative_int(
            payload.get("temporal_contradictions_considered")
        ),
        linked_temporal_relations_considered=_non_negative_int(
            payload.get("linked_temporal_relations_considered")
        ),
        linked_temporal_replacements_applied=_non_negative_int(
            payload.get("linked_temporal_replacements_applied")
        ),
        linked_temporal_contradictions_considered=_non_negative_int(
            payload.get("linked_temporal_contradictions_considered")
        ),
        linked_temporal_relations_skipped_by_validity=_non_negative_int(
            payload.get("linked_temporal_relations_skipped_by_validity")
        ),
        pending_conflict_suggestions_considered=_non_negative_int(
            payload.get("pending_conflict_suggestions_considered")
        ),
        pending_duplicate_merge_suggestions_considered=_non_negative_int(
            payload.get("pending_duplicate_merge_suggestions_considered")
        ),
        approved_context_links_considered=_non_negative_int(
            payload.get("approved_context_links_considered")
        ),
        approved_context_links_used=_non_negative_int(payload.get("approved_context_links_used")),
        approved_context_linked_chunks_used=_non_negative_int(
            payload.get("approved_context_linked_chunks_used")
        ),
        approved_context_linked_facts_used=_non_negative_int(
            payload.get("approved_context_linked_facts_used")
        ),
        approved_context_linked_anchors_used=_non_negative_int(
            payload.get("approved_context_linked_anchors_used")
        ),
        approved_context_linked_assets_used=_non_negative_int(
            payload.get("approved_context_linked_assets_used")
        ),
        approved_context_linked_asset_manifest_jobs_considered=_non_negative_int(
            payload.get("approved_context_linked_asset_manifest_jobs_considered")
        ),
        approved_context_linked_asset_manifest_artifacts_considered=_non_negative_int(
            payload.get("approved_context_linked_asset_manifest_artifacts_considered")
        ),
        approved_context_linked_asset_manifest_items_used=_non_negative_int(
            payload.get("approved_context_linked_asset_manifest_items_used")
        ),
        approved_context_linked_asset_manifest_blob_storage_disabled_count=_non_negative_int(
            payload.get("approved_context_linked_asset_manifest_blob_storage_disabled_count")
        ),
        approved_context_linked_asset_manifest_too_large_count=_non_negative_int(
            payload.get("approved_context_linked_asset_manifest_too_large_count")
        ),
        approved_context_linked_asset_manifest_read_error_count=_non_negative_int(
            payload.get("approved_context_linked_asset_manifest_read_error_count")
        ),
        approved_context_linked_asset_manifest_parse_error_count=_non_negative_int(
            payload.get("approved_context_linked_asset_manifest_parse_error_count")
        ),
        approved_context_linked_asset_manifest_schema_skip_count=_non_negative_int(
            payload.get("approved_context_linked_asset_manifest_schema_skip_count")
        ),
        approved_context_linked_extraction_artifacts_used=_non_negative_int(
            payload.get("approved_context_linked_extraction_artifacts_used")
        ),
        approved_context_linked_extraction_artifact_manifest_items_used=_non_negative_int(
            payload.get("approved_context_linked_extraction_artifact_manifest_items_used")
        ),
        approved_context_linked_extraction_artifact_blob_storage_disabled_count=_non_negative_int(
            payload.get("approved_context_linked_extraction_artifact_blob_storage_disabled_count")
        ),
        approved_context_linked_extraction_artifact_manifest_too_large_count=_non_negative_int(
            payload.get("approved_context_linked_extraction_artifact_manifest_too_large_count")
        ),
        approved_context_linked_extraction_artifact_read_error_count=_non_negative_int(
            payload.get("approved_context_linked_extraction_artifact_read_error_count")
        ),
        approved_context_linked_extraction_artifact_parse_error_count=_non_negative_int(
            payload.get("approved_context_linked_extraction_artifact_parse_error_count")
        ),
        approved_context_linked_extraction_artifact_schema_skip_count=_non_negative_int(
            payload.get("approved_context_linked_extraction_artifact_schema_skip_count")
        ),
        stale_context_linked_chunk_drop_count=_non_negative_int(
            payload.get("stale_context_linked_chunk_drop_count")
        ),
        stale_context_linked_fact_drop_count=_non_negative_int(
            payload.get("stale_context_linked_fact_drop_count")
        ),
        stale_context_linked_anchor_drop_count=_non_negative_int(
            payload.get("stale_context_linked_anchor_drop_count")
        ),
        stale_context_linked_asset_drop_count=_non_negative_int(
            payload.get("stale_context_linked_asset_drop_count")
        ),
        stale_context_linked_extraction_artifact_drop_count=_non_negative_int(
            payload.get("stale_context_linked_extraction_artifact_drop_count")
        ),
        diversity_families_considered=_non_negative_int(payload.get("diversity_families_considered")),
        diversity_families_used=_non_negative_int(payload.get("diversity_families_used")),
        diversity_items_used=_non_negative_int(payload.get("diversity_items_used")),
        chunk_sources_considered=_non_negative_int(payload.get("chunk_sources_considered")),
        chunk_sources_used=_non_negative_int(payload.get("chunk_sources_used")),
        max_chunks_used_per_source=_non_negative_int(payload.get("max_chunks_used_per_source")),
        source_capped_sources_considered=_non_negative_int(
            payload.get("source_capped_sources_considered")
        ),
        source_capped_sources_used=_non_negative_int(payload.get("source_capped_sources_used")),
        max_source_capped_items_used_per_source=_non_negative_int(
            payload.get("max_source_capped_items_used_per_source")
        ),
        source_diversity_chunks_reordered=_non_negative_int(
            payload.get("source_diversity_chunks_reordered")
        ),
        multimodal_source_ref_count=_non_negative_int(payload.get("multimodal_source_ref_count")),
        items_with_multimodal_source_refs=_non_negative_int(
            payload.get("items_with_multimodal_source_refs")
        ),
        source_refs_with_page_count=_non_negative_int(payload.get("source_refs_with_page_count")),
        source_refs_with_bbox_count=_non_negative_int(payload.get("source_refs_with_bbox_count")),
        source_refs_with_time_range_count=_non_negative_int(
            payload.get("source_refs_with_time_range_count")
        ),
        source_refs_with_char_range_count=_non_negative_int(
            payload.get("source_refs_with_char_range_count")
        ),
        query_snippet_items_used=_non_negative_int(payload.get("query_snippet_items_used")),
        query_snippet_source_refs_enriched=_non_negative_int(
            payload.get("query_snippet_source_refs_enriched")
        ),
        media_time_query_items_used=_non_negative_int(payload.get("media_time_query_items_used")),
        media_time_query_matched_items_used=_non_negative_int(
            payload.get("media_time_query_matched_items_used")
        ),
        requirement_guard_items_considered=_non_negative_int(
            payload.get("requirement_guard_items_considered")
        ),
        requirement_guard_items_dropped=_non_negative_int(
            payload.get("requirement_guard_items_dropped")
        ),
        anchor_lookup_keys_considered=_non_negative_int(payload.get("anchor_lookup_keys_considered")),
        anchors_loaded_by_lookup=_non_negative_int(payload.get("anchors_loaded_by_lookup")),
        anchors_used_by_query_intent=_non_negative_int(payload.get("anchors_used_by_query_intent")),
        anchors_dropped_by_query_intent_conflict=_non_negative_int(payload.get("anchors_dropped_by_query_intent_conflict")),
        query_anchor_hint_count=_non_negative_int(payload.get("query_anchor_hint_count")),
        query_anchor_person_hint_count=_non_negative_int(payload.get("query_anchor_person_hint_count")),
        query_anchor_event_hint_count=_non_negative_int(payload.get("query_anchor_event_hint_count")),
        query_anchor_project_hint_count=_non_negative_int(payload.get("query_anchor_project_hint_count")),
        query_anchor_organization_hint_count=_non_negative_int(payload.get("query_anchor_organization_hint_count")),
        query_anchor_temporal_hint_count=_non_negative_int(payload.get("query_anchor_temporal_hint_count")),
        query_anchor_event_type_hint_count=_non_negative_int(payload.get("query_anchor_event_type_hint_count")),
        keyword_query_count=_non_negative_int(payload.get("keyword_query_count")),
        keyword_neighbor_chunks_considered=_non_negative_int(payload.get("keyword_neighbor_chunks_considered")),
        keyword_neighbor_chunks_used=_non_negative_int(payload.get("keyword_neighbor_chunks_used")),
        keyword_neighbor_chunks_skipped=_non_negative_int(payload.get("keyword_neighbor_chunks_skipped")),
        keyword_source_sibling_chunks_considered=_non_negative_int(payload.get("keyword_source_sibling_chunks_considered")),
        keyword_source_sibling_chunks_used=_non_negative_int(payload.get("keyword_source_sibling_chunks_used")),
        keyword_source_sibling_chunks_skipped=_non_negative_int(payload.get("keyword_source_sibling_chunks_skipped")),
        keyword_source_sibling_group_count=_non_negative_int(payload.get("keyword_source_sibling_group_count")),
        keyword_source_sibling_candidate_limit=_non_negative_int(payload.get("keyword_source_sibling_candidate_limit")),
        keyword_aggregation_chunks_considered=_non_negative_int(payload.get("keyword_aggregation_chunks_considered")),
        keyword_aggregation_chunks_used=_non_negative_int(payload.get("keyword_aggregation_chunks_used")),
        keyword_aggregation_chunks_skipped=_non_negative_int(payload.get("keyword_aggregation_chunks_skipped")),
        keyword_aggregation_relaxed_relevance_used=_non_negative_int(
            payload.get("keyword_aggregation_relaxed_relevance_used")
        ),
        keyword_aggregation_slot_reservations_used=_non_negative_int(
            payload.get("keyword_aggregation_slot_reservations_used")
        ),
        keyword_aggregation_source_families_used=_non_negative_int(
            payload.get("keyword_aggregation_source_families_used")
        ),
        keyword_aggregation_numeric_corroborations=_non_negative_int(
            payload.get("keyword_aggregation_numeric_corroborations")
        ),
        keyword_aggregation_distinct_member_candidates=_non_negative_int(
            payload.get("keyword_aggregation_distinct_member_candidates")
        ),
        keyword_aggregation_distinct_member_reservations_used=_non_negative_int(
            payload.get("keyword_aggregation_distinct_member_reservations_used")
        ),
        keyword_aggregation_distinct_member_slots_used=_non_negative_int(
            payload.get("keyword_aggregation_distinct_member_slots_used")
        ),
        keyword_aggregation_chunks_deduplicated=_non_negative_int(
            payload.get("keyword_aggregation_chunks_deduplicated")
        ),
        keyword_aggregation_admitted_not_selected=_non_negative_int(
            payload.get("keyword_aggregation_admitted_not_selected")
        ),
        keyword_aggregation_continuity_items_used=_non_negative_int(
            payload.get("keyword_aggregation_continuity_items_used")
        ),
        keyword_aggregation_continuity_limit=_non_negative_int(
            payload.get("keyword_aggregation_continuity_limit")
        ),
        keyword_aggregation_continuity_items_promoted=_non_negative_int(
            payload.get("keyword_aggregation_continuity_items_promoted")
        ),
        keyword_aggregation_continuity_items_suppressed=_non_negative_int(
            payload.get("keyword_aggregation_continuity_items_suppressed")
        ),
        keyword_aggregation_admission_queries=_non_negative_int(
            payload.get("keyword_aggregation_admission_queries")
        ),
        keyword_aggregation_admission_seed_chunks=_non_negative_int(
            payload.get("keyword_aggregation_admission_seed_chunks")
        ),
        keyword_aggregation_admission_seed_chunks_added=_non_negative_int(
            payload.get("keyword_aggregation_admission_seed_chunks_added")
        ),
        pre_rerank_distinct_set_evidence_items_considered=_non_negative_int(
            payload.get("pre_rerank_distinct_set_evidence_items_considered")
        ),
        pre_rerank_distinct_set_evidence_bodies_restored=_non_negative_int(
            payload.get("pre_rerank_distinct_set_evidence_bodies_restored")
        ),
        pre_rerank_distinct_set_evidence_items_added_for_rerank=_non_negative_int(
            payload.get("pre_rerank_distinct_set_evidence_items_added_for_rerank")
        ),
        pre_rerank_distinct_set_evidence_items_rejected_before_rerank=_non_negative_int(
            payload.get("pre_rerank_distinct_set_evidence_items_rejected_before_rerank")
        ),
        distinct_set_evidence_items_considered=_non_negative_int(
            payload.get("distinct_set_evidence_items_considered")
        ),
        distinct_set_evidence_bodies_restored=_non_negative_int(
            payload.get("distinct_set_evidence_bodies_restored")
        ),
        distinct_set_evidence_items_readded=_non_negative_int(
            payload.get("distinct_set_evidence_items_readded")
        ),
        distinct_set_evidence_items_missing_after_ranking=_non_negative_int(
            payload.get("distinct_set_evidence_items_missing_after_ranking")
        ),
        distinct_set_evidence_items_rejected_by_rerank=_non_negative_int(
            payload.get("distinct_set_evidence_items_rejected_by_rerank")
        ),
        distinct_set_candidates_considered=_non_negative_int(
            payload.get("distinct_set_candidates_considered")
        ),
        distinct_set_source_candidates=_non_negative_int(
            payload.get("distinct_set_source_candidates")
        ),
        distinct_set_items_selected=_non_negative_int(
            payload.get("distinct_set_items_selected")
        ),
        distinct_set_member_slots_selected=_non_negative_int(
            payload.get("distinct_set_member_slots_selected")
        ),
        distinct_set_redundant_items_suppressed=_non_negative_int(
            payload.get("distinct_set_redundant_items_suppressed")
        ),
        vector_query_count=_non_negative_int(payload.get("vector_query_count")),
        vector_embedding_vector_count=_non_negative_int(payload.get("vector_embedding_vector_count")),
        vector_search_count=_non_negative_int(payload.get("vector_search_count")),
        vector_query_limit=_non_negative_int(payload.get("vector_query_limit")),
        vector_query_degraded_count=_non_negative_int(payload.get("vector_query_degraded_count")),
        graph_query_count=_non_negative_int(payload.get("graph_query_count")),
        graph_query_limit=_non_negative_int(payload.get("graph_query_limit")),
        graph_query_degraded_count=_non_negative_int(payload.get("graph_query_degraded_count")),
        rag_query_count=_non_negative_int(payload.get("rag_query_count")),
        rag_query_limit=_non_negative_int(payload.get("rag_query_limit")),
        rag_candidate_count=_non_negative_int(payload.get("rag_candidate_count")),
        rag_hydrated_count=_non_negative_int(payload.get("rag_hydrated_count")),
        rag_query_degraded_count=_non_negative_int(payload.get("rag_query_degraded_count")),
        final_rank_source_item_count=_non_negative_int(payload.get("final_rank_source_item_count")),
        final_rank_candidate_item_count=_non_negative_int(payload.get("final_rank_candidate_item_count")),
        answer_support_families_considered=_non_negative_int(payload.get("answer_support_families_considered")),
        answer_support_families_used=_non_negative_int(payload.get("answer_support_families_used")),
        answer_support_items_used=_non_negative_int(payload.get("answer_support_items_used")),
        dropped_by_source_group_cap=_non_negative_int(payload.get("dropped_by_source_group_cap")),
        source_refs_total=_non_negative_int(raw.get("source_refs_total")),
        source_refs_returned=_non_negative_int(raw.get("source_refs_returned")),
        source_refs_truncated=_safe_bool(raw.get("source_refs_truncated")),
        citations_rendered=_non_negative_int(payload.get("citations_rendered")),
        citations_total=_non_negative_int(raw.get("citations_total")),
        citations_returned=_non_negative_int(raw.get("citations_returned")),
        citations_truncated=_safe_bool(raw.get("citations_truncated")),
        items_with_citations=_non_negative_int(raw.get("items_with_citations")),
        answer_support_status=answer_support_status,
        answer_support_items_returned=answer_support_items_returned,
        answer_support_cited_count=answer_support_cited_count,
        answer_support_precise_location_count=answer_support_precise_location_count,
        answer_support_multimodal_count=answer_support_multimodal_count,
        answer_support_coverage_ratio=answer_support_coverage_ratio,
        answer_support_source_type_count=answer_support_source_type_count,
        answer_support_evidence_kind_count=answer_support_evidence_kind_count,
        answer_support_evidence_modality_count=answer_support_evidence_modality_count,
        answer_support_warnings=answer_support_warnings,
        citation_quote_previews_rendered=_non_negative_int(
            payload.get("citation_quote_previews_rendered")
        ),
        sensitive_citation_quote_previews_skipped=_non_negative_int(
            payload.get("sensitive_citation_quote_previews_skipped")
        ),
        sensitive_source_identity_parts_redacted=_non_negative_int(
            payload.get("sensitive_source_identity_parts_redacted")
        ),
        unsafe_source_identity_parts_sanitized=_non_negative_int(
            payload.get("unsafe_source_identity_parts_sanitized")
        ),
        sensitive_item_text_redacted=_non_negative_int(payload.get("sensitive_item_text_redacted")),
        rendered_chars=_non_negative_int(payload.get("rendered_chars")),
        max_rendered_chars=_non_negative_int(payload.get("max_rendered_chars")),
        provenance_summary=provenance_summary,
        retrieval_quality_summary=retrieval_quality_summary,
        retrieval_trace=retrieval_trace,
    )


def _retrieval_trace_entry_from_payload(
    payload: Mapping[str, object],
) -> ContextRetrievalTraceEntry:
    return ContextRetrievalTraceEntry(
        retrieval_source=_safe_text(
            payload.get("retrieval_source"),
            default="unknown",
            limit=MAX_KEY_CHARS,
        ),
        item_count=_non_negative_int(payload.get("item_count")),
        item_types=_int_mapping(payload.get("item_types")),
        source_ref_count=_non_negative_int(payload.get("source_ref_count")),
        multimodal_source_ref_count=_non_negative_int(payload.get("multimodal_source_ref_count")),
        evidence_kind_counts=_int_mapping(payload.get("evidence_kind_counts")),
        evidence_modality_counts=_int_mapping(payload.get("evidence_modality_counts")),
        max_score=_safe_float(payload.get("max_score")),
        review_only_count=_non_negative_int(payload.get("review_only_count")),
        stale_count=_non_negative_int(payload.get("stale_count")),
        source_refs_with_char_range_count=_non_negative_int(
            payload.get("source_refs_with_char_range_count")
        ),
        source_refs_with_page_count=_non_negative_int(
            payload.get("source_refs_with_page_count")
        ),
        source_refs_with_bbox_count=_non_negative_int(
            payload.get("source_refs_with_bbox_count")
        ),
        source_refs_with_time_range_count=_non_negative_int(
            payload.get("source_refs_with_time_range_count")
        ),
        media_time_query_match_count=_non_negative_int(
            payload.get("media_time_query_match_count")
        ),
    )


def _retrieval_trace_entry_to_raw(entry: ContextRetrievalTraceEntry) -> dict[str, object]:
    return {
        "retrieval_source": entry.retrieval_source,
        "item_count": entry.item_count,
        "item_types": dict(entry.item_types),
        "source_ref_count": entry.source_ref_count,
        "multimodal_source_ref_count": entry.multimodal_source_ref_count,
        "evidence_kind_counts": dict(entry.evidence_kind_counts),
        "evidence_modality_counts": dict(entry.evidence_modality_counts),
        "max_score": entry.max_score,
        "review_only_count": entry.review_only_count,
        "stale_count": entry.stale_count,
        "source_refs_with_char_range_count": entry.source_refs_with_char_range_count,
        "source_refs_with_page_count": entry.source_refs_with_page_count,
        "source_refs_with_bbox_count": entry.source_refs_with_bbox_count,
        "source_refs_with_time_range_count": entry.source_refs_with_time_range_count,
        "media_time_query_match_count": entry.media_time_query_match_count,
    }
