from __future__ import annotations

from infinity_context_server.memory_comparison_candidate_features import (
    build_candidate_evidence_features,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.memory_comparison_source_identity import (
    safe_source_refs_for_output,
    source_identity_audit_gap_codes,
    source_identity_refs_from_dedupe_key,
    source_identity_refs_from_source_refs,
)


def test_source_identity_refs_from_source_refs_dedupe_key_normalizes_safely() -> None:
    refs = source_identity_refs_from_dedupe_key(
        "source_refs:"
        "LoCoMo:conv-private:SESSION_4:d4:5:TURN-secret|"
        "source_turn_refs:d1:2|"
        "provider:private-token-abc123|"
        "SOURCE_SESSION_TURN_REFS:SESSION_2:d2:3"
    )

    assert refs == (
        "source_session_turn_refs:session_4:D4:5",
        "source_turn_refs:D4:5",
        "source_turn_refs:D1:2",
        "source_session_turn_refs:session_2:D2:3",
        "source_turn_refs:D2:3",
    )
    assert "provider:private-token-abc123" not in refs


def test_source_identity_refs_from_structured_prefixed_turn_ids() -> None:
    refs = source_identity_refs_from_source_refs(
        {
            "source_session_number": "12",
            "source_turn_id": "turn-6",
            "evidence_refs": ("utt_7", "utterance:8"),
        }
    )

    assert refs == (
        "source_session_turn_refs:session_12:D12:6",
        "source_session_turn_refs:session_12:D12:7",
        "source_session_turn_refs:session_12:D12:8",
        "source_turn_refs:D12:6",
        "source_turn_refs:D12:7",
        "source_turn_refs:D12:8",
    )


def test_source_identity_refs_from_locomo_session_metadata_aliases() -> None:
    for session_key in (
        "locomo_session_index",
        "locomo_session_key",
        "locomo_session_number",
        "session_index",
        "session_number",
        "session_order",
    ):
        assert source_identity_refs_from_source_refs(
            {
                session_key: "session_12",
                "turn_index": "t6",
            }
        ) == (
            "source_session_turn_refs:session_12:D12:6",
            "source_turn_refs:D12:6",
        )


def test_source_identity_refs_from_structured_session_label_variants() -> None:
    for session_value in (
        "session #12",
        "session 12",
        "dialogue #12",
        "dialog 12",
    ):
        assert source_identity_refs_from_source_refs(
            {
                "source_session_id": session_value,
                "turn_index": "t6",
            }
        ) == (
            "source_session_turn_refs:session_12:D12:6",
            "source_turn_refs:D12:6",
        )


def test_source_identity_refs_from_plain_session_metadata_aliases() -> None:
    assert source_identity_refs_from_source_refs(
        {
            "session": "session 12",
            "turn": "turn #6",
        }
    ) == (
        "source_session_turn_refs:session_12:D12:6",
        "source_turn_refs:D12:6",
    )
    assert safe_source_refs_for_output(
        {
            "source_session": "dialog 12",
            "turn_ids": ("utt_7",),
        }
    ) == (
        "source_session_turn_refs:session_12:D12:7",
        "source_turn_refs:D12:7",
    )


def test_source_identity_refs_from_single_plural_session_metadata_aliases() -> None:
    for session_key in (
        "locomo_session_ids",
        "locomo_session_numbers",
        "session_ids",
        "session_numbers",
        "source_session_ids",
        "source_session_numbers",
    ):
        assert source_identity_refs_from_source_refs(
            {
                session_key: ("session #12",),
                "turn_index": "t6",
            }
        ) == (
            "source_session_turn_refs:session_12:D12:6",
            "source_turn_refs:D12:6",
        )


def test_source_identity_refs_do_not_qualify_ambiguous_plural_sessions() -> None:
    assert source_identity_refs_from_source_refs(
        {
            "source_session_ids": ("session #12", "session #13"),
            "turn_index": "t6",
        }
    ) == ()


def test_source_identity_refs_from_single_plural_dialogue_metadata_aliases() -> None:
    for dialogue_key in (
        "dialogue_ids",
        "dialogue_indexes",
        "dia_ids",
        "source_dialogue_ids",
        "source_dialogue_indexes",
        "source_dia_ids",
    ):
        assert source_identity_refs_from_source_refs(
            {
                dialogue_key: ("D12",),
                "turn_index": "t6",
            }
        ) == ("source_turn_refs:D12:6",)


def test_source_identity_refs_do_not_qualify_ambiguous_plural_dialogues() -> None:
    assert source_identity_refs_from_source_refs(
        {
            "source_dialogue_ids": ("D12", "D13"),
            "turn_index": "t6",
        }
    ) == ()


def test_source_identity_refs_from_structured_turn_label_variants() -> None:
    for turn_value, expected_turn in (
        ("turn #6", "D12:6"),
        ("turn 6", "D12:6"),
        ("utt #7", "D12:7"),
        ("utt 7", "D12:7"),
        ("utterance #8", "D12:8"),
        ("utterance 8", "D12:8"),
        ("t #9", "D12:9"),
    ):
        assert source_identity_refs_from_source_refs(
            {
                "source_session_number": "12",
                "source_turn_id": turn_value,
            }
        ) == (
            f"source_session_turn_refs:session_12:{expected_turn}",
            f"source_turn_refs:{expected_turn}",
        )


def test_source_identity_refs_from_locomo_turn_metadata_aliases() -> None:
    for turn_key in (
        "dialogue_turn_id",
        "dialogue_turn_ids",
        "locomo_turn_id",
        "locomo_turn_index",
        "locomo_turn_number",
        "locomo_dialogue_turn_id",
        "locomo_dialogue_turn_ids",
        "conversation_turn_id",
        "conversation_turn_index",
        "conversation_turn_number",
        "conv_turn_id",
        "source_conversation_turn_id",
        "source_conversation_turn_index",
        "source_conversation_turn_number",
        "source_dialogue_turn_id",
        "source_dialogue_turn_ids",
        "source_turn_ref",
        "source_turn_refs",
        "source_utterance_id",
        "source_utterance_index",
        "source_utterance_number",
        "turn_ref",
        "turn_refs",
        "turn_number",
        "utt_id",
        "utt_index",
        "utt_number",
        "utterance_id",
        "utterance_index",
        "utterance_number",
    ):
        assert source_identity_refs_from_source_refs(
            {
                "locomo_session_number": "12",
                turn_key: "utt_6",
            }
        ) == (
            "source_session_turn_refs:session_12:D12:6",
            "source_turn_refs:D12:6",
        )


def test_source_identity_refs_from_nested_source_turn_mapping() -> None:
    assert source_identity_refs_from_source_refs(
        {
            "source_turn": {
                "dialogue_id": 12,
                "turn_id": 6,
            }
        }
    ) == ("source_turn_refs:D12:6",)


def test_source_identity_refs_from_nested_source_turns_inherit_session_scope() -> None:
    assert source_identity_refs_from_source_refs(
        {
            "session_key": "session_12",
            "source_turns": (
                {"turn_id": "utt_6"},
                {"turn_id": "turn-7"},
            ),
        }
    ) == (
        "source_session_turn_refs:session_12:D12:6",
        "source_session_turn_refs:session_12:D12:7",
        "source_turn_refs:D12:6",
        "source_turn_refs:D12:7",
    )


def test_source_identity_refs_from_plural_dialogue_turn_metadata_aliases() -> None:
    for turn_key in (
        "dialogue_turn_ids",
        "locomo_turn_ids",
        "locomo_turn_indexes",
        "locomo_turn_numbers",
        "locomo_dialogue_turn_ids",
        "conversation_turn_ids",
        "conversation_turn_indexes",
        "conversation_turn_numbers",
        "conv_turn_ids",
        "source_conversation_turn_ids",
        "source_conversation_turn_indexes",
        "source_conversation_turn_numbers",
        "source_dialogue_turn_ids",
        "source_utterance_ids",
        "source_utterance_indexes",
        "source_utterance_numbers",
        "utt_ids",
        "utt_indexes",
        "utt_numbers",
        "utterance_ids",
        "utterance_indexes",
        "utterance_numbers",
    ):
        assert source_identity_refs_from_source_refs(
            {
                "locomo_session_number": "12",
                turn_key: ("turn-6", "utt_7"),
            }
        ) == (
            "source_session_turn_refs:session_12:D12:6",
            "source_session_turn_refs:session_12:D12:7",
            "source_turn_refs:D12:6",
            "source_turn_refs:D12:7",
        )


def test_source_identity_refs_from_source_refs_dedupe_key_bounds_generic_refs() -> None:
    long_ref = "document-" + ("x" * 200)
    raw_refs = (
        "backend:source:opaque-id",
        "graphiti:episode:opaque-id",
        "qdrant:point:opaque-id",
        "openai:response:opaque-id",
        "mem0:memory:opaque-id",
        "provider-ref-abc123",
    )

    refs = source_identity_refs_from_dedupe_key(
        "source_refs:" + "|".join((*raw_refs, "document:profile-note", long_ref, "D1:2"))
    )

    assert refs == ("document:profile-note", "source_turn_refs:D1:2")
    for raw_ref in raw_refs:
        assert raw_ref not in refs
    assert long_ref not in refs


def test_source_identity_audit_distinguishes_missing_source_ids() -> None:
    assert source_identity_audit_gap_codes(source_refs=(), text="No turn marker") == (
        "missing_source_refs",
    )
    assert source_identity_audit_gap_codes(source_refs=(), text="D5:7 Alex: hello") == (
        "missing_source_refs_with_text_turn_identity",
    )


def test_candidate_features_report_mentioned_person_without_speaker_hit() -> None:
    features = _identity_features(
        "D1:4 Maria: Alex mentioned my nickname Sunshine.",
        entity_hits=("alex",),
        speaker_hits=(),
    )

    assert features.direct_speaker_turn is True
    assert features.direct_turn_speakers == ("maria",)
    assert features.direct_turn_mentioned_entity_without_speaker_hit is True
    diagnostics = features.to_diagnostics()
    assert diagnostics["direct_turn_speakers"] == ["maria"]
    assert diagnostics["direct_turn_mentioned_entity_without_speaker_hit"] is True


def test_candidate_features_do_not_report_speaker_mismatch_for_query_speaker_turn() -> None:
    features = _identity_features(
        "D1:4 Alex: My nickname is Sunshine.",
        entity_hits=("alex",),
        speaker_hits=("alex",),
    )

    assert features.direct_turn_speakers == ("alex",)
    assert features.direct_turn_mentioned_entity_without_speaker_hit is False
    assert (
        features.to_diagnostics()["direct_turn_mentioned_entity_without_speaker_hit"]
        is False
    )


def _identity_features(
    text: str,
    *,
    entity_hits: tuple[str, ...],
    speaker_hits: tuple[str, ...],
):
    return build_candidate_evidence_features(
        RetrievedMemory(
            item_id="identity-edge-case",
            rank=1,
            text=text,
            source_refs=("D1:4",),
            metadata={"item_type": "raw_turn"},
        ),
        memory_terms={"alex", "maria", "nickname", "sunshine", "mentioned"},
        query_terms=("alex", "nickname"),
        relation_terms=("nickname",),
        relation_variant_terms=("alias", "name"),
        relation_category_terms={"alias_profile": ("nickname", "alias", "name")},
        entities=("alex",),
        entity_hits=entity_hits,
        speaker_hits=speaker_hits,
        high_signal_relation_terms={"nickname", "alias"},
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
