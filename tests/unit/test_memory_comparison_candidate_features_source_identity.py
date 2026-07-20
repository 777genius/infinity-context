from __future__ import annotations

import pytest
from infinity_context_server.memory_comparison_candidate_features import (
    build_candidate_evidence_features,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory


def test_candidate_features_use_text_turn_refs_for_dedupe_when_source_refs_are_generic() -> None:
    memory = RetrievedMemory(
        item_id="fact-with-generic-provenance",
        rank=1,
        text="D5:7 Caroline: The support group meets on Thursday evenings.",
        source_refs=("locomo-conv-5",),
        metadata={"item_type": "fact"},
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={"caroline", "support", "group", "thursday"},
        query_terms=("caroline", "support", "group"),
        relation_terms=("support",),
        relation_variant_terms=("group",),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        high_signal_relation_terms={"support"},
        is_temporal_query=False,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )

    assert features.turn_ref_count == 1
    assert features.duplicate_key == "source_refs:locomo-conv-5"
    assert features.source_ref_dedupe_key == "source_turn_refs:D5:7"
    assert features.source_identity_audit_gap_codes == (
        "generic_source_refs_with_text_turn_identity",
    )
    assert (
        features.to_diagnostics()["source_ref_dedupe_key"]
        == "source_turn_refs:D5:7"
    )
    assert features.to_diagnostics()["source_identity_audit_gap_codes"] == [
        "generic_source_refs_with_text_turn_identity"
    ]


def test_candidate_features_report_missing_source_refs_text_identity_gap() -> None:
    memory = RetrievedMemory(
        item_id="fact-without-provenance",
        rank=1,
        text="D5:7 Caroline: The support group meets on Thursday evenings.",
        metadata={"item_type": "fact"},
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={"caroline", "support", "group", "thursday"},
        query_terms=("caroline", "support", "group"),
        relation_terms=("support",),
        relation_variant_terms=("group",),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        high_signal_relation_terms={"support"},
        is_temporal_query=False,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )

    assert features.source_ref_count == 0
    assert features.source_ref_dedupe_key == "source_turn_refs:D5:7"
    assert features.source_identity_audit_gap_codes == (
        "missing_source_refs_with_text_turn_identity",
    )
    assert features.to_diagnostics()["source_identity_audit_gap_codes"] == [
        "missing_source_refs_with_text_turn_identity"
    ]


@pytest.mark.parametrize(
    ("text", "source_refs", "expected_gap_code"),
    (
        (
            "D5:7 Caroline: The support group meets on Thursday evenings.",
            ("D5:8",),
            "source_text_turn_mismatch",
        ),
        (
            "session_5 turn D5:7 date: 8:00 pm "
            "D5:7 Caroline: The support group meets on Thursday evenings.",
            ("locomo:conv-26:session_6:D5:7:turn",),
            "source_text_session_turn_mismatch",
        ),
        (
            "D5:7 in session 6 Caroline: The support group meets on Thursday evenings.",
            ("locomo:conv-26:session_5:D5:7:turn",),
            "source_text_session_turn_mismatch",
        ),
    ),
)
def test_candidate_features_report_source_text_identity_mismatch(
    text: str,
    source_refs: tuple[str, ...],
    expected_gap_code: str,
) -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="mismatched-source-turn",
            rank=1,
            text=text,
            source_refs=source_refs,
            metadata={"item_type": "chunk"},
        ),
        memory_terms={"caroline", "support", "group", "thursday"},
        query_terms=("caroline", "support", "group"),
        relation_terms=("support",),
        relation_variant_terms=("group",),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        high_signal_relation_terms={"support"},
        is_temporal_query=False,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )

    assert features.source_identity_audit_gap_codes == (expected_gap_code,)
    assert features.identity_confusion_reason_codes == (
        f"source_identity:{expected_gap_code}",
    )
    assert features.source_locality_score == 1.0
    assert features.answerability_score >= 0.8


def test_candidate_features_do_not_promote_safe_turn_like_source_labels() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="safe-turn-like-label",
            rank=1,
            text="Caroline mentioned a support group.",
            source_refs=("session_2", "chunk-D2-6", "document:D3-7"),
            metadata={"item_type": "chunk"},
        ),
        memory_terms={"caroline", "support", "group"},
        query_terms=("caroline", "support"),
        relation_terms=("support",),
        relation_variant_terms=("group",),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        high_signal_relation_terms={"support"},
        is_temporal_query=False,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=False,
    )

    assert features.source_ref_count == 3
    assert features.turn_ref_count == 0
    assert features.source_ref_dedupe_key == ""
    assert "localized_turn_refs" not in features.source_locality_reason_codes


def test_candidate_features_use_source_ref_turns_for_locality_and_dedupe() -> None:
    memory = RetrievedMemory(
        item_id="adjacent-source-refs",
        rank=1,
        text=(
            "Caroline said the adoption agency felt inclusive and her friend "
            "helped her compare options."
        ),
        source_refs=(
            "locomo:conv-26:session_2:D2:8:turn",
            "locomo:conv-26:session_2:D2:9:turn",
        ),
        metadata={"item_type": "chunk"},
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={
            "caroline",
            "adoption",
            "agency",
            "inclusive",
            "friend",
            "helped",
            "compare",
            "options",
        },
        query_terms=("caroline", "adoption", "agency"),
        relation_terms=("adoption", "agency"),
        relation_variant_terms=("inclusive", "help"),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=(),
        high_signal_relation_terms={"inclusive"},
        is_temporal_query=False,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=True,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=False,
    )

    assert features.source_turn_refs == ("D2:8", "D2:9")
    assert features.turn_ref_count == 2
    assert features.source_turn_span == 2
    assert features.source_locality_score == 0.95
    assert features.source_locality_reason_codes == ("proximate_source_turn_refs",)
    assert features.source_ref_dedupe_key == (
        "source_session_turn_refs:session_2:D2:8|session_2:D2:9"
    )
    assert "source_provenance" in features.answerability_reason_codes
    diagnostics = features.to_diagnostics()
    assert diagnostics["source_turn_refs"] == ["D2:8", "D2:9"]
    assert diagnostics["source_turn_span"] == 2


@pytest.mark.parametrize(
    ("text", "expected_dedupe_key"),
    (
        (
            "session 2 turn D2:8 Caroline reviewed adoption options. "
            "session #2 turn D2:9 Caroline chose an inclusive agency.",
            "source_session_turn_refs:session_2:D2:8|session_2:D2:9",
        ),
        (
            "session 2 date: Monday D2:8 Caroline reviewed adoption options. "
            "session_2 date: Tuesday D2:9 Caroline chose an inclusive agency.",
            "source_session_turn_refs:session_2:D2:8|session_2:D2:9",
        ),
        (
            "turn D2:8 in session 2 Caroline reviewed adoption options. "
            "turn D2:9 in session 2 Caroline chose an inclusive agency.",
            "source_session_turn_refs:session_2:D2:8|session_2:D2:9",
        ),
    ),
)
def test_candidate_features_use_spaced_text_session_turns_for_locality(
    text: str,
    expected_dedupe_key: str,
) -> None:
    memory = RetrievedMemory(
        item_id="spaced-text-session-turns",
        rank=1,
        text=text,
        metadata={"item_type": "fact"},
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={"caroline", "adoption", "agency", "inclusive"},
        query_terms=("caroline", "adoption", "agency"),
        relation_terms=("adoption", "agency"),
        relation_variant_terms=("inclusive",),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        high_signal_relation_terms={"inclusive"},
        is_temporal_query=False,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )

    assert features.source_turn_refs == ()
    assert features.turn_ref_count == 2
    assert features.source_turn_span == 2
    assert features.source_locality_score == 0.95
    assert features.source_ref_dedupe_key == expected_dedupe_key
    assert features.source_identity_audit_gap_codes == (
        "missing_source_refs_with_text_turn_identity",
    )


@pytest.mark.parametrize(
    "source_refs",
    (
        ("locomo:conv-26:session_4", "D4:3"),
        ("conversation session #4", "D4:3"),
    ),
)
def test_candidate_features_qualify_split_session_and_turn_source_refs(
    source_refs: tuple[str, ...],
) -> None:
    memory = RetrievedMemory(
        item_id="split-session-turn-source-refs",
        rank=1,
        text="Caroline said the adoption agency felt inclusive.",
        source_refs=source_refs,
        metadata={"item_type": "chunk"},
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={"caroline", "adoption", "agency", "inclusive"},
        query_terms=("caroline", "adoption", "agency"),
        relation_terms=("adoption", "agency"),
        relation_variant_terms=("inclusive",),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=(),
        high_signal_relation_terms={"inclusive"},
        is_temporal_query=False,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=False,
    )

    assert features.source_turn_refs == ("D4:3",)
    assert features.turn_ref_count == 1
    assert features.source_ref_dedupe_key == (
        "source_session_turn_refs:session_4:D4:3"
    )
    assert features.source_identity_audit_gap_codes == ()
    assert features.to_diagnostics()["source_ref_dedupe_key"] == (
        "source_session_turn_refs:session_4:D4:3"
    )


def test_candidate_features_use_metadata_source_ref_payloads_for_identity() -> None:
    memory = RetrievedMemory(
        item_id="metadata-source-ref-payloads",
        rank=1,
        text="Caroline said the adoption agency felt inclusive.",
        source_refs=(),
        metadata={
            "item_type": "chunk",
            "source_ref_payloads": [
                {
                    "session_key": "session_12",
                    "source_dialogue_index": "D12",
                    "source_turn_index": "6",
                }
            ],
        },
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={"caroline", "adoption", "agency", "inclusive"},
        query_terms=("caroline", "adoption", "agency"),
        relation_terms=("adoption", "agency"),
        relation_variant_terms=("inclusive",),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=(),
        high_signal_relation_terms={"inclusive"},
        is_temporal_query=False,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=False,
    )

    assert features.source_ref_count == 2
    assert features.source_turn_refs == ("D12:6",)
    assert features.turn_ref_count == 1
    assert features.source_ref_dedupe_key == (
        "source_session_turn_refs:session_12:D12:6"
    )
    assert features.source_identity_audit_gap_codes == ()
    assert features.to_diagnostics()["source_ref_dedupe_key"] == (
        "source_session_turn_refs:session_12:D12:6"
    )


def test_candidate_features_use_source_evidence_refs_payloads_for_identity() -> None:
    memory = RetrievedMemory(
        item_id="metadata-source-evidence-refs",
        rank=1,
        text="Alex confirmed the workshop date.",
        source_refs=(),
        metadata={
            "item_type": "chunk",
            "source_ref_payloads": [
                {
                    "source_external_id": "locomo:conv-private:turn-secret",
                    "session_key": "session_4",
                    "source_evidence_refs": ("locomo:conv-private:D4:5",),
                }
            ],
        },
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={"alex", "workshop", "date"},
        query_terms=("alex", "workshop", "date"),
        relation_terms=("workshop", "date"),
        relation_variant_terms=(),
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=(),
        high_signal_relation_terms={"workshop", "date"},
        is_temporal_query=False,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=False,
    )

    assert features.source_ref_count == 2
    assert features.source_turn_refs == ("D4:5",)
    assert features.turn_ref_count == 1
    assert features.source_ref_dedupe_key == (
        "source_session_turn_refs:session_4:D4:5"
    )
    assert features.source_identity_audit_gap_codes == ()


def test_candidate_features_use_supporting_evidence_payloads_for_identity() -> None:
    memory = RetrievedMemory(
        item_id="metadata-supporting-evidence-refs",
        rank=1,
        text="Alex confirmed the workshop date.",
        source_refs=(),
        metadata={
            "item_type": "chunk",
            "source_ref_payloads": [
                {
                    "source_external_id": "locomo:conv-private:turn-secret",
                    "session_key": "session_4",
                    "supporting_evidence": [
                        {"source_evidence_ref": "locomo:conv-private:D4:5"}
                    ],
                }
            ],
        },
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={"alex", "workshop", "date"},
        query_terms=("alex", "workshop", "date"),
        relation_terms=("workshop", "date"),
        relation_variant_terms=(),
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=(),
        high_signal_relation_terms={"workshop", "date"},
        is_temporal_query=False,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=False,
    )

    assert features.source_ref_count == 2
    assert features.source_turn_refs == ("D4:5",)
    assert features.turn_ref_count == 1
    assert features.source_ref_dedupe_key == (
        "source_session_turn_refs:session_4:D4:5"
    )
    assert features.source_identity_audit_gap_codes == ()


def test_candidate_features_use_nested_evidence_payloads_for_identity() -> None:
    memory = RetrievedMemory(
        item_id="metadata-nested-evidence-refs",
        rank=1,
        text="Alex confirmed the workshop date.",
        source_refs=(),
        metadata={
            "item_type": "chunk",
            "source_ref_payloads": [
                {
                    "source_external_id": "locomo:conv-private:turn-secret",
                    "session_key": "session_4",
                    "evidence": [
                        {"source_evidence_ref": "locomo:conv-private:D4:5"}
                    ],
                }
            ],
        },
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={"alex", "workshop", "date"},
        query_terms=("alex", "workshop", "date"),
        relation_terms=("workshop", "date"),
        relation_variant_terms=(),
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=(),
        high_signal_relation_terms={"workshop", "date"},
        is_temporal_query=False,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=False,
    )

    assert features.source_ref_count == 2
    assert features.source_turn_refs == ("D4:5",)
    assert features.turn_ref_count == 1
    assert features.source_ref_dedupe_key == (
        "source_session_turn_refs:session_4:D4:5"
    )
    assert features.source_identity_audit_gap_codes == ()


def test_candidate_features_do_not_treat_split_direct_refs_as_perfect_locality() -> None:
    memory = RetrievedMemory(
        item_id="split-direct-source-refs",
        rank=1,
        text=(
            "D2:8 Caroline: The adoption agency felt inclusive. "
            "D9:31 Caroline: My hiking club meets every Sunday."
        ),
        source_refs=(
            "locomo:conv-26:session_2:D2:8:turn",
            "locomo:conv-26:session_2:D9:31:turn",
        ),
        metadata={"item_type": "chunk"},
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={
            "caroline",
            "adoption",
            "agency",
            "inclusive",
            "hiking",
            "club",
            "sunday",
        },
        query_terms=("caroline", "adoption", "agency"),
        relation_terms=("adoption", "agency"),
        relation_variant_terms=("inclusive",),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        high_signal_relation_terms={"inclusive"},
        is_temporal_query=False,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )

    assert features.turn_ref_count == 2
    assert features.source_turn_span == 0
    assert features.source_locality_score == 0.65
    assert features.source_locality_reason_codes == ("multi_turn_refs",)


def test_candidate_features_keep_single_session_source_refs_dedupe_qualified() -> None:
    first_session = _features_for_session_source_ref(
        "locomo:conv-26:session_1:D1:8:turn"
    )
    second_session = _features_for_session_source_ref(
        "locomo:conv-26:session_2:D1:8:turn"
    )

    assert first_session.source_ref_dedupe_key == (
        "source_session_turn_refs:session_1:D1:8"
    )
    assert second_session.source_ref_dedupe_key == (
        "source_session_turn_refs:session_2:D1:8"
    )
    assert first_session.source_ref_dedupe_key != second_session.source_ref_dedupe_key


def test_candidate_features_normalize_hyphenated_locomo_session_source_refs() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="hyphenated-session-source-refs",
            rank=1,
            text="Caroline compared adoption agencies with a friend.",
            source_refs=(
                "locomo-conv-private-session-8-D8-3-turn-secret",
                "backend-locomo-conv-private-session-8-D8-4-chunk-secret",
            ),
            metadata={"item_type": "chunk"},
        ),
        memory_terms={"caroline", "adoption", "agency", "friend"},
        query_terms=("caroline", "adoption", "agency"),
        relation_terms=("adoption", "agency"),
        relation_variant_terms=("friend",),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=(),
        high_signal_relation_terms={"agency"},
        is_temporal_query=False,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=True,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=False,
    )

    assert features.source_turn_refs == ("D8:3", "D8:4")
    assert features.turn_ref_count == 2
    assert features.source_turn_span == 2
    assert features.source_locality_reason_codes == ("proximate_source_turn_refs",)
    assert features.source_ref_dedupe_key == (
        "source_session_turn_refs:session_8:D8:3|session_8:D8:4"
    )
    assert features.source_identity_audit_gap_codes == ()


def test_candidate_features_use_hyphenated_text_session_turn_refs_for_dedupe() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="hyphenated-text-session-turn",
            rank=1,
            text="session-3 turn D3-5 Alex confirmed the planning date.",
            source_refs=("document:planning-note",),
            metadata={"item_type": "fact"},
        ),
        memory_terms={"alex", "confirm", "planning", "date"},
        query_terms=("alex", "planning", "date"),
        relation_terms=("planning", "date"),
        relation_variant_terms=("confirm",),
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
        high_signal_relation_terms={"date"},
        is_temporal_query=True,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=True,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )

    assert features.turn_ref_count == 1
    assert features.source_locality_reason_codes == ("localized_turn_refs",)
    assert features.source_ref_dedupe_key == (
        "source_session_turn_refs:session_3:D3:5"
    )
    assert features.source_identity_audit_gap_codes == (
        "generic_source_refs_with_text_turn_identity",
    )


def _features_for_session_source_ref(source_ref: str):
    return build_candidate_evidence_features(
        RetrievedMemory(
            item_id=source_ref,
            rank=1,
            text="Caroline brought a notebook to the planning meeting.",
            source_refs=(source_ref,),
            metadata={"item_type": "chunk"},
        ),
        memory_terms={"caroline", "brought", "notebook", "planning", "meeting"},
        query_terms=("caroline", "brought", "notebook"),
        relation_terms=("brought", "notebook"),
        relation_variant_terms=("planning", "meeting"),
        relation_category_terms={"action_event": ("brought", "notebook")},
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        high_signal_relation_terms={"notebook"},
        is_temporal_query=False,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=True,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )


def test_candidate_features_do_not_treat_cross_session_turn_refs_as_proximate() -> None:
    memory = RetrievedMemory(
        item_id="cross-session-summary",
        rank=1,
        text="Caroline had several conversations about adoption support.",
        source_refs=(
            "locomo:conv-26:session_2:D2:8:turn",
            "locomo:conv-26:session_9:D9:8:turn",
        ),
        metadata={"item_type": "fact"},
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={"caroline", "conversation", "adoption", "support"},
        query_terms=("caroline", "adoption", "support"),
        relation_terms=("adoption", "support"),
        relation_variant_terms=("agency",),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=(),
        high_signal_relation_terms={"support"},
        is_temporal_query=False,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=True,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=False,
    )

    assert features.source_turn_refs == ("D2:8", "D9:8")
    assert features.source_turn_span == 0
    assert features.source_locality_score == 0.65
    assert features.source_locality_reason_codes == ("multi_turn_refs",)


def test_candidate_features_do_not_treat_same_dialogue_cross_session_refs_as_proximate() -> None:
    memory = RetrievedMemory(
        item_id="same-dialogue-cross-session-summary",
        rank=1,
        text="Caroline had repeated conversations about adoption support.",
        source_refs=(
            "locomo:conv-26:session_1:D1:8:turn",
            "locomo:conv-26:session_11:D1:9:turn",
        ),
        metadata={"item_type": "fact"},
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={"caroline", "conversation", "adoption", "support"},
        query_terms=("caroline", "adoption", "support"),
        relation_terms=("adoption", "support"),
        relation_variant_terms=("agency",),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=(),
        high_signal_relation_terms={"support"},
        is_temporal_query=False,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=True,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=False,
    )

    assert features.source_turn_refs == ("D1:8", "D1:9")
    assert features.source_turn_span == 0
    assert features.source_locality_score == 0.65
    assert features.source_locality_reason_codes == ("multi_turn_refs",)


def test_candidate_features_do_not_treat_text_session_turns_as_proximate() -> None:
    memory = RetrievedMemory(
        item_id="same-dialogue-text-cross-session-summary",
        rank=1,
        text=(
            "session_1 date: Monday D1:8 Caroline discussed adoption support. "
            "session_11 date: Friday D1:9 Caroline revisited adoption support."
        ),
        metadata={"item_type": "fact"},
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={"caroline", "adoption", "support", "revisited"},
        query_terms=("caroline", "adoption", "support"),
        relation_terms=("adoption", "support"),
        relation_variant_terms=("agency",),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=(),
        high_signal_relation_terms={"support"},
        is_temporal_query=False,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=True,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=False,
    )

    assert features.source_turn_refs == ()
    assert features.turn_ref_count == 2
    assert features.source_turn_span == 0
    assert features.source_locality_score == 0.65
    assert features.source_locality_reason_codes == ("multi_turn_refs",)
    assert features.source_ref_dedupe_key == (
        "source_session_turn_refs:session_11:D1:9|session_1:D1:8"
    )
    assert features.source_identity_audit_gap_codes == (
        "missing_source_refs_with_text_turn_identity",
        "cross_session_text_identity",
    )


def test_candidate_features_keep_cross_session_chunk_refs_dedupe_qualified() -> None:
    memory = RetrievedMemory(
        item_id="same-dialogue-chunk-cross-session-summary",
        rank=1,
        text="Caroline had repeated conversations about adoption support.",
        source_refs=(
            "locomo:conv-26:session_1:D1:8:chunk",
            "locomo:conv-26:session_11:D1:9:fact",
        ),
        metadata={"item_type": "fact"},
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={"caroline", "conversation", "adoption", "support"},
        query_terms=("caroline", "adoption", "support"),
        relation_terms=("adoption", "support"),
        relation_variant_terms=("agency",),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=(),
        high_signal_relation_terms={"support"},
        is_temporal_query=False,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=True,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=False,
    )

    assert features.source_turn_span == 0
    assert features.source_ref_dedupe_key == (
        "source_session_turn_refs:session_11:D1:9|session_1:D1:8"
    )


def test_candidate_features_read_retrieval_sources_from_candidate_fusion() -> None:
    memory = RetrievedMemory(
        item_id="fusion-only-provenance",
        rank=1,
        text="D2:8 Caroline looked into adoption agencies.",
        metadata={
            "item_type": "chunk",
            "diagnostics": {
                "benchmark_candidate_fusion": {
                    "source_types": ["chunk", "raw_turn"],
                    "retrieval_sources": ["semantic_chunks", "keyword_chunks"],
                    "query_roles": ["original_question", "compact_relation"],
                }
            },
        },
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={"caroline", "look", "adoption", "agencies"},
        query_terms=("caroline", "adoption"),
        relation_terms=("adoption",),
        relation_variant_terms=("look", "agency"),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=(),
        high_signal_relation_terms={"adoption"},
        is_temporal_query=False,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )

    assert features.source_types == ("chunk", "raw_turn")
    assert features.retrieval_sources == ("semantic_chunks", "keyword_chunks")
    assert features.to_diagnostics()["source_types"] == ["chunk", "raw_turn"]
    assert features.to_diagnostics()["retrieval_sources"] == [
        "semantic_chunks",
        "keyword_chunks",
    ]

