from infinity_context_core.application.context_person_occupation import (
    person_occupation_signal,
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


def test_person_occupation_signal_matches_named_person_role() -> None:
    signal = person_occupation_signal(
        query="What does Alice Chen do for work?",
        text="D2:6 Alice: I work as a pediatric nurse.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_occupation_match"


def test_person_occupation_signal_penalizes_other_person_role() -> None:
    signal = person_occupation_signal(
        query="What is Alice's job?",
        text="D2:6 Ben: I work as a product designer.",
    )

    assert signal.penalty > 0
    assert signal.reason == "person_occupation_other_person"


def test_person_occupation_signal_matches_named_person_employer() -> None:
    signal = person_occupation_signal(
        query="Who does Alice Chen work for?",
        text="D2:6 Alice: I work for Harbor Clinic.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_occupation_match"


def test_person_occupation_signal_matches_named_person_company_question() -> None:
    signal = person_occupation_signal(
        query="What company does Alice work for?",
        text="D2:6 Alice: I work for Harbor Clinic.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_occupation_match"


def test_person_occupation_signal_matches_named_person_employer_lookup() -> None:
    signal = person_occupation_signal(
        query="Who is Alice Chen's employer?",
        text="D2:6 Alice: Harbor Clinic is my employer.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_occupation_match"


def test_person_occupation_signal_does_not_boost_reversed_employer_direction() -> None:
    signal = person_occupation_signal(
        query="Who does Alice Chen work for?",
        text="D2:6 Ben works for Alice Chen.",
    )

    assert signal.boost == 0


def test_person_occupation_signal_does_not_boost_person_as_employer_for_work_role() -> None:
    signal = person_occupation_signal(
        query="What does Alice Chen do for work?",
        text="D2:6 Ben works as Alice Chen's studio assistant.",
    )

    assert signal.boost == 0


def test_deterministic_rerank_prefers_named_person_occupation() -> None:
    query = "What does Alice Chen do for work?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alice_job = _item(
        "alice_job",
        score=0.7,
        text="D2:6 Alice: I work as a pediatric nurse.",
    )
    ben_job = _item(
        "ben_job",
        score=0.72,
        text="D2:7 Ben: I work as a product designer.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alice_job, ben_job),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "person_occupation_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "person_occupation_other_person"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_named_person_employer() -> None:
    query = "What company does Alice Chen work for?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alice_workplace = _item(
        "alice_workplace",
        score=0.7,
        text="D2:6 Alice: I work for Harbor Clinic.",
    )
    ben_workplace = _item(
        "ben_workplace",
        score=0.72,
        text="D2:7 Ben: I work for Cedar School.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alice_workplace, ben_workplace),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "person_occupation_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "person_occupation_other_person"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_named_person_employer_lookup() -> None:
    query = "Who is Alice Chen's employer?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    alice_employer = _item(
        "alice_employer",
        score=0.7,
        text="D2:6 Alice: Harbor Clinic is my employer.",
    )
    ben_employer = _item(
        "ben_employer",
        score=0.72,
        text="D2:7 Ben: Cedar School is my employer.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (alice_employer, ben_employer),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "person_occupation_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "person_occupation_other_person"
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
