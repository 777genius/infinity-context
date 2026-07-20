from __future__ import annotations

import pytest
from infinity_context_server.memory_comparison_candidate_features import (
    build_candidate_evidence_features,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory


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

