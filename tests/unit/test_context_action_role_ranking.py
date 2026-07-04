from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.application.context_ranking import (
    apply_deterministic_rerank_adjustments,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_deterministic_rerank_uses_after_recommendation_roles() -> None:
    query = "What book did Melanie read after Caroline recommended it?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "caroline_to_melanie",
        score=0.7,
        text="Caroline recommended Becoming Nicole by Amy Ellis Nutt to Melanie.",
    )
    reversed_roles = _item(
        "melanie_to_caroline",
        score=0.72,
        text="Melanie recommended Becoming Nicole to Caroline.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (reversed_roles, correct),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["caroline_to_melanie"].score > by_id["melanie_to_caroline"].score
    assert (
        "action_role_actor_recipient_match"
        in by_id["caroline_to_melanie"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "action_role_actor_recipient_reversed"
        in by_id["melanie_to_caroline"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_uses_recommended_that_recipient_roles() -> None:
    query = "Who recommended that Melanie read Becoming Nicole?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "caroline_recommended_melanie",
        score=0.7,
        text="Caroline recommended that Melanie read Becoming Nicole by Amy Ellis Nutt.",
    )
    reversed_roles = _item(
        "melanie_recommended_caroline",
        score=0.72,
        text="Melanie recommended that Caroline read Becoming Nicole by Amy Ellis Nutt.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (reversed_roles, correct),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["caroline_recommended_melanie"].score > by_id[
        "melanie_recommended_caroline"
    ].score
    assert (
        "action_role_recipient_match"
        in by_id["caroline_recommended_melanie"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "action_role_recipient_mismatch"
        in by_id["melanie_recommended_caroline"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_uses_recommend_object_actor_recipient_roles() -> None:
    query = "What book did Caroline recommend Melanie read?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "caroline_to_melanie",
        score=0.7,
        text="Caroline recommended that Melanie read Becoming Nicole by Amy Ellis Nutt.",
    )
    reversed_roles = _item(
        "melanie_to_caroline",
        score=0.72,
        text="Melanie recommended that Caroline read Becoming Nicole by Amy Ellis Nutt.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (reversed_roles, correct),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["caroline_to_melanie"].score > by_id["melanie_to_caroline"].score
    assert (
        "action_role_actor_recipient_match"
        in by_id["caroline_to_melanie"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "action_role_actor_recipient_reversed"
        in by_id["melanie_to_caroline"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_requested_recipient_evidence() -> None:
    query = "Who did Caroline recommend Becoming Nicole to?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "caroline_to_melanie",
        score=0.7,
        text="Caroline recommended Becoming Nicole by Amy Ellis Nutt to Melanie.",
    )
    actor_only = _item(
        "caroline_actor_only",
        score=0.72,
        text="Caroline recommended Becoming Nicole by Amy Ellis Nutt.",
    )
    wrong_actor = _item(
        "melanie_to_caroline",
        score=0.73,
        text="Melanie recommended Becoming Nicole to Caroline.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (actor_only, wrong_actor, correct),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["caroline_to_melanie"].score > by_id["caroline_actor_only"].score
    assert by_id["caroline_to_melanie"].score > by_id["melanie_to_caroline"].score
    assert (
        "action_role_actor_to_recipient_evidence"
        in by_id["caroline_to_melanie"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "action_role_requested_recipient_missing"
        in by_id["caroline_actor_only"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "action_role_actor_mismatch"
        in by_id["melanie_to_caroline"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_passive_requested_recipient_evidence() -> None:
    query = "Who was told about the Atlas delay by Alex?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "alex_to_maria",
        score=0.7,
        text="Alex told Maria about the Atlas delay after the call.",
    )
    actor_only = _item(
        "alex_actor_only",
        score=0.72,
        text="Alex told the Atlas delay story after the call.",
    )
    wrong_actor = _item(
        "sam_to_alex",
        score=0.73,
        text="Sam told Alex about the Atlas delay after the call.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (actor_only, wrong_actor, correct),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["alex_to_maria"].score > by_id["alex_actor_only"].score
    assert by_id["alex_to_maria"].score > by_id["sam_to_alex"].score
    assert (
        "action_role_actor_to_recipient_evidence"
        in by_id["alex_to_maria"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "action_role_requested_recipient_missing"
        in by_id["alex_actor_only"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "action_role_actor_mismatch"
        in by_id["sam_to_alex"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_does_not_treat_action_object_as_recipient() -> None:
    cases = (
        (
            "Who asked Maria to send the Atlas invoice?",
            "Alex asked Maria to send the Atlas invoice after the call.",
            "Maria asked Alex to send the Atlas invoice after the call.",
        ),
        (
            "Who told Maria to send the Atlas invoice?",
            "Alex told Maria to send the Atlas invoice after the call.",
            "Maria told Alex to send the Atlas invoice after the call.",
        ),
        (
            "Who asked Maria for help with the Atlas invoice?",
            "Alex asked Maria for help with the Atlas invoice after the call.",
            "Maria asked Alex for help with the Atlas invoice after the call.",
        ),
    )

    for index, (query, correct_text, reversed_text) in enumerate(cases):
        plan = build_query_expansion_plan(query)
        intent = build_query_anchor_intent(query)
        correct = _item(f"correct_{index}", score=0.7, text=correct_text)
        reversed_roles = _item(f"reversed_{index}", score=0.72, text=reversed_text)

        reranked = apply_deterministic_rerank_adjustments(
            (reversed_roles, correct),
            query=query,
            plan=plan,
            query_anchor_intent=intent,
        )
        by_id = {item.item_id: item for item in reranked}

        assert by_id[f"correct_{index}"].score > by_id[f"reversed_{index}"].score
        assert (
            "action_role_recipient_match"
            in by_id[f"correct_{index}"].diagnostics["provenance"][
                "deterministic_rerank_reasons"
            ]
        )
        assert (
            "action_role_recipient_mismatch"
            in by_id[f"reversed_{index}"].diagnostics["provenance"][
                "deterministic_rerank_reasons"
            ]
        )


def test_deterministic_rerank_uses_russian_whose_advice_recipient() -> None:
    query = "По чьему совету Мелани прочитала Becoming Nicole?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "caroline_to_melanie",
        score=0.7,
        text="Кэролайн посоветовала Мелани прочитать Becoming Nicole.",
    )
    reversed_roles = _item(
        "melanie_to_caroline",
        score=0.72,
        text="Мелани посоветовала Кэролайн прочитать Becoming Nicole.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (reversed_roles, correct),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["caroline_to_melanie"].score > by_id["melanie_to_caroline"].score
    assert (
        "action_role_recipient_match"
        in by_id["caroline_to_melanie"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "action_role_recipient_mismatch"
        in by_id["melanie_to_caroline"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_exact_event_attendance_actor_evidence() -> None:
    query = "Who attended the Atlas kickoff?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "maria_attended",
        score=0.7,
        text="D4:8 Maria: I attended the Atlas kickoff with Dana.",
    )
    related_mention = _item(
        "alex_asked",
        score=0.72,
        text="D4:9 Alex asked Maria about the Atlas kickoff.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (related_mention, correct),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["maria_attended"].score > by_id["alex_asked"].score
    assert (
        "action_role_actor_evidence"
        in by_id["maria_attended"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "action_role_actor_evidence"
        not in by_id["alex_asked"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )


def test_deterministic_rerank_prefers_actual_companion_over_mentioned_person() -> None:
    query = "Who visited Spain with Maria?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    correct = _item(
        "alex_with_maria",
        score=0.7,
        text="Alex visited Spain with Maria after the conference.",
    )
    mentioned_person = _item(
        "alex_alone_maria_mentioned",
        score=0.72,
        text="Alex visited Spain alone after Maria mentioned the conference.",
    )
    participant_without_companion = _item(
        "maria_without_companion",
        score=0.71,
        text="Maria visited Spain after the conference.",
    )

    reranked = apply_deterministic_rerank_adjustments(
        (mentioned_person, participant_without_companion, correct),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )
    by_id = {item.item_id: item for item in reranked}

    assert by_id["alex_with_maria"].score > by_id["alex_alone_maria_mentioned"].score
    assert by_id["alex_with_maria"].score > by_id["maria_without_companion"].score
    assert (
        "action_role_companion_match"
        in by_id["alex_with_maria"].diagnostics["provenance"][
            "deterministic_rerank_reasons"
        ]
    )
    assert (
        "action_role_companion_missing"
        in by_id["maria_without_companion"].diagnostics["provenance"][
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
