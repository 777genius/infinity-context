from dataclasses import replace

from infinity_context_core.application.context_diagnostics import (
    context_rank_key,
    merge_context_diagnostics,
    normalize_context_bundle_diagnostics,
    normalize_context_item_diagnostics,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_merge_context_diagnostics_preserves_positive_source_sibling_flags() -> None:
    merged = merge_context_diagnostics(
        primary={
            "score_signals": {
                "source_sibling_answer_evidence": 0,
                "source_sibling_dialogue_visual_reference": 0,
                "source_sibling_group_level_seed": 1,
            },
            "provenance": {
                "source_sibling_answer_evidence": False,
                "source_sibling_dialogue_visual_reference": False,
                "source_sibling_group_level_seed": True,
            },
        },
        secondary={
            "score_signals": {
                "source_sibling_answer_evidence": 1,
                "source_sibling_dialogue_visual_reference": 1,
                "source_sibling_visual_continuation": 1,
            },
            "provenance": {
                "source_sibling_answer_evidence": True,
                "source_sibling_dialogue_visual_reference": True,
                "source_sibling_visual_continuation": True,
            },
        },
        retrieval_sources=("keyword_source_sibling_chunks",),
        source_ref_count=1,
        primary_score=0.99,
        secondary_score=0.98,
        hybrid_boost=0.0,
    )

    assert merged["score_signals"]["source_sibling_dialogue_visual_reference"] == 1
    assert merged["score_signals"]["source_sibling_answer_evidence"] == 1
    assert merged["score_signals"]["source_sibling_group_level_seed"] == 1
    assert merged["score_signals"]["source_sibling_visual_continuation"] == 1
    assert merged["provenance"]["source_sibling_dialogue_visual_reference"] is True
    assert merged["provenance"]["source_sibling_answer_evidence"] is True
    assert merged["provenance"]["source_sibling_group_level_seed"] is True
    assert merged["provenance"]["source_sibling_visual_continuation"] is True


def test_normalize_context_item_diagnostics_preserves_source_sibling_answer_evidence() -> None:
    item = ContextItem(
        item_id="chunk_answer",
        item_type="chunk",
        text="D7:8 Melanie mentioned a book she read last year.",
        score=0.9,
        source_refs=(
            SourceRef(source_type="document", source_id="locomo:conv:session_7:D7:8:turn"),
        ),
        diagnostics={
            **{f"extra_{index}": index for index in range(40)},
            "retrieval_source": "keyword_source_sibling_chunks",
            "score_signals": {
                **{f"extra_signal_{index}": index for index in range(40)},
                "source_sibling_answer_evidence": 1,
                "source_sibling_dialogue_visual_reference": 1,
                "source_sibling_group_level_seed": 1,
                "source_sibling_turn_distance": 0,
            },
            "provenance": {
                **{f"extra_provenance_{index}": index for index in range(40)},
                "source_sibling_answer_evidence": True,
                "source_sibling_dialogue_visual_reference": True,
                "source_sibling_group_level_seed": True,
                "source_sibling_turn_distance": 0,
            },
        },
    )

    normalized = normalize_context_item_diagnostics(item)
    score_signals = normalized.diagnostics["score_signals"]
    provenance = normalized.diagnostics["provenance"]

    assert score_signals["source_sibling_answer_evidence"] == 1
    assert score_signals["source_sibling_dialogue_visual_reference"] == 1
    assert score_signals["source_sibling_group_level_seed"] == 1
    assert score_signals["source_sibling_turn_distance"] == 0
    assert provenance["source_sibling_answer_evidence"] is True
    assert provenance["source_sibling_dialogue_visual_reference"] is True
    assert provenance["source_sibling_group_level_seed"] is True
    assert provenance["source_sibling_turn_distance"] == 0
    assert context_rank_key(normalized) < context_rank_key(
        normalize_context_item_diagnostics(
            replace(
                item,
                item_id="chunk_other",
                diagnostics={
                    **item.diagnostics,
                    "score_signals": {},
                    "provenance": {},
                },
            )
        )
    )


def test_context_bundle_diagnostics_are_bounded_redacted_and_typed() -> None:
    item = ContextItem(
        item_id="chunk_contract",
        item_type="chunk",
        text="Contract diagnostics item.",
        score=0.9,
        source_refs=(),
        diagnostics={
            "retrieval_sources": [f"source_{index}" for index in range(12)],
            "retrieval_source": "source_extra",
        },
    )
    raw_diagnostics = {
        "context_assembly_version": "context-v2-hybrid-explainable",
        "consistency_mode": "best_effort",
        "hybrid_items_used": 2,
        "temporal_replacements_applied": 1,
        "stale_facts_considered": 3,
        "stale_facts_used": 1,
        "answer_support_families_considered": 4,
        "answer_support_families_used": 3,
        "answer_support_items_used": 2,
        "api_key": "SECRET_VALUE_SHOULD_NOT_LEAK",
        **{f"extra_{index}": "x" * 500 for index in range(80)},
    }

    diagnostics = normalize_context_bundle_diagnostics(
        raw_diagnostics,
        items=(item,),
    )

    assert diagnostics["context_assembly_version"] == "context-v2-hybrid-explainable"
    assert diagnostics["consistency_mode"] == "best_effort"
    assert diagnostics["retrieval_sources_used"] == [f"source_{index}" for index in range(8)]
    assert diagnostics["hybrid_items_used"] == 2
    assert diagnostics["temporal_replacements_applied"] == 1
    assert diagnostics["stale_facts_considered"] == 3
    assert diagnostics["stale_facts_used"] == 1
    assert diagnostics["answer_support_families_considered"] == 4
    assert diagnostics["answer_support_families_used"] == 3
    assert diagnostics["answer_support_items_used"] == 2
    assert diagnostics["diagnostics_truncated"] is True
    assert "api_key" not in diagnostics
    assert "SECRET_VALUE_SHOULD_NOT_LEAK" not in str(diagnostics)


def test_context_bundle_diagnostics_preserve_requirement_coverage() -> None:
    item = ContextItem(
        item_id="chunk_contract",
        item_type="chunk",
        text="Contract diagnostics item.",
        score=0.9,
        source_refs=(SourceRef(source_type="document", source_id="doc", page_number=2),),
        diagnostics={},
    )
    secret = "sk-proj-contextcoverage-secret1234567890"
    raw_diagnostics = {
        **{f"extra_{index}": "x" * 500 for index in range(90)},
        "context_requirement_coverage": {
            "status": "partial",
            "requested_total": 2,
            "covered_total": 1,
            "missing_total": 1,
            "requested_modalities": ["document", secret],
            "covered_modalities": ["document"],
            "missing_modalities": [secret],
        },
    }

    diagnostics = normalize_context_bundle_diagnostics(
        raw_diagnostics,
        items=(item,),
    )

    assert diagnostics["context_requirement_coverage"] == {
        "schema_version": "context-requirement-coverage-v1",
        "status": "partial",
        "requested_total": 2,
        "covered_total": 1,
        "missing_total": 1,
        "coverage_ratio": 0.5,
        "requested_anchor_kinds": [],
        "covered_anchor_kinds": [],
        "missing_anchor_kinds": [],
        "requested_modalities": ["document"],
        "covered_modalities": ["document"],
        "missing_modalities": [],
        "requested_evidence_features": [],
        "covered_evidence_features": [],
        "missing_evidence_features": [],
        "requested_answer_shapes": [],
        "covered_answer_shapes": [],
        "missing_answer_shapes": [],
        "answer_shape_warnings": [],
        "item_count": 0,
    }
    assert secret not in str(diagnostics)


def test_context_item_diagnostics_preserve_requirement_score_signals_when_bounded() -> None:
    item = ContextItem(
        item_id="artifact_requirement_boost",
        item_type="extraction_artifact",
        text="Screenshot OCR says Atlas owner is Alex.",
        score=0.9,
        source_refs=(),
        diagnostics={
            "retrieval_source": "artifact_evidence",
            "score_signals": {
                **{f"provider_signal_{index}": index for index in range(40)},
                "context_requirement_boost": 0.036,
                "context_requirement_matched_anchor_kind_count": 1,
                "context_requirement_matched_modality_count": 1,
                "context_requirement_matched_feature_count": 2,
            },
            "provenance": {
                **{f"provider_trace_{index}": index for index in range(40)},
                "context_requirement_boost_applied": True,
                "context_requirement_matched_anchor_kinds": ["project"],
                "context_requirement_matched_modalities": ["image"],
                "context_requirement_matched_evidence_features": [
                    "citation",
                    "visual_region",
                ],
            },
        },
    )

    normalized = normalize_context_item_diagnostics(item)

    score_signals = normalized.diagnostics["score_signals"]
    assert score_signals["context_requirement_boost"] == 0.036
    assert score_signals["context_requirement_matched_anchor_kind_count"] == 1
    assert score_signals["context_requirement_matched_modality_count"] == 1
    assert score_signals["context_requirement_matched_feature_count"] == 2
    assert normalized.diagnostics["provenance"]["context_requirement_boost_applied"] is True
    assert normalized.diagnostics["provenance"][
        "context_requirement_matched_anchor_kinds"
    ] == ["project"]
    assert normalized.diagnostics["provenance"]["context_requirement_matched_modalities"] == [
        "image"
    ]
    assert normalized.diagnostics["provenance"][
        "context_requirement_matched_evidence_features"
    ] == ["citation", "visual_region"]


def test_context_bundle_diagnostics_preserve_temporal_query_intent_when_bounded() -> None:
    diagnostics = normalize_context_bundle_diagnostics(
        {
            **{f"extra_{index}": "x" * 500 for index in range(90)},
            "temporal_query_intent_status": "available",
            "temporal_query_prefers_current": True,
            "temporal_query_requests_previous": False,
            "temporal_query_requests_change": True,
            "temporal_query_after_event": True,
            "temporal_query_before_event": False,
            "temporal_query_excludes_stale": False,
            "temporal_query_include_superseded_review": True,
            "temporal_query_intent_reasons": [
                "prefers_current",
                "requests_change",
                "after_event",
            ],
            "temporal_query_relative_time_hints": [
                "last_week",
                "hours_ago",
            ],
        },
        items=(),
    )

    assert diagnostics["diagnostics_truncated"] is True
    assert diagnostics["temporal_query_intent_status"] == "available"
    assert diagnostics["temporal_query_prefers_current"] is True
    assert diagnostics["temporal_query_requests_previous"] is False
    assert diagnostics["temporal_query_requests_change"] is True
    assert diagnostics["temporal_query_after_event"] is True
    assert diagnostics["temporal_query_before_event"] is False
    assert diagnostics["temporal_query_excludes_stale"] is False
    assert diagnostics["temporal_query_include_superseded_review"] is True
    assert diagnostics["temporal_query_intent_reasons"] == [
        "prefers_current",
        "requests_change",
        "after_event",
    ]
    assert diagnostics["temporal_query_relative_time_hints"] == [
        "last_week",
        "hours_ago",
    ]


def test_context_bundle_diagnostics_preserve_query_plan_when_bounded() -> None:
    diagnostics = normalize_context_bundle_diagnostics(
        {
            **{f"extra_{index}": "x" * 500 for index in range(90)},
            "query_expansion_status": "available",
            "query_expansion_count": 2,
            "query_expansion_reasons": [
                "visual_text_evidence_bridge",
                "change_over_time_bridge",
            ],
            "query_decomposition_status": "available",
            "query_decomposition_count": 3,
            "query_decomposition_reasons": [
                "decomposition_clause",
                "decomposition_temporal_change",
                "decomposition_artifact_evidence",
            ],
        },
        items=(),
    )

    assert diagnostics["diagnostics_truncated"] is True
    assert diagnostics["query_expansion_status"] == "available"
    assert diagnostics["query_expansion_count"] == 2
    assert diagnostics["query_expansion_reasons"] == [
        "visual_text_evidence_bridge",
        "change_over_time_bridge",
    ]
    assert diagnostics["query_decomposition_status"] == "available"
    assert diagnostics["query_decomposition_count"] == 3
    assert diagnostics["query_decomposition_reasons"] == [
        "decomposition_clause",
        "decomposition_temporal_change",
        "decomposition_artifact_evidence",
    ]


def test_context_bundle_diagnostics_preserve_derived_multi_query_counters() -> None:
    diagnostics = normalize_context_bundle_diagnostics(
        {
            **{f"extra_{index}": "x" * 500 for index in range(90)},
            "keyword_query_count": 4,
            "keyword_query_reasons": [
                "original_query",
                "decomposition_relative_time",
                "source_evidence_bridge",
            ],
            "vector_query_count": 6,
            "vector_embedding_vector_count": 6,
            "vector_search_count": 6,
            "vector_query_limit": 15,
            "vector_query_degraded_count": 1,
            "graph_query_count": 4,
            "graph_query_limit": 10,
            "graph_query_degraded_count": 1,
            "rag_query_count": 5,
            "rag_query_limit": 12,
            "rag_candidate_count": 7,
            "rag_hydrated_count": 3,
            "rag_query_degraded_count": 1,
        },
        items=(),
    )

    assert diagnostics["diagnostics_truncated"] is True
    assert diagnostics["keyword_query_count"] == 4
    assert diagnostics["keyword_query_reasons"] == [
        "original_query",
        "decomposition_relative_time",
        "source_evidence_bridge",
    ]
    assert diagnostics["vector_query_count"] == 6
    assert diagnostics["vector_embedding_vector_count"] == 6
    assert diagnostics["vector_search_count"] == 6
    assert diagnostics["vector_query_limit"] == 15
    assert diagnostics["vector_query_degraded_count"] == 1
    assert diagnostics["graph_query_count"] == 4
    assert diagnostics["graph_query_limit"] == 10
    assert diagnostics["graph_query_degraded_count"] == 1
    assert diagnostics["rag_query_count"] == 5
    assert diagnostics["rag_query_limit"] == 12
    assert diagnostics["rag_candidate_count"] == 7
    assert diagnostics["rag_hydrated_count"] == 3
    assert diagnostics["rag_query_degraded_count"] == 1


def test_context_bundle_diagnostics_preserve_artifact_coordinate_drop_counters() -> None:
    diagnostics = normalize_context_bundle_diagnostics(
        {
            "artifact_evidence_visual_region_query_drop_count": 1,
            "artifact_evidence_document_location_query_drop_count": 2,
            "artifact_evidence_extracted_text_query_drop_count": 3,
        },
        items=(),
    )

    assert diagnostics["artifact_evidence_visual_region_query_drop_count"] == 1
    assert diagnostics["artifact_evidence_document_location_query_drop_count"] == 2
    assert diagnostics["artifact_evidence_extracted_text_query_drop_count"] == 3


def test_context_rank_key_uses_phrase_signal_when_scores_tie() -> None:
    target = ContextItem(
        item_id="target",
        item_type="fact",
        text="Graphiti remains the temporal fact engine.",
        score=0.99,
        source_refs=(),
        diagnostics={
            "score_signals": {
                "phrase_bigram_hits": 2,
                "phrase_boost": 0.012,
                "distinctive_term_hits": 4,
                "unique_term_hits": 4,
            }
        },
    )
    decoy = ContextItem(
        item_id="decoy",
        item_type="fact",
        text="Obsidian 3D graph is the primary runtime engine.",
        score=0.99,
        source_refs=(),
        diagnostics={
            "score_signals": {
                "phrase_bigram_hits": 1,
                "phrase_boost": 0.006,
                "distinctive_term_hits": 5,
                "unique_term_hits": 5,
            }
        },
    )

    assert context_rank_key(target) < context_rank_key(decoy)


def test_context_rank_key_uses_deterministic_rerank_net_when_scores_tie() -> None:
    target = ContextItem(
        item_id="self_identification",
        item_type="fact",
        text="Melanie identifies as part of the LGBTQ community.",
        score=0.99,
        source_refs=(),
        diagnostics={
            "score_signals": {
                "deterministic_rerank_net_adjustment": 0.055,
                "deterministic_rerank_requirement_coverage": 1.0,
                "deterministic_rerank_boost": 0.055,
                "phrase_bigram_hits": 1,
                "distinctive_term_hits": 4,
                "unique_term_hits": 4,
            }
        },
    )
    ally_decoy = ContextItem(
        item_id="ally_support",
        item_type="fact",
        text="Melanie supports the LGBTQ community as an ally.",
        score=0.99,
        source_refs=(),
        diagnostics={
            "score_signals": {
                "deterministic_rerank_net_adjustment": 0.0148,
                "deterministic_rerank_requirement_coverage": 1.0,
                "deterministic_rerank_boost": 0.0528,
                "phrase_bigram_hits": 2,
                "distinctive_term_hits": 5,
                "unique_term_hits": 5,
            }
        },
    )

    assert context_rank_key(target) < context_rank_key(ally_decoy)


def test_context_bundle_diagnostics_report_source_totals_and_truncation() -> None:
    item = ContextItem(
        item_id="chunk_contract",
        item_type="chunk",
        text="Contract diagnostics item.",
        score=0.9,
        source_refs=(
            SourceRef(source_type="document", source_id="doc", chunk_id="chunk_1"),
            SourceRef(source_type="manual", source_id="note"),
        ),
        diagnostics={
            "retrieval_sources": [f"source_{index}" for index in range(12)],
            "provenance": {"source_ref_count": 5},
        },
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {"context_assembly_version": "context-v2-hybrid-explainable"},
        items=(item,),
    )

    assert diagnostics["retrieval_sources_used"] == [f"source_{index}" for index in range(8)]
    assert diagnostics["retrieval_sources_total"] == 12
    assert diagnostics["retrieval_sources_returned"] == 8
    assert diagnostics["retrieval_sources_truncated"] is True
    assert diagnostics["source_refs_total"] == 5
    assert diagnostics["source_refs_returned"] == 2
    assert diagnostics["source_refs_truncated"] is True


def test_context_bundle_diagnostics_count_char_range_source_refs() -> None:
    item = ContextItem(
        item_id="chunk_contract",
        item_type="chunk",
        text="Contract diagnostics item.",
        score=0.9,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id="contract_1",
                chunk_id="chunk_7",
                char_start=120,
                char_end=188,
            ),
            SourceRef(source_type="manual", source_id="note"),
        ),
        diagnostics={},
    )

    diagnostics = normalize_context_bundle_diagnostics({}, items=(item,))

    assert diagnostics["source_refs_with_char_range_count"] == 1
    assert diagnostics["source_refs_with_page_count"] == 0
    assert diagnostics["source_refs_with_bbox_count"] == 0
    assert diagnostics["source_refs_with_time_range_count"] == 0


def test_context_bundle_diagnostics_count_evidence_kinds_and_modalities() -> None:
    transcript = ContextItem(
        item_id="artifact_transcript",
        item_type="extraction_artifact",
        text="Transcript says Atlas billing moved.",
        score=0.91,
        source_refs=(
            SourceRef(
                source_type="extraction_artifact",
                source_id="artifact_audio",
                chunk_id="segment_1",
                time_start_ms=1200,
                time_end_ms=6400,
            ),
        ),
        diagnostics={
            "evidence_kind": "transcript_segment",
            "evidence_modality": "audio",
        },
    )
    ocr = ContextItem(
        item_id="artifact_ocr",
        item_type="extraction_artifact",
        text="Screenshot OCR shows Atlas invoice.",
        score=0.9,
        source_refs=(
            SourceRef(
                source_type="extraction_artifact",
                source_id="artifact_image",
                chunk_id="region_1",
                bbox=(10.0, 12.0, 90.0, 44.0),
            ),
        ),
        diagnostics={
            "provenance": {
                "evidence_kind": "ocr_region",
                "evidence_modality": "image",
            },
        },
    )
    keyframe = ContextItem(
        item_id="artifact_video_frame",
        item_type="extraction_artifact",
        text="Video keyframe shows the dashboard.",
        score=0.82,
        source_refs=(),
        diagnostics={
            "evidence_kind": "video_keyframe",
            "evidence_modality": "video",
        },
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {"context_assembly_version": "context-v2-hybrid-explainable"},
        items=(transcript, ocr, keyframe),
    )

    assert diagnostics["evidence_kind_counts"] == {
        "ocr_region": 1,
        "transcript_segment": 1,
        "video_keyframe": 1,
    }
    assert diagnostics["evidence_modality_counts"] == {
        "audio": 1,
        "image": 1,
        "video": 1,
    }
    assert diagnostics["items_with_evidence_kind"] == 3
    assert diagnostics["items_with_evidence_modality"] == 3
    assert diagnostics["evidence_coverage_profile"] == {
        "schema_version": "evidence-coverage-v1",
        "items_total": 3,
        "evidence_items_total": 3,
        "precise_evidence_items": 2,
        "precise_evidence_location_coverage_ratio": 0.6667,
        "transcript_items_total": 1,
        "transcript_time_range_coverage_ratio": 1.0,
        "image_region_items_total": 1,
        "image_bbox_coverage_ratio": 1.0,
        "video_frame_items_total": 1,
        "video_time_range_coverage_ratio": 0.0,
        "document_items_total": 0,
        "document_page_or_char_coverage_ratio": 0.0,
        "evidence_location_gap_count": 1,
        "evidence_location_gaps": ["video_frame_without_time_range"],
        "prompt_ready_multimodal_evidence": False,
    }
    assert diagnostics["retrieval_quality_summary"]["retrieval_mode"] == (
        "multimodal_single_source"
    )


def test_context_bundle_diagnostics_count_media_time_query_matches() -> None:
    transcript = ContextItem(
        item_id="artifact_transcript",
        item_type="extraction_artifact",
        text="Transcript segment at the requested timestamp.",
        score=0.91,
        source_refs=(
            SourceRef(
                source_type="extraction_artifact",
                source_id="artifact_audio",
                chunk_id="segment_42",
                time_start_ms=40_000,
                time_end_ms=45_000,
            ),
        ),
        diagnostics={
            "retrieval_sources": ["artifact_evidence"],
            "evidence_kind": "transcript_segment",
            "evidence_modality": "audio",
            "media_time_query_count": 1,
            "score_signals": {
                "media_time_match_boost": 0.06,
                "media_time_matched_window_count": 1,
            },
        },
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {
            "artifact_evidence_time_query_count": 1,
            "artifact_evidence_time_query_match_count": 1,
            "artifact_evidence_time_query_drop_count": 2,
        },
        items=(transcript,),
    )

    assert diagnostics["artifact_evidence_time_query_count"] == 1
    assert diagnostics["artifact_evidence_time_query_match_count"] == 1
    assert diagnostics["artifact_evidence_time_query_drop_count"] == 2
    assert diagnostics["media_time_query_items_used"] == 1
    assert diagnostics["media_time_query_matched_items_used"] == 1
    assert diagnostics["retrieval_trace"][0]["media_time_query_match_count"] == 1


def test_context_bundle_diagnostics_report_multimodal_evidence_location_gaps() -> None:
    transcript_without_time = ContextItem(
        item_id="audio_transcript",
        item_type="extraction_artifact",
        text="Transcript mentions Atlas without segment coordinates.",
        score=0.88,
        source_refs=(SourceRef(source_type="extraction_artifact", source_id="audio_1"),),
        diagnostics={
            "evidence_kind": "transcript_segment",
            "evidence_modality": "audio",
        },
    )
    ocr_without_bbox = ContextItem(
        item_id="image_ocr",
        item_type="extraction_artifact",
        text="OCR says Atlas budget changed.",
        score=0.87,
        source_refs=(SourceRef(source_type="extraction_artifact", source_id="image_1"),),
        diagnostics={"evidence_kind": "ocr_region", "evidence_modality": "image"},
    )
    keyframe_without_time = ContextItem(
        item_id="video_keyframe",
        item_type="extraction_artifact",
        text="Keyframe shows the roadmap slide.",
        score=0.86,
        source_refs=(SourceRef(source_type="extraction_artifact", source_id="video_1"),),
        diagnostics={"evidence_kind": "video_keyframe", "evidence_modality": "video"},
    )
    document_without_location = ContextItem(
        item_id="document_page",
        item_type="chunk",
        text="Document says Atlas launch moved.",
        score=0.85,
        source_refs=(SourceRef(source_type="document", source_id="doc_1"),),
        diagnostics={"evidence_kind": "document_page", "evidence_modality": "document"},
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {"context_assembly_version": "context-v2-hybrid-explainable"},
        items=(
            transcript_without_time,
            ocr_without_bbox,
            keyframe_without_time,
            document_without_location,
        ),
    )

    assert diagnostics["evidence_coverage_profile"] == {
        "schema_version": "evidence-coverage-v1",
        "items_total": 4,
        "evidence_items_total": 4,
        "precise_evidence_items": 0,
        "precise_evidence_location_coverage_ratio": 0.0,
        "transcript_items_total": 1,
        "transcript_time_range_coverage_ratio": 0.0,
        "image_region_items_total": 1,
        "image_bbox_coverage_ratio": 0.0,
        "video_frame_items_total": 1,
        "video_time_range_coverage_ratio": 0.0,
        "document_items_total": 1,
        "document_page_or_char_coverage_ratio": 0.0,
        "evidence_location_gap_count": 4,
        "evidence_location_gaps": [
            "transcript_without_time_range",
            "image_region_without_bbox",
            "video_frame_without_time_range",
            "document_without_page_or_char_range",
        ],
        "prompt_ready_multimodal_evidence": False,
    }
    summary = diagnostics["retrieval_quality_summary"]
    assert summary["evidence_location_coverage_ratio"] == 0.0
    assert summary["evidence_location_gap_count"] == 4
    assert "low_evidence_location_coverage" in summary["actionable_gaps"]
    assert "evidence_location_gaps_present" in summary["actionable_gaps"]


def test_context_bundle_diagnostics_defaults_empty_contract() -> None:
    diagnostics = normalize_context_bundle_diagnostics(
        {
            "context_assembly_version": "context-v2-hybrid-explainable",
            "consistency_mode": "best_effort",
        },
        items=(),
    )

    assert diagnostics["context_assembly_version"] == "context-v2-hybrid-explainable"
    assert diagnostics["consistency_mode"] == "best_effort"
    assert diagnostics["retrieval_sources_used"] == []
    assert diagnostics["retrieval_sources_total"] == 0
    assert diagnostics["retrieval_sources_returned"] == 0
    assert diagnostics["retrieval_sources_truncated"] is False
    assert diagnostics["vector_status"] == "unknown"
    assert diagnostics["graph_status"] == "unknown"
    assert diagnostics["rag_status"] == "unknown"
    assert diagnostics["facts_considered"] == 0
    assert diagnostics["keyword_chunks_considered"] == 0
    assert diagnostics["hybrid_items_used"] == 0
    assert diagnostics["temporal_replacements_applied"] == 0
    assert diagnostics["items_considered"] == 0
    assert diagnostics["items_used"] == 0
    assert diagnostics["diversity_families_considered"] == 0
    assert diagnostics["diversity_families_used"] == 0
    assert diagnostics["diversity_items_used"] == 0
    assert diagnostics["answer_support_families_considered"] == 0
    assert diagnostics["answer_support_families_used"] == 0
    assert diagnostics["answer_support_items_used"] == 0
    assert diagnostics["chunk_sources_considered"] == 0
    assert diagnostics["chunk_sources_used"] == 0
    assert diagnostics["max_chunks_used_per_source"] == 0
    assert diagnostics["source_diversity_chunks_reordered"] == 0
    assert diagnostics["dropped_by_instruction_flag"] == 0
    assert diagnostics["dropped_by_budget"] == 0
    assert diagnostics["anchors_considered"] == 0
    assert diagnostics["anchors_used"] == 0
    assert diagnostics["citations_rendered"] == 0
    assert diagnostics["citation_quote_previews_rendered"] == 0
    assert diagnostics["sensitive_citation_quote_previews_skipped"] == 0
    assert diagnostics["sensitive_item_text_redacted"] == 0
    assert diagnostics["source_refs_with_char_range_count"] == 0
    assert diagnostics["source_refs_with_bbox_count"] == 0
    assert diagnostics["source_refs_total"] == 0
    assert diagnostics["source_refs_returned"] == 0
    assert diagnostics["source_refs_truncated"] is False
    assert diagnostics["evidence_kind_counts"] == {}
    assert diagnostics["evidence_modality_counts"] == {}
    assert diagnostics["items_with_evidence_kind"] == 0
    assert diagnostics["items_with_evidence_modality"] == 0
    assert diagnostics["evidence_coverage_profile"] == {
        "schema_version": "evidence-coverage-v1",
        "items_total": 0,
        "evidence_items_total": 0,
        "precise_evidence_items": 0,
        "precise_evidence_location_coverage_ratio": 0.0,
        "transcript_items_total": 0,
        "transcript_time_range_coverage_ratio": 0.0,
        "image_region_items_total": 0,
        "image_bbox_coverage_ratio": 0.0,
        "video_frame_items_total": 0,
        "video_time_range_coverage_ratio": 0.0,
        "document_items_total": 0,
        "document_page_or_char_coverage_ratio": 0.0,
        "evidence_location_gap_count": 0,
        "evidence_location_gaps": [],
        "prompt_ready_multimodal_evidence": True,
    }
    assert diagnostics["retrieval_quality_summary"] == {
        "schema_version": "retrieval-quality-v1",
        "evidence_strength": "empty",
        "answerability_status": "insufficient_context",
        "recommended_response_policy": "ask_for_more_context",
        "retrieval_mode": "empty",
        "freshness_status": "empty",
        "items_total": 0,
        "retrieval_source_count": 0,
        "hybrid_item_ratio": 0.0,
        "citation_coverage_ratio": 0.0,
        "precise_location_coverage_ratio": 0.0,
        "query_snippet_coverage_ratio": 0.0,
        "multimodal_item_ratio": 0.0,
        "evidence_location_coverage_ratio": 0.0,
        "evidence_location_gap_count": 0,
        "review_pressure_ratio": 0.0,
        "stale_item_ratio": 0.0,
        "stale_filtered_count": 0,
        "temporal_replacement_count": 0,
        "superseded_review_ratio": 0.0,
        "default_context_excludes_stale": True,
        "high_confidence_items": 0,
        "medium_confidence_items": 0,
        "low_confidence_items": 0,
        "evidence_kind_count": 0,
        "evidence_modality_count": 0,
        "actionable_gaps": ["no_context_items"],
        "answerability_reasons": ["no_context_items"],
    }


def test_context_bundle_diagnostics_report_strong_retrieval_quality_summary() -> None:
    fact = ContextItem(
        item_id="fact_atlas",
        item_type="fact",
        text="Alex approved the Atlas renewal.",
        score=0.96,
        source_refs=(
            SourceRef(
                source_type="fact",
                source_id="fact_atlas",
                char_start=8,
                char_end=36,
                quote_preview="Alex approved the Atlas renewal.",
            ),
        ),
        diagnostics={
            "retrieval_sources": ["postgres_facts", "approved_context_linked_facts"],
        },
    )
    transcript = ContextItem(
        item_id="artifact_audio",
        item_type="extraction_artifact",
        text="Audio transcript says the Atlas renewal was approved.",
        score=0.9,
        source_refs=(
            SourceRef(
                source_type="extraction_artifact",
                source_id="artifact_audio",
                chunk_id="segment_1",
                time_start_ms=1200,
                time_end_ms=5400,
                quote_preview="Atlas renewal was approved.",
            ),
        ),
        diagnostics={
            "retrieval_sources": ["artifact_evidence", "rag_recall"],
            "evidence_kind": "transcript_segment",
            "evidence_modality": "audio",
            "query_snippet": "Atlas renewal was approved.",
        },
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {
            "context_assembly_version": "context-v2-hybrid-explainable",
            "hybrid_items_used": 2,
            "query_snippet_items_used": 1,
        },
        items=(fact, transcript),
    )

    assert diagnostics["retrieval_quality_summary"] == {
        "schema_version": "retrieval-quality-v1",
        "evidence_strength": "strong",
        "answerability_status": "grounded",
        "recommended_response_policy": "answer_with_citations",
        "retrieval_mode": "hybrid_multimodal",
        "freshness_status": "fresh",
        "items_total": 2,
        "retrieval_source_count": 4,
        "hybrid_item_ratio": 1.0,
        "citation_coverage_ratio": 1.0,
        "precise_location_coverage_ratio": 1.0,
        "query_snippet_coverage_ratio": 0.5,
        "multimodal_item_ratio": 0.5,
        "evidence_location_coverage_ratio": 1.0,
        "evidence_location_gap_count": 0,
        "review_pressure_ratio": 0.0,
        "stale_item_ratio": 0.0,
        "stale_filtered_count": 0,
        "temporal_replacement_count": 0,
        "superseded_review_ratio": 0.0,
        "default_context_excludes_stale": True,
        "high_confidence_items": 2,
        "medium_confidence_items": 0,
        "low_confidence_items": 0,
        "evidence_kind_count": 1,
        "evidence_modality_count": 1,
        "actionable_gaps": [],
        "answerability_reasons": [],
    }


def test_context_quality_uses_answer_shape_warnings_as_caveats() -> None:
    item = ContextItem(
        item_id="melanie_support_only",
        item_type="chunk",
        text=(
            "Melanie supports Caroline's transgender journey and encourages "
            "LGBTQ community acceptance as an ally."
        ),
        score=0.96,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="D3:5",
                quote_preview="Melanie supports Caroline as an ally.",
            ),
        ),
        diagnostics={"retrieval_sources": ["keyword_chunks"]},
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {
            "context_requirement_coverage": {
                "requested_total": 1,
                "covered_total": 1,
                "missing_total": 0,
                "requested_answer_shapes": ["inference"],
                "covered_answer_shapes": ["inference"],
                "missing_answer_shapes": [],
                "answer_shape_warnings": [
                    "community_membership_support_only_without_self_identification"
                ],
                "item_count": 1,
            }
        },
        items=(item,),
    )

    summary = diagnostics["retrieval_quality_summary"]
    assert summary["evidence_strength"] == "strong"
    assert summary["answerability_status"] == "usable_with_caveats"
    assert summary["recommended_response_policy"] == "answer_with_caveat_and_citations"
    assert summary["actionable_gaps"] == [
        "community_membership_support_only_without_self_identification"
    ]
    assert summary["answerability_reasons"] == [
        "community_membership_support_only_without_self_identification"
    ]


def test_context_quality_downgrades_when_explicit_visual_region_requirement_missing() -> None:
    item = ContextItem(
        item_id="chunk_atlas",
        item_type="chunk",
        text="Atlas invoice owner is Alex, but this chunk has no screen region.",
        score=0.96,
        source_refs=(
            SourceRef(
                source_type="asset_extraction",
                source_id="extract_atlas",
                chunk_id="ocr_owner_text",
                quote_preview="Atlas invoice owner is Alex.",
            ),
        ),
        diagnostics={
            "retrieval_sources": ["artifact_evidence", "keyword_chunks"],
            "query_snippet": "Atlas invoice owner is Alex.",
            "evidence_kind": "ocr_region",
            "evidence_modality": "image",
        },
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {
            "context_assembly_version": "context-v2-hybrid-explainable",
            "query_snippet_items_used": 1,
            "context_requirement_coverage": {
                "requested_total": 1,
                "covered_total": 0,
                "requested_evidence_features": ["visual_region"],
                "missing_evidence_features": ["visual_region"],
            },
        },
        items=(item,),
    )

    summary = diagnostics["retrieval_quality_summary"]
    assert summary["evidence_strength"] == "strong"
    assert summary["answerability_status"] == "insufficient_evidence"
    assert summary["recommended_response_policy"] == "ask_for_more_context"
    assert "explicit_requirements_missing" in summary["actionable_gaps"]
    assert "missing_visual_region_requirement" in summary["actionable_gaps"]
    assert "missing_visual_region_requirement" in summary["answerability_reasons"]


def test_context_quality_downgrades_when_explicit_extracted_text_requirement_missing() -> None:
    item = ContextItem(
        item_id="image_metadata_atlas",
        item_type="extraction_artifact",
        text="Project Atlas screenshot metadata is available, but OCR text is missing.",
        score=0.95,
        source_refs=(SourceRef(source_type="asset", source_id="asset_atlas_screenshot"),),
        diagnostics={
            "retrieval_sources": ["artifact_evidence", "keyword_chunks"],
            "query_snippet": "Project Atlas screenshot metadata is available.",
            "evidence_kind": "image_metadata",
            "evidence_modality": "image",
        },
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {
            "context_assembly_version": "context-v2-hybrid-explainable",
            "query_snippet_items_used": 1,
            "context_requirement_coverage": {
                "requested_total": 1,
                "covered_total": 0,
                "requested_evidence_features": ["extracted_text"],
                "missing_evidence_features": ["extracted_text"],
            },
        },
        items=(item,),
    )

    summary = diagnostics["retrieval_quality_summary"]
    assert summary["answerability_status"] == "insufficient_evidence"
    assert summary["recommended_response_policy"] == "ask_for_more_context"
    assert "missing_extracted_text_requirement" in summary["actionable_gaps"]
    assert "missing_extracted_text_requirement" in summary["answerability_reasons"]


def test_context_quality_downgrades_when_choice_answer_shape_missing() -> None:
    item = ContextItem(
        item_id="john_option_echo",
        item_type="chunk",
        text="John discussed whether a beach or mountains sounded nice someday.",
        score=0.95,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="D8:3",
                char_start=0,
                char_end=62,
                quote_preview="John discussed whether a beach or mountains sounded nice someday.",
            ),
        ),
        diagnostics={
            "retrieval_sources": ["keyword_chunks"],
            "query_snippet": "beach or mountains",
        },
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {
            "context_assembly_version": "context-v2-hybrid-explainable",
            "query_snippet_items_used": 1,
            "context_requirement_coverage": {
                "requested_total": 1,
                "covered_total": 0,
                "requested_answer_shapes": ["choice"],
                "missing_answer_shapes": ["choice"],
            },
        },
        items=(item,),
    )

    summary = diagnostics["retrieval_quality_summary"]
    assert summary["answerability_status"] == "insufficient_evidence"
    assert summary["recommended_response_policy"] == "ask_for_more_context"
    assert "missing_choice_answer_shape_requirement" in summary["actionable_gaps"]
    assert "missing_choice_answer_shape_requirement" in summary["answerability_reasons"]


def test_context_quality_downgrades_when_constraint_answer_shape_missing() -> None:
    item = ContextItem(
        item_id="alex_positive_food_note",
        item_type="chunk",
        text="Alex eats peanuts and enjoys shellfish at weekend dinners.",
        score=0.95,
        source_refs=(
            SourceRef(
                source_type="note",
                source_id="food_note",
                char_start=0,
                char_end=58,
                quote_preview="Alex eats peanuts and enjoys shellfish at weekend dinners.",
            ),
        ),
        diagnostics={
            "retrieval_sources": ["keyword_chunks"],
            "query_snippet": "Alex eats peanuts and enjoys shellfish.",
        },
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {
            "context_assembly_version": "context-v2-hybrid-explainable",
            "query_snippet_items_used": 1,
            "context_requirement_coverage": {
                "requested_total": 1,
                "covered_total": 0,
                "requested_answer_shapes": ["constraint"],
                "missing_answer_shapes": ["constraint"],
            },
        },
        items=(item,),
    )

    summary = diagnostics["retrieval_quality_summary"]
    assert summary["answerability_status"] == "insufficient_evidence"
    assert summary["recommended_response_policy"] == "ask_for_more_context"
    assert "missing_constraint_answer_shape_requirement" in summary["actionable_gaps"]
    assert "missing_constraint_answer_shape_requirement" in summary["answerability_reasons"]


def test_context_quality_downgrades_when_action_role_answer_shape_missing() -> None:
    item = ContextItem(
        item_id="passive_recommendation",
        item_type="chunk",
        text="Becoming Nicole was recommended during the reading discussion.",
        score=0.95,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="D5:3",
                char_start=0,
                char_end=62,
                quote_preview="Becoming Nicole was recommended during the reading discussion.",
            ),
        ),
        diagnostics={
            "retrieval_sources": ["keyword_chunks"],
            "query_snippet": "recommended Becoming Nicole to Melanie",
        },
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {
            "context_assembly_version": "context-v2-hybrid-explainable",
            "query_snippet_items_used": 1,
            "context_requirement_coverage": {
                "requested_total": 1,
                "covered_total": 0,
                "requested_answer_shapes": ["action_role"],
                "missing_answer_shapes": ["action_role"],
            },
        },
        items=(item,),
    )

    summary = diagnostics["retrieval_quality_summary"]
    assert summary["answerability_status"] == "insufficient_evidence"
    assert summary["recommended_response_policy"] == "ask_for_more_context"
    assert "missing_action_role_answer_shape_requirement" in summary["actionable_gaps"]
    assert "missing_action_role_answer_shape_requirement" in summary["answerability_reasons"]


def test_context_quality_downgrades_when_location_answer_shape_missing() -> None:
    item = ContextItem(
        item_id="alex_generic_move",
        item_type="chunk",
        text="Alex discussed moving someday but did not name a city.",
        score=0.95,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="D9:3",
                char_start=0,
                char_end=54,
                quote_preview="Alex discussed moving someday but did not name a city.",
            ),
        ),
        diagnostics={
            "retrieval_sources": ["keyword_chunks"],
            "query_snippet": "where Alex live now",
        },
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {
            "context_assembly_version": "context-v2-hybrid-explainable",
            "query_snippet_items_used": 1,
            "context_requirement_coverage": {
                "requested_total": 1,
                "covered_total": 0,
                "requested_answer_shapes": ["location"],
                "missing_answer_shapes": ["location"],
            },
        },
        items=(item,),
    )

    summary = diagnostics["retrieval_quality_summary"]
    assert summary["answerability_status"] == "insufficient_evidence"
    assert summary["recommended_response_policy"] == "ask_for_more_context"
    assert "missing_location_answer_shape_requirement" in summary["actionable_gaps"]
    assert "missing_location_answer_shape_requirement" in summary["answerability_reasons"]


def test_context_quality_downgrades_when_preference_answer_shape_missing() -> None:
    item = ContextItem(
        item_id="alex_music_mention",
        item_type="chunk",
        text="Alex discussed ambient music during the studio call.",
        score=0.95,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="D11:3",
                char_start=0,
                char_end=53,
                quote_preview="Alex discussed ambient music during the studio call.",
            ),
        ),
        diagnostics={
            "retrieval_sources": ["keyword_chunks"],
            "query_snippet": "what music Alex like",
        },
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {
            "context_assembly_version": "context-v2-hybrid-explainable",
            "query_snippet_items_used": 1,
            "context_requirement_coverage": {
                "requested_total": 1,
                "covered_total": 0,
                "requested_answer_shapes": ["preference"],
                "missing_answer_shapes": ["preference"],
            },
        },
        items=(item,),
    )

    summary = diagnostics["retrieval_quality_summary"]
    assert summary["answerability_status"] == "insufficient_evidence"
    assert summary["recommended_response_policy"] == "ask_for_more_context"
    assert "missing_preference_answer_shape_requirement" in summary["actionable_gaps"]
    assert "missing_preference_answer_shape_requirement" in summary["answerability_reasons"]


def test_context_quality_downgrades_when_relationship_answer_shape_missing() -> None:
    item = ContextItem(
        item_id="alex_school_note",
        item_type="chunk",
        text="Alex went to school with Maria.",
        score=0.95,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="D4:3",
                char_start=0,
                char_end=31,
                quote_preview="Alex went to school with Maria.",
            ),
        ),
        diagnostics={
            "retrieval_sources": ["keyword_chunks"],
            "query_snippet": "Alex old friend school",
        },
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {
            "context_assembly_version": "context-v2-hybrid-explainable",
            "query_snippet_items_used": 1,
            "context_requirement_coverage": {
                "requested_total": 1,
                "covered_total": 0,
                "requested_answer_shapes": ["relationship"],
                "missing_answer_shapes": ["relationship"],
            },
        },
        items=(item,),
    )

    summary = diagnostics["retrieval_quality_summary"]
    assert summary["answerability_status"] == "insufficient_evidence"
    assert summary["recommended_response_policy"] == "ask_for_more_context"
    assert "missing_relationship_answer_shape_requirement" in summary["actionable_gaps"]
    assert "missing_relationship_answer_shape_requirement" in summary["answerability_reasons"]


def test_context_quality_downgrades_when_commitment_answer_shape_missing() -> None:
    item = ContextItem(
        item_id="atlas_discussion",
        item_type="chunk",
        text="Atlas was discussed during the meeting with Alex.",
        score=0.95,
        source_refs=(
            SourceRef(
                source_type="meeting_notes",
                source_id="D14:4",
                char_start=0,
                char_end=49,
                quote_preview="Atlas was discussed during the meeting with Alex.",
            ),
        ),
        diagnostics={
            "retrieval_sources": ["keyword_chunks"],
            "query_snippet": "Atlas meeting action items",
        },
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {
            "context_assembly_version": "context-v2-hybrid-explainable",
            "query_snippet_items_used": 1,
            "context_requirement_coverage": {
                "requested_total": 1,
                "covered_total": 0,
                "requested_answer_shapes": ["commitment"],
                "missing_answer_shapes": ["commitment"],
            },
        },
        items=(item,),
    )

    summary = diagnostics["retrieval_quality_summary"]
    assert summary["answerability_status"] == "insufficient_evidence"
    assert summary["recommended_response_policy"] == "ask_for_more_context"
    assert "missing_commitment_answer_shape_requirement" in summary["actionable_gaps"]
    assert "missing_commitment_answer_shape_requirement" in summary["answerability_reasons"]


def test_context_quality_downgrades_when_gotcha_answer_shape_missing() -> None:
    item = ContextItem(
        item_id="atlas_deployment_plain",
        item_type="chunk",
        text="Atlas deployment uses Docker, Postgres, Qdrant, and the API worker.",
        score=0.95,
        source_refs=(
            SourceRef(
                source_type="runbook",
                source_id="atlas_deploy",
                char_start=0,
                char_end=68,
                quote_preview="Atlas deployment uses Docker, Postgres, Qdrant, and the API worker.",
            ),
        ),
        diagnostics={
            "retrieval_sources": ["keyword_chunks"],
            "query_snippet": "Atlas deployment known issues",
        },
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {
            "context_assembly_version": "context-v2-hybrid-explainable",
            "query_snippet_items_used": 1,
            "context_requirement_coverage": {
                "requested_total": 1,
                "covered_total": 0,
                "requested_answer_shapes": ["gotcha"],
                "missing_answer_shapes": ["gotcha"],
            },
        },
        items=(item,),
    )

    summary = diagnostics["retrieval_quality_summary"]
    assert summary["answerability_status"] == "insufficient_evidence"
    assert summary["recommended_response_policy"] == "ask_for_more_context"
    assert "missing_gotcha_answer_shape_requirement" in summary["actionable_gaps"]
    assert "missing_gotcha_answer_shape_requirement" in summary["answerability_reasons"]


def test_context_quality_downgrades_when_existence_answer_shape_missing() -> None:
    item = ContextItem(
        item_id="atlas_topic_note",
        item_type="chunk",
        text="Project Atlas was approved after the billing call.",
        score=0.95,
        source_refs=(
            SourceRef(
                source_type="note",
                source_id="atlas_note",
                char_start=0,
                char_end=49,
                quote_preview="Project Atlas was approved after the billing call.",
            ),
        ),
        diagnostics={
            "retrieval_sources": ["keyword_chunks"],
            "query_snippet": "Alex ever mentioned Project Atlas",
        },
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {
            "context_assembly_version": "context-v2-hybrid-explainable",
            "query_snippet_items_used": 1,
            "context_requirement_coverage": {
                "requested_total": 1,
                "covered_total": 0,
                "requested_answer_shapes": ["existence"],
                "missing_answer_shapes": ["existence"],
            },
        },
        items=(item,),
    )

    summary = diagnostics["retrieval_quality_summary"]
    assert summary["answerability_status"] == "insufficient_evidence"
    assert summary["recommended_response_policy"] == "ask_for_more_context"
    assert "missing_existence_answer_shape_requirement" in summary["actionable_gaps"]
    assert "missing_existence_answer_shape_requirement" in summary["answerability_reasons"]


def test_context_quality_downgrades_when_state_update_answer_shape_missing() -> None:
    item = ContextItem(
        item_id="atlas_provider_without_current_marker",
        item_type="chunk",
        text="Atlas provider is OpenAI.",
        score=0.95,
        source_refs=(
            SourceRef(
                source_type="fact",
                source_id="provider_plain",
                char_start=0,
                char_end=25,
                quote_preview="Atlas provider is OpenAI.",
            ),
        ),
        diagnostics={
            "retrieval_sources": ["postgres_facts"],
            "query_snippet": "latest current Atlas provider",
        },
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {
            "context_assembly_version": "context-v2-hybrid-explainable",
            "query_snippet_items_used": 1,
            "context_requirement_coverage": {
                "requested_total": 1,
                "covered_total": 0,
                "requested_answer_shapes": ["state_update"],
                "missing_answer_shapes": ["state_update"],
            },
        },
        items=(item,),
    )

    summary = diagnostics["retrieval_quality_summary"]
    assert summary["answerability_status"] == "insufficient_evidence"
    assert summary["recommended_response_policy"] == "ask_for_more_context"
    assert "missing_state_update_answer_shape_requirement" in summary["actionable_gaps"]
    assert "missing_state_update_answer_shape_requirement" in summary["answerability_reasons"]


def test_context_quality_keeps_caveat_for_noncritical_missing_anchor_requirement() -> None:
    item = ContextItem(
        item_id="fact_atlas",
        item_type="fact",
        text="Atlas renewal was approved by Alex.",
        score=0.95,
        source_refs=(
            SourceRef(
                source_type="fact",
                source_id="fact_atlas",
                char_start=0,
                char_end=35,
                quote_preview="Atlas renewal was approved by Alex.",
            ),
        ),
        diagnostics={
            "retrieval_sources": ["postgres_facts", "keyword_chunks"],
            "query_snippet": "Atlas renewal was approved by Alex.",
        },
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {
            "context_assembly_version": "context-v2-hybrid-explainable",
            "query_snippet_items_used": 1,
            "context_requirement_coverage": {
                "requested_total": 2,
                "covered_total": 1,
                "requested_anchor_kinds": ["project", "person"],
                "covered_anchor_kinds": ["project"],
                "missing_anchor_kinds": ["person"],
            },
        },
        items=(item,),
    )

    summary = diagnostics["retrieval_quality_summary"]
    assert summary["evidence_strength"] == "strong"
    assert summary["answerability_status"] == "usable_with_caveats"
    assert summary["recommended_response_policy"] == "answer_with_caveat_and_citations"
    assert "missing_person_anchor_requirement" in summary["actionable_gaps"]
    assert summary["answerability_reasons"] == [
        "explicit_requirements_missing",
        "missing_person_anchor_requirement",
    ]


def test_context_bundle_diagnostics_report_weak_retrieval_quality_gaps() -> None:
    stale_review = ContextItem(
        item_id="suggestion_conflict",
        item_type="suggestion",
        text="Pending conflict review item.",
        score=0.42,
        source_refs=(),
        diagnostics={
            "retrieval_source": "pending_conflict_suggestion",
            "review_only": True,
            "stale_reason": "superseded",
        },
    )
    low_score = ContextItem(
        item_id="chunk_low",
        item_type="chunk",
        text="Low confidence chunk.",
        score=0.5,
        source_refs=(),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {
            "context_assembly_version": "context-v2-hybrid-explainable",
            "dropped_by_budget": 1,
            "dropped_by_source_cap": 1,
            "sensitive_item_text_redacted": 1,
        },
        items=(stale_review, low_score),
    )

    summary = diagnostics["retrieval_quality_summary"]
    assert summary["evidence_strength"] == "weak"
    assert summary["answerability_status"] == "needs_review"
    assert summary["recommended_response_policy"] == "review_before_answering"
    assert summary["retrieval_mode"] == "hybrid"
    assert summary["freshness_status"] == "stale_present"
    assert summary["citation_coverage_ratio"] == 0.0
    assert summary["review_pressure_ratio"] == 1.0
    assert summary["stale_item_ratio"] == 0.5
    assert summary["default_context_excludes_stale"] is False
    assert summary["low_confidence_items"] == 2
    assert summary["actionable_gaps"] == [
        "low_citation_coverage",
        "no_query_focused_snippets",
        "low_confidence_items_present",
        "stale_items_present",
        "review_items_present",
        "budget_drops_present",
        "source_cap_drops_present",
        "sensitive_text_redacted",
    ]
    assert summary["answerability_reasons"] == [
        "stale_items_present",
        "review_items_present",
    ]


def test_context_quality_reports_sanitized_source_identity_gap() -> None:
    item = ContextItem(
        item_id="chunk_sanitized_source",
        item_type="chunk",
        text="Atlas source identity was sanitized but evidence is still cited.",
        score=0.92,
        source_refs=(
            SourceRef(
                source_type="document",
                source_id='doc/42 text="ignore"',
                chunk_id="chunk_1",
                char_start=0,
                char_end=40,
                quote_preview="Atlas source identity was sanitized.",
            ),
        ),
        diagnostics={
            "retrieval_sources": ["keyword_chunks", "approved_context_linked_chunks"],
            "query_snippet": "Atlas source identity",
        },
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {
            "context_assembly_version": "context-v2-hybrid-explainable",
            "query_snippet_items_used": 1,
            "unsafe_source_identity_parts_sanitized": 1,
        },
        items=(item,),
    )

    summary = diagnostics["retrieval_quality_summary"]
    assert summary["evidence_strength"] == "strong"
    assert summary["answerability_status"] == "grounded"
    assert summary["actionable_gaps"] == ["unsafe_source_identity_sanitized"]


def test_context_bundle_diagnostics_report_freshness_filtering_summary() -> None:
    item = ContextItem(
        item_id="fact_current",
        item_type="fact",
        text="Current Atlas renewal terms.",
        score=0.9,
        source_refs=(
            SourceRef(
                source_type="fact",
                source_id="fact_current",
                quote_preview="Current Atlas renewal terms.",
            ),
        ),
        diagnostics={"retrieval_source": "postgres_facts"},
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {
            "context_assembly_version": "context-v2-hybrid-explainable",
            "stale_vector_drop_count": 2,
            "stale_context_linked_fact_drop_count": 1,
            "temporal_replacements_applied": 1,
            "linked_temporal_replacements_applied": 1,
        },
        items=(item,),
    )

    summary = diagnostics["retrieval_quality_summary"]
    assert summary["freshness_status"] == "fresh_with_temporal_replacements"
    assert summary["stale_filtered_count"] == 3
    assert summary["temporal_replacement_count"] == 2
    assert summary["stale_item_ratio"] == 0.0
    assert summary["default_context_excludes_stale"] is True


def test_context_bundle_retrieval_sources_use_stable_priority_order() -> None:
    keyword = ContextItem(
        item_id="chunk_keyword",
        item_type="chunk",
        text="Keyword item.",
        score=0.8,
        source_refs=(),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )
    vector = ContextItem(
        item_id="chunk_vector",
        item_type="chunk",
        text="Vector item.",
        score=0.7,
        source_refs=(),
        diagnostics={"retrieval_source": "vector_chunks"},
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {"context_assembly_version": "context-v2-hybrid-explainable"},
        items=(keyword, vector),
    )

    assert diagnostics["retrieval_sources_used"] == ["vector_chunks", "keyword_chunks"]


def test_context_bundle_retrieval_sources_prioritize_rag_over_keyword() -> None:
    keyword = ContextItem(
        item_id="chunk_keyword",
        item_type="chunk",
        text="Keyword item.",
        score=0.9,
        source_refs=(),
        diagnostics={"retrieval_source": "keyword_chunks"},
    )
    rag = ContextItem(
        item_id="chunk_rag",
        item_type="chunk",
        text="RAG item.",
        score=0.8,
        source_refs=(),
        diagnostics={"retrieval_source": "rag_recall"},
    )

    diagnostics = normalize_context_bundle_diagnostics(
        {"context_assembly_version": "context-v2-hybrid-explainable"},
        items=(keyword, rag),
    )

    assert diagnostics["retrieval_sources_used"] == ["rag_recall", "keyword_chunks"]


def test_context_item_diagnostics_report_retrieval_source_truncation() -> None:
    item = ContextItem(
        item_id="chunk_many_sources",
        item_type="chunk",
        text="Many source diagnostics item.",
        score=0.9,
        source_refs=(),
        diagnostics={
            "retrieval_source": "source_0",
            "retrieval_sources": [f"source_{index}" for index in range(1, 20)],
        },
    )

    normalized = normalize_context_item_diagnostics(item).diagnostics

    assert normalized["retrieval_sources"] == [f"source_{index}" for index in range(8)]
    assert normalized["retrieval_sources_total"] == 20
    assert normalized["retrieval_sources_returned"] == 8
    assert normalized["retrieval_sources_truncated"] is True
    assert "source_8" not in normalized["retrieval_sources"]


def test_context_item_diagnostics_always_report_retrieval_source_counts() -> None:
    item = ContextItem(
        item_id="fact_single_source",
        item_type="fact",
        text="Single source diagnostics item.",
        score=0.9,
        source_refs=(),
        diagnostics={
            "retrieval_source": "postgres_facts",
            "ranking_reason": "canonical active fact matched query and filters",
        },
    )

    normalized = normalize_context_item_diagnostics(item).diagnostics

    assert normalized["retrieval_sources"] == ["postgres_facts"]
    assert normalized["retrieval_sources_total"] == 1
    assert normalized["retrieval_sources_returned"] == 1
    assert normalized["retrieval_sources_truncated"] is False
    assert normalized["ranking_reason"] == "canonical active fact matched query and filters"


def test_context_item_diagnostics_include_computed_evidence_profile() -> None:
    item = ContextItem(
        item_id="artifact_video_segment",
        item_type="extraction_artifact",
        text="Video transcript mentions Atlas renewal.",
        score=0.93,
        source_refs=(
            SourceRef(
                source_type="extraction_artifact",
                source_id="video_artifact",
                chunk_id="segment_1",
                char_start=12,
                char_end=44,
                page_number=2,
                time_start_ms=1_500,
                time_end_ms=4_200,
                bbox=(10.0, 20.0, 120.0, 80.0),
                quote_preview="Atlas renewal moved to Friday.",
            ),
            SourceRef(
                source_type="manual",
                source_id="note_1",
            ),
        ),
        diagnostics={"retrieval_source": "artifact_evidence"},
    )

    normalized = normalize_context_item_diagnostics(item).diagnostics

    assert normalized["citation_count"] == 2
    assert normalized["has_citations"] is True
    assert normalized["has_quote_preview"] is True
    assert normalized["has_precise_location"] is True
    assert normalized["has_multimodal_location"] is True
    assert normalized["source_refs_with_quote_preview_count"] == 1
    assert normalized["source_refs_with_char_range_count"] == 1
    assert normalized["source_refs_with_page_count"] == 1
    assert normalized["source_refs_with_bbox_count"] == 1
    assert normalized["source_refs_with_time_range_count"] == 1
    assert normalized["evidence_profile"] == {
        "schema_version": "context-item-evidence-profile-v1",
        "citation_count": 2,
        "source_ref_count": 2,
        "has_citations": True,
        "has_quote_preview": True,
        "has_precise_location": True,
        "has_multimodal_location": True,
        "source_refs_with_quote_preview_count": 1,
        "source_refs_with_char_range_count": 1,
        "source_refs_with_page_count": 1,
        "source_refs_with_bbox_count": 1,
        "source_refs_with_time_range_count": 1,
        "location_kinds": ["char_range", "page", "bbox", "time_range"],
    }
    assert normalized["provenance"]["source_ref_count"] == 2


def test_context_item_evidence_profile_does_not_copy_quote_text() -> None:
    secretish_quote = "sk-proj-provider-secret should never be mirrored into diagnostics"
    item = ContextItem(
        item_id="fact_secret_quote",
        item_type="fact",
        text="Fact with sensitive quoted evidence.",
        score=0.9,
        source_refs=(
            SourceRef(
                source_type="manual",
                source_id="source_1",
                quote_preview=secretish_quote,
            ),
        ),
        diagnostics={},
    )

    normalized = normalize_context_item_diagnostics(item).diagnostics

    assert normalized["evidence_profile"]["has_quote_preview"] is True
    assert secretish_quote not in str(normalized["evidence_profile"])
