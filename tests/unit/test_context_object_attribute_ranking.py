from infinity_context_core.application.context_query_expansion import (
    build_query_expansion_plan,
)
from infinity_context_core.application.context_query_intent import (
    build_query_anchor_intent,
)
from infinity_context_core.application.context_ranking import (
    apply_deterministic_rerank_adjustments,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_deterministic_rerank_prefers_locally_grounded_object_attribute() -> None:
    query = "What color is Maya's backpack?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    person_attribute_noise = _item(
        "maya_red_dress",
        score=0.9,
        text=(
            "D4:7 Maya: I picked a red dress for the reunion and packed my "
            "tickets in the side pocket."
        ),
    )
    local_object_attribute = _item(
        "maya_red_backpack",
        score=0.82,
        text=(
            "D4:6 Maya: I finally bought the red hiking backpack for the "
            "summer field trip."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (person_attribute_noise, local_object_attribute),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    by_id = {item.item_id: item for item in reranked}
    assert by_id["maya_red_backpack"].score > by_id["maya_red_dress"].score
    assert "object_attribute_local_evidence" in _rerank_reasons(
        by_id["maya_red_backpack"]
    )
    assert "object_attribute_person_attribute_noise" in _rerank_reasons(
        by_id["maya_red_dress"]
    )


def test_deterministic_rerank_prefers_local_model_for_named_object() -> None:
    query = "What model is Jordan's car?"
    plan = build_query_expansion_plan(query)
    intent = build_query_anchor_intent(query)
    person_model_noise = _item(
        "jordan_role_model",
        score=0.88,
        text="D8:3 Jordan: My coach is the role model who got me into engineering.",
    )
    local_object_attribute = _item(
        "jordan_car_model",
        score=0.82,
        text=(
            "D8:2 Jordan: My project car is a Subaru Forester, and I'm "
            "restoring the engine this month."
        ),
    )

    reranked = apply_deterministic_rerank_adjustments(
        (person_model_noise, local_object_attribute),
        query=query,
        plan=plan,
        query_anchor_intent=intent,
    )

    by_id = {item.item_id: item for item in reranked}
    assert by_id["jordan_car_model"].score > by_id["jordan_role_model"].score
    assert "object_attribute_local_evidence" in _rerank_reasons(
        by_id["jordan_car_model"]
    )


def _item(item_id: str, *, score: float, text: str) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(
            SourceRef(source_type="locomo_turn", source_id=f"conv:{item_id}"),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_chunks"],
        },
    )


def _rerank_reasons(item: ContextItem) -> tuple[str, ...]:
    provenance = item.diagnostics.get("provenance", {})
    if not isinstance(provenance, dict):
        return ()
    reasons = provenance.get("deterministic_rerank_reasons", ())
    if not isinstance(reasons, list):
        return ()
    return tuple(str(reason) for reason in reasons)
