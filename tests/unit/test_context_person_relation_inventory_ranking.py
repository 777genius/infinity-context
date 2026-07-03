from infinity_context_core.application.context_person_relation_inventory import (
    person_relation_inventory_signal,
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


def test_person_relation_inventory_signal_matches_work_relation_evidence() -> None:
    signal = person_relation_inventory_signal(
        query="Who works with Alice?",
        text="D4:8 Alice: Ben is my colleague on the mobile team.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_relation_inventory_match"


def test_person_relation_inventory_signal_penalizes_anchor_only_decoy() -> None:
    signal = person_relation_inventory_signal(
        query="Who are Alice's friends?",
        text="D4:8 Alice discussed weekend plans and the weather.",
    )

    assert signal.penalty > 0
    assert signal.reason == "person_relation_inventory_anchor_only"


def test_person_relation_inventory_signal_matches_full_name_anchor_alias() -> None:
    signal = person_relation_inventory_signal(
        query="Who works with Alice Chen?",
        text="D4:8 Alice: Ben is my colleague on the mobile team.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_relation_inventory_match"


def test_person_relation_inventory_signal_ignores_different_full_name_anchor() -> None:
    signal = person_relation_inventory_signal(
        query="Who is Alice Chen's boss?",
        text="D4:8 Alice Smith: Maria is my boss at the clinic.",
    )

    assert signal == (0.0, 0.0, "")


def test_person_relation_inventory_signal_matches_named_person_boss() -> None:
    signal = person_relation_inventory_signal(
        query="Who is Alice Chen's boss?",
        text="D4:8 Alice: Maria is my boss at the clinic.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_relation_inventory_match"


def test_person_relation_inventory_signal_matches_named_person_supervisor() -> None:
    signal = person_relation_inventory_signal(
        query="Who is the supervisor of Alice?",
        text="D4:8 Alice: Maria is my supervisor at the clinic.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_relation_inventory_match"


def test_person_relation_inventory_signal_matches_named_person_roommate() -> None:
    signal = person_relation_inventory_signal(
        query="Who is Alice Chen's roommate?",
        text="D4:8 Alice: Maria is my roommate in Portland.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_relation_inventory_match"


def test_person_relation_inventory_signal_matches_named_person_spouse_role_alias() -> None:
    signal = person_relation_inventory_signal(
        query="Who is Alice Chen's wife?",
        text="D4:8 Alice: Maria is my spouse and partner.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_relation_inventory_match"


def test_person_relation_inventory_signal_matches_named_person_neighbor() -> None:
    signal = person_relation_inventory_signal(
        query="Who is the neighbor of Alice?",
        text="D4:8 Alice: Maria is my neighbor across the hall.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_relation_inventory_match"


def test_person_relation_inventory_signal_matches_named_person_coach() -> None:
    signal = person_relation_inventory_signal(
        query="Who is Alice Chen's coach?",
        text="D4:8 Alice: Maria is my coach for marathon training.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_relation_inventory_match"


def test_person_relation_inventory_signal_matches_named_person_trainer() -> None:
    signal = person_relation_inventory_signal(
        query="Who is the trainer of Alice?",
        text="D4:8 Alice: Maria is my trainer at the gym.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_relation_inventory_match"


def test_person_relation_inventory_signal_matches_named_person_teacher() -> None:
    signal = person_relation_inventory_signal(
        query="Who is Alice Chen's teacher?",
        text="D4:8 Alice: Maria is my teacher for calculus.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_relation_inventory_match"


def test_person_relation_inventory_signal_matches_named_person_tutor() -> None:
    signal = person_relation_inventory_signal(
        query="Who is the tutor of Alice?",
        text="D4:8 Alice: Maria is my tutor after school.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_relation_inventory_match"


def test_person_relation_inventory_signal_matches_named_person_doctor() -> None:
    signal = person_relation_inventory_signal(
        query="Who is Alice Chen's doctor?",
        text="D4:8 Alice: Dr. Maria Lee is my doctor at the clinic.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_relation_inventory_match"


def test_person_relation_inventory_signal_matches_named_person_therapist() -> None:
    signal = person_relation_inventory_signal(
        query="Who is the therapist of Alice?",
        text="D4:8 Alice: Maria is my therapist for anxiety.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_relation_inventory_match"


def test_person_relation_inventory_signal_matches_named_person_classmate() -> None:
    signal = person_relation_inventory_signal(
        query="Who is Alice Chen's classmate?",
        text="D4:8 Alice: Maria is my classmate in biology.",
    )

    assert signal.boost > 0
    assert signal.reason == "person_relation_inventory_match"


def test_deterministic_rerank_prefers_person_relation_evidence() -> None:
    query = "Who works with Alice?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    colleague = _item(
        "colleague",
        score=0.7,
        text="D4:8 Alice: Ben is my colleague on the mobile team.",
    )
    anchor_only = _item(
        "anchor_only",
        score=0.72,
        text="D4:9 Alice reviewed the release notes after lunch.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (colleague, anchor_only),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "person_relation_inventory_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "person_relation_inventory_anchor_only"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_named_person_boss_evidence() -> None:
    query = "Who is Alice Chen's boss?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    boss = _item(
        "boss",
        score=0.7,
        text="D4:8 Alice: Maria is my boss at the clinic.",
    )
    anchor_only = _item(
        "anchor_only",
        score=0.72,
        text="D4:9 Alice reviewed the release notes after lunch.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (boss, anchor_only),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "person_relation_inventory_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "person_relation_inventory_anchor_only"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_named_person_roommate_evidence() -> None:
    query = "Who is Alice Chen's roommate?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    roommate = _item(
        "roommate",
        score=0.7,
        text="D4:8 Alice: Maria is my roommate in Portland.",
    )
    anchor_only = _item(
        "anchor_only",
        score=0.72,
        text="D4:9 Alice reviewed the release notes after lunch.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (roommate, anchor_only),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "person_relation_inventory_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "person_relation_inventory_anchor_only"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_query_expansion_adds_spouse_role_bridge_for_wife_question() -> None:
    plan = build_query_expansion_plan("Who is Alice Chen's wife?")

    expansion = next(
        item
        for item in plan.expansions
        if item.reason == "relationship_status_bridge"
    )
    assert "Alice" in expansion.query
    assert "Chen" in expansion.query
    assert "spouse" in expansion.query
    assert "partner" in expansion.query


def test_deterministic_rerank_prefers_named_person_spouse_role_alias_evidence() -> None:
    query = "Who is Alice Chen's wife?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    spouse = _item(
        "spouse",
        score=0.7,
        text="D4:8 Alice: Maria is my spouse and partner.",
    )
    anchor_only = _item(
        "anchor_only",
        score=0.72,
        text="D4:9 Alice reviewed the release notes after lunch.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (spouse, anchor_only),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "person_relation_inventory_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "person_relation_inventory_anchor_only"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_named_person_coach_evidence() -> None:
    query = "Who is Alice Chen's coach?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    coach = _item(
        "coach",
        score=0.7,
        text="D4:8 Alice: Maria is my coach for marathon training.",
    )
    anchor_only = _item(
        "anchor_only",
        score=0.72,
        text="D4:9 Alice reviewed the release notes after lunch.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (coach, anchor_only),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "person_relation_inventory_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "person_relation_inventory_anchor_only"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_named_person_teacher_evidence() -> None:
    query = "Who is Alice Chen's teacher?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    teacher = _item(
        "teacher",
        score=0.7,
        text="D4:8 Alice: Maria is my teacher for calculus.",
    )
    anchor_only = _item(
        "anchor_only",
        score=0.72,
        text="D4:9 Alice reviewed the release notes after lunch.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (teacher, anchor_only),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "person_relation_inventory_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "person_relation_inventory_anchor_only"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_named_person_doctor_evidence() -> None:
    query = "Who is Alice Chen's doctor?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    doctor = _item(
        "doctor",
        score=0.7,
        text="D4:8 Alice: Dr. Maria Lee is my doctor at the clinic.",
    )
    anchor_only = _item(
        "anchor_only",
        score=0.72,
        text="D4:9 Alice reviewed the release notes after lunch.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (doctor, anchor_only),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "person_relation_inventory_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "person_relation_inventory_anchor_only"
        in reranked[1].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )


def test_deterministic_rerank_prefers_named_person_classmate_evidence() -> None:
    query = "Who is Alice Chen's classmate?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    classmate = _item(
        "classmate",
        score=0.7,
        text="D4:8 Alice: Maria is my classmate in biology.",
    )
    anchor_only = _item(
        "anchor_only",
        score=0.72,
        text="D4:9 Alice reviewed the release notes after lunch.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (classmate, anchor_only),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    assert reranked[0].score > reranked[1].score
    assert (
        "person_relation_inventory_match"
        in reranked[0].diagnostics["provenance"]["deterministic_rerank_reasons"]
    )
    assert (
        "person_relation_inventory_anchor_only"
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
