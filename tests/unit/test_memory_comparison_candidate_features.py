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
    assert diagnostics["identity_confusion_reason_codes"] == []


@pytest.mark.parametrize(
    "text",
    (
        (
            "turn D2:14 in session 2 Caroline: Family will be a challenge "
            "as a parent after the breakup, but my friends support me."
        ),
        (
            "session 2 turn D2:14 Caroline: Family will be a challenge "
            "as a parent after the breakup, but my friends support me."
        ),
        (
            "session 2 turn D2-14 Caroline: Family will be a challenge "
            "as a parent after the breakup, but my friends support me."
        ),
        (
            "session 2 - turn # D2-14 Caroline: Family will be a challenge "
            "as a parent after the breakup, but my friends support me."
        ),
        (
            "dialogue 2 turn D2:14 Caroline: Family will be a challenge "
            "as a parent after the breakup, but my friends support me."
        ),
        (
            "D2:14 in conversation 2 Caroline: Family will be a challenge "
            "as a parent after the breakup, but my friends support me."
        ),
    ),
)
def test_candidate_features_capture_turn_prefixed_direct_session_turn(
    text: str,
) -> None:
    memory = RetrievedMemory(
        item_id="turn-prefixed-direct-session-turn",
        rank=1,
        text=text,
        metadata={"item_type": "raw_turn"},
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
    assert features.source_locality_score == 1.0
    assert features.source_locality_reason_codes == ("direct_localized_turn",)
    assert features.source_ref_dedupe_key == "source_session_turn_refs:session_2:D2:14"
    assert features.source_identity_audit_gap_codes == (
        "missing_source_refs_with_text_turn_identity",
    )


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
            ("symbol", "mean", "represent", "gift", "reminder"),
            {"represent", "gift", "reminder"},
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


def test_candidate_features_cap_vague_support_below_explicit_answer_evidence() -> None:
    vague_support = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="vague-roommate-support",
            rank=1,
            text=(
                "D4:7 Dana: Riley stopped by the apartment while I was "
                "searching for a roommate."
            ),
            source_refs=("D4:7",),
        ),
        memory_terms={"dana", "riley", "apartment", "searching", "roommate"},
        query_terms=("dana", "roommate"),
        relation_terms=("roommate",),
        relation_variant_terms=(),
        relation_category_terms={
            "status_profile": ("roommate", "apartment", "living")
        },
        entities=("dana",),
        entity_hits=("dana",),
        speaker_hits=("dana",),
        high_signal_relation_terms={"roommate", "roommates"},
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
    explicit_answer = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="explicit-roommate-answer",
            rank=2,
            text="D4:8 Dana: Riley is my roommate.",
            source_refs=("D4:8",),
        ),
        memory_terms={"dana", "riley", "roommate"},
        query_terms=("dana", "roommate"),
        relation_terms=("roommate",),
        relation_variant_terms=(),
        relation_category_terms={
            "status_profile": ("roommate", "apartment", "living")
        },
        entities=("dana",),
        entity_hits=("dana",),
        speaker_hits=("dana",),
        high_signal_relation_terms={"roommate", "roommates"},
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

    assert vague_support.relation_category_hits == ()
    assert "missing_status_profile_evidence" in (
        vague_support.answerability_reason_codes
    )
    assert "missing_answer_specificity_cap" in (
        vague_support.answerability_reason_codes
    )
    assert "low_answerability" in vague_support.answerability_reason_codes
    assert vague_support.answerability_score < 0.55
    assert explicit_answer.relation_category_hits == ("status_profile",)
    assert "status_profile_evidence" in explicit_answer.answerability_reason_codes
    assert "high_answerability" in explicit_answer.answerability_reason_codes
    assert explicit_answer.answerability_score > vague_support.answerability_score


def test_candidate_features_ground_partner_status_relation_evidence() -> None:
    generic_mention = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="generic-mention",
            rank=1,
            text="D1:2 Dana: I mentioned Riley during lunch.",
            source_refs=("D1:2",),
        ),
        memory_terms={"dana", "riley", "mention", "lunch"},
        query_terms=("dana", "girlfriend"),
        relation_terms=("girlfriend",),
        relation_variant_terms=("partner", "dating", "relationship"),
        relation_category_terms={
            "status_profile": (
                "girlfriend",
                "partner",
                "dating",
                "relationship",
            )
        },
        entities=("dana",),
        entity_hits=("dana",),
        speaker_hits=("dana",),
        high_signal_relation_terms={"girlfriend", "partner", "dating"},
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
    grounded_status = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="girlfriend-status",
            rank=2,
            text="D2:5 Dana: Riley is my girlfriend.",
            source_refs=("D2:5",),
        ),
        memory_terms={"dana", "riley", "girlfriend"},
        query_terms=("dana", "girlfriend"),
        relation_terms=("girlfriend",),
        relation_variant_terms=("partner", "dating", "relationship"),
        relation_category_terms={
            "status_profile": (
                "girlfriend",
                "partner",
                "dating",
                "relationship",
            )
        },
        entities=("dana",),
        entity_hits=("dana",),
        speaker_hits=("dana",),
        high_signal_relation_terms={"girlfriend", "partner", "dating"},
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

    assert generic_mention.relation_category_hits == ()
    assert "missing_status_profile_evidence" in (
        generic_mention.answerability_reason_codes
    )
    assert grounded_status.relation_category_hits == ("status_profile",)
    assert "status_profile_evidence" in grounded_status.answerability_reason_codes
    assert grounded_status.answerability_score > generic_mention.answerability_score


def test_candidate_features_report_other_speaker_alias_relation() -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="other-speaker-alias",
            rank=1,
            text=(
                "session_1 turn D1:1 date: 10:00 am "
                "D1:1 Maria: Alex mentioned my nickname Sunshine."
            ),
            source_refs=("D1:1",),
        ),
        memory_terms={"maria", "alex", "mention", "nickname", "sunshine"},
        query_terms=("alex", "nickname"),
        relation_terms=("nickname",),
        relation_variant_terms=("alias", "name"),
        relation_category_terms={"alias_profile": ("nickname", "alias", "name")},
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=(),
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

    assert features.relation_category_hits == ()
    assert features.other_speaker_profile_relation_categories == ("alias_profile",)
    assert features.identity_confusion_reason_codes == (
        "speaker_identity:first_person_profile_relation:alias_profile",
    )
    assert "missing_alias_profile_evidence" in features.answerability_reason_codes
    diagnostics = features.to_diagnostics()
    assert diagnostics["other_speaker_profile_relation_categories"] == [
        "alias_profile"
    ]


def test_candidate_features_ground_person_role_relation_evidence() -> None:
    generic_mention = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="generic-roommate-mention",
            rank=1,
            text="D1:2 Dana: Riley stopped by the apartment yesterday.",
            source_refs=("D1:2",),
        ),
        memory_terms={"dana", "riley", "stopped", "apartment", "yesterday"},
        query_terms=("dana", "roommate"),
        relation_terms=("roommate",),
        relation_variant_terms=("housemate", "apartment", "home", "living"),
        relation_category_terms={
            "status_profile": (
                "roommate",
                "housemate",
                "apartment",
                "home",
                "living",
            )
        },
        entities=("dana",),
        entity_hits=("dana",),
        speaker_hits=("dana",),
        high_signal_relation_terms={"roommate", "housemate"},
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
    grounded_role = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="roommate-status",
            rank=2,
            text="D2:5 Dana: Riley is my roommate.",
            source_refs=("D2:5",),
        ),
        memory_terms={"dana", "riley", "roommate"},
        query_terms=("dana", "roommate"),
        relation_terms=("roommate",),
        relation_variant_terms=("housemate", "apartment", "home", "living"),
        relation_category_terms={
            "status_profile": (
                "roommate",
                "housemate",
                "apartment",
                "home",
                "living",
            )
        },
        entities=("dana",),
        entity_hits=("dana",),
        speaker_hits=("dana",),
        high_signal_relation_terms={"roommate", "housemate"},
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

    assert generic_mention.relation_category_hits == ()
    assert "missing_status_profile_evidence" in (
        generic_mention.answerability_reason_codes
    )
    assert grounded_role.relation_category_hits == ("status_profile",)
    assert "status_profile_evidence" in grounded_role.answerability_reason_codes
    assert grounded_role.answerability_score > generic_mention.answerability_score


def test_candidate_features_do_not_ground_wrong_status_relation_role() -> None:
    wrong_role = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="friend-status",
            rank=1,
            text="D1:2 Dana: Riley is my friend.",
            source_refs=("D1:2",),
        ),
        memory_terms={"dana", "riley", "friend"},
        query_terms=("dana", "roommate"),
        relation_terms=("roommate",),
        relation_variant_terms=("housemate", "apartment", "home", "living"),
        relation_category_terms={
            "status_profile": (
                "roommate",
                "housemate",
                "apartment",
                "home",
                "living",
            )
        },
        entities=("dana",),
        entity_hits=("dana",),
        speaker_hits=("dana",),
        high_signal_relation_terms={"roommate", "housemate"},
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
    matching_role = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="roommate-status",
            rank=2,
            text="D2:5 Dana: Riley is my roommate.",
            source_refs=("D2:5",),
        ),
        memory_terms={"dana", "riley", "roommate"},
        query_terms=("dana", "roommate"),
        relation_terms=("roommate",),
        relation_variant_terms=("housemate", "apartment", "home", "living"),
        relation_category_terms={
            "status_profile": (
                "roommate",
                "housemate",
                "apartment",
                "home",
                "living",
            )
        },
        entities=("dana",),
        entity_hits=("dana",),
        speaker_hits=("dana",),
        high_signal_relation_terms={"roommate", "housemate"},
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

    assert wrong_role.relation_category_hits == ()
    assert "missing_status_profile_evidence" in wrong_role.answerability_reason_codes
    assert matching_role.relation_category_hits == ("status_profile",)
    assert matching_role.answerability_score > wrong_role.answerability_score


def test_candidate_features_detect_location_transition_destination_surface() -> None:
    generic_move = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="generic-move",
            rank=1,
            text="D1:1 Morgan: I moved the design review meeting to Tuesday.",
            source_refs=("D1:1",),
        ),
        memory_terms={"morgan", "mov", "move", "moved", "design", "review", "meeting"},
        query_terms=("morgan", "move"),
        relation_terms=("move",),
        relation_variant_terms=("moved", "home", "country", "origin"),
        relation_category_terms={
            "location_transition": ("move", "moved", "home", "country", "origin")
        },
        entities=("morgan",),
        entity_hits=("morgan",),
        speaker_hits=("morgan",),
        high_signal_relation_terms=set(),
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
    destination_move = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="destination-move",
            rank=2,
            text="D2:4 Morgan: I moved to Denver for the new studio role.",
            source_refs=("D2:4",),
        ),
        memory_terms={
            "morgan",
            "mov",
            "move",
            "moved",
            "denver",
            "new",
            "studio",
            "role",
        },
        query_terms=("morgan", "move"),
        relation_terms=("move",),
        relation_variant_terms=("moved", "home", "country", "origin"),
        relation_category_terms={
            "location_transition": ("move", "moved", "home", "country", "origin")
        },
        entities=("morgan",),
        entity_hits=("morgan",),
        speaker_hits=("morgan",),
        high_signal_relation_terms=set(),
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

    assert generic_move.relation_category_hits == ()
    assert destination_move.relation_category_hits == ("location_transition",)
    assert "location_transition_evidence" in (
        destination_move.answerability_reason_codes
    )
    assert destination_move.answerability_score > generic_move.answerability_score


def test_candidate_features_detect_direct_exchange_surface() -> None:
    support_abstract = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="abstract-support",
            rank=1,
            text="D1:1 Morgan: I received support after the hard week.",
            source_refs=("D1:1",),
        ),
        memory_terms={"morgan", "receive", "received", "support", "week"},
        query_terms=("morgan", "receive"),
        relation_terms=("receive",),
        relation_variant_terms=("received", "got", "gift"),
        relation_category_terms={"exchange": ("receive", "received", "got", "gift")},
        entities=("morgan",),
        entity_hits=("morgan",),
        speaker_hits=("morgan",),
        high_signal_relation_terms=set(),
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
    direct_exchange = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="direct-exchange",
            rank=2,
            text="D2:4 Morgan: I gave Maria a scarf after dinner.",
            source_refs=("D2:4",),
        ),
        memory_terms={"morgan", "gave", "maria", "scarf", "dinner"},
        query_terms=("morgan", "give"),
        relation_terms=("give",),
        relation_variant_terms=("gave", "gift", "received"),
        relation_category_terms={"exchange": ("give", "gave", "gift", "received")},
        entities=("morgan",),
        entity_hits=("morgan",),
        speaker_hits=("morgan",),
        high_signal_relation_terms=set(),
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

    assert support_abstract.relation_category_hits == ()
    assert direct_exchange.relation_category_hits == ("exchange",)
    assert "exchange_evidence" in direct_exchange.answerability_reason_codes
    assert direct_exchange.answerability_score > support_abstract.answerability_score


def test_candidate_features_do_not_ground_wrong_exchange_action() -> None:
    wrong_action = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="wrong-action-exchange",
            rank=1,
            text="D1:3 Morgan: I bought Maria a scarf after dinner.",
            source_refs=("D1:3",),
        ),
        memory_terms={"morgan", "bought", "maria", "scarf", "dinner"},
        query_terms=("morgan", "give"),
        relation_terms=("give",),
        relation_variant_terms=("gave", "gift", "received"),
        relation_category_terms={"exchange": ("give", "gave", "gift", "received")},
        entities=("morgan",),
        entity_hits=("morgan",),
        speaker_hits=("morgan",),
        high_signal_relation_terms=set(),
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
    matching_action = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="matching-action-exchange",
            rank=2,
            text="D2:4 Morgan: I gave Maria a scarf after dinner.",
            source_refs=("D2:4",),
        ),
        memory_terms={"morgan", "gave", "maria", "scarf", "dinner"},
        query_terms=("morgan", "give"),
        relation_terms=("give",),
        relation_variant_terms=("gave", "gift", "received"),
        relation_category_terms={"exchange": ("give", "gave", "gift", "received")},
        entities=("morgan",),
        entity_hits=("morgan",),
        speaker_hits=("morgan",),
        high_signal_relation_terms=set(),
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

    assert wrong_action.relation_category_hits == ()
    assert "missing_exchange_evidence" in wrong_action.answerability_reason_codes
    assert matching_action.relation_category_hits == ("exchange",)
    assert matching_action.answerability_score > wrong_action.answerability_score


def test_candidate_features_keep_cross_session_source_refs_dedupe_qualified() -> None:
    memory = RetrievedMemory(
        item_id="same-dialogue-source-cross-session-summary",
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

    assert features.source_turn_span == 0
    assert features.source_ref_dedupe_key == (
        "source_session_turn_refs:session_11:D1:9|session_1:D1:8"
    )
    assert features.source_identity_audit_gap_codes == (
        "source_session_turn_mismatch",
        "cross_session_source_identity",
    )
