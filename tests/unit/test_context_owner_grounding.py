from infinity_context_core.application.context_owner_grounding import owner_grounding_signal
from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.application.context_ranking import (
    apply_deterministic_rerank_adjustments,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_owner_grounding_matches_speaker_possessive_object() -> None:
    signal = owner_grounding_signal(
        query="What laptop does Alice Chen use?",
        text="D8:3 Alice: My laptop is the ThinkPad I use for class notes.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "owner_grounded_object_match"


def test_owner_grounding_matches_named_person_her_object_context() -> None:
    signal = owner_grounding_signal(
        query="What is Alice Chen's ticket?",
        text="D8:3 Ben: Alice said her ticket is IC-42 and she is working on it.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "owner_grounded_object_match"


def test_owner_grounding_matches_nearby_pronoun_antecedent_after_other_person() -> None:
    signal = owner_grounding_signal(
        query="What is Alice Chen's ticket?",
        text="D8:3 Ben: Carlos reminded Alice that her ticket is IC-42.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "owner_grounded_object_match"


def test_owner_grounding_penalizes_other_speaker_possessive_object() -> None:
    signal = owner_grounding_signal(
        query="What is Alice Chen's plan?",
        text="D8:4 Ben: My plan is to move the review to Friday.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "owner_grounded_object_other_owner"


def test_owner_grounding_penalizes_wrong_nearby_pronoun_antecedent() -> None:
    signal = owner_grounding_signal(
        query="What is Alice Chen's ticket?",
        text="D8:3 Ben: Alice asked Carlos about his ticket IC-99.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "owner_grounded_object_other_owner"


def test_owner_grounding_matches_their_object_when_owner_is_in_nearby_group() -> None:
    signal = owner_grounding_signal(
        query="What is Alice Chen's task?",
        text="D8:3 Ben: Alice and Carlos said their task is the migration.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "owner_grounded_object_match"


def test_owner_grounding_penalizes_their_object_for_other_nearby_group() -> None:
    signal = owner_grounding_signal(
        query="What is Alice Chen's task?",
        text="D8:3 Ben: Carlos and Dana said their task is the migration.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "owner_grounded_object_other_owner"


def test_owner_grounding_penalizes_it_when_object_belongs_to_other_named_owner() -> None:
    signal = owner_grounding_signal(
        query="What is Alice Chen's ticket?",
        text="D8:3 Ben: Alice reviewed Carlos's ticket and filed it.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "owner_grounded_object_other_owner"


def test_owner_grounding_does_not_boost_ungrounded_object_mention() -> None:
    signal = owner_grounding_signal(
        query="What is Alice Chen's class?",
        text="The class schedule was updated after the campus email.",
    )

    assert signal == (0.0, 0.0, "")


def test_owner_grounding_does_not_treat_dialogue_speaker_as_third_person_owner() -> None:
    signal = owner_grounding_signal(
        query="What is Alice Chen's ticket?",
        text="D8:3 Alice: Her ticket was already printed.",
    )

    assert signal == (0.0, 0.0, "")


def test_deterministic_rerank_prefers_owner_grounded_pronoun_evidence() -> None:
    query = "What is Alice Chen's laptop?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alice_laptop = _item(
        "alice_laptop",
        score=0.70,
        text="D8:3 Alice: My laptop is a silver ThinkPad for school.",
    )
    ben_laptop = _item(
        "ben_laptop",
        score=0.72,
        text="D8:4 Ben: My laptop is a black MacBook for work.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alice_laptop, ben_laptop),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].item_id == "alice_laptop"
    assert reranked[0].score > reranked[1].score
    assert (
        "owner_grounded_object_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "owner_grounded_object_other_owner"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prevents_wrong_owner_pronoun_false_positive() -> None:
    query = "What is Alice Chen's ticket?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alice_ticket = _item(
        "alice_ticket",
        score=0.70,
        text="D8:3 Ben: Carlos reminded Alice that her ticket is IC-42.",
    )
    carlos_ticket = _item(
        "carlos_ticket",
        score=0.72,
        text="D8:4 Ben: Alice asked Carlos about his ticket IC-99.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alice_ticket, carlos_ticket),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].item_id == "alice_ticket"
    assert reranked[0].score > reranked[1].score
    assert (
        "owner_grounded_object_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "owner_grounded_object_other_owner"
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
