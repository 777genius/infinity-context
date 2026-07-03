from __future__ import annotations

from infinity_context_server.memory_comparison_intent import (
    RetrievalTimeIntent,
    infer_bundle_evidence_roles,
    infer_evidence_need,
    infer_relation_intents,
    merge_relation_evidence_needs,
)
from infinity_context_server.memory_comparison_relation_support import (
    typed_relation_category_support,
)


def test_team_member_question_promotes_status_support_role() -> None:
    time_intent = RetrievalTimeIntent(
        is_temporal=False,
        terms=(),
        surface_terms=(),
        kind="none",
    )
    relation_intents = infer_relation_intents(
        question="Who is Maria's team member?",
        relation_terms=("member", "team"),
        relation_variant_terms=("teammate", "colleague", "coworker"),
        time_intent=time_intent,
        visual_terms=(),
        multi_hop_markers=(),
    )
    evidence_need = merge_relation_evidence_needs(
        infer_evidence_need(
            question="Who is Maria's team member?",
            relation_terms=("member", "team"),
            time_intent=time_intent,
            visual_terms=(),
            multi_hop_markers=(),
            benchmark_category=4,
        ),
        relation_intents,
    )

    assert [intent.category for intent in relation_intents] == ["status_profile"]
    assert evidence_need == ("status_profile",)
    assert infer_bundle_evidence_roles(evidence_need=evidence_need) == (
        "primary",
        "status_support",
    )


def test_status_profile_support_accepts_explicit_team_member_evidence() -> None:
    assert (
        typed_relation_category_support(
            "status_profile",
            {"alex", "maria", "member", "team"},
            memory_text="D1:1 Alex is Maria's team member.",
        )
        is True
    )
    assert (
        typed_relation_category_support(
            "status_profile",
            {"alex", "maria", "team"},
            memory_text="D1:2 Alex and Maria are on the same team.",
        )
        is True
    )
