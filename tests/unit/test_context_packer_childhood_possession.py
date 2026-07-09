from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _childhood_item(
    *,
    item_id: str,
    source_id: str,
    text: str,
    score: float,
    distinctive_term_hits: int = 6,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id=source_id,
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_chunks"],
            "score_signals": {
                "query_expansion_reason": "childhood_possession_inventory_bridge",
                "distinctive_term_hits": distinctive_term_hits,
            },
        },
    )


def test_context_packer_prefers_direct_childhood_possession_turns() -> None:
    noise = tuple(
        _childhood_item(
            item_id=f"childhood_noise_{index}",
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:2:turn",
            text=(
                f"D{index}:2 Jordan talked about childhood memories and how "
                "important family support felt."
            ),
            score=0.99 - index * 0.001,
            distinctive_term_hits=8,
        )
        for index in range(1, 9)
    )
    doll = _childhood_item(
        item_id="doll",
        source_id="locomo:conv-fixture:session_10:D10:13:turn",
        text=(
            "D10:13 Jordan said it reminded him of his childhood because he "
            "had a little doll like this as a kid."
        ),
        score=0.82,
    )
    camera = _childhood_item(
        item_id="camera",
        source_id="locomo:conv-fixture:session_11:D11:15:turn",
        text=(
            "D11:15 Jordan said nature reminded him of the film camera he "
            "used to have as a kid."
        ),
        score=0.81,
    )

    result = ContextPacker().pack(
        bundle_id="ctx_childhood_possession",
        items=(*noise, doll, camera),
        token_budget=1600,
        query="What items did Jordan mention having as a child?",
    )

    selected_source_ids = {
        ref.source_id for item in result.bundle.items for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_10:D10:13:turn" in selected_source_ids
    assert "locomo:conv-fixture:session_11:D11:15:turn" in selected_source_ids
