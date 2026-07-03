from infinity_context_core.application.context_named_person_preference import (
    named_person_preference_signal,
)
from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.application.context_ranking import (
    apply_deterministic_rerank_adjustments,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_named_person_preference_signal_matches_speaker_preference() -> None:
    signal = named_person_preference_signal(
        query="What is Alice Chen's favorite dessert?",
        text="D3:4 Alice: Chocolate cake is my favorite dessert.",
    )

    assert signal.boost > 0
    assert signal.reason == "named_person_preference_match"


def test_named_person_preference_signal_penalizes_other_person_preference() -> None:
    signal = named_person_preference_signal(
        query="What does Alice like?",
        text="D3:4 Ben: I like jazz records.",
    )

    assert signal.penalty > 0
    assert signal.reason == "named_person_preference_other_person"


def test_named_person_preference_signal_matches_domain_qualified_question() -> None:
    signal = named_person_preference_signal(
        query="What food does Alice Chen like?",
        text="D3:4 Alice: I like Thai food best.",
    )

    assert signal.boost > 0
    assert signal.reason == "named_person_preference_match"


def test_named_person_preference_signal_uses_domain_terms_as_guard() -> None:
    signal = named_person_preference_signal(
        query="What food does Alice like?",
        text="D3:4 Alice: I like jazz records.",
    )

    assert signal == (0.0, 0.0, "")


def test_named_person_preference_signal_penalizes_obsolete_preference() -> None:
    signal = named_person_preference_signal(
        query="What does Alice like?",
        text="D3:4 Alice: I no longer like Thai food.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "named_person_preference_negative_or_obsolete"


def test_named_person_preference_signal_ignores_other_person_negative_cue() -> None:
    signal = named_person_preference_signal(
        query="What food does Alice like?",
        text=(
            "D3:4 Alice: I like Thai food. "
            "D3:5 Ben: I dislike spicy food."
        ),
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "named_person_preference_match"


def test_deterministic_rerank_prefers_named_person_preference_evidence() -> None:
    query = "What is Alice Chen's favorite dessert?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alice_preference = _item(
        "alice_preference",
        score=0.7,
        text="D3:4 Alice: Chocolate cake is my favorite dessert.",
    )
    ben_preference = _item(
        "ben_preference",
        score=0.72,
        text="D3:5 Ben: Lemon pie is my favorite dessert.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alice_preference, ben_preference),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "named_person_preference_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "named_person_preference_other_person"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_current_preference_over_obsolete_evidence() -> None:
    query = "What does Alice like?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    obsolete_preference = _item(
        "obsolete_preference",
        score=0.72,
        text="D3:4 Alice: I used to like Thai food.",
    )
    current_preference = _item(
        "current_preference",
        score=0.7,
        text="D3:5 Alice: I now like ramen.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (obsolete_preference, current_preference),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["current_preference"].score > by_id["obsolete_preference"].score
    assert (
        "named_person_preference_match"
        in by_id["current_preference"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "named_person_preference_negative_or_obsolete"
        in by_id["obsolete_preference"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_domain_qualified_preference() -> None:
    query = "What food does Alice Chen like?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alice_food = _item(
        "alice_food",
        score=0.7,
        text="D3:4 Alice: I like Thai food best.",
    )
    ben_food = _item(
        "ben_food",
        score=0.72,
        text="D3:5 Ben: I like pasta food trucks.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alice_food, ben_food),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "named_person_preference_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "named_person_preference_other_person"
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
