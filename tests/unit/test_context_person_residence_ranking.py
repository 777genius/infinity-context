from infinity_context_core.application.context_person_residence import (
    person_residence_signal,
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


def test_person_residence_signal_matches_named_person_residence() -> None:
    signal = person_residence_signal(
        query="Where does Alice Chen live?",
        text="D2:6 Alice: I live in Portland now.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_residence_match"


def test_person_residence_signal_penalizes_other_person_residence() -> None:
    signal = person_residence_signal(
        query="Where does Alice live?",
        text="D2:6 Ben: I live in Seattle now.",
    )

    assert signal.penalty > 0
    assert signal.reason == "person_residence_other_person"


def test_person_residence_signal_matches_named_person_origin() -> None:
    signal = person_residence_signal(
        query="What is Alice Chen's hometown?",
        text="D2:6 Alice: I was born in Portland and grew up there.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_residence_match"


def test_person_residence_signal_penalizes_other_person_origin() -> None:
    signal = person_residence_signal(
        query="What country is Alice originally from?",
        text="D2:6 Ben: I am originally from Canada.",
    )

    assert signal.penalty > 0
    assert signal.reason == "person_residence_other_person"


def test_person_residence_signal_matches_named_person_relocation_origin() -> None:
    signal = person_residence_signal(
        query="Where did Alice Chen move from?",
        text="D2:6 Alice: I moved from Boston to Portland.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_residence_match"


def test_person_residence_signal_matches_relocation_origin_after_destination() -> None:
    signal = person_residence_signal(
        query="Where did Alice Chen move from?",
        text="D2:6 Alice: I moved to Portland from Boston.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_residence_match"


def test_person_residence_signal_matches_relocation_destination_after_origin() -> None:
    signal = person_residence_signal(
        query="Where did Alice Chen move to?",
        text="D2:6 Alice: I moved from Boston to Portland.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_residence_match"


def test_person_residence_signal_penalizes_other_person_relocation_origin() -> None:
    signal = person_residence_signal(
        query="Where did Alice move from?",
        text="D2:6 Ben: I moved from Seattle to Portland.",
    )

    assert signal.penalty > 0
    assert signal.reason == "person_residence_other_person"


def test_deterministic_rerank_prefers_named_person_residence() -> None:
    query = "Where does Alice Chen live?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alice_residence = _item(
        "alice_residence",
        score=0.7,
        text="D2:6 Alice: I live in Portland now.",
    )
    ben_residence = _item(
        "ben_residence",
        score=0.72,
        text="D2:7 Ben: I live in Seattle now.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alice_residence, ben_residence),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "person_residence_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "person_residence_other_person"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_named_person_origin() -> None:
    query = "Where is Alice Chen from?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alice_origin = _item(
        "alice_origin",
        score=0.7,
        text="D2:6 Alice: I am originally from Canada.",
    )
    ben_origin = _item(
        "ben_origin",
        score=0.72,
        text="D2:7 Ben: I am originally from Sweden.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alice_origin, ben_origin),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "person_residence_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "person_residence_other_person"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_named_person_relocation_origin() -> None:
    query = "Where did Alice Chen move from?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alice_origin = _item(
        "alice_relocation_origin",
        score=0.7,
        text="D2:6 Alice: I moved from Boston to Portland.",
    )
    ben_origin = _item(
        "ben_relocation_origin",
        score=0.72,
        text="D2:7 Ben: I moved from Seattle to Portland.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alice_origin, ben_origin),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "person_residence_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "person_residence_other_person"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_relocation_origin_over_destination_mention() -> None:
    query = "Where did Alice Chen move from?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alice_origin = _item(
        "alice_relocation_origin",
        score=0.7,
        text="D2:6 Alice: I moved to Portland from Boston.",
    )
    alice_destination_only = _item(
        "alice_destination_only",
        score=0.72,
        text="D2:7 Alice: I moved to Portland last spring and love the city.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alice_origin, alice_destination_only),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].item_id == "alice_relocation_origin"
    assert (
        "person_residence_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
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
