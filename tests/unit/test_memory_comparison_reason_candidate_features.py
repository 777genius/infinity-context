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
        relation_category_terms={"causal": ("motivat", "motivation", "reason", "because", "cause")},
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
        relation_category_terms={"causal": ("motivat", "motivation", "reason", "because", "cause")},
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
        relation_category_terms={"causal": ("reason", "because", "cause", "caus", "explain")},
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


def test_purpose_clause_counts_as_causal_candidate_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="purpose-running-turn",
            rank=1,
            text=(
                "D1:5 Alex: I started running in order to clear my head "
                "after stressful shifts."
            ),
            source_refs=("D1:5",),
        ),
        memory_terms={
            "alex",
            "started",
            "running",
            "clear",
            "head",
            "stressful",
            "shifts",
        },
        query_terms=("alex", "reason", "running"),
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


def test_directional_to_clause_without_purpose_is_not_causal_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="running-location-turn",
            rank=1,
            text="D1:5 Alex: I started running to the park after work.",
            source_refs=("D1:5",),
        ),
        memory_terms={"alex", "started", "running", "park", "work"},
        query_terms=("alex", "reason", "running"),
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
        relation_category_terms={"causal": ("reason", "because", "cause", "caus", "explain")},
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


def test_due_to_surface_counts_as_causal_candidate_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="due-to-turn",
            rank=1,
            text=("D1:4 Jon: Jon is starting his own dance studio due to his passion for dancing."),
            source_refs=("D1:4",),
        ),
        memory_terms={"jon", "start", "studio", "due", "passion", "dancing"},
        query_terms=("jon", "reason", "start", "studio"),
        relation_terms=("reason",),
        relation_variant_terms=("because", "cause", "caus", "explain"),
        relation_category_terms={"causal": ("reason", "because", "cause", "caus", "explain")},
        entities=("jon",),
        entity_hits=("jon",),
        speaker_hits=("jon",),
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


def test_due_date_surface_without_explanation_is_not_causal_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="due-date-turn",
            rank=1,
            text="D1:4 Jon: The studio rent due date is Friday.",
            source_refs=("D1:4",),
        ),
        memory_terms={"jon", "studio", "rent", "due", "date", "friday"},
        query_terms=("jon", "reason", "start", "studio"),
        relation_terms=("reason",),
        relation_variant_terms=("because", "cause", "caus", "explain"),
        relation_category_terms={"causal": ("reason", "because", "cause", "caus", "explain")},
        entities=("jon",),
        entity_hits=("jon",),
        speaker_hits=("jon",),
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
        relation_category_terms={"causal": ("cause", "caus", "because", "reason", "prompt")},
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


def test_prompted_reflection_surface_counts_as_causal_candidate_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="prompted-reflection-turn",
            rank=1,
            text=(
                "D1:2 Alex: Finding my old notebooks prompted me to reflect "
                "on my progress as a writer."
            ),
            source_refs=("D1:2",),
        ),
        memory_terms={
            "alex",
            "find",
            "old",
            "notebook",
            "prompt",
            "reflect",
            "progres",
            "writer",
        },
        query_terms=("alex", "prompt", "reflect"),
        relation_terms=("prompt",),
        relation_variant_terms=("reason", "because", "cause", "reflect"),
        relation_category_terms={"causal": ("prompt", "reason", "because", "cause", "reflect")},
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
        high_signal_relation_terms={"prompt", "because", "cause"},
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

    assert features.relation_category_hits == ("causal",)
    assert "causal_evidence" in features.answerability_reason_codes


def test_stemmed_caused_surface_counts_as_causal_candidate_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="caused-move-turn",
            rank=1,
            text="D1:2 Alex: The closure caused me to move.",
            source_refs=("D1:2",),
        ),
        memory_terms={"alex", "closure", "caus", "move"},
        query_terms=("alex", "because", "cause", "move"),
        relation_terms=("because", "cause"),
        relation_variant_terms=("caus", "reason", "result", "prompt", "explain"),
        relation_category_terms={"causal": ("because", "cause", "caus", "reason", "result")},
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
        high_signal_relation_terms={"because", "cause", "caus"},
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


def test_health_motivation_surface_counts_as_causal_candidate_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="health-motivation-turn",
            rank=1,
            text="D1:2 Alex: The health issue motivated me to change my lifestyle.",
            source_refs=("D1:2",),
        ),
        memory_terms={"alex", "health", "issue", "motivat", "change", "lifestyle"},
        query_terms=("alex", "health", "motivat", "change"),
        relation_terms=("health", "motivat"),
        relation_variant_terms=("motivation", "reason", "because", "cause"),
        relation_category_terms={
            "causal": ("motivat", "motivation", "reason", "because", "cause"),
            "health_profile": ("health", "doctor", "medicine", "condition"),
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

    assert features.relation_category_hits == ("causal", "health_profile")
    assert "causal_evidence" in features.answerability_reason_codes


def test_song_motivation_surface_counts_as_causal_candidate_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="song-motivation-turn",
            rank=1,
            text="D1:2 Alex: That song motivates me to be courageous.",
            source_refs=("D1:2",),
        ),
        memory_terms={"alex", "song", "motivat", "courageou"},
        query_terms=("alex", "song", "motivate", "courageou"),
        relation_terms=("song", "motivate"),
        relation_variant_terms=("motivat", "motivation", "reason", "because", "cause"),
        relation_category_terms={
            "activity": ("song", "music", "composer"),
            "causal": ("motivate", "motivat", "motivation", "reason", "because"),
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

    assert features.relation_category_hits == ("activity", "causal")
    assert "causal_evidence" in features.answerability_reason_codes


def test_running_group_motivation_surface_counts_as_causal_candidate_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="running-group-motivation-turn",
            rank=1,
            text="D1:2 Alex: The running group made it easy to stay motivated.",
            source_refs=("D1:2",),
        ),
        memory_terms={"alex", "run", "group", "made", "easy", "motivat"},
        query_terms=("alex", "run", "group", "motivat", "cause"),
        relation_terms=("run", "group", "motivat", "cause"),
        relation_variant_terms=("ran", "race", "motivation", "reason", "because"),
        relation_category_terms={
            "activity": ("run", "group", "ran", "race"),
            "causal": ("motivat", "cause", "motivation", "reason", "because"),
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

    assert features.relation_category_hits == ("activity", "causal")
    assert "causal_evidence" in features.answerability_reason_codes


def test_vehicle_frustration_surface_counts_as_causal_candidate_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="vehicle-frustration-turn",
            rank=1,
            text="D1:2 Alex: I was frustrated because my Prius broke down.",
            source_refs=("D1:2",),
        ),
        memory_terms={"alex", "frustrat", "because", "priu", "broke", "down"},
        query_terms=("alex", "reason", "frustration", "priu", "break"),
        relation_terms=("reason",),
        relation_variant_terms=("because", "cause", "caus", "explain"),
        relation_category_terms={"causal": ("reason", "because", "cause", "caus", "explain")},
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


def test_emotion_surface_with_context_counts_as_causal_candidate_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="made-happy-turn",
            rank=1,
            text="D1:2 Alex: My family made me happy.",
            source_refs=("D1:2",),
        ),
        memory_terms={"alex", "family", "made", "happy"},
        query_terms=("alex", "cause", "feel", "happy"),
        relation_terms=("cause", "feel"),
        relation_variant_terms=(
            "caus",
            "because",
            "reason",
            "felt",
            "reaction",
            "response",
            "happy",
        ),
        relation_category_terms={
            "causal": (
                "cause",
                "feel",
                "caus",
                "because",
                "reason",
                "reaction",
                "response",
            ),
            "emotion_response": (
                "feel",
                "felt",
                "reaction",
                "response",
                "happy",
            ),
        },
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
        high_signal_relation_terms={"cause", "because", "happy"},
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

    assert features.relation_category_hits == ("causal", "emotion_response")
    assert "causal_evidence" in features.answerability_reason_codes
    assert "emotion_response_evidence" in features.answerability_reason_codes


def test_negative_emotion_surface_with_context_counts_as_causal_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="made-sad-turn",
            rank=1,
            text="D1:2 Alex: The move made me sad.",
            source_refs=("D1:2",),
        ),
        memory_terms={"alex", "move", "made", "sad"},
        query_terms=("alex", "cause", "feel", "sad"),
        relation_terms=("cause", "feel"),
        relation_variant_terms=(
            "caus",
            "because",
            "reason",
            "felt",
            "reaction",
            "response",
        ),
        relation_category_terms={
            "causal": (
                "cause",
                "feel",
                "caus",
                "because",
                "reason",
                "reaction",
                "response",
            ),
            "emotion_response": (
                "feel",
                "felt",
                "reaction",
                "response",
            ),
        },
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
        high_signal_relation_terms={"cause", "because", "sad"},
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


def test_prompt_surface_counts_as_causal_candidate_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="prompted-turn",
            rank=1,
            text="D1:2 Alex: My family prompted me to leave.",
            source_refs=("D1:2",),
        ),
        memory_terms={"alex", "family", "prompt", "leave"},
        query_terms=("alex", "cause", "prompt", "leave"),
        relation_terms=("cause",),
        relation_variant_terms=("caus", "because", "reason", "prompt"),
        relation_category_terms={"causal": ("cause", "caus", "because", "reason", "prompt")},
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

    assert features.relation_category_hits == ("causal",)
    assert "causal_evidence" in features.answerability_reason_codes


def test_inspired_surface_with_context_counts_as_causal_candidate_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="inspired-turn",
            rank=1,
            text="D1:2 Alex: My family inspired me to leave.",
            source_refs=("D1:2",),
        ),
        memory_terms={"alex", "family", "inspir", "leave"},
        query_terms=("alex", "cause", "inspir", "leave"),
        relation_terms=("cause",),
        relation_variant_terms=("caus", "because", "reason", "inspir"),
        relation_category_terms={"causal": ("cause", "caus", "because", "reason", "inspir")},
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
        high_signal_relation_terms={"cause", "because", "inspir"},
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


def test_inspired_volunteering_surface_counts_as_causal_candidate_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="inspired-volunteering-turn",
            rank=1,
            text="D1:2 Alex: Jordan inspired me to start volunteering.",
            source_refs=("D1:2",),
        ),
        memory_terms={"alex", "jordan", "inspir", "start", "volunteer"},
        query_terms=("alex", "inspir", "start", "volunteer"),
        relation_terms=("inspir",),
        relation_variant_terms=("inspired", "inspiring", "reason", "because", "cause"),
        relation_category_terms={
            "causal": ("inspir", "inspired", "inspiring", "reason", "because", "cause")
        },
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
        high_signal_relation_terms={"inspir", "because", "cause"},
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


def test_inspired_cooking_surface_counts_as_causal_candidate_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="inspired-cooking-turn",
            rank=1,
            text="D1:2 Alex: The cookbook I got in Italy inspired me to cook.",
            source_refs=("D1:2",),
        ),
        memory_terms={"alex", "book", "italy", "inspir", "cook"},
        query_terms=("alex", "book", "inspir", "cook"),
        relation_terms=("book", "get", "inspir"),
        relation_variant_terms=("inspiring", "motivation", "reason", "because", "cause"),
        relation_category_terms={
            "causal": ("inspir", "inspiring", "motivation", "reason", "because"),
            "activity": ("book", "bookshelf", "story"),
        },
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
        high_signal_relation_terms={"inspir", "because", "cause"},
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


def test_inspired_gaming_video_surface_counts_as_causal_candidate_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="inspired-gaming-video-turn",
            rank=1,
            text="D1:2 Alex: The hikes inspired me to start making gaming videos.",
            source_refs=("D1:2",),
        ),
        memory_terms={"alex", "hike", "inspir", "start", "mak", "gam", "video"},
        query_terms=("alex", "inspir", "start", "gam", "video"),
        relation_terms=("inspir", "cause"),
        relation_variant_terms=("inspiring", "motivation", "reason", "because", "cause"),
        relation_category_terms={
            "causal": ("inspir", "inspiring", "motivation", "reason", "because")
        },
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
        high_signal_relation_terms={"inspir", "because", "cause"},
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


def test_inspired_design_surface_counts_as_causal_candidate_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="inspired-design-turn",
            rank=1,
            text="D1:2 Alex: I designed it inspired by my love for space and engines.",
            source_refs=("D1:2",),
        ),
        memory_terms={"alex", "design", "inspir", "love", "space", "engine"},
        query_terms=("alex", "design", "inspir", "space", "engine"),
        relation_terms=("inspir",),
        relation_variant_terms=("inspiring", "motivation", "reason", "because", "cause"),
        relation_category_terms={
            "causal": ("inspir", "inspiring", "motivation", "reason", "because")
        },
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
        high_signal_relation_terms={"inspir", "because", "cause"},
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


def test_inspired_script_surface_counts_as_causal_candidate_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="inspired-script-turn",
            rank=1,
            text="D1:2 Alex: The sunset inspired my new screenplay.",
            source_refs=("D1:2",),
        ),
        memory_terms={"alex", "sunset", "inspir", "new", "screenplay"},
        query_terms=("alex", "inspir", "screenplay"),
        relation_terms=("inspir",),
        relation_variant_terms=("inspiring", "motivation", "reason", "because", "cause"),
        relation_category_terms={
            "causal": ("inspir", "inspiring", "motivation", "reason", "because")
        },
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
        high_signal_relation_terms={"inspir", "because", "cause"},
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


def test_inspired_military_join_surface_counts_as_causal_candidate_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="inspired-military-turn",
            rank=1,
            text="D1:2 Alex: The hospital visit inspired me to join the military.",
            source_refs=("D1:2",),
        ),
        memory_terms={"alex", "hospital", "visit", "inspir", "join", "military"},
        query_terms=("alex", "inspir", "join", "military", "hospital"),
        relation_terms=("feel", "inspir", "join", "visit"),
        relation_variant_terms=("inspiring", "felt", "reaction", "reason", "because"),
        relation_category_terms={
            "causal": ("inspir", "inspiring", "motivation", "reason", "because")
        },
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
        high_signal_relation_terms={"inspir", "because", "cause"},
        is_temporal_query=True,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=True,
        has_temporal_surface=True,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )

    assert features.relation_category_hits == ("causal",)
    assert "causal_evidence" in features.answerability_reason_codes


def test_inspired_auto_engineering_surface_counts_as_causal_candidate_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="inspired-auto-engineering-turn",
            rank=1,
            text="D1:2 Dave: Those repairs inspired me to take up auto engineering.",
            source_refs=("D1:2",),
        ),
        memory_terms={"dave", "repair", "inspir", "tak", "auto", "engineering"},
        query_terms=("dave", "inspir", "auto", "engineer"),
        relation_terms=("inspir",),
        relation_variant_terms=("inspiring", "motivation", "reason", "because", "cause"),
        relation_category_terms={
            "causal": ("inspir", "inspiring", "motivation", "reason", "because")
        },
        entities=("dave",),
        entity_hits=("dave",),
        speaker_hits=("dave",),
        high_signal_relation_terms={"inspir", "because", "cause"},
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


def test_inspired_surface_without_context_is_not_causal_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="inspiring-story-turn",
            rank=1,
            text="D1:2 Alex: The story was inspiring.",
            source_refs=("D1:2",),
        ),
        memory_terms={"alex", "story", "inspir"},
        query_terms=("alex", "cause", "inspir", "leave"),
        relation_terms=("cause",),
        relation_variant_terms=("caus", "because", "reason", "inspir"),
        relation_category_terms={"causal": ("cause", "caus", "because", "reason", "inspir")},
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
        high_signal_relation_terms={"cause", "because", "inspir"},
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
