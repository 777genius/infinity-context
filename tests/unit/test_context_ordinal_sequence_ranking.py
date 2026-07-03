from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.application.context_ranking import (
    apply_context_requirement_boosts,
    apply_deterministic_rerank_adjustments,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_deterministic_rerank_prefers_requested_second_step_over_wrong_ordinal() -> None:
    query = "What was the second step in the Atlas migration plan?"
    wrong_order = _item(
        "atlas_third_step",
        score=0.78,
        text="The third step in the Atlas migration plan was switching dashboards.",
    )
    exact = _item(
        "atlas_second_step",
        score=0.70,
        text="The second step in the Atlas migration plan was validating invoice exports.",
    )

    reranked = _rerank(query, wrong_order, exact)
    by_id = {item.item_id: item for item in reranked}

    assert by_id["atlas_second_step"].score > by_id["atlas_third_step"].score
    assert _has_reason(by_id["atlas_second_step"], "ordinal_sequence_exact_evidence")
    assert _has_reason(by_id["atlas_third_step"], "ordinal_sequence_order_conflict")


def test_deterministic_rerank_prefers_requested_third_event_in_sequence() -> None:
    query = "Which event was third in the launch sequence?"
    wrong_order = _item(
        "launch_second_event",
        score=0.77,
        text="The second event in the launch sequence was the partner review.",
    )
    exact = _item(
        "launch_third_event",
        score=0.70,
        text="The third event in the launch sequence was the customer rollout.",
    )

    reranked = _rerank(query, wrong_order, exact)
    by_id = {item.item_id: item for item in reranked}

    assert by_id["launch_third_event"].score > by_id["launch_second_event"].score
    assert _has_reason(by_id["launch_third_event"], "ordinal_sequence_exact_evidence")
    assert _has_reason(by_id["launch_second_event"], "ordinal_sequence_order_conflict")


def test_deterministic_rerank_prefers_requested_last_item_over_wrong_ordinal() -> None:
    query = "What was the last item on Alex's checklist?"
    wrong_order = _item(
        "checklist_second_item",
        score=0.77,
        text="The second item on Alex's checklist was the staging smoke test.",
    )
    exact = _item(
        "checklist_last_item",
        score=0.70,
        text="The final item on Alex's checklist was sending the rollout note.",
    )

    reranked = _rerank(query, wrong_order, exact)
    by_id = {item.item_id: item for item in reranked}

    assert by_id["checklist_last_item"].score > by_id["checklist_second_item"].score
    assert _has_reason(by_id["checklist_last_item"], "ordinal_sequence_exact_evidence")
    assert _has_reason(by_id["checklist_second_item"], "ordinal_sequence_order_conflict")


def test_deterministic_rerank_keeps_latest_conversation_temporal_path() -> None:
    query = "What was my latest call with Alex about?"
    event_note = _item(
        "latest_call",
        score=0.70,
        text="Yesterday's call with Alex covered Project Atlas migration risks.",
    )
    generic_note = _item(
        "generic_alex",
        score=0.72,
        text="Alex owns the Project Atlas renewal follow-up.",
    )

    reranked = _rerank(query, generic_note, event_note)
    by_id = {item.item_id: item for item in reranked}

    assert by_id["latest_call"].score > by_id["generic_alex"].score
    assert _has_reason(by_id["latest_call"], "conversation_recency_temporal_evidence")
    assert not _has_reason_prefix(by_id["latest_call"], "ordinal_sequence_")


def test_context_requirement_ordinal_answer_shape_still_applies() -> None:
    query = "Which tournament did Nate win fourth?"
    generic = _item(
        "generic_tournament_note",
        score=0.7,
        text="Nate won video game tournaments at charity arcade nights.",
    )
    ordinal = _item(
        "ordinal_tournament_note",
        score=0.7,
        text="Nate won his fourth video game tournament at the charity arcade night.",
    )

    boosted = apply_context_requirement_boosts(
        (generic, ordinal),
        query=query,
        query_anchor_intent=build_query_anchor_intent(query),
        max_boost=0.04,
    )

    assert boosted[1].score > boosted[0].score
    assert boosted[1].diagnostics["provenance"][
        "context_requirement_matched_answer_shapes"
    ] == ["ordinal"]


def _rerank(query: str, *items: ContextItem) -> tuple[ContextItem, ...]:
    return apply_deterministic_rerank_adjustments(
        tuple(items),
        query=query,
        plan=build_query_expansion_plan(query),
        query_anchor_intent=build_query_anchor_intent(query),
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


def _has_reason(item: ContextItem, reason: str) -> bool:
    return reason in _reasons(item)


def _has_reason_prefix(item: ContextItem, prefix: str) -> bool:
    return any(reason.startswith(prefix) for reason in _reasons(item))


def _reasons(item: ContextItem) -> tuple[str, ...]:
    provenance = item.diagnostics.get("provenance")
    if not isinstance(provenance, dict):
        return ()
    reasons = provenance.get("deterministic_rerank_reasons")
    if not isinstance(reasons, list | tuple):
        return ()
    return tuple(str(reason) for reason in reasons)
