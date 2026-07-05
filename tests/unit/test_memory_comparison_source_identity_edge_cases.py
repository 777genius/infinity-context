from __future__ import annotations

from infinity_context_server.memory_comparison_candidate_features import (
    build_candidate_evidence_features,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory


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
