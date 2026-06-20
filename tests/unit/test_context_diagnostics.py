from infinity_context_core.application.context_diagnostics import (
    context_rank_key,
    normalize_context_bundle_diagnostics,
    normalize_context_item_diagnostics,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


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
    assert diagnostics["diagnostics_truncated"] is True
    assert "api_key" not in diagnostics
    assert "SECRET_VALUE_SHOULD_NOT_LEAK" not in str(diagnostics)


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
    assert diagnostics["retrieval_quality_summary"]["multimodal_item_ratio"] == 0.6667
    assert diagnostics["retrieval_quality_summary"]["evidence_location_gap_count"] == 1


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
    }


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
