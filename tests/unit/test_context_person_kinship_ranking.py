from infinity_context_core.application.context_person_kinship import person_kinship_signal
from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.application.context_ranking import (
    apply_deterministic_rerank_adjustments,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_person_kinship_signal_matches_named_person_sibling() -> None:
    signal = person_kinship_signal(
        query="Who is Alice Chen's brother?",
        text="D2:6 Alice: My brother Ben is visiting this weekend.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_kinship_match"


def test_person_kinship_signal_penalizes_other_person_family_relation() -> None:
    signal = person_kinship_signal(
        query="Who is Alice's brother?",
        text="D2:6 Carla: My brother Ben is visiting this weekend.",
    )

    assert signal.penalty > 0
    assert signal.reason == "person_kinship_other_person"


def test_person_kinship_signal_matches_relation_name_question() -> None:
    signal = person_kinship_signal(
        query="What is Alice Chen's brother's name?",
        text="D2:6 Alice: My brother Ben is visiting this weekend.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_kinship_match"


def test_person_kinship_signal_matches_plural_relation_names_question() -> None:
    signal = person_kinship_signal(
        query="What are Alice Chen's parents' names?",
        text="D2:6 Alice: My parents Maya and Luis are visiting this weekend.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_kinship_match"


def test_person_kinship_signal_treats_married_to_as_spouse_evidence() -> None:
    signal = person_kinship_signal(
        query="Who is Melanie's spouse?",
        text="D7:2 Melanie: I am married to Noah.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_kinship_match"


def test_person_kinship_signal_ignores_sibling_false_friend_phrase() -> None:
    signal = person_kinship_signal(
        query="Who is Alex's sister?",
        text="D1:1 Alex visited a sister city festival with Maria.",
    )

    assert signal == (0.0, 0.0, "")


def test_person_kinship_signal_ignores_non_family_partner_phrase() -> None:
    signal = person_kinship_signal(
        query="Who is Caroline's partner?",
        text="D4:2 Caroline's project partner on Atlas is Maria.",
    )

    assert signal == (0.0, 0.0, "")


def test_person_kinship_signal_ignores_unrelated_marriage_mention() -> None:
    signal = person_kinship_signal(
        query="Who is Melanie's spouse?",
        text="D7:2 Melanie: Noah is married to Ada.",
    )

    assert signal == (0.0, 0.0, "")


def test_person_kinship_signal_does_not_boost_reversed_parent_direction() -> None:
    signal = person_kinship_signal(
        query="Who is Alice's mother?",
        text="D2:6 Alice is Maya's mother.",
    )

    assert signal.boost == 0


def test_person_kinship_signal_matches_parent_possessive_direction() -> None:
    signal = person_kinship_signal(
        query="Who is Alice's mother?",
        text="D2:6 Maya is Alice's mother.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_kinship_match"


def test_deterministic_rerank_prefers_named_person_kinship_evidence() -> None:
    query = "Who is Alice Chen's brother?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alice_family = _item(
        "alice_family",
        score=0.7,
        text="D2:6 Alice: My brother Ben is visiting this weekend.",
    )
    carla_family = _item(
        "carla_family",
        score=0.72,
        text="D2:7 Carla: My brother Owen is visiting this weekend.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alice_family, carla_family),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "person_kinship_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "person_kinship_other_person"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_relation_name_evidence() -> None:
    query = "What is Alice Chen's brother's name?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alice_family = _item(
        "alice_family",
        score=0.7,
        text="D2:6 Alice: My brother Ben is visiting this weekend.",
    )
    carla_family = _item(
        "carla_family",
        score=0.72,
        text="D2:7 Carla: My brother Owen is visiting this weekend.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alice_family, carla_family),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "person_kinship_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "person_kinship_other_person"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_plural_relation_names_evidence() -> None:
    query = "What are Alice Chen's parents' names?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alice_family = _item(
        "alice_family",
        score=0.7,
        text="D2:6 Alice: My parents Maya and Luis are visiting this weekend.",
    )
    carla_family = _item(
        "carla_family",
        score=0.72,
        text="D2:7 Carla: My parents Ana and Owen are visiting this weekend.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alice_family, carla_family),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "person_kinship_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "person_kinship_other_person"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_married_to_spouse_evidence() -> None:
    query = "Who is Melanie's spouse?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    melanie_spouse = _item(
        "melanie_spouse",
        score=0.7,
        text="D7:2 Melanie: I am married to Noah.",
    )
    generic_partner = _item(
        "generic_partner",
        score=0.71,
        text="D7:3 Caroline's project partner on Atlas is Maria.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (generic_partner, melanie_spouse),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["melanie_spouse"].score > by_id["generic_partner"].score
    assert (
        "person_kinship_match"
        in by_id["melanie_spouse"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def _item(item_id: str, *, score: float, text: str) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(SourceRef(source_type="document", source_id="doc"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "retrieval_sources": ["keyword_chunks"],
            "score_signals": {"base_score": score},
            "provenance": {"retrieval_sources": ["keyword_chunks"]},
        },
    )
