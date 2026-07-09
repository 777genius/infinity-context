from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _cause_item(
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
                "query_expansion_reason": "cause_event_inventory_bridge",
                "distinctive_term_hits": distinctive_term_hits,
            },
        },
    )


def test_context_packer_keeps_distinct_cause_event_evidence() -> None:
    noise = tuple(
        _cause_item(
            item_id=f"cause_noise_{index}",
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:1:turn",
            text=(
                f"D{index}:1 Jordan talked about a generic community event "
                "and said it was meaningful."
            ),
            score=0.99 - index * 0.001,
            distinctive_term_hits=8,
        )
        for index in range(1, 8)
    )
    shelter_toy_drive = _cause_item(
        item_id="shelter_toy_drive",
        source_id="locomo:conv-fixture:session_8:D8:5:turn",
        text=(
            "D8:5 Jordan held events at a homeless shelter to give out food "
            "and supplies, and organized a toy drive for kids in need."
        ),
        score=0.83,
    )
    food_drive = _cause_item(
        item_id="food_drive",
        source_id="locomo:conv-fixture:session_9:D9:12:turn",
        text=(
            "D9:12 Jordan started a community food drive after seeing the "
            "effect unemployment had on neighbors."
        ),
        score=0.82,
    )
    domestic_abuse = _cause_item(
        item_id="domestic_abuse",
        source_id="locomo:conv-fixture:session_10:D10:4:turn",
        text=(
            "D10:4 Jordan worked with a local organization that helps victims "
            "of domestic abuse and raised awareness at the event."
        ),
        score=0.81,
    )

    result = ContextPacker().pack(
        bundle_id="ctx_cause_event_inventory",
        items=(*noise, shelter_toy_drive, food_drive, domestic_abuse),
        token_budget=1800,
        query="What causes has Jordan done events for?",
    )

    selected_source_ids = {
        ref.source_id for item in result.bundle.items for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_8:D8:5:turn" in selected_source_ids
    assert "locomo:conv-fixture:session_9:D9:12:turn" in selected_source_ids
    assert "locomo:conv-fixture:session_10:D10:4:turn" in selected_source_ids


def test_context_packer_promotes_exact_cause_event_turn_slots() -> None:
    generic_events = tuple(
        _cause_item(
            item_id=f"generic_event_{index}",
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:2:turn",
            text=(
                f"D{index}:2 Jordan talked about community events, causes, "
                "neighbors, support, and making a difference in general terms."
            ),
            score=0.99 - index * 0.001,
            distinctive_term_hits=10,
        )
        for index in range(1, 10)
    )
    shelter_toy_drive = _cause_item(
        item_id="exact_shelter_toy_drive",
        source_id="locomo:conv-fixture:session_20:D20:5:turn",
        text=(
            "D20:5 Jordan held events at a homeless shelter to give out food "
            "and supplies, and organized a toy drive for kids in need."
        ),
        score=0.65,
    )
    shelter_food_supplies = _cause_item(
        item_id="exact_shelter_food_supplies",
        source_id="locomo:conv-fixture:session_23:D23:5:turn",
        text=(
            "D23:5 Jordan held events with an online group and went to a "
            "homeless shelter to give out food and supplies."
        ),
        score=0.645,
    )
    food_drive = _cause_item(
        item_id="exact_food_drive",
        source_id="locomo:conv-fixture:session_21:D21:12:turn",
        text=(
            "D21:12 Jordan saw unemployment hurting neighbors and started a "
            "community food drive to help out during tough times."
        ),
        score=0.64,
    )
    domestic_abuse = _cause_item(
        item_id="exact_domestic_abuse",
        source_id="locomo:conv-fixture:session_22:D22:10:turn",
        text=(
            "D22:10 Jordan worked with a local organization that helps victims "
            "of domestic abuse and raised awareness and funds at the event."
        ),
        score=0.63,
    )

    result = ContextPacker().pack(
        bundle_id="ctx_exact_cause_event_inventory",
        items=(
            *generic_events,
            shelter_toy_drive,
            shelter_food_supplies,
            food_drive,
            domestic_abuse,
        ),
        token_budget=1200,
        query="What causes has Jordan done events for?",
    )

    selected_source_ids = {
        ref.source_id for item in result.bundle.items for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_20:D20:5:turn" in selected_source_ids
    assert "locomo:conv-fixture:session_23:D23:5:turn" in selected_source_ids
    assert "locomo:conv-fixture:session_21:D21:12:turn" in selected_source_ids
    assert "locomo:conv-fixture:session_22:D22:10:turn" in selected_source_ids
