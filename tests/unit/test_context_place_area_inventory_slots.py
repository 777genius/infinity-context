from infinity_context_core.application.context_packer_answer_support import (
    _answer_support_diversity_candidates,
    _answer_support_diversity_family,
    _ordered_answer_support_families_for_query,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_place_area_inventory_keeps_concrete_state_slots_distinct() -> None:
    query = "What states has Maria vacationed at?"
    california = _place_area_item(
        "california",
        "D1:1 Maria went on a vacation in California with her family.",
    )
    texas = _place_area_item(
        "texas",
        "D2:1 Maria took a road trip to Texas during spring break.",
    )
    new_york = _place_area_item(
        "new_york",
        "D3:1 Maria visited New York for a long weekend.",
    )
    florida = _place_area_item(
        "florida",
        "D4:1 Maria has a picture from a vacation in Florida.",
    )
    oregon = _place_area_item(
        "oregon",
        "D5:1 Maria went on a road trip to Oregon when she was younger.",
    )
    shelter_noise = _place_area_item(
        "shelter_noise",
        "D6:1 Maria went to a homeless shelter to volunteer.",
    )

    candidates = _answer_support_diversity_candidates(
        [shelter_noise, new_york, texas, california, oregon, florida],
        query=query,
    )
    ordered = _ordered_answer_support_families_for_query(candidates, query=query)
    ordered_item_ids = [candidates[family].item_id for family in ordered]
    families = {
        _answer_support_diversity_family(item)
        for item in (california, texas, new_york, florida, oregon)
    }

    assert any(":state-california" in family for family in families)
    assert any(":state-texas" in family for family in families)
    assert any(":state-new-york" in family for family in families)
    assert set(ordered_item_ids[:5]) == {
        "california",
        "texas",
        "new_york",
        "florida",
        "oregon",
    }
    assert ordered_item_ids[-1] == "shelter_noise"


def _place_area_item(item_id: str, text: str) -> ContextItem:
    marker = text.split(" ", 1)[0]
    session = marker.split(":", 1)[0].removeprefix("D")
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=0.9,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id=f"locomo:conv-fixture:session_{session}:{marker}:turn",
            ),
        ),
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "score_signals": {"query_expansion_reason": "decomposition_inventory_list"},
        },
    )
