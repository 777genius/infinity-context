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


def test_community_membership_question_promotes_support_role() -> None:
    time_intent = RetrievalTimeIntent(
        is_temporal=False,
        terms=(),
        surface_terms=(),
        kind="none",
    )
    relation_intents = infer_relation_intents(
        question="Is Alex part of the LGBTQ community?",
        relation_terms=("part", "lgbtq", "community"),
        relation_variant_terms=("member", "joined", "pride"),
        time_intent=time_intent,
        visual_terms=(),
        multi_hop_markers=(),
    )
    evidence_need = merge_relation_evidence_needs(
        infer_evidence_need(
            question="Is Alex part of the LGBTQ community?",
            relation_terms=("part", "lgbtq", "community"),
            time_intent=time_intent,
            visual_terms=(),
            multi_hop_markers=(),
            benchmark_category=4,
        ),
        relation_intents,
    )

    assert [intent.category for intent in relation_intents] == [
        "community_membership"
    ]
    assert evidence_need == ("community_membership",)
    assert infer_bundle_evidence_roles(evidence_need=evidence_need) == (
        "primary",
        "community_membership_support",
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


def test_community_membership_support_requires_membership_not_ally_noise() -> None:
    assert (
        typed_relation_category_support(
            "community_membership",
            {"alex", "part", "lgbtq", "community"},
            memory_text="D1:5 Alex is part of the LGBTQ community.",
        )
        is True
    )
    assert (
        typed_relation_category_support(
            "community_membership",
            {"alex", "joined", "lgbtq", "support", "group"},
            memory_text="D1:6 Alex joined an LGBTQ support group.",
        )
        is True
    )
    assert (
        typed_relation_category_support(
            "community_membership",
            {"melanie", "supportive", "caroline", "transgender", "community"},
            memory_text=(
                "D1:7 Melanie is supportive of Caroline's transgender journey "
                "and encourages the LGBTQ community as an ally."
            ),
        )
        is False
    )


def test_preference_support_accepts_book_author_evidence() -> None:
    assert (
        typed_relation_category_support(
            "preference",
            {"dana", "liked", "author", "novels", "octavia"},
            memory_text="D4:6 Dana: I liked Octavia as an author for those novels.",
        )
        is True
    )
    assert (
        typed_relation_category_support(
            "preference",
            {"dana", "author", "novels", "school"},
            memory_text="D4:7 Dana: I read novels by that author for school.",
        )
        is False
    )


def test_commitment_profile_support_accepts_remember_object_evidence() -> None:
    assert (
        typed_relation_category_support(
            "commitment_profile",
            {"alex", "need", "remember", "badge"},
            memory_text="D1:3 Alex: I need to remember my badge tomorrow.",
        )
        is True
    )
    assert (
        typed_relation_category_support(
            "commitment_profile",
            {"alex", "remembered", "badge", "story"},
            memory_text="D1:4 Alex remembered a badge story from childhood.",
        )
        is False
    )
