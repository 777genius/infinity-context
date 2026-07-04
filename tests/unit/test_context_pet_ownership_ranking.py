from infinity_context_core.application.context_pet_ownership import pet_ownership_signal
from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.application.context_ranking import (
    apply_deterministic_rerank_adjustments,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_pet_ownership_signal_matches_owner_pet_name_evidence() -> None:
    signal = pet_ownership_signal(
        query="What is Alice Chen's dog's name?",
        text="D8:3 Alice: My dog is named Max.",
    )

    assert signal.boost > 0
    assert signal.reason == "pet_ownership_match"


def test_pet_ownership_signal_penalizes_other_owner_pet_evidence() -> None:
    signal = pet_ownership_signal(
        query="What is Alice's dog's name?",
        text="D8:3 Ben: My dog is named Max.",
    )

    assert signal.penalty > 0
    assert signal.reason == "pet_ownership_other_owner"


def test_pet_ownership_signal_matches_owner_pet_inventory_query() -> None:
    signal = pet_ownership_signal(
        query="What pet does Alice have?",
        text="D8:3 Alice: I have a dog named Max.",
    )

    assert signal.boost > 0
    assert signal.reason == "pet_ownership_match"


def test_pet_ownership_signal_matches_named_pet_owner_lookup() -> None:
    signal = pet_ownership_signal(
        query="Who has a dog named Max?",
        text="D8:3 Alice: My dog is named Max.",
    )

    assert signal.boost > 0
    assert signal.reason == "pet_ownership_match"


def test_pet_ownership_signal_matches_named_cat_owner_lookup() -> None:
    signal = pet_ownership_signal(
        query="Who has a cat named Luna?",
        text="D8:3 Alice: My cat is named Luna.",
    )

    assert signal.boost > 0
    assert signal.reason == "pet_ownership_match"


def test_pet_ownership_signal_matches_whose_named_pet_lookup() -> None:
    signal = pet_ownership_signal(
        query="Whose dog is named Max?",
        text="D8:3 Alice: My dog is named Max.",
    )

    assert signal.boost > 0
    assert signal.reason == "pet_ownership_match"


def test_pet_ownership_signal_matches_owner_and_named_pet_question() -> None:
    signal = pet_ownership_signal(
        query="Does Alice Chen have a dog named Max?",
        text="D8:3 Alice: My dog is named Max.",
    )

    assert signal.boost > 0
    assert signal.reason == "pet_ownership_match"


def test_pet_ownership_signal_penalizes_same_owner_wrong_named_pet() -> None:
    signal = pet_ownership_signal(
        query="Does Alice have a dog named Max?",
        text="D8:3 Alice: My dog is named Scout.",
    )

    assert signal.penalty > 0
    assert signal.reason == "pet_ownership_other_owner"


def test_deterministic_rerank_prefers_named_owner_pet_evidence() -> None:
    query = "What is Alice Chen's dog's name?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alice_pet = _item(
        "alice_pet",
        score=0.7,
        text="D8:3 Alice: My dog is named Max.",
    )
    ben_pet = _item(
        "ben_pet",
        score=0.72,
        text="D8:4 Ben: My dog is named Scout.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alice_pet, ben_pet),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "pet_ownership_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "pet_ownership_other_owner"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_owner_pet_inventory_evidence() -> None:
    query = "What pet does Alice have?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alice_pet = _item(
        "alice_pet",
        score=0.7,
        text="D8:3 Alice: I have a dog named Max.",
    )
    ben_pet = _item(
        "ben_pet",
        score=0.72,
        text="D8:4 Ben: I have a cat named Scout.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alice_pet, ben_pet),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].item_id == "alice_pet"
    assert reranked[0].score > reranked[1].score
    assert (
        "pet_ownership_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "pet_ownership_other_owner"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_named_pet_owner_lookup() -> None:
    query = "Who has a dog named Max?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    max_pet = _item(
        "max_pet",
        score=0.7,
        text="D8:3 Alice: My dog is named Max.",
    )
    scout_pet = _item(
        "scout_pet",
        score=0.72,
        text="D8:4 Ben: My dog is named Scout.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (max_pet, scout_pet),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "pet_ownership_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_owner_and_named_pet_evidence() -> None:
    query = "Does Alice Chen have a dog named Max?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    max_pet = _item(
        "max_pet",
        score=0.7,
        text="D8:3 Alice: My dog is named Max.",
    )
    scout_pet = _item(
        "scout_pet",
        score=0.72,
        text="D8:4 Alice: My dog is named Scout.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (max_pet, scout_pet),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "pet_ownership_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "pet_ownership_other_owner"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
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
