from __future__ import annotations

from infinity_context_server.memory_comparison_candidate_features import (
    build_candidate_evidence_features,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory


def test_motivation_surface_counts_as_causal_candidate_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="motivation-turn",
            rank=1,
            text="D2:4 Alex: My family motivated me to leave.",
            source_refs=("D2:4",),
        ),
        memory_terms={"alex", "family", "motivat", "leave"},
        query_terms=("alex", "motivat", "leave"),
        relation_terms=("motivat",),
        relation_variant_terms=("motivation", "reason", "because", "cause"),
        relation_category_terms={
            "causal": ("motivat", "motivation", "reason", "because", "cause")
        },
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
        high_signal_relation_terms={"motivat", "because", "cause"},
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

    assert features.relation_category_hits == ("causal",)
    assert "causal_evidence" in features.answerability_reason_codes


def test_motivation_surface_without_context_is_not_causal_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="motivation-topic-turn",
            rank=1,
            text="D2:4 Alex: My motivation has been low lately.",
            source_refs=("D2:4",),
        ),
        memory_terms={"alex", "motivation", "low", "lately"},
        query_terms=("alex", "motivat", "leave"),
        relation_terms=("motivat",),
        relation_variant_terms=("motivation", "reason", "because", "cause"),
        relation_category_terms={
            "causal": ("motivat", "motivation", "reason", "because", "cause")
        },
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
        high_signal_relation_terms={"motivat", "because", "cause"},
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

    assert features.relation_category_hits == ()
    assert "missing_causal_evidence" in features.answerability_reason_codes


def test_vehicle_frustration_context_without_reason_surface_is_causal_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="vehicle-frustration-context-turn",
            rank=1,
            text="D1:2 Alex: My new Prius getting stolen left me frustrated.",
            source_refs=("D1:2",),
        ),
        memory_terms={"alex", "new", "priu", "stolen", "frustrat"},
        query_terms=("alex", "reason", "frustration", "priu", "stolen"),
        relation_terms=("reason",),
        relation_variant_terms=("because", "cause", "caus", "explain"),
        relation_category_terms={
            "causal": ("reason", "because", "cause", "caus", "explain")
        },
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
        high_signal_relation_terms={"because", "cause"},
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

    assert features.relation_category_hits == ("causal",)
    assert "causal_evidence" in features.answerability_reason_codes


def test_frustration_surface_without_context_is_not_causal_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="frustration-topic-turn",
            rank=1,
            text="D1:2 Alex: I felt frustrated today.",
            source_refs=("D1:2",),
        ),
        memory_terms={"alex", "felt", "frustrat", "today"},
        query_terms=("alex", "reason", "frustration", "priu"),
        relation_terms=("reason",),
        relation_variant_terms=("because", "cause", "caus", "explain"),
        relation_category_terms={
            "causal": ("reason", "because", "cause", "caus", "explain")
        },
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
        high_signal_relation_terms={"because", "cause"},
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

    assert features.relation_category_hits == ()
    assert "missing_causal_evidence" in features.answerability_reason_codes


def test_prompt_surface_without_context_is_not_causal_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="system-prompt-turn",
            rank=1,
            text="D1:2 Alex: The system prompt was confusing.",
            source_refs=("D1:2",),
        ),
        memory_terms={"alex", "system", "prompt", "confusing"},
        query_terms=("alex", "cause", "prompt", "leave"),
        relation_terms=("cause",),
        relation_variant_terms=("caus", "because", "reason", "prompt"),
        relation_category_terms={
            "causal": ("cause", "caus", "because", "reason", "prompt")
        },
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
        high_signal_relation_terms={"cause", "because", "prompt"},
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

    assert features.relation_category_hits == ()
    assert "missing_causal_evidence" in features.answerability_reason_codes


def test_action_query_without_action_event_surface_marks_missing_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="notebook-topic-turn",
            rank=1,
            text="D1:3 Caroline: The notebook is on my desk.",
            source_refs=("D1:3",),
        ),
        memory_terms={"caroline", "notebook", "desk"},
        query_terms=("caroline", "brought", "notebook"),
        relation_terms=("brought", "notebook"),
        relation_variant_terms=("brought", "notebook", "prepared"),
        relation_category_terms={"action_event": ("brought", "notebook")},
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        high_signal_relation_terms={"notebook"},
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

    assert features.relation_category_hits == ()
    assert "missing_action_event_evidence" in features.answerability_reason_codes
