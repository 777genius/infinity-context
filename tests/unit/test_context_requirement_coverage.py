from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.application.context_requirement_coverage import (
    context_requirement_coverage,
    sanitize_context_requirement_coverage,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_context_requirement_coverage_satisfies_anchor_and_multimodal_request() -> None:
    query = "созвон с алексом про атлас час назад, дай цитату и таймкод"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="anchor_event_call",
            item_type="anchor",
            text="event: Call with Alex about Atlas hour ago.",
            score=0.94,
            source_refs=(),
            diagnostics={"anchor_kind": "event", "memory_scope_id": "scope"},
        ),
        ContextItem(
            item_id="artifact_audio_segment",
            item_type="extraction_artifact",
            text="Transcript: Alex approved Atlas rollout.",
            score=0.91,
            source_refs=(
                SourceRef(
                    source_type="extraction_artifact",
                    source_id="artifact_audio",
                    chunk_id="segment_1",
                    quote_preview="Alex approved Atlas rollout.",
                    time_start_ms=1200,
                    time_end_ms=6400,
                ),
            ),
            diagnostics={
                "evidence_kind": "transcript_segment",
                "evidence_modality": "audio",
                "memory_scope_id": "scope",
            },
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert coverage["status"] == "satisfied"
    assert set(coverage["requested_anchor_kinds"]) >= {"person", "project", "event"}
    assert set(coverage["covered_anchor_kinds"]) >= {"event", "person", "project"}
    assert coverage["requested_modalities"] == ["audio"]
    assert coverage["covered_modalities"] == ["audio"]
    assert set(coverage["requested_evidence_features"]) == {"citation", "time_range"}
    assert set(coverage["covered_evidence_features"]) >= {"citation", "time_range"}
    assert coverage["missing_total"] == 0
    assert coverage["coverage_ratio"] == 1.0


def test_context_requirement_coverage_does_not_treat_what_as_timestamp_request() -> None:
    query = "What hobbies do Caroline and Melanie have in common?"
    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(),
    )

    assert "time_range" not in coverage["requested_evidence_features"]
    assert coverage["requested_answer_shapes"] == ["list", "commonality"]


def test_context_requirement_coverage_detects_explicit_timestamp_request() -> None:
    query = "What does Alex say at 01:23 in the video?"
    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        items=(),
    )

    assert "video" in coverage["requested_modalities"]
    assert "time_range" in coverage["requested_evidence_features"]


def test_context_requirement_coverage_reports_missing_visual_region() -> None:
    query = "покажи что было на скриншоте про Atlas, нужна область на экране"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="fact_atlas",
            item_type="fact",
            text="Atlas billing was approved, but no screenshot evidence is attached.",
            score=0.88,
            source_refs=(SourceRef(source_type="manual", source_id="fact_atlas"),),
            diagnostics={"memory_scope_id": "scope"},
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert coverage["status"] == "missing"
    assert "image" in coverage["missing_modalities"]
    assert "visual_region" in coverage["missing_evidence_features"]
    assert coverage["missing_total"] > 0
    assert coverage["coverage_ratio"] == 0.0


def test_context_requirement_coverage_requires_extracted_text_for_screenshot_text_query() -> None:
    query = "что написано на скриншоте Project Atlas"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="image_metadata_only",
            item_type="extraction_artifact",
            text="Screenshot metadata: 1280x720 PNG.",
            score=0.86,
            source_refs=(
                SourceRef(
                    source_type="asset",
                    source_id="asset_screenshot",
                    quote_preview="Screenshot metadata: 1280x720 PNG.",
                ),
            ),
            diagnostics={
                "evidence_kind": "image_metadata",
                "evidence_modality": "image",
            },
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert coverage["status"] == "partial"
    assert coverage["requested_modalities"] == ["image"]
    assert coverage["covered_modalities"] == ["image"]
    assert "extracted_text" in coverage["requested_evidence_features"]
    assert "extracted_text" in coverage["missing_evidence_features"]


def test_context_requirement_coverage_satisfies_screenshot_text_with_ocr_region() -> None:
    query = "read text on screenshot Project Atlas, where on screen"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="artifact_screenshot_ocr",
            item_type="extraction_artifact",
            text="OCR region: Project Atlas approved.",
            score=0.92,
            source_refs=(
                SourceRef(
                    source_type="extraction_artifact",
                    source_id="artifact_screenshot_ocr",
                    chunk_id="ocr-region-1",
                    quote_preview="Project Atlas approved.",
                    bbox=(12.0, 20.0, 260.0, 64.0),
                ),
            ),
            diagnostics={
                "evidence_kind": "ocr_region",
                "evidence_modality": "image",
            },
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert coverage["status"] == "satisfied"
    assert coverage["requested_modalities"] == ["image"]
    assert set(coverage["requested_evidence_features"]) >= {
        "extracted_text",
        "visual_region",
    }
    assert set(coverage["covered_evidence_features"]) >= {
        "citation",
        "extracted_text",
        "visual_region",
    }
    assert coverage["missing_total"] == 0


def test_context_requirement_coverage_supports_document_page_citations() -> None:
    query = "find the page in the PDF document where Atlas renewal is mentioned"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="doc_chunk_7",
            item_type="chunk",
            text="Atlas renewal appears in section 7.",
            score=0.9,
            source_refs=(
                SourceRef(
                    source_type="document",
                    source_id="doc_atlas_pdf",
                    chunk_id="chunk_7",
                    page_number=7,
                    quote_preview="Atlas renewal appears in section 7.",
                ),
            ),
            diagnostics={"memory_scope_id": "scope"},
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert coverage["status"] == "satisfied"
    assert coverage["requested_modalities"] == ["document"]
    assert coverage["covered_modalities"] == ["document"]
    assert set(coverage["requested_evidence_features"]) >= {"citation", "page_or_char"}
    assert set(coverage["covered_evidence_features"]) >= {"citation", "page_or_char"}


def test_context_requirement_coverage_treats_attachment_as_document() -> None:
    query = "Найди вложение по Atlas renewal"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="attached_doc",
            item_type="chunk",
            text="Atlas renewal attachment summary.",
            score=0.9,
            source_refs=(
                SourceRef(
                    source_type="document_chunk",
                    source_id="attached_atlas_pdf",
                    chunk_id="chunk_1",
                    quote_preview="Atlas renewal attachment summary.",
                ),
            ),
            diagnostics={"memory_scope_id": "scope"},
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert coverage["status"] == "satisfied"
    assert coverage["requested_modalities"] == ["document"]
    assert coverage["covered_modalities"] == ["document"]


def test_context_requirement_coverage_requests_time_range_for_word_relative_time() -> None:
    query = "What did Alex say two weeks ago?"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="transcript_segment",
            item_type="extraction_artifact",
            text=(
                "event: call with Alex two weeks ago. "
                "Alex discussed Atlas in a transcript segment."
            ),
            score=0.9,
            source_refs=(
                SourceRef(
                    source_type="extraction_artifact",
                    source_id="audio_transcript",
                    chunk_id="segment_2",
                    time_start_ms=12_000,
                    time_end_ms=18_000,
                ),
            ),
            diagnostics={"evidence_kind": "transcript_segment"},
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert coverage["status"] == "satisfied"
    assert "time_range" in coverage["requested_evidence_features"]
    assert "time_range" in coverage["covered_evidence_features"]


def test_context_requirement_coverage_tracks_answer_shapes() -> None:
    query = "How many tournaments did Nate win, and when did he win the fourth one?"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="nate_fourth_tournament",
            item_type="chunk",
            text="Nate won his fourth video game tournament last Friday.",
            score=0.9,
            source_refs=(SourceRef(source_type="locomo_turn", source_id="D17:1"),),
            diagnostics={"memory_scope_id": "scope"},
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert set(coverage["requested_answer_shapes"]) == {"count", "ordinal", "temporal"}
    assert set(coverage["covered_answer_shapes"]) >= {"count", "ordinal", "temporal"}
    assert coverage["missing_answer_shapes"] == []
    assert coverage["status"] == "satisfied"


def test_context_requirement_coverage_tracks_ordinal_answer_shape() -> None:
    query = "Which tournament did Nate win fourth?"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="nate_fourth_tournament",
            item_type="chunk",
            text="Nate won his fourth video game tournament at the charity arcade night.",
            score=0.9,
            source_refs=(SourceRef(source_type="locomo_turn", source_id="D17:1"),),
            diagnostics={"memory_scope_id": "scope"},
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert "ordinal" in coverage["requested_answer_shapes"]
    assert "ordinal" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []
    assert coverage["status"] == "satisfied"


def test_context_requirement_coverage_counts_explicit_enumerated_list_as_count() -> None:
    query = "How many pets does Gina have?"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="gina_pets",
            item_type="chunk",
            text="Gina has a rescue dog, a cat, and a turtle at home.",
            score=0.9,
            source_refs=(SourceRef(source_type="locomo_turn", source_id="D8:4"),),
            diagnostics={"memory_scope_id": "scope"},
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert coverage["requested_answer_shapes"] == ["count"]
    assert set(coverage["covered_answer_shapes"]) >= {"count", "list"}
    assert coverage["missing_answer_shapes"] == []
    assert coverage["status"] == "satisfied"


def test_context_requirement_coverage_tracks_inference_answer_shape() -> None:
    query = "Would Melanie be considered an ally?"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="melanie_ally_support",
            item_type="chunk",
            text="Melanie encourages Caroline and helps her feel accepted and supported.",
            score=0.9,
            source_refs=(SourceRef(source_type="locomo_turn", source_id="D12:3"),),
            diagnostics={"memory_scope_id": "scope"},
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert coverage["requested_answer_shapes"] == ["inference"]
    assert "inference" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []
    assert coverage["answer_shape_warnings"] == []
    assert coverage["status"] == "satisfied"


def test_context_requirement_coverage_tracks_social_inference_without_likely_marker() -> None:
    query = "Does Nate have friends besides Joanna?"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="nate_team_friends",
            item_type="chunk",
            text="Nate plays Valorant with online teammates and gaming friends from tournaments.",
            score=0.9,
            source_refs=(SourceRef(source_type="locomo_turn", source_id="D7:2"),),
            diagnostics={"memory_scope_id": "scope"},
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert coverage["requested_answer_shapes"] == ["inference"]
    assert "inference" in coverage["covered_answer_shapes"]
    assert "inference" not in coverage["missing_answer_shapes"]


def test_context_requirement_coverage_tracks_support_role_inference_evidence() -> None:
    query = "Would Caroline be a good mentor for Alex?"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="caroline_mentor_fit",
            item_type="chunk",
            text=(
                "Caroline mentored LGBTQ youth, listened patiently, and helped "
                "people feel safe in the community program."
            ),
            score=0.9,
            source_refs=(SourceRef(source_type="locomo_turn", source_id="D9:2"),),
            diagnostics={"memory_scope_id": "scope"},
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert "inference" in coverage["requested_answer_shapes"]
    assert "inference" in coverage["covered_answer_shapes"]
    assert "inference" not in coverage["missing_answer_shapes"]


def test_context_requirement_coverage_tracks_generic_behavior_inference_evidence() -> None:
    query = "Would Alex be considered reliable?"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="alex_reliable_behavior",
            item_type="chunk",
            text=(
                "Alex kept his promises, followed through, and prepared the "
                "launch notes early."
            ),
            score=0.9,
            source_refs=(SourceRef(source_type="locomo_turn", source_id="D4:9"),),
            diagnostics={"memory_scope_id": "scope"},
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert coverage["requested_answer_shapes"] == ["inference"]
    assert "inference" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []
    assert coverage["answer_shape_warnings"] == []


def test_context_requirement_coverage_tracks_direct_trait_inference_evidence() -> None:
    query = "Would Caroline be considered patient?"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="caroline_patient_trait",
            item_type="chunk",
            text="Caroline is thoughtful and patient with new volunteers.",
            score=0.9,
            source_refs=(SourceRef(source_type="locomo_turn", source_id="D16:18"),),
            diagnostics={"memory_scope_id": "scope"},
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert coverage["requested_answer_shapes"] == ["inference"]
    assert "inference" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []
    assert coverage["answer_shape_warnings"] == []


def test_context_requirement_coverage_tracks_preference_inference_evidence() -> None:
    query = 'Would Melanie likely enjoy the song "The Four Seasons" by Vivaldi?'
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="melanie_classical_music",
        item_type="chunk",
        text="Melanie is a fan of classical music like Bach and Mozart.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D15:3"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["inference"]
    assert "inference" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []
    assert coverage["answer_shape_warnings"] == []


def test_context_requirement_coverage_tracks_state_residence_inference_evidence() -> None:
    query = "Which US state do Audrey and Andrew potentially live in?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="andrew_map_trail",
        item_type="chunk",
        text=(
            "Andrew image caption: a photo of a map of a park with a lot of "
            "trees. Andrew image query: hiking trails map perfect spot."
        ),
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D11:9"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["inference"]
    assert "inference" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []
    assert coverage["answer_shape_warnings"] == []


def test_context_requirement_coverage_tracks_political_inference_evidence() -> None:
    query = "What would Caroline's political leaning likely be?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="caroline_political_values",
        item_type="chunk",
        text=(
            "Caroline said religious conservatives made her feel unwelcoming "
            "about her transition and LGBTQ rights."
        ),
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D12:1"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["inference"]
    assert "inference" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_indirect_degree_policy_inference_with_caveat() -> None:
    query = "What might John's degree be in?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="john_policy_degree",
        item_type="chunk",
        text=(
            "John: I'm considering going into policymaking because of my degree "
            "and my passion for making a positive impact."
        ),
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D9:6"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["inference"]
    assert "inference" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []
    assert coverage["answer_shape_warnings"] == [
        "degree_field_inferred_from_policy_career_evidence"
    ]


def test_context_requirement_coverage_tracks_direct_degree_field_inference_without_caveat() -> None:
    query = "What might John's degree be in?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="john_direct_degree",
        item_type="chunk",
        text="John studied political science and public policy at university.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D9:4"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["inference"]
    assert "inference" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []
    assert coverage["answer_shape_warnings"] == []


def test_context_requirement_coverage_tracks_community_membership_inference() -> None:
    query = "Would Melanie be considered a member of the LGBTQ community?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="melanie_lgbtq_membership",
        item_type="chunk",
        text=(
            "Melanie identifies as part of the LGBTQ community and joined "
            "the pride support group."
        ),
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D12:8"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["inference"]
    assert "inference" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_support_only_community_membership_inference() -> None:
    query = "Would Melanie be considered a member of the LGBTQ community?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="melanie_lgbtq_support_only",
        item_type="chunk",
        text=(
            "Melanie is supportive of Caroline's transgender journey and "
            "encourages LGBTQ community acceptance as an ally."
        ),
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D3:5"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["inference"]
    assert "inference" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []
    assert coverage["answer_shape_warnings"] == [
        "community_membership_support_only_without_self_identification"
    ]


def test_context_requirement_coverage_tracks_allergy_condition_inference() -> None:
    query = "What underlying condition might Joanna have based on her allergies?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="joanna_broad_animal_allergy",
        item_type="chunk",
        text=(
            "Joanna is allergic to reptiles, animals with fur, and cockroaches. "
            "Her face gets puffy and itchy."
        ),
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D2:23"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["inference"]
    assert "inference" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_keeps_topic_only_music_out_of_inference() -> None:
    query = 'Would Melanie likely enjoy the song "The Four Seasons" by Vivaldi?'
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="vivaldi_topic_only",
        item_type="chunk",
        text="The orchestra discussed Vivaldi and classical symphony forms in music class.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D15:4"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "inference" in coverage["requested_answer_shapes"]
    assert "inference" not in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == ["inference"]


def test_context_requirement_coverage_tracks_choice_answer_shape() -> None:
    query = "Does John live close to a beach or the mountains?"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="john_beach_evidence",
            item_type="chunk",
            text="John goes on weekly walks by the ocean and lives close to the beach.",
            score=0.9,
            source_refs=(SourceRef(source_type="locomo_turn", source_id="D8:2"),),
            diagnostics={"memory_scope_id": "scope"},
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert coverage["requested_answer_shapes"] == ["choice"]
    assert "choice" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []
    assert coverage["status"] == "satisfied"


def test_context_requirement_coverage_tracks_missing_choice_answer_shape() -> None:
    query = "Does John live close to a beach or the mountains?"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="john_option_echo",
            item_type="chunk",
            text="John discussed whether a beach or mountains sounded nice someday.",
            score=0.9,
            source_refs=(SourceRef(source_type="locomo_turn", source_id="D8:3"),),
            diagnostics={"memory_scope_id": "scope"},
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert coverage["requested_answer_shapes"] == ["choice"]
    assert "choice" not in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == ["choice"]
    assert coverage["status"] == "missing"


def test_context_requirement_coverage_does_not_treat_plain_or_as_choice() -> None:
    query = "What did Alex say or write about Project Atlas?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="alex_message",
        item_type="chunk",
        text="Alex wrote that Project Atlas needs a billing follow-up.",
        score=0.9,
        source_refs=(SourceRef(source_type="message", source_id="msg_1"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "choice" not in coverage["requested_answer_shapes"]


def test_context_requirement_coverage_tracks_speaker_answer_shape() -> None:
    query = "Who said Project Atlas was approved?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="alex_turn",
        item_type="chunk",
        text="D3:4 Alex: Project Atlas was approved after the billing call.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D3:4"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["speaker"]
    assert "speaker" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_according_to_speaker_shape() -> None:
    query = "According to Melanie, what traits does Caroline have?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="melanie_turn",
        item_type="chunk",
        text="D16:18 Melanie: Caroline is thoughtful and patient.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D16:18"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "speaker" in coverage["requested_answer_shapes"]
    assert "speaker" in coverage["covered_answer_shapes"]
    assert "speaker" not in coverage["missing_answer_shapes"]


def test_context_requirement_coverage_tracks_russian_according_to_speaker_shape() -> None:
    query = "По словам Мелани, какие черты есть у Кэролайн?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="melanie_turn",
        item_type="chunk",
        text="D16:18 Мелани: Кэролайн внимательная и терпеливая.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D16:18"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "speaker" in coverage["requested_answer_shapes"]
    assert "speaker" in coverage["covered_answer_shapes"]
    assert "speaker" not in coverage["missing_answer_shapes"]


def test_context_requirement_coverage_tracks_missing_speaker_answer_shape() -> None:
    query = "Who said Project Atlas was approved?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="generic_note",
        item_type="chunk",
        text="Project Atlas was approved after the billing call.",
        score=0.9,
        source_refs=(SourceRef(source_type="note", source_id="note_1"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["speaker"]
    assert "speaker" not in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == ["speaker"]


def test_context_requirement_coverage_tracks_conversation_participant_answer_shape() -> None:
    cases = (
        (
            "Who did Alex talk to about Project Atlas?",
            "Alex talked to Maria about Project Atlas.",
        ),
        (
            "Who did Alex meet with about Atlas?",
            "Alex met with Maria about Atlas.",
        ),
        (
            "С кем Алекс говорил про Atlas?",
            "Алекс говорил с Марией про Atlas.",
        ),
    )

    for query, text in cases:
        coverage = context_requirement_coverage(
            query=query,
            query_anchor_intent=build_query_anchor_intent(query),
            items=(
                ContextItem(
                    item_id="conversation_participant",
                    item_type="chunk",
                    text=text,
                    score=0.9,
                    source_refs=(SourceRef(source_type="locomo_turn", source_id="D3:5"),),
                    diagnostics={"memory_scope_id": "scope"},
                ),
            ),
        )

        assert coverage["requested_answer_shapes"] == ["conversation_participant"]
        assert "conversation_participant" in coverage["covered_answer_shapes"]
        assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_missing_conversation_participant_shape() -> None:
    query = "Who did Alex talk to about Project Atlas?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="generic_note",
        item_type="chunk",
        text="Project Atlas was approved after the billing call.",
        score=0.9,
        source_refs=(SourceRef(source_type="note", source_id="note_1"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["conversation_participant"]
    assert "conversation_participant" not in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == ["conversation_participant"]


def test_context_requirement_coverage_tracks_conversation_topic_answer_shape() -> None:
    cases = (
        (
            "What did Alex and Maria talk about?",
            "Alex talked with Maria about Project Atlas.",
        ),
        (
            "What topic did Alex discuss with Maria?",
            "Alex discussed Project Atlas with Maria.",
        ),
        (
            "What was Alex's conversation with Maria about?",
            "Alex talked with Maria about Project Atlas.",
        ),
        (
            "О чем Алекс говорил с Марией?",
            "Алекс говорил с Марией про Atlas.",
        ),
    )

    for query, text in cases:
        coverage = context_requirement_coverage(
            query=query,
            query_anchor_intent=build_query_anchor_intent(query),
            items=(
                ContextItem(
                    item_id="conversation_topic",
                    item_type="chunk",
                    text=text,
                    score=0.9,
                    source_refs=(SourceRef(source_type="locomo_turn", source_id="D3:6"),),
                    diagnostics={"memory_scope_id": "scope"},
                ),
            ),
        )

        assert coverage["requested_answer_shapes"] == ["conversation_topic"]
        assert "conversation_topic" in coverage["covered_answer_shapes"]
        assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_missing_conversation_topic_shape() -> None:
    query = "What did Alex and Maria talk about?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="participant_only",
        item_type="chunk",
        text="Alex talked with Maria after lunch.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D3:7"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["conversation_topic"]
    assert "conversation_topic" not in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == ["conversation_topic"]


def test_context_requirement_coverage_tracks_constraint_answer_shape() -> None:
    query = "Which foods can't Alex eat?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="alex_food_constraint",
        item_type="chunk",
        text="Alex cannot eat peanuts and avoids shellfish because of allergies.",
        score=0.9,
        source_refs=(SourceRef(source_type="note", source_id="food_note"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["constraint"]
    assert "constraint" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_missing_constraint_answer_shape() -> None:
    query = "Which foods can't Alex eat?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="alex_positive_food_note",
        item_type="chunk",
        text="Alex eats peanuts and enjoys shellfish at weekend dinners.",
        score=0.9,
        source_refs=(SourceRef(source_type="note", source_id="food_note"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["constraint"]
    assert "constraint" not in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == ["constraint"]


def test_context_requirement_coverage_tracks_action_role_recipient_shape() -> None:
    query = "Who recommended Becoming Nicole to Melanie?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="caroline_recommendation",
        item_type="chunk",
        text="Caroline recommended Becoming Nicole by Amy Ellis Nutt to Melanie.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D5:2"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["action_role"]
    assert "action_role" in coverage["covered_answer_shapes"]
    assert "commitment" not in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_requested_recipient_action_role_shape() -> None:
    query = "Who did Caroline recommend Becoming Nicole to?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="caroline_recommendation",
        item_type="chunk",
        text="Caroline recommended Becoming Nicole by Amy Ellis Nutt to Melanie.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D5:2"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["action_role"]
    assert "action_role" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_requested_recipient_with_trailing_context() -> None:
    query = "Who did Caroline recommend Becoming Nicole to during the book club?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="caroline_recommendation",
        item_type="chunk",
        text="Caroline recommended Becoming Nicole by Amy Ellis Nutt to Melanie.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D5:2"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "action_role" in coverage["requested_answer_shapes"]
    assert "action_role" in coverage["covered_answer_shapes"]
    assert "action_role" not in coverage["missing_answer_shapes"]


def test_context_requirement_coverage_tracks_possession_source_shape() -> None:
    query = "Who gave Caroline the necklace?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="caroline_necklace_source",
        item_type="chunk",
        text=(
            "D4:3 Caroline: This necklace was a gift from my grandma in my home "
            "country, Sweden."
        ),
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D4:3"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["possession_source"]
    assert "possession_source" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_missing_possession_source_shape() -> None:
    query = "Who gave Caroline the necklace?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="caroline_necklace_symbols",
        item_type="chunk",
        text="Caroline shared a pendant necklace with a transgender symbol and a cross.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D8:2"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "possession_source" in coverage["requested_answer_shapes"]
    assert "possession_source" not in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == ["possession_source"]


def test_context_requirement_coverage_tracks_russian_requested_recipient_action_role() -> None:
    query = "Кому Кэролайн посоветовала прочитать Becoming Nicole?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="caroline_recommendation",
        item_type="chunk",
        text="Кэролайн посоветовала Мелани прочитать Becoming Nicole.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D5:2"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["action_role"]
    assert "action_role" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_russian_whose_advice_action_role() -> None:
    query = "По чьему совету Мелани прочитала Becoming Nicole?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="caroline_recommendation",
        item_type="chunk",
        text="Кэролайн посоветовала Мелани прочитать Becoming Nicole.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D5:2"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["action_role"]
    assert "action_role" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_after_recommendation_action_role() -> None:
    query = "What book did Melanie read after Caroline recommended it?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="caroline_recommendation",
        item_type="chunk",
        text="Caroline recommended Becoming Nicole by Amy Ellis Nutt to Melanie.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D5:2"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "action_role" in coverage["requested_answer_shapes"]
    assert "action_role" in coverage["covered_answer_shapes"]
    assert "action_role" not in coverage["missing_answer_shapes"]


def test_context_requirement_coverage_tracks_action_role_promise_shape() -> None:
    query = "What did Alex promise Maria after the Atlas call?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="alex_promise",
        item_type="chunk",
        text="Alex promised Maria he would send the Atlas invoice after the call.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D3:4"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert set(coverage["requested_answer_shapes"]) == {"action_role", "commitment"}
    assert "action_role" in coverage["covered_answer_shapes"]
    assert "commitment" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_action_role_owner_shape() -> None:
    query = "Is Alex responsible for the Atlas invoice?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="alex_owner",
        item_type="chunk",
        text="Alex is responsible for the Atlas invoice follow-up.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D3:4"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert set(coverage["requested_answer_shapes"]) == {"action_role", "commitment"}
    assert "action_role" in coverage["covered_answer_shapes"]
    assert "commitment" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_missing_action_role_shape() -> None:
    query = "Who recommended Becoming Nicole to Melanie?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="passive_recommendation",
        item_type="chunk",
        text="Becoming Nicole was recommended during the reading discussion.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D5:3"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["action_role"]
    assert "action_role" not in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == ["action_role"]


def test_context_requirement_coverage_does_not_treat_speaker_query_as_action_role() -> None:
    query = "Who said Project Atlas was approved?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="alex_turn",
        item_type="chunk",
        text="D3:4 Alex: Project Atlas was approved after the billing call.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D3:4"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "speaker" in coverage["requested_answer_shapes"]
    assert "action_role" not in coverage["requested_answer_shapes"]


def test_context_requirement_coverage_tracks_location_answer_shape() -> None:
    query = "Where does Alex live now?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="alex_residence",
        item_type="chunk",
        text="Alex currently lives in Berlin and is based in Germany now.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D9:2"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["location"]
    assert "location" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_activity_location_answer_shape() -> None:
    query = "Where has Melanie camped?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="melanie_camping_location",
        item_type="chunk",
        text="Melanie camped near Yosemite with her family in June.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D12:2"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["location"]
    assert "location" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_trip_destination_answer_shape() -> None:
    query = "Where did John take a trip last year?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="john_trip_destination",
        item_type="chunk",
        text="John took a trip to the Rocky Mountains last year.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D20:40"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["temporal", "location"]
    assert "temporal" in coverage["covered_answer_shapes"]
    assert "location" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_trip_destination_noun_answer_shape() -> None:
    cases = (
        (
            "What city did John visit on vacation?",
            "John visited Berlin on vacation.",
        ),
        (
            "Which country did Maria travel to?",
            "Maria traveled to Portugal last summer.",
        ),
        (
            "What was the place John went for vacation?",
            "John went to Yosemite for vacation.",
        ),
        (
            "Какой город Алекс посетил в отпуске?",
            "Алекс посетил Берлин в отпуске.",
        ),
    )

    for query, text in cases:
        coverage = context_requirement_coverage(
            query=query,
            query_anchor_intent=build_query_anchor_intent(query),
            items=(
                ContextItem(
                    item_id="trip_destination",
                    item_type="chunk",
                    text=text,
                    score=0.9,
                    source_refs=(SourceRef(source_type="locomo_turn", source_id="D20:42"),),
                    diagnostics={"memory_scope_id": "scope"},
                ),
            ),
        )

        assert coverage["requested_answer_shapes"] == ["location"]
        assert "location" in coverage["covered_answer_shapes"]
        assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_russian_trip_destination_answer_shape() -> None:
    query = "Куда Алекс ездил в отпуск?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="alex_trip_destination_ru",
        item_type="chunk",
        text="Алекс ездил в отпуск в Берлин прошлым летом.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D20:41"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["location"]
    assert "location" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_missing_location_answer_shape() -> None:
    query = "Where does Alex live now?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="alex_generic",
        item_type="chunk",
        text="Alex discussed moving someday but did not name a city.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D9:3"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["location"]
    assert "location" not in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == ["location"]


def test_context_requirement_coverage_does_not_treat_generic_where_said_as_location() -> None:
    query = "Where did Alex say Project Atlas was approved?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="alex_approval",
        item_type="chunk",
        text="Alex said Project Atlas was approved after the billing call.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D3:4"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "location" not in coverage["requested_answer_shapes"]


def test_context_requirement_coverage_tracks_preference_answer_shape() -> None:
    query = "What music does Alex like?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="alex_music_preference",
        item_type="chunk",
        text="Alex likes ambient music and is a fan of Brian Eno.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D11:2"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["preference"]
    assert "preference" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_missing_preference_answer_shape() -> None:
    query = "What music does Alex like?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="alex_music_mention",
        item_type="chunk",
        text="Alex discussed ambient music during the studio call.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D11:3"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["preference"]
    assert "preference" not in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == ["preference"]


def test_context_requirement_coverage_does_not_treat_look_like_as_preference() -> None:
    query = "What does the screenshot look like?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="screenshot_description",
        item_type="chunk",
        text="The screenshot shows an approval modal with a purple button.",
        score=0.9,
        source_refs=(SourceRef(source_type="image_ocr", source_id="img_1"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "preference" not in coverage["requested_answer_shapes"]


def test_context_requirement_coverage_tracks_commonality_answer_shape() -> None:
    query = "What hobbies do Caroline and Melanie have in common?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="shared_hobbies",
        item_type="chunk",
        text="Caroline and Melanie both enjoy painting and weekend camping.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D15:7"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["list", "commonality"]
    assert "commonality" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_broad_commonality_answer_shape() -> None:
    query = "What do Jon and Gina have in common?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="shared_business_origin",
        item_type="chunk",
        text="Jon and Gina both lost their jobs and started their own businesses.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D1:4"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "commonality" in coverage["requested_answer_shapes"]
    assert "commonality" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_flags_broad_commonality_missing_shape() -> None:
    query = "What do Jon and Gina have in common?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="single_business_update",
        item_type="chunk",
        text="Jon lost his job as a banker and started his own business.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D1:2"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "commonality" in coverage["requested_answer_shapes"]
    assert "commonality" not in coverage["covered_answer_shapes"]
    assert "commonality" in coverage["missing_answer_shapes"]


def test_context_requirement_coverage_tracks_russian_commonality_answer_shape() -> None:
    query = "Что Алиса и Мария обе любят?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="ru_shared_hobbies",
        item_type="chunk",
        text="Алиса и Мария обе любят походы и настольные игры.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D15:10"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "commonality" in coverage["requested_answer_shapes"]
    assert "commonality" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_who_else_commonality_shape() -> None:
    query = "Who else likes camping like Caroline?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="maria_also_camping",
        item_type="chunk",
        text="Maria also likes camping and hiking on weekends.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D15:11"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["commonality"]
    assert "commonality" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_russian_who_else_commonality_shape() -> None:
    query = "Кто ещё любит походы как Алиса?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="maria_too_hiking",
        item_type="chunk",
        text="Мария тоже любит походы и поездки в горы.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D15:12"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["commonality"]
    assert "commonality" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_missing_commonality_answer_shape() -> None:
    query = "What hobbies do Caroline and Melanie have in common?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="single_person_hobby",
        item_type="chunk",
        text="Caroline enjoys painting on weekends.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D15:8"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "commonality" in coverage["requested_answer_shapes"]
    assert "commonality" not in coverage["covered_answer_shapes"]
    assert "commonality" in coverage["missing_answer_shapes"]


def test_context_requirement_coverage_does_not_treat_shared_photo_as_commonality() -> None:
    query = "What hobbies do Caroline and Melanie have in common?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="shared_photo",
        item_type="chunk",
        text="Caroline shared a photo of a painting with Melanie.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D15:9"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "commonality" in coverage["requested_answer_shapes"]
    assert "commonality" not in coverage["covered_answer_shapes"]


def test_context_requirement_coverage_tracks_relationship_status_shape() -> None:
    query = "What is Caroline's relationship status?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="caroline_relationship_status",
        item_type="chunk",
        text="Caroline mentioned dating after a breakup and leaning on friends.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D12:2"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["relationship"]
    assert "relationship" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_old_friend_relationship_shape() -> None:
    query = "Who is Alex's old friend from school?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="alex_old_friend",
        item_type="chunk",
        text="Alex's old friend from school is Maria.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D4:2"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["relationship"]
    assert "relationship" in coverage["covered_answer_shapes"]
    assert "state_update" not in coverage["requested_answer_shapes"]


def test_context_requirement_coverage_tracks_marriage_duration_relationship_shape() -> None:
    query = "How long have Mel and her husband been married?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="mel_marriage_duration",
        item_type="chunk",
        text="Mel and her husband have been married for nine years.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D6:7"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "relationship" in coverage["requested_answer_shapes"]
    assert "relationship" in coverage["covered_answer_shapes"]
    assert "relationship" not in coverage["missing_answer_shapes"]


def test_context_requirement_coverage_tracks_missing_relationship_shape() -> None:
    query = "Who is Alex's old friend from school?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="alex_school_note",
        item_type="chunk",
        text="Alex went to school with Maria.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D4:3"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["relationship"]
    assert "relationship" not in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == ["relationship"]


def test_context_requirement_coverage_tracks_deadline_commitment_shape() -> None:
    query = "When is the Atlas launch deadline after the call?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="atlas_launch_deadline",
        item_type="chunk",
        text="Alex confirmed the Atlas launch deadline and due date is 2026-08-15.",
        score=0.9,
        source_refs=(SourceRef(source_type="meeting_notes", source_id="D14:2"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "commitment" in coverage["requested_answer_shapes"]
    assert "commitment" in coverage["covered_answer_shapes"]
    assert "commitment" not in coverage["missing_answer_shapes"]


def test_context_requirement_coverage_tracks_followup_commitment_shape() -> None:
    query = "What follow up task came from the Atlas meeting?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="atlas_action_item",
        item_type="chunk",
        text="Atlas meeting notes: action item task follow up is assigned to Alex.",
        score=0.9,
        source_refs=(SourceRef(source_type="meeting_notes", source_id="D14:3"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["commitment"]
    assert "commitment" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_remaining_work_commitment_shape() -> None:
    query = "What is left to do for Atlas?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="atlas_remaining_work",
        item_type="chunk",
        text="Alex noted the remaining Atlas follow up task is to update the SDK docs.",
        score=0.9,
        source_refs=(SourceRef(source_type="meeting_notes", source_id="D14:3"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["commitment"]
    assert "commitment" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_need_to_commitment_shape() -> None:
    query = "What does Alex need to do after Atlas?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="atlas_needed_action",
        item_type="chunk",
        text="Alex needs to send the Atlas invoice after the call.",
        score=0.9,
        source_refs=(SourceRef(source_type="meeting_notes", source_id="D14:5"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "commitment" in coverage["requested_answer_shapes"]
    assert "commitment" in coverage["covered_answer_shapes"]
    assert "commitment" not in coverage["missing_answer_shapes"]


def test_context_requirement_coverage_tracks_supposed_to_commitment_shape() -> None:
    query = "What is Alex supposed to do after Atlas?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="atlas_expected_action",
        item_type="chunk",
        text="Alex is supposed to send the Atlas invoice after the call.",
        score=0.9,
        source_refs=(SourceRef(source_type="meeting_notes", source_id="D14:6"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "commitment" in coverage["requested_answer_shapes"]
    assert "commitment" in coverage["covered_answer_shapes"]
    assert "commitment" not in coverage["missing_answer_shapes"]


def test_context_requirement_coverage_tracks_russian_need_to_commitment_shape() -> None:
    query = "Что нужно сделать по Атласу?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="atlas_russian_needed_action",
        item_type="chunk",
        text="По Атласу нужно отправить инвойс после созвона.",
        score=0.9,
        source_refs=(SourceRef(source_type="meeting_notes", source_id="D14:6"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "commitment" in coverage["requested_answer_shapes"]
    assert "commitment" in coverage["covered_answer_shapes"]
    assert "commitment" not in coverage["missing_answer_shapes"]


def test_context_requirement_coverage_tracks_missing_commitment_shape() -> None:
    query = "What follow up task came from the Atlas meeting?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="atlas_discussion",
        item_type="chunk",
        text="Atlas was discussed during the meeting with Alex.",
        score=0.9,
        source_refs=(SourceRef(source_type="meeting_notes", source_id="D14:4"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["commitment"]
    assert "commitment" not in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == ["commitment"]


def test_context_requirement_coverage_tracks_gotcha_shape() -> None:
    query = "What should I watch out for in Atlas deployment?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="atlas_deploy_gotcha",
        item_type="chunk",
        text=(
            "Atlas deployment gotcha: Docker failed when Qdrant was not ready. "
            "Workaround: wait for health checks before running migrations."
        ),
        score=0.9,
        source_refs=(SourceRef(source_type="runbook", source_id="atlas_deploy"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["gotcha"]
    assert "gotcha" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_blocker_gotcha_shape() -> None:
    query = "What blockers are open for Atlas?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="atlas_open_blocker",
        item_type="chunk",
        text="Atlas blocker: Docker is blocked on the Qdrant health check.",
        score=0.9,
        source_refs=(SourceRef(source_type="runbook", source_id="atlas_blocker"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "gotcha" in coverage["requested_answer_shapes"]
    assert "gotcha" in coverage["covered_answer_shapes"]
    assert "gotcha" not in coverage["missing_answer_shapes"]


def test_context_requirement_coverage_tracks_missing_gotcha_shape() -> None:
    query = "What known issues does Atlas deployment have?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="atlas_deploy_plain",
        item_type="chunk",
        text="Atlas deployment uses Docker, Postgres, Qdrant, and the API worker.",
        score=0.9,
        source_refs=(SourceRef(source_type="runbook", source_id="atlas_deploy"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["gotcha"]
    assert "gotcha" not in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == ["gotcha"]


def test_context_requirement_coverage_keeps_issue_number_out_of_gotcha() -> None:
    query = "Which issue number did Alex mention?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="issue_number",
        item_type="chunk",
        text="Alex mentioned issue #123 during the planning call.",
        score=0.9,
        source_refs=(SourceRef(source_type="meeting_notes", source_id="issue_call"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "gotcha" not in coverage["requested_answer_shapes"]


def test_context_requirement_coverage_keeps_provider_recommendation_out_of_commitment() -> None:
    query = "Which provider should I use?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="provider_recommendation",
        item_type="chunk",
        text="OpenAI is the recommended current retrieval provider.",
        score=0.9,
        source_refs=(SourceRef(source_type="fact", source_id="provider_current"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "commitment" not in coverage["requested_answer_shapes"]


def test_context_requirement_coverage_tracks_current_state_update_shape() -> None:
    query = "Which Atlas provider is still valid?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="atlas_current_provider",
        item_type="chunk",
        text="Atlas provider remains valid and current: OpenAI.",
        score=0.9,
        source_refs=(SourceRef(source_type="fact", source_id="provider_current"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["state_update"]
    assert "state_update" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_final_decision_state_update_shape() -> None:
    query = "What is the final Atlas decision?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="atlas_final_decision",
        item_type="chunk",
        text="Atlas final source of truth: OpenAI is the selected provider.",
        score=0.9,
        source_refs=(SourceRef(source_type="fact", source_id="provider_final"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["state_update"]
    assert "state_update" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_chosen_provider_state_update_shape() -> None:
    query = "Which Atlas provider was chosen?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="atlas_chosen_provider",
        item_type="chunk",
        text="The chosen current Atlas provider is OpenAI.",
        score=0.9,
        source_refs=(SourceRef(source_type="fact", source_id="provider_chosen"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["state_update"]
    assert "state_update" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_does_not_treat_plain_choose_as_state_update() -> None:
    query = "Which shoes did Alex choose?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="alex_shoes",
        item_type="chunk",
        text="Alex chose purple running shoes.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D9:2"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "state_update" not in coverage["requested_answer_shapes"]


def test_context_requirement_coverage_uses_active_fact_status_for_state_update_shape() -> None:
    query = "What is the current Atlas provider?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="atlas_current_provider_fact",
        item_type="fact",
        text="Atlas provider: OpenAI.",
        score=0.9,
        source_refs=(SourceRef(source_type="fact", source_id="provider_current"),),
        diagnostics={
            "memory_scope_id": "scope",
            "provenance": {"fact_status": "active"},
        },
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["state_update"]
    assert "state_update" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_stale_state_update_shape() -> None:
    query = "Which Atlas provider is no longer valid?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="atlas_stale_provider",
        item_type="chunk",
        text="LocalAI is no longer valid for Atlas after the provider switch.",
        score=0.9,
        source_refs=(SourceRef(source_type="fact", source_id="provider_stale"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["state_update"]
    assert "state_update" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_change_state_update_shape() -> None:
    query = "What changed after the meeting with Alex?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="atlas_changed_provider",
        item_type="chunk",
        text="After the meeting, Atlas changed from LocalAI to OpenAI.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D15:2"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["state_update"]
    assert "state_update" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_state_transition_shape() -> None:
    query = "What did Atlas switch from LocalAI to?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="atlas_provider_transition",
        item_type="chunk",
        text=(
            "Atlas provider transition: LocalAI was replaced by OpenAI after "
            "the review. The current active provider is OpenAI."
        ),
        score=0.9,
        source_refs=(SourceRef(source_type="fact", source_id="provider_transition"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["state_update"]
    assert "state_update" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_does_not_treat_switch_setting_as_state_update() -> None:
    query = "Which switch setting did Alex mention?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="switch_setting",
        item_type="chunk",
        text="Alex mentioned the advanced switch setting during the planning call.",
        score=0.9,
        source_refs=(SourceRef(source_type="meeting_notes", source_id="switch_setting"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "state_update" not in coverage["requested_answer_shapes"]


def test_context_requirement_coverage_tracks_missing_state_update_shape() -> None:
    query = "What is the latest current Atlas provider?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="atlas_provider_without_current_marker",
        item_type="chunk",
        text="Atlas provider is OpenAI.",
        score=0.9,
        source_refs=(SourceRef(source_type="fact", source_id="provider_plain"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["state_update"]
    assert "state_update" not in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == ["state_update"]


def test_context_requirement_coverage_does_not_cover_state_update_from_before_only() -> None:
    query = "What is the latest current Atlas provider?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="atlas_before_call_note",
        item_type="chunk",
        text="Project Atlas was approved before the billing call.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D3:4"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["state_update"]
    assert "state_update" not in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == ["state_update"]


def test_context_requirement_coverage_does_not_cover_state_update_from_russian_old_friend() -> None:
    query = "Какой текущий провайдер Атласа?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="alex_old_friend_ru",
        item_type="chunk",
        text="Алекс сказал, что Мария его старый друг со школы.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D4:2"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["state_update"]
    assert "state_update" not in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == ["state_update"]


def test_context_requirement_coverage_covers_plain_text_stale_state_without_metadata() -> None:
    query = "Which Atlas provider is no longer valid?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="atlas_stale_provider_chunk",
        item_type="chunk",
        text="LocalAI is no longer valid for Atlas after the provider switch.",
        score=0.9,
        source_refs=(SourceRef(source_type="document", source_id="atlas_note"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["state_update"]
    assert "state_update" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_does_not_treat_old_friend_as_state_update() -> None:
    query = "Who is Alex's old friend from school?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="alex_old_friend",
        item_type="chunk",
        text="Alex's old friend from school is Maria.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D4:2"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "state_update" not in coverage["requested_answer_shapes"]


def test_context_requirement_coverage_tracks_positive_existence_shape() -> None:
    query = "Do we know whether Alex ever mentioned Project Atlas?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="alex_mentioned_atlas",
        item_type="chunk",
        text="Alex mentioned Project Atlas during the billing call.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D3:4"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["existence"]
    assert "existence" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_negative_existence_shape() -> None:
    query = "Is there any evidence that Alex has a cat?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="no_cat_evidence",
        item_type="chunk",
        text="No evidence mentions Alex having a cat.",
        score=0.9,
        source_refs=(SourceRef(source_type="note", source_id="pet_audit"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["existence"]
    assert "existence" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []


def test_context_requirement_coverage_tracks_missing_existence_shape() -> None:
    query = "Do we know whether Alex ever mentioned Project Atlas?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="atlas_topic_note",
        item_type="chunk",
        text="Project Atlas was approved after the billing call.",
        score=0.9,
        source_refs=(SourceRef(source_type="note", source_id="atlas_note"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert coverage["requested_answer_shapes"] == ["existence"]
    assert "existence" not in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == ["existence"]


def test_context_requirement_coverage_does_not_treat_plain_mention_query_as_existence() -> None:
    query = "What did Alex mention about Project Atlas?"
    intent = build_query_anchor_intent(query)
    item = ContextItem(
        item_id="alex_mentioned_atlas",
        item_type="chunk",
        text="Alex mentioned Project Atlas during the billing call.",
        score=0.9,
        source_refs=(SourceRef(source_type="locomo_turn", source_id="D3:4"),),
        diagnostics={"memory_scope_id": "scope"},
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(item,),
    )

    assert "existence" not in coverage["requested_answer_shapes"]


def test_context_requirement_coverage_tracks_missing_inference_answer_shape() -> None:
    query = "Would Melanie be considered an ally?"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="melanie_generic_note",
            item_type="chunk",
            text="Melanie visited Caroline after the community meetup.",
            score=0.9,
            source_refs=(SourceRef(source_type="locomo_turn", source_id="D12:4"),),
            diagnostics={"memory_scope_id": "scope"},
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert coverage["requested_answer_shapes"] == ["inference"]
    assert "inference" not in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == ["inference"]
    assert coverage["status"] == "missing"


def test_context_requirement_coverage_tracks_missing_causal_answer_shape() -> None:
    query = "Why did Gina start her clothing store?"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="generic_store",
            item_type="chunk",
            text="Gina opened an online clothing store with dresses, shoes, and unique pieces.",
            score=0.9,
            source_refs=(SourceRef(source_type="locomo_turn", source_id="D6:8"),),
            diagnostics={"memory_scope_id": "scope"},
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert coverage["requested_answer_shapes"] == ["causal"]
    assert set(coverage["covered_answer_shapes"]) >= {"count", "list"}
    assert coverage["missing_answer_shapes"] == ["causal"]
    assert coverage["status"] == "missing"


def test_context_requirement_coverage_tracks_so_could_causal_answer_shape() -> None:
    query = "Why did Gina start her clothing store?"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="store_reason",
            item_type="chunk",
            text="Gina started her clothing store so she could share handmade dresses.",
            score=0.9,
            source_refs=(SourceRef(source_type="locomo_turn", source_id="D6:9"),),
            diagnostics={"memory_scope_id": "scope"},
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert coverage["requested_answer_shapes"] == ["causal"]
    assert "causal" in coverage["covered_answer_shapes"]
    assert coverage["missing_answer_shapes"] == []
    assert coverage["status"] == "satisfied"


def test_context_requirement_coverage_infers_video_from_frame_timeline_source() -> None:
    query = "покажи таймкод в видео где Atlas launch approved"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="artifact_video_timeline",
            item_type="extraction_artifact",
            text="Video frame timeline: Atlas launch approved at 00:42.",
            score=0.91,
            source_refs=(
                SourceRef(
                    source_type="extraction_artifact",
                    source_id="video_frame_timeline_artifact",
                    chunk_id="keyframe-0001",
                    quote_preview="Atlas launch approved at 00:42.",
                    time_start_ms=42_000,
                    time_end_ms=49_000,
                ),
            ),
            diagnostics={},
        ),
        ContextItem(
            item_id="anchor_launch_event",
            item_type="anchor",
            text="event: Atlas launch approved in the video.",
            score=0.89,
            source_refs=(),
            diagnostics={"anchor_kind": "event", "memory_scope_id": "scope"},
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert coverage["status"] == "satisfied"
    assert coverage["requested_modalities"] == ["video"]
    assert coverage["covered_modalities"] == ["video"]
    assert "audio" not in coverage["covered_modalities"]
    assert set(coverage["covered_evidence_features"]) >= {"citation", "time_range"}


def test_context_requirement_coverage_does_not_treat_unknown_timestamp_as_audio() -> None:
    query = "найди аудио где Atlas renewal approved"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="generic_timed_artifact",
            item_type="extraction_artifact",
            text="Atlas renewal approved.",
            score=0.9,
            source_refs=(
                SourceRef(
                    source_type="extraction_artifact",
                    source_id="generic_artifact",
                    chunk_id="segment-1",
                    quote_preview="Atlas renewal approved.",
                    time_start_ms=1200,
                    time_end_ms=6400,
                ),
            ),
            diagnostics={},
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert coverage["status"] == "partial"
    assert coverage["requested_modalities"] == ["audio"]
    assert coverage["missing_modalities"] == ["audio"]
    assert "time_range" in coverage["covered_evidence_features"]


def test_context_requirement_coverage_does_not_request_audio_for_invoice_voice_substring() -> None:
    query = "where on screen is Project Atlas screenshot invoice owner Alex"
    intent = build_query_anchor_intent(query)
    items = (
        ContextItem(
            item_id="artifact_invoice_screenshot",
            item_type="extraction_artifact",
            text="Project Atlas screenshot invoice owner Alex",
            score=0.91,
            source_refs=(
                SourceRef(
                    source_type="extraction_artifact",
                    source_id="artifact_invoice_screenshot",
                    chunk_id="ocr-owner",
                    quote_preview="Project Atlas screenshot invoice owner Alex",
                    bbox=(12.0, 32.0, 300.0, 88.0),
                ),
            ),
            diagnostics={
                "evidence_kind": "ocr_region",
                "evidence_modality": "image",
            },
        ),
    )

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=items,
    )

    assert coverage["status"] == "satisfied"
    assert coverage["requested_modalities"] == ["image"]
    assert "audio" not in coverage["requested_modalities"]


def test_context_requirement_coverage_still_requests_audio_for_voice_word() -> None:
    query = "find the voice recording where Alex approved Atlas"
    intent = build_query_anchor_intent(query)

    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=intent,
        items=(),
    )

    assert coverage["status"] == "missing"
    assert coverage["requested_modalities"] == ["audio"]
    assert coverage["missing_modalities"] == ["audio"]


def test_sanitize_context_requirement_coverage_bounds_and_redacts_payload() -> None:
    secret = "sk-proj-contextcoverage-secret1234567890"

    sanitized = sanitize_context_requirement_coverage(
        {
            "schema_version": "evil",
            "status": "satisfied",
            "requested_total": 3,
            "covered_total": 99,
            "missing_total": 99,
            "coverage_ratio": 99,
            "requested_modalities": ["image", secret, *[f"extra_{index}" for index in range(20)]],
            "covered_modalities": ["image"],
            "missing_modalities": [secret],
            "answer_shape_warnings": [
                "community_membership_support_only_without_self_identification",
                secret,
            ],
            "item_count": 2,
        }
    )

    assert sanitized["schema_version"] == "context-requirement-coverage-v1"
    assert sanitized["status"] == "satisfied"
    assert sanitized["covered_total"] == 3
    assert sanitized["missing_total"] == 0
    assert sanitized["coverage_ratio"] == 1.0
    assert secret not in str(sanitized)
    assert "[redacted]" not in str(sanitized)
    assert len(sanitized["requested_modalities"]) <= 12
    assert sanitized["answer_shape_warnings"] == [
        "community_membership_support_only_without_self_identification"
    ]
