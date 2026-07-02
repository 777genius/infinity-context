from __future__ import annotations

import pytest
from infinity_context_server.memory_comparison_candidate_features import (
    build_candidate_evidence_features,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory


def test_candidate_features_capture_focused_direct_turn_and_provenance() -> None:
    memory = RetrievedMemory(
        item_id="relationship-status",
        rank=1,
        text=(
            "session_2 turn D2:14 date: 8:10 pm "
            "D2:14 Caroline: Family will be a challenge as a parent after "
            "the breakup, but my friends support me."
        ),
        source_refs=("D2:14", "conv-26"),
        metadata={
            "item_type": "chunk",
            "diagnostics": {
                "retrieval_sources": ["keyword_chunks"],
                "benchmark_query_roles": ["multi_hop_bridge"],
                "benchmark_bridge_query_hit": True,
            },
        },
    )

    features = build_candidate_evidence_features(
        memory,
        memory_terms={
            "caroline",
            "family",
            "challenge",
            "parent",
            "breakup",
            "friend",
            "support",
        },
        query_terms=("caroline", "relationship", "status"),
        relation_terms=("relationship", "status"),
        relation_variant_terms=("parent", "breakup", "family", "support"),
        relation_category_terms={
            "status_profile": (
                "relationship",
                "status",
                "parent",
                "breakup",
                "family",
                "support",
            )
        },
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        high_signal_relation_terms={"support"},
        is_temporal_query=False,
        is_preference_query=False,
        has_visual_terms=False,
        has_multi_hop_markers=False,
        has_temporal_surface=True,
        has_sequence_surface=True,
        has_preference_evidence=False,
        has_visual_evidence=False,
        has_focused_turn_surface=True,
    )

    assert features.direct_speaker_turn is True
    assert features.broad_summary is False
    assert features.focused_turn_score == 0.08
    assert features.relation_hits == ("parent", "breakup", "family", "support")
    assert features.relation_categories == ("status_profile",)
    assert features.relation_category_hits == ("status_profile",)
    assert features.relation_category_coverage_ratio == 1.0
    assert features.high_signal_relation_hit_count == 1
    assert features.source_ref_count == 2
    assert features.turn_ref_count == 1
    assert features.source_ref_density == 2.0
    assert features.source_locality_score == 1.0
    assert features.source_locality_reason_codes == ("direct_localized_turn",)
    assert features.source_type == "chunk"
    assert features.retrieval_sources == ("keyword_chunks",)
    assert features.query_roles == ("multi_hop_bridge",)
    assert features.bridge_query_hit is True
    assert features.duplicate_key == "source_refs:D2:14|conv-26"
    assert features.source_ref_dedupe_key == "source_turn_refs:D2:14"
    assert features.answerability_score >= 0.9
    assert "high_answerability" in features.answerability_reason_codes
    assert "direct_provenance" in features.answerability_reason_codes
    diagnostics = features.to_diagnostics()
    assert diagnostics["schema_version"] == "candidate_evidence_features.v1"
    assert diagnostics["focused_turn_score"] == 0.08
    assert diagnostics["source_locality_score"] == 1.0
    assert diagnostics["source_locality_reason_codes"] == ["direct_localized_turn"]
    assert diagnostics["answerability_score"] == features.answerability_score
    assert diagnostics["relation_category_hits"] == ["status_profile"]
    assert diagnostics["query_roles"] == ["multi_hop_bridge"]
    assert diagnostics["bridge_query_hit"] is True
    assert diagnostics["source_ref_dedupe_key"] == "source_turn_refs:D2:14"


@pytest.mark.parametrize(
    ("category", "relation_terms", "relation_variant_terms", "support_terms"),
    (
        (
            "causal",
            ("reason",),
            ("because", "decision", "fit", "value"),
            {"because", "support"},
        ),
        (
            "contrast",
            ("different",),
            ("before", "current", "now", "previous"),
            {"before", "now"},
        ),
        (
            "registration_event",
            ("register",),
            ("signed", "class", "course", "workshop"),
            {"signed", "class"},
        ),
        (
            "symbolic_meaning",
            ("necklace", "symbolize"),
            ("symbol", "mean", "represent", "gift", "grandma"),
            {"represent", "gift", "grandma"},
        ),
        (
            "participation_event",
            ("visit",),
            ("visited", "studio", "place", "event"),
            {"visited", "studio"},
        ),
        (
            "status_profile",
            ("relationship", "status"),
            ("parent", "breakup", "family", "support"),
            {"parent", "breakup"},
        ),
        (
            "activity",
            ("activity",),
            ("hobby", "class", "creative", "paint", "swim", "run"),
            {"class", "creative"},
        ),
        (
            "current_goal",
            ("plan",),
            ("hope", "goal", "future", "soon"),
            {"goal", "future"},
        ),
        (
            "location_transition",
            ("move",),
            ("from", "home", "country", "origin", "relocated"),
            {"from", "home", "country"},
        ),
        (
            "preference",
            ("like",),
            ("animal", "outdoors", "refresh", "routine"),
            {"like", "animal"},
        ),
        (
            "support_goal",
            ("counsel", "support", "receive", "grow"),
            ("counseling", "mental", "health", "helped"),
            {"support", "got", "counseling", "life"},
        ),
        (
            "identity_profile",
            ("identity",),
            ("support", "inspir", "story", "pride"),
            {"transgender", "pride", "flag", "mural", "story"},
        ),
    ),
)
def test_candidate_features_require_typed_relation_evidence_for_answerability(
    category: str,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    support_terms: set[str],
) -> None:
    relation_category_terms = {
        category: (*relation_terms, *relation_variant_terms),
    }
    weak = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="weak-topic",
            rank=1,
            text="D1:1 Caroline: I mentioned the topic briefly.",
            source_refs=("D1:1",),
        ),
        memory_terms={"caroline", *relation_terms[:1]},
        query_terms=("caroline", *relation_terms),
        relation_terms=relation_terms,
        relation_variant_terms=relation_variant_terms,
        relation_category_terms=relation_category_terms,
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        high_signal_relation_terms=set(relation_variant_terms),
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
    grounded = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="grounded-evidence",
            rank=2,
            text="D2:3 Caroline: I described the evidence clearly.",
            source_refs=("D2:3",),
        ),
        memory_terms={"caroline", *relation_terms[:1], *support_terms},
        query_terms=("caroline", *relation_terms),
        relation_terms=relation_terms,
        relation_variant_terms=relation_variant_terms,
        relation_category_terms=relation_category_terms,
        entities=("caroline",),
        entity_hits=("caroline",),
        speaker_hits=("caroline",),
        high_signal_relation_terms=set(relation_variant_terms),
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

    assert weak.relation_category_hits == ()
    assert f"missing_{category}_evidence" in weak.answerability_reason_codes
    assert category in grounded.relation_category_hits
    assert f"{category}_evidence" in grounded.answerability_reason_codes
    assert grounded.answerability_score > weak.answerability_score


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
    assert (
        features.to_diagnostics()["source_ref_dedupe_key"]
        == "source_turn_refs:D5:7"
    )


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
    assert features.source_ref_dedupe_key == "source_turn_refs:D2:8|D2:9"
    assert "source_provenance" in features.answerability_reason_codes
    diagnostics = features.to_diagnostics()
    assert diagnostics["source_turn_refs"] == ["D2:8", "D2:9"]
    assert diagnostics["source_turn_span"] == 2


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
