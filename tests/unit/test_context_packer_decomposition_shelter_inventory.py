from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _inventory_item(
    *,
    item_id: str,
    source_id: str,
    text: str,
    score: float,
    distinctive_term_hits: int = 5,
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
                "query_expansion_reason": "decomposition_inventory_list",
                "distinctive_term_hits": distinctive_term_hits,
            },
        },
    )


def test_context_packer_keeps_repeated_direct_shelter_anchors() -> None:
    unrelated_inventory = tuple(
        _inventory_item(
            item_id=f"inventory_noise_{index}",
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:1:turn",
            text=(
                f"D{index}:1 Jordan mentioned an unrelated inventory detail "
                "about a dessert, a community event, and a local place."
            ),
            score=0.99 - index * 0.001,
            distinctive_term_hits=9,
        )
        for index in range(1, 8)
    )
    car_donation_shelter = _inventory_item(
        item_id="car_donation_shelter",
        source_id="locomo:conv-fixture:session_8:D8:1:turn",
        text=(
            "D8:1 Jordan donated an old car to a homeless shelter where "
            "Jordan volunteers every week."
        ),
        score=0.72,
    )
    talks_shelter = _inventory_item(
        item_id="talks_shelter",
        source_id="locomo:conv-fixture:session_11:D11:10:turn",
        text=(
            "D11:10 Jordan recently gave a few talks at the homeless shelter "
            "where Jordan volunteers and received compliments from volunteers."
        ),
        score=0.71,
    )

    result = ContextPacker().pack(
        bundle_id="ctx_decomposition_shelter_inventory",
        items=(*unrelated_inventory, car_donation_shelter, talks_shelter),
        token_budget=1200,
        query="What shelters does Jordan volunteer at?",
    )

    selected_source_ids = {
        ref.source_id for item in result.bundle.items for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_8:D8:1:turn" in selected_source_ids
    assert "locomo:conv-fixture:session_11:D11:10:turn" in selected_source_ids
