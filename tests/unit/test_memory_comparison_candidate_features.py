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


def test_candidate_features_do_not_ground_status_relation_to_wrong_target() -> None:
    wrong_target = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="wrong-target-roommate-status",
            rank=1,
            text="D1:2 Dana: Riley is Jordan's roommate.",
            source_refs=("D1:2",),
        ),
        memory_terms={"dana", "riley", "jordan", "roommate"},
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
    matching_target = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="matching-target-roommate-status",
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

    assert wrong_target.relation_category_hits == ()
    assert wrong_target.relation_target_specificity_reason_codes == (
        "target_mismatch:status_profile",
    )
    assert wrong_target.identity_confusion_reason_codes == (
        "person_identity:target_mismatch:status_profile",
    )
    assert (
        "missing_status_profile_evidence"
        in wrong_target.answerability_reason_codes
    )
    assert matching_target.relation_category_hits == ("status_profile",)
    assert matching_target.relation_target_specificity_reason_codes == ()
    assert matching_target.answerability_score > wrong_target.answerability_score
    assert wrong_target.to_diagnostics()[
        "relation_target_specificity_reason_codes"
    ] == ["target_mismatch:status_profile"]


def test_candidate_features_detect_directed_communication_surface() -> None:
    topic_mention = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="topic-mention",
            rank=1,
            text="D1:1 Alex: I reviewed Project Atlas during standup.",
            source_refs=("D1:1",),
        ),
        memory_terms={"alex", "reviewed", "project", "atlas", "standup"},
        query_terms=("alex", "tell"),
        relation_terms=("tell",),
        relation_variant_terms=("told", "mention", "mentioned", "said"),
        relation_category_terms={
            "communication": ("tell", "told", "mention", "mentioned", "said")
        },
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
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
    directed_message = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="directed-message",
            rank=2,
            text="D2:4 Alex: I told Maria yesterday.",
            source_refs=("D2:4",),
        ),
        memory_terms={"alex", "tell", "told", "maria", "yesterday"},
        query_terms=("alex", "tell"),
        relation_terms=("tell",),
        relation_variant_terms=("told", "mention", "mentioned", "said"),
        relation_category_terms={
            "communication": ("tell", "told", "mention", "mentioned", "said")
        },
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
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
        question="Who did Alex tell yesterday?",
    )

    assert topic_mention.relation_category_hits == ()
    assert directed_message.relation_category_hits == ("communication",)
    assert "communication_evidence" in directed_message.answerability_reason_codes
    assert directed_message.answerability_score > topic_mention.answerability_score
    directed_diagnostics = directed_message.to_diagnostics()
    assert directed_diagnostics["communication_direction_grounded"] is True
    assert directed_diagnostics["communication_query_speaker"] == "Alex"
    assert directed_diagnostics["communication_query_addressee"] == ""


def test_candidate_features_do_not_ground_wrong_communication_action() -> None:
    wrong_action = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="wrong-action-message",
            rank=1,
            text="D1:3 Alex: I recommended Maria yesterday.",
            source_refs=("D1:3",),
        ),
        memory_terms={"alex", "recommend", "recommended", "maria", "yesterday"},
        query_terms=("alex", "tell"),
        relation_terms=("tell",),
        relation_variant_terms=("told", "mention", "mentioned", "said"),
        relation_category_terms={
            "communication": ("tell", "told", "mention", "mentioned", "said")
        },
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
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
            item_id="matching-action-message",
            rank=2,
            text="D2:4 Alex: I told Maria yesterday.",
            source_refs=("D2:4",),
        ),
        memory_terms={"alex", "tell", "told", "maria", "yesterday"},
        query_terms=("alex", "tell"),
        relation_terms=("tell",),
        relation_variant_terms=("told", "mention", "mentioned", "said"),
        relation_category_terms={
            "communication": ("tell", "told", "mention", "mentioned", "said")
        },
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
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
    assert "missing_communication_evidence" in wrong_action.answerability_reason_codes
    assert matching_action.relation_category_hits == ("communication",)
    assert matching_action.answerability_score > wrong_action.answerability_score


@pytest.mark.parametrize(
    "text",
    (
        "D2:4 Alex: I told her yesterday.",
        "D2:4 Alex: I asked my sister after dinner.",
        "D2:4 Alex: I mentioned the delay to the team.",
    ),
)
def test_candidate_features_detect_recipient_grounded_communication_surfaces(
    text: str,
) -> None:
    features = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="recipient-grounded-message",
            rank=1,
            text=text,
            source_refs=("D2:4",),
        ),
        memory_terms={"alex", "tell", "told", "asked", "mention", "mentioned"},
        query_terms=("alex", "tell"),
        relation_terms=("tell",),
        relation_variant_terms=("told", "mention", "mentioned", "said"),
        relation_category_terms={
            "communication": ("tell", "told", "mention", "mentioned", "said")
        },
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
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

    assert features.relation_category_hits == ("communication",)
    assert "communication_evidence" in features.answerability_reason_codes


def test_candidate_features_mark_who_told_direction_grounding() -> None:
    grounded = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="grounded-message",
            rank=1,
            text="D2:4 Maria: I told Alex about the Project Atlas delay.",
            source_refs=("D2:4",),
        ),
        memory_terms={"maria", "tell", "told", "alex", "project", "atlas", "delay"},
        query_terms=("alex", "told"),
        relation_terms=("told",),
        relation_variant_terms=("tell", "said", "mention"),
        relation_category_terms={"communication": ("told", "tell", "said", "mention")},
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=(),
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
        question="Who told Alex about the Project Atlas delay?",
    )
    name_only = build_candidate_evidence_features(
        RetrievedMemory(
            item_id="name-only",
            rank=2,
            text="D2:5 Alex: Project Atlas had an invoice delay.",
            source_refs=("D2:5",),
        ),
        memory_terms={"alex", "project", "atlas", "delay"},
        query_terms=("alex", "told"),
        relation_terms=("told",),
        relation_variant_terms=("tell", "said", "mention"),
        relation_category_terms={"communication": ("told", "tell", "said", "mention")},
        entities=("alex",),
        entity_hits=("alex",),
        speaker_hits=("alex",),
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
        question="Who told Alex about the Project Atlas delay?",
    )

    assert grounded.communication_direction_grounded is True
    assert grounded.communication_query_direction == "ask_speaker"
    assert grounded.communication_query_speaker == ""
    assert grounded.communication_query_addressee == "Alex"
    assert name_only.communication_direction_ungrounded is True
    grounded_diagnostics = grounded.to_diagnostics()
    assert grounded_diagnostics["communication_direction_grounded"] is True
    assert grounded_diagnostics["communication_query_addressee"] == "Alex"


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


def test_candidate_features_qualify_split_session_and_turn_source_refs() -> None:
    memory = RetrievedMemory(
        item_id="split-session-turn-source-refs",
        rank=1,
        text="Caroline said the adoption agency felt inclusive.",
        source_refs=("locomo:conv-26:session_4", "D4:3"),
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
        "cross_session_source_identity",
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
