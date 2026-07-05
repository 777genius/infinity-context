from __future__ import annotations

from infinity_context_server.memory_comparison_candidate_features import (
    build_candidate_evidence_features,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.memory_comparison_source_identity import (
    safe_source_identity_ref,
    safe_source_refs_for_output,
    safe_turn_ref,
    source_identity_audit_gap_codes,
    source_identity_refs_from_dedupe_key,
    source_identity_refs_from_source_refs,
)


def test_safe_source_identity_ref_normalizes_only_bounded_identity_refs() -> None:
    assert safe_source_identity_ref(" source_turn_refs:d1:7 ") == (
        "source_turn_refs:D1:7"
    )
    assert safe_source_identity_ref(
        "SOURCE_SESSION_TURN_REFS:SESSION_2:d3:4"
    ) == "source_session_turn_refs:session_2:D3:4"

    assert safe_source_identity_ref(
        "locomo:conv-private:session_2:D3:4:turn-secret"
    ) is None
    assert safe_source_identity_ref(f"source_turn_refs:D1:{'9' * 40}") is None
    assert safe_source_identity_ref(f"source_turn_refs:D1:{'9' * 90}") is None
    assert safe_turn_ref(" d1:7 ") == "D1:7"
    assert safe_turn_ref(f"D1:{'9' * 40}") is None


def test_source_identity_refs_dedupe_noisy_canonical_source_refs() -> None:
    refs = source_identity_refs_from_source_refs(
        (
            "locomo:conv-private:session_1:D1:2:turn-secret",
            "locomo:conv-private:session_1:D1:2:turn-secret",
            "generic-conversation-id",
        )
    )

    assert refs == (
        "source_session_turn_refs:session_1:D1:2",
        "source_turn_refs:D1:2",
    )


def test_source_identity_refs_normalize_fuzzed_source_refs() -> None:
    assert source_identity_refs_from_source_refs(
        (
            "",
            "LoCoMo:conv-private:SESSION_8:d8:1:TURN-secret",
            "locomo:conv-private:session_8:D8:1:turn-secret",
            f"locomo:conv-private:session_8:D8:{'9' * 90}:turn-secret",
            "provider:private-token-abc123",
        )
    ) == (
        "source_session_turn_refs:session_8:D8:1",
        "source_turn_refs:D8:1",
    )

    assert source_identity_refs_from_source_refs(
        (" source_turn_refs:d8:2 ",)
    ) == ("source_turn_refs:D8:2",)
    assert source_identity_refs_from_source_refs(
        (" SOURCE_SESSION_TURN_REFS:SESSION_8:d8:3 ",)
    ) == (
        "source_session_turn_refs:session_8:D8:3",
        "source_turn_refs:D8:3",
    )


def test_safe_source_refs_for_output_filters_raw_provider_refs() -> None:
    assert safe_source_refs_for_output(
        (
            "locomo:conv-private:session_8:D8:1:turn-secret",
            "source_turn_refs:d1:2",
            "D2:3",
            "document:profile-note",
            "provider:private-token-abc123",
            "provider-ref-abc123",
            f"D5:{'9' * 90}",
        )
    ) == (
        "source_session_turn_refs:session_8:D8:1",
        "source_turn_refs:D8:1",
        "source_turn_refs:D1:2",
        "D2:3",
        "document:profile-note",
    )


def test_source_identity_refs_from_dedupe_key_filters_noisy_prefixed_refs() -> None:
    assert source_identity_refs_from_dedupe_key(
        "SOURCE_IDENTITY:SOURCE_TURN_REFS:d2:8|D2:8|D2:9"
    ) == ("source_turn_refs:D2:8", "source_turn_refs:D2:9")
    assert source_identity_refs_from_dedupe_key(
        f"source_turn_refs:D1:{'9' * 90}|D1:2"
    ) == ("source_turn_refs:D1:2",)
    assert source_identity_refs_from_dedupe_key(
        "source_session_turn_refs:SESSION_3:d3:4|provider:private-token"
    ) == ("source_session_turn_refs:session_3:D3:4",)


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


def test_source_identity_refs_from_source_refs_dedupe_key_bounds_generic_refs() -> None:
    long_ref = "document-" + ("x" * 200)

    refs = source_identity_refs_from_dedupe_key(
        "source_refs:"
        "provider-ref-abc123|"
        "document:profile-note|"
        f"{long_ref}|"
        "D1:2"
    )

    assert refs == ("document:profile-note", "source_turn_refs:D1:2")
    assert "provider-ref-abc123" not in refs
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
