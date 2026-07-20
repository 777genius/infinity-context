from __future__ import annotations

from infinity_context_server.memory_comparison_candidate_features import (
    build_candidate_evidence_features,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory


def test_candidate_features_merge_winner_and_fused_retrieval_sources() -> None:
    memory = RetrievedMemory(
        item_id="fused-provenance",
        rank=1,
        text="D2:8 Caroline looked into adoption agencies.",
        metadata={
            "item_type": "chunk",
            "diagnostics": {
                "retrieval_sources": ["semantic_chunks"],
                "benchmark_candidate_fusion": {
                    "source_types": ["chunk", "raw_turn"],
                    "retrieval_sources": ["semantic_chunks", "raw_turns"],
                },
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
    assert features.retrieval_sources == ("semantic_chunks", "raw_turns")
    assert features.to_diagnostics()["retrieval_sources"] == [
        "semantic_chunks",
        "raw_turns",
    ]


def test_candidate_features_detect_broad_summary_and_stale_conflict() -> None:
    memory = RetrievedMemory(
        item_id="summary",
        rank=1,
        text="Observations: related turns D1:1 D1:2 D1:3 mention family support.",
        metadata={
            "diagnostics": {
                "retrieval_sources": ["postgres_facts"],
                "stale_reason": "superseded",
            }
        },
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={"family", "support"},
        query_terms=("family",),
        relation_terms=("relationship",),
        relation_variant_terms=("family", "support"),
        entities=(),
        entity_hits=(),
        speaker_hits=(),
        high_signal_relation_terms={"support"},
        is_temporal_query=False,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=False,
        has_sequence_surface=True,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=False,
    )

    assert features.direct_speaker_turn is False
    assert features.broad_summary is True
    assert features.focused_turn_score == 0.0
    assert features.conflict_or_stale is True
    assert features.source_locality_score == 0.45
    assert features.source_locality_reason_codes == (
        "multi_turn_refs",
        "broad_summary_locality_cap",
    )
    assert features.answerability_score < 0.7
    assert "broad_summary_penalty" in features.answerability_reason_codes
    assert "conflict_or_stale_penalty" in features.answerability_reason_codes
    assert features.duplicate_key.startswith("item_id:summary")


def test_candidate_features_detect_labeled_generated_summary() -> None:
    memory = RetrievedMemory(
        item_id="conversation-summary",
        rank=1,
        text=(
            "Conversation summary: D2:1 D2:2 Caroline discussed family "
            "support and adoption agencies."
        ),
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={"caroline", "family", "support", "adoption", "agency"},
        query_terms=("caroline", "family", "support"),
        relation_terms=("relationship",),
        relation_variant_terms=("family", "support"),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=(),
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

    assert features.broad_summary is True
    assert features.direct_speaker_turn is False
    assert features.source_locality_score == 0.45
    assert "broad_summary_penalty" in features.answerability_reason_codes


def test_candidate_features_keep_compact_related_turns_localized() -> None:
    memory = RetrievedMemory(
        item_id="compact-source-sibling",
        rank=1,
        text=(
            "related turns: D2:8 Caroline: The adoption agency felt inclusive. "
            "D2:9 Caroline: Riley helped me compare the options."
        ),
        source_refs=("D2:8", "D2:9"),
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={
            "caroline",
            "adoption",
            "agency",
            "inclusive",
            "riley",
            "helped",
            "compare",
            "options",
        },
        query_terms=("caroline", "adoption", "agency"),
        relation_terms=("adoption", "agency"),
        relation_variant_terms=("inclusive", "helped", "compare"),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        high_signal_relation_terms={"inclusive"},
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

    assert features.broad_summary is False
    assert features.direct_speaker_turn is True
    assert features.source_turn_refs == ("D2:8", "D2:9")
    assert features.source_locality_score == 1.0
    assert features.source_locality_reason_codes == ("direct_localized_turn",)
    assert "broad_summary_penalty" not in features.answerability_reason_codes


def test_candidate_features_keep_direct_turn_summary_phrase_localized() -> None:
    memory = RetrievedMemory(
        item_id="direct-summary-phrase",
        rank=1,
        text=(
            "D2:1 Caroline: In summary, my family support helped me through "
            "the adoption agency process."
        ),
        source_refs=("D2:1",),
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={"caroline", "family", "support", "adoption", "agency"},
        query_terms=("caroline", "family", "support"),
        relation_terms=("relationship",),
        relation_variant_terms=("family", "support"),
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

    assert features.broad_summary is False
    assert features.direct_speaker_turn is True
    assert features.source_locality_score == 1.0
    assert features.source_locality_reason_codes == ("direct_localized_turn",)


def test_candidate_features_penalize_broad_turn_provenance_locality() -> None:
    memory = RetrievedMemory(
        item_id="wide-summary",
        rank=1,
        text=(
            "Observations: related turns D1:1 D1:2 D1:3 D1:4 D1:5 D1:6 "
            "mention Caroline and agency support."
        ),
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={"caroline", "agency", "support"},
        query_terms=("caroline", "agency"),
        relation_terms=("agency",),
        relation_variant_terms=("support",),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=(),
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

    assert features.broad_summary is True
    assert features.turn_ref_count == 6
    assert features.source_locality_score == 0.35
    assert features.source_locality_reason_codes == (
        "broad_turn_refs",
        "broad_summary_locality_cap",
    )
    assert "source_provenance" in features.answerability_reason_codes


def test_candidate_features_detect_textual_contrast_and_currentness() -> None:
    memory = RetrievedMemory(
        item_id="changed-plan",
        rank=1,
        text=(
            "D7:5 Caroline: I used to think about writing, but now I don't. "
            "Counseling is my current plan."
        ),
        source_refs=("D7:5",),
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={
            "caroline",
            "used",
            "writing",
            "counseling",
            "current",
            "plan",
        },
        query_terms=("caroline", "current", "plan"),
        relation_terms=("current", "plan"),
        relation_variant_terms=("writing", "counseling"),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        high_signal_relation_terms={"plan"},
        is_temporal_query=True,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=True,
        has_sequence_surface=True,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )

    assert features.conflict_or_stale is False
    assert features.negation_surface is True
    assert features.currentness_surface is True
    assert features.stale_surface is True
    assert features.contrast_surface is True
    diagnostics = features.to_diagnostics()
    assert diagnostics["contrast_surface"] is True
    assert diagnostics["currentness_surface"] is True


def test_candidate_features_score_contrast_intent_from_old_new_surfaces() -> None:
    current_only = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="current-only",
            rank=1,
            text="D7:4 Caroline: My current career path is still about work.",
            source_refs=("D7:4",),
        ),
        memory_terms={"caroline", "current", "career", "path", "work"},
        query_terms=("caroline", "current", "career", "path", "different", "before"),
        relation_terms=("current", "career", "path", "different"),
        relation_variant_terms=("previous", "before", "earlier"),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        high_signal_relation_terms={"different"},
        is_temporal_query=False,
        is_preference_query=False,
        is_contrast_query=True,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )
    old_new = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="old-new",
            rank=2,
            text=(
                "D7:5 Caroline: It used to be different before, but now "
                "my current career path is clearer."
            ),
            source_refs=("D7:5",),
        ),
        memory_terms={
            "caroline",
            "used",
            "different",
            "before",
            "now",
            "current",
            "career",
            "path",
        },
        query_terms=("caroline", "current", "career", "path", "different", "before"),
        relation_terms=("current", "career", "path", "different"),
        relation_variant_terms=("previous", "before", "earlier"),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        high_signal_relation_terms={"different"},
        is_temporal_query=False,
        is_preference_query=False,
        is_contrast_query=True,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )

    assert current_only.is_contrast_query is True
    assert current_only.currentness_surface is True
    assert current_only.stale_surface is False
    assert "intent_partial" in current_only.answerability_reason_codes
    assert old_new.contrast_surface is True
    assert old_new.currentness_surface is True
    assert old_new.stale_surface is True
    assert "intent_satisfied" in old_new.answerability_reason_codes
    assert old_new.answerability_score > current_only.answerability_score
    assert old_new.to_diagnostics()["is_contrast_query"] is True


def test_candidate_features_score_typed_duration_temporal_evidence() -> None:
    duration = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="known-friends-duration",
            rank=1,
            text="D2:4 Caroline: I have known those friends for 4 years.",
            source_refs=("D2:4",),
        ),
        memory_terms={"caroline", "known", "friend", "4", "year"},
        query_terms=("caroline", "known", "friend"),
        relation_terms=("known", "friend"),
        relation_variant_terms=(),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        high_signal_relation_terms={"known"},
        is_temporal_query=True,
        time_intent_kind="duration",
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=True,
        has_sequence_surface=True,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )
    relative_only = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="known-friends-relative",
            rank=2,
            text="D2:5 Caroline: I have known those friends since yesterday.",
            source_refs=("D2:5",),
        ),
        memory_terms={"caroline", "known", "friend", "yesterday"},
        query_terms=("caroline", "known", "friend"),
        relation_terms=("known", "friend"),
        relation_variant_terms=(),
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        high_signal_relation_terms={"known"},
        is_temporal_query=True,
        time_intent_kind="duration",
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=True,
        has_sequence_surface=True,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )

    assert duration.time_intent_kind == "duration"
    assert duration.has_duration_surface is True
    assert relative_only.has_relative_time_surface is True
    assert relative_only.has_duration_surface is False
    assert "duration_temporal_evidence" in duration.answerability_reason_codes
    assert (
        "duration_temporal_evidence_partial"
        in relative_only.answerability_reason_codes
    )
    assert duration.answerability_score > relative_only.answerability_score
    assert duration.to_diagnostics()["time_intent_kind"] == "duration"


def test_candidate_features_count_qualitative_duration_surfaces() -> None:
    qualitative = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="taking-classes-duration",
            rank=1,
            text="D2:4 Lina: I have been taking pottery classes for a few months.",
            source_refs=("D2:4",),
        ),
        memory_terms={"lina", "taking", "pottery", "class", "few", "month"},
        query_terms=("lina", "pottery", "class"),
        relation_terms=("pottery", "class"),
        relation_variant_terms=("taking",),
        entities=("lina",),
        entity_hits=("lina",),
        speaker_hits=("lina",),
        high_signal_relation_terms={"taking"},
        is_temporal_query=True,
        time_intent_kind="duration",
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=True,
        has_sequence_surface=True,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )

    assert qualitative.has_duration_surface is True
    assert "duration_temporal_evidence" in qualitative.answerability_reason_codes


def test_candidate_features_do_not_count_metadata_date_as_temporal_answer() -> None:
    metadata_only = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="studio-topic",
            rank=1,
            text=(
                "session_2 turn D2:1 date: 10:00 am "
                "D2:1 Morgan: I reviewed the studio schedule."
            ),
            source_refs=("D2:1",),
        ),
        memory_terms={"morgan", "studio", "schedule"},
        query_terms=("morgan", "visit", "studio"),
        relation_terms=("visit",),
        relation_variant_terms=("studio",),
        entities=("morgan",),
        entity_hits=("morgan",),
        speaker_hits=("morgan",),
        high_signal_relation_terms=set(),
        is_temporal_query=True,
        time_intent_kind="temporal_lookup",
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=True,
        has_sequence_surface=True,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )
    content_time = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="studio-visit",
            rank=2,
            text=(
                "session_5 turn D5:2 date: 8:00 pm "
                "D5:2 Morgan: I visited the studio yesterday."
            ),
            source_refs=("D5:2",),
        ),
        memory_terms={"morgan", "visit", "studio", "yesterday"},
        query_terms=("morgan", "visit", "studio"),
        relation_terms=("visit",),
        relation_variant_terms=("studio",),
        entities=("morgan",),
        entity_hits=("morgan",),
        speaker_hits=("morgan",),
        high_signal_relation_terms=set(),
        is_temporal_query=True,
        time_intent_kind="temporal_lookup",
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=True,
        has_sequence_surface=True,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )

    assert metadata_only.has_explicit_time_surface is True
    assert metadata_only.has_explicit_time_content_surface is False
    assert "missing_temporal_evidence" in metadata_only.answerability_reason_codes
    assert "generic_temporal_evidence" in content_time.answerability_reason_codes
    assert content_time.answerability_score > metadata_only.answerability_score


def test_candidate_features_score_weekend_relative_time_evidence() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="weekend-hike",
            rank=1,
            text="D6:4 Morgan: I am hiking with friends this weekend.",
            source_refs=("D6:4",),
        ),
        memory_terms={"morgan", "hiking", "friends", "this", "weekend"},
        query_terms=("morgan", "this", "weekend"),
        relation_terms=("hiking",),
        relation_variant_terms=("friends",),
        entities=("morgan",),
        entity_hits=("morgan",),
        speaker_hits=("morgan",),
        high_signal_relation_terms={"hiking"},
        is_temporal_query=True,
        time_intent_kind="relative_time",
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=True,
        has_sequence_surface=True,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )

    assert features.has_relative_time_surface is True
    assert "relative_temporal_evidence" in features.answerability_reason_codes


def test_candidate_features_score_explicit_date_as_relative_time_answer() -> None:
    explicit_date = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="friday-hike",
            rank=1,
            text="D6:4 Morgan: I am hiking with friends on Friday.",
            source_refs=("D6:4",),
        ),
        memory_terms={"morgan", "hiking", "friends", "friday"},
        query_terms=("morgan", "this", "weekend"),
        relation_terms=("hiking",),
        relation_variant_terms=("friends",),
        entities=("morgan",),
        entity_hits=("morgan",),
        speaker_hits=("morgan",),
        high_signal_relation_terms={"hiking"},
        is_temporal_query=True,
        time_intent_kind="relative_time",
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=True,
        has_sequence_surface=True,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )
    generic_temporal = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="generic-weekend",
            rank=2,
            text="D6:5 Morgan: I am hiking with friends soon.",
            source_refs=("D6:5",),
        ),
        memory_terms={"morgan", "hiking", "friends", "soon"},
        query_terms=("morgan", "this", "weekend"),
        relation_terms=("hiking",),
        relation_variant_terms=("friends",),
        entities=("morgan",),
        entity_hits=("morgan",),
        speaker_hits=("morgan",),
        high_signal_relation_terms={"hiking"},
        is_temporal_query=True,
        time_intent_kind="relative_time",
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=True,
        has_sequence_surface=True,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )

    assert explicit_date.has_explicit_time_content_surface is True
    assert explicit_date.has_relative_time_surface is False
    assert (
        "relative_temporal_explicit_answer_evidence"
        in explicit_date.answerability_reason_codes
    )
    assert "missing_relative_temporal_evidence" in (
        generic_temporal.answerability_reason_codes
    )
    assert explicit_date.answerability_score > generic_temporal.answerability_score


def test_candidate_features_score_during_event_temporal_evidence() -> None:
    no_temporal_content = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="call-topic",
            rank=1,
            text="D6:3 Morgan: The studio checklist is ready.",
            source_refs=("D6:3",),
        ),
        memory_terms={"morgan", "studio", "checklist", "ready"},
        query_terms=("morgan", "during", "call", "studio"),
        relation_terms=("call", "studio"),
        relation_variant_terms=(),
        entities=("morgan",),
        entity_hits=("morgan",),
        speaker_hits=("morgan",),
        high_signal_relation_terms=set(),
        is_temporal_query=True,
        time_intent_kind="temporal_lookup",
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=True,
        has_sequence_surface=True,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )
    during_event = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="during-call",
            rank=2,
            text="D6:4 Morgan: During the call, I agreed to book the studio desk.",
            source_refs=("D6:4",),
        ),
        memory_terms={"morgan", "during", "call", "agreed", "book", "studio", "desk"},
        query_terms=("morgan", "during", "call", "studio"),
        relation_terms=("call", "studio"),
        relation_variant_terms=(),
        entities=("morgan",),
        entity_hits=("morgan",),
        speaker_hits=("morgan",),
        high_signal_relation_terms=set(),
        is_temporal_query=True,
        time_intent_kind="temporal_lookup",
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=True,
        has_sequence_surface=True,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )

    assert during_event.has_temporal_sequence_surface is True
    assert during_event.temporal_sequence_direction == "during"
    assert during_event.to_diagnostics()["temporal_sequence_direction"] == "during"
    assert "generic_temporal_evidence" in during_event.answerability_reason_codes
    assert "missing_temporal_evidence" in no_temporal_content.answerability_reason_codes
    assert during_event.answerability_score > no_temporal_content.answerability_score


def test_candidate_features_bind_explicit_dates_to_local_event_sentence() -> None:
    unrelated_date = _temporal_candidate_features(
        text=(
            "D8:2 Alex: In 2022, I moved apartments. "
            "I met Riley after the conference."
        ),
        memory_terms={
            "alex",
            "2022",
            "moved",
            "apartments",
            "met",
            "riley",
            "after",
            "conference",
        },
        relation_terms=("meet", "conference"),
        relation_variant_terms=("met",),
        time_intent_kind="explicit_time",
    )
    local_date = _temporal_candidate_features(
        text="D8:3 Alex: I met Riley on Friday after the conference.",
        memory_terms={"alex", "met", "riley", "friday", "after", "conference"},
        relation_terms=("meet", "conference"),
        relation_variant_terms=("met",),
        time_intent_kind="explicit_time",
    )

    assert unrelated_date.has_explicit_time_surface is True
    assert unrelated_date.has_explicit_time_content_surface is False
    assert "explicit_temporal_evidence_partial" in (
        unrelated_date.answerability_reason_codes
    )
    assert local_date.has_explicit_time_content_surface is True
    assert "explicit_temporal_evidence" in local_date.answerability_reason_codes
    assert local_date.answerability_score > unrelated_date.answerability_score


def test_candidate_features_ignore_unrelated_current_and_stale_surfaces() -> None:
    unrelated_stale = _temporal_candidate_features(
        text=(
            "D4:1 Alex: I used to live in Boston. "
            "I currently work on Atlas."
        ),
        memory_terms={
            "alex",
            "used",
            "live",
            "boston",
            "currently",
            "work",
            "atlas",
        },
        query_terms=("alex", "current", "work", "atlas"),
        relation_terms=("work", "atlas"),
        relation_variant_terms=("currently",),
        time_intent_kind="relative_time",
    )
    local_stale = _temporal_candidate_features(
        text="D4:2 Alex: I used to work on Atlas before the team changed.",
        memory_terms={"alex", "used", "work", "atlas", "before", "team", "changed"},
        query_terms=("alex", "current", "work", "atlas"),
        relation_terms=("work", "atlas"),
        relation_variant_terms=("currently",),
        time_intent_kind="relative_time",
    )

    assert unrelated_stale.currentness_surface is True
    assert unrelated_stale.stale_surface is False
    assert local_stale.currentness_surface is False
    assert local_stale.stale_surface is True


def test_candidate_features_use_ordered_local_boundary_evidence() -> None:
    unordered_neighbor = _temporal_candidate_features(
        text=(
            "D5:1 Alex: Before lunch, Jordan moved the boxes. "
            "I met Riley after the conference."
        ),
        memory_terms={
            "alex",
            "before",
            "lunch",
            "jordan",
            "moved",
            "boxes",
            "met",
            "riley",
            "after",
            "conference",
        },
        relation_terms=("meet", "conference"),
        relation_variant_terms=("met",),
        time_intent_kind="temporal_sequence",
    )
    until_boundary = _temporal_candidate_features(
        text="D5:2 Alex: Until June, I met Riley at the old studio.",
        memory_terms={"alex", "until", "june", "met", "riley", "old", "studio"},
        relation_terms=("meet", "studio"),
        relation_variant_terms=("met",),
        time_intent_kind="temporal_sequence",
    )
    since_boundary = _temporal_candidate_features(
        text="D5:3 Alex: Since June, I met Riley at the new studio.",
        memory_terms={"alex", "since", "june", "met", "riley", "new", "studio"},
        relation_terms=("meet", "studio"),
        relation_variant_terms=("met",),
        time_intent_kind="temporal_sequence",
    )

    assert unordered_neighbor.has_temporal_sequence_surface is True
    assert unordered_neighbor.temporal_sequence_direction == "after"
    assert until_boundary.temporal_sequence_direction == "before"
    assert since_boundary.temporal_sequence_direction == "after"


def test_candidate_features_do_not_count_question_echo_as_category_hit() -> None:
    memory = RetrievedMemory(
        item_id="current-group-distractor",
        rank=1,
        text="Caroline mentioned a current group chat with friends.",
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={"caroline", "current", "group", "friend"},
        query_terms=("caroline", "current", "group", "friend"),
        relation_terms=("current", "group", "friend"),
        relation_variant_terms=("known", "year", "been"),
        relation_category_terms={
            "temporal": ("current", "known", "year", "been")
        },
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=(),
        high_signal_relation_terms={"year"},
        is_temporal_query=True,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=True,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=False,
    )

    assert features.relation_categories == ("temporal",)
    assert features.relation_category_hits == ()
    assert features.relation_category_coverage_ratio == 0.0


def test_candidate_features_credit_book_author_preference_evidence() -> None:
    generic_book_reference = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="generic-author-reference",
            rank=1,
            text="D3:5 Dana: I read novels by Octavia for school.",
            source_refs=("D3:5",),
        ),
        memory_terms={"dana", "read", "novels", "octavia", "school"},
        query_terms=("dana", "liked", "author"),
        relation_terms=("liked", "author"),
        relation_variant_terms=("novel", "novels", "read", "reading"),
        relation_category_terms={
            "preference": ("liked", "author", "novel", "novels", "read", "reading")
        },
        entities=("dana",),
        entity_hits=("dana",),
        speaker_hits=("dana",),
        high_signal_relation_terms={"liked"},
        is_temporal_query=False,
        is_preference_query=True,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )
    liked_author = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="liked-author",
            rank=2,
            text="D4:6 Dana: I liked Octavia as an author for those novels.",
            source_refs=("D4:6",),
        ),
        memory_terms={"dana", "liked", "octavia", "author", "novels"},
        query_terms=("dana", "liked", "author"),
        relation_terms=("liked", "author"),
        relation_variant_terms=("novel", "novels", "read", "reading"),
        relation_category_terms={
            "preference": ("liked", "author", "novel", "novels", "read", "reading")
        },
        entities=("dana",),
        entity_hits=("dana",),
        speaker_hits=("dana",),
        high_signal_relation_terms={"liked"},
        is_temporal_query=False,
        is_preference_query=True,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=False,
        has_sequence_surface=False,
        has_preference_evidence=True,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )

    assert generic_book_reference.relation_category_hits == ()
    assert "missing_preference_evidence" in (
        generic_book_reference.answerability_reason_codes
    )
    assert liked_author.relation_category_hits == ("preference",)
    assert "preference_evidence" in liked_author.answerability_reason_codes
    assert liked_author.answerability_score > generic_book_reference.answerability_score
    assert liked_author.answerability_score >= 0.8


def _temporal_candidate_features(
    *,
    text: str,
    memory_terms: set[str],
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...] = (),
    time_intent_kind: str,
    query_terms: tuple[str, ...] = ("alex", "after", "conference"),
):
    return build_candidate_evidence_features(
        RetrievedMemory(
            item_id="temporal-locality",
            rank=1,
            text=text,
            source_refs=("D8:2",),
        ),
        memory_terms=memory_terms,
        query_terms=query_terms,
        relation_terms=relation_terms,
        relation_variant_terms=relation_variant_terms,
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
        high_signal_relation_terms=set(relation_terms),
        is_temporal_query=True,
        time_intent_kind=time_intent_kind,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=True,
        has_sequence_surface=True,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )
