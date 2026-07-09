from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _action_role_item(
    *,
    item_id: str,
    source_ids: tuple[str, ...],
    text: str,
    score: float,
    distinctive_term_hits: int = 6,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=tuple(
            SourceRef(source_type="locomo", source_id=source_id)
            for source_id in source_ids
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "decomposition_action_role",
                "distinctive_term_hits": distinctive_term_hits,
            },
        },
    )


def test_context_packer_keeps_gift_joy_observation_anchor_source_group() -> None:
    filler_items = tuple(
        _action_role_item(
            item_id=f"joy_only_filler_{index}",
            source_ids=(
                f"locomo:conv-fixture:session_{index}",
                f"locomo:conv-fixture:session_{index}:D{index}:8:turn",
            ),
            text=(
                f"D{index}:8 Dana talked about something that brings joy and "
                "helps her focus, but nobody described a gift object."
            ),
            score=0.99 - index * 0.001,
            distinctive_term_hits=9,
        )
        for index in range(1, 9)
    )
    gift_observation = _action_role_item(
        item_id="gift_joy_observation",
        source_ids=(
            "locomo:conv-fixture:session_20:observation",
            "locomo:conv-fixture:session_20:D20:2:turn",
            "locomo:conv-fixture:session_20:D20:4:turn",
            "locomo:conv-fixture:session_20:D20:8:turn",
        ),
        text=(
            "D20:2 Dana opened the conversation after finishing a recipe. "
            "Related turns: D20:4. "
            "D20:4 Dana has a stuffed animal dog named Pippa that was a gift "
            "from Sam. Related turns: D20:8. "
            "D20:8 Pippa brings Dana so much joy and helps her focus."
        ),
        score=0.86,
    )

    result = ContextPacker().pack(
        bundle_id="ctx_gift_joy_observation_anchor",
        items=(*filler_items, gift_observation),
        token_budget=2600,
        query="What is something Sam gave to Dana that brings her a lot of joy?",
    )

    selected_source_ids = {
        ref.source_id for item in result.bundle.items for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_20:D20:2:turn" in selected_source_ids
