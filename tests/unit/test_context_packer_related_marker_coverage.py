from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _church_activity_item(
    *,
    item_id: str,
    source_id: str | tuple[str, ...],
    text: str,
    score: float,
    source_type: str = "locomo_turn",
) -> ContextItem:
    source_ids = (source_id,) if isinstance(source_id, str) else source_id
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=tuple(
            SourceRef(
                source_type="locomo_turn",
                source_id=value,
            )
            for value in source_ids
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_aggregation_chunks"],
            "source_type": source_type,
            "score_signals": {
                "query_expansion_reason": "church_friend_activity_inventory_bridge",
                "distinctive_term_hits": 6,
            },
        },
    )


def test_context_packer_keeps_related_marker_near_selected_activity_turn() -> None:
    other_activity = _church_activity_item(
        item_id="other_church_activity",
        source_id="locomo:conv-fixture:session_24:D24:6:turn",
        text="D24:6 Maria had a picnic with friends from church.",
        score=0.995,
    )
    other_marker_coverage = _church_activity_item(
        item_id="other_marker_coverage",
        source_id=(
            "locomo:conv-fixture:session_24:D24:5:turn",
            "locomo:conv-fixture:session_24:D24:7:turn",
            "locomo:conv-fixture:session_24:D24:8:turn",
        ),
        text=(
            "D24:5 John mentioned a nearby event. Related turns: D24:6.\n"
            "D24:7 John discussed another nearby detail. Related turns: D24:6.\n"
            "D24:8 Maria reacted to the picnic with church friends."
        ),
        score=0.9,
        source_type="locomo_observation",
    )
    activity = _church_activity_item(
        item_id="church_activity",
        source_id="locomo:conv-fixture:session_28:D28:8:turn",
        text=(
            "D28:8 Maria did community work with friends from church and "
            "said it was super rewarding."
        ),
        score=0.99,
    )
    nearby_marker_coverage = _church_activity_item(
        item_id="nearby_marker_coverage",
        source_id=(
            "locomo:conv-fixture:session_28:D28:5:turn",
            "locomo:conv-fixture:session_28:D28:7:turn",
        ),
        text=(
            "D28:5 John found a job at a tech company that needed mechanical "
            "skills. Related turns: D28:7 D28:8.\n"
            "D28:7 John said he would update Maria soon.\n"
            "D28:8 Maria did community work with friends from church."
        ),
        score=0.82,
        source_type="locomo_observation",
    )
    distractors = tuple(
        _church_activity_item(
            item_id=f"activity_noise_{index}",
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:1:turn",
            text=(
                f"D{index}:1 Maria mentioned a generic activity with friends "
                "and community work."
            ),
            score=0.98 - index * 0.001,
        )
        for index in range(1, 8)
    )

    result = ContextPacker().pack(
        bundle_id="ctx_related_marker_coverage",
        items=(
            *distractors,
            other_activity,
            other_marker_coverage,
            activity,
            nearby_marker_coverage,
        ),
        token_budget=1200,
        query="What activities has Maria done with her church friends?",
    )

    selected_source_ids = {
        ref.source_id for item in result.bundle.items for ref in item.source_refs
    }
    selected_related_marker_source_ids = {
        ref.source_id
        for item in result.bundle.items
        if ":related_marker:" in item.item_id
        for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_28:D28:8:turn" in selected_source_ids
    assert "locomo:conv-fixture:session_28:D28:5:turn" in selected_source_ids
    assert (
        "locomo:conv-fixture:session_28:D28:5:turn"
        in selected_related_marker_source_ids
    )
    assert (
        "locomo:conv-fixture:session_28:D28:7:turn"
        not in selected_related_marker_source_ids
    )
