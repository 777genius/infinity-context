from infinity_context_core.application.context_person_team_membership import (
    person_team_membership_signal,
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


def test_person_team_membership_signal_matches_named_person_team() -> None:
    signal = person_team_membership_signal(
        query="What team is Alice Chen on?",
        text="D5:6 Alice: I joined the robotics team this spring.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_team_membership_match"


def test_person_team_membership_signal_penalizes_other_person_team() -> None:
    signal = person_team_membership_signal(
        query="What team is Alice on?",
        text="D5:6 Ben: I joined the robotics team this spring.",
    )

    assert signal.penalty > 0
    assert signal.reason == "person_team_membership_other_person"


def test_person_team_membership_signal_matches_belong_to_question() -> None:
    signal = person_team_membership_signal(
        query="Which club does Alice Chen belong to?",
        text="D5:6 Alice: I belong to the robotics club.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_team_membership_match"


def test_person_team_membership_signal_matches_member_of_question() -> None:
    signal = person_team_membership_signal(
        query="What group is Alice a member of?",
        text="D5:6 Alice: I am a member of the neighborhood garden group.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_team_membership_match"


def test_person_team_membership_signal_matches_class_question() -> None:
    signal = person_team_membership_signal(
        query="What class is Alice Chen in?",
        text="D5:6 Alice: I signed up for the pottery class this spring.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_team_membership_match"


def test_person_team_membership_signal_penalizes_stale_current_membership() -> None:
    signal = person_team_membership_signal(
        query="Which club does Alice Chen belong to?",
        text="D5:6 Alice: I used to belong to the chess club, but I left last year.",
    )

    assert signal.boost == 0
    assert signal.penalty > 0
    assert signal.reason == "person_team_membership_stale_membership"


def test_person_team_membership_signal_accepts_stale_membership_for_past_query() -> None:
    signal = person_team_membership_signal(
        query="Which club did Alice Chen belong to?",
        text="D5:6 Alice: I used to belong to the chess club, but I left last year.",
    )

    assert signal.boost > 0
    assert signal.penalty == 0
    assert signal.reason == "person_team_membership_match"


def test_person_team_membership_signal_penalizes_other_person_class() -> None:
    signal = person_team_membership_signal(
        query="What class is Alice Chen in?",
        text="D5:6 Ben: I signed up for the pottery class this spring.",
    )

    assert signal.penalty > 0
    assert signal.reason == "person_team_membership_other_person"


def test_deterministic_rerank_prefers_named_person_team_membership() -> None:
    query = "What team is Alice Chen on?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alice_team = _item(
        "alice_team",
        score=0.7,
        text="D5:6 Alice: I joined the robotics team this spring.",
    )
    ben_team = _item(
        "ben_team",
        score=0.72,
        text="D5:7 Ben: I joined the robotics team this spring.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alice_team, ben_team),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "person_team_membership_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "person_team_membership_other_person"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_current_membership_over_stale_state() -> None:
    query = "Which club does Alice Chen belong to?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    current_club = _item(
        "current_club",
        score=0.7,
        text="D5:6 Alice: I belong to the robotics club.",
    )
    stale_club = _item(
        "stale_club",
        score=0.72,
        text="D5:7 Alice: I used to belong to the chess club, but I left last year.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (stale_club, current_club),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["current_club"].score > by_id["stale_club"].score
    assert (
        "person_team_membership_match"
        in by_id["current_club"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "person_team_membership_stale_membership"
        in by_id["stale_club"]
        .diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_named_person_club_membership() -> None:
    query = "Which club does Alice Chen belong to?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alice_club = _item(
        "alice_club",
        score=0.7,
        text="D5:6 Alice: I belong to the robotics club.",
    )
    ben_club = _item(
        "ben_club",
        score=0.72,
        text="D5:7 Ben: I belong to the hiking club.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alice_club, ben_club),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "person_team_membership_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "person_team_membership_other_person"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_named_person_class_membership() -> None:
    query = "What class is Alice Chen in?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alice_class = _item(
        "alice_class",
        score=0.7,
        text="D5:6 Alice: I signed up for the pottery class this spring.",
    )
    ben_class = _item(
        "ben_class",
        score=0.72,
        text="D5:7 Ben: I signed up for the pottery class this spring.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alice_class, ben_class),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "person_team_membership_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "person_team_membership_other_person"
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
