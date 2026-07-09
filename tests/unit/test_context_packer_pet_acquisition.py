from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _pet_acquisition_item(
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
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "score_signals": {
                "query_expansion_reason": "pet_acquisition_date_bridge",
                "source_sibling_answer_evidence": 1,
                "distinctive_term_hits": distinctive_term_hits,
            },
        },
    )


def test_context_packer_keeps_pet_gift_date_anchor_when_name_is_later() -> None:
    filler_items = tuple(
        _pet_acquisition_item(
            item_id=f"pet_temporal_filler_{index}",
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:1:turn",
            text=(
                f"session_{index} turn D{index}:1\n"
                f"session_{index} date: yesterday\n"
                f"D{index}:1 Sam and Dana talked about pets and family plans."
            ),
            score=0.99 - index * 0.001,
            distinctive_term_hits=10,
        )
        for index in range(1, 10)
    )
    date_anchor = _pet_acquisition_item(
        item_id="direct_pet_gift_date_anchor",
        source_id="locomo:conv-fixture:session_20:D20:2:turn",
        text=(
            "session_20 turn D20:2\n"
            "session_20 date: 2:01 pm on 21 October, 2022\n"
            "D20:2 Sam: Look here, I got this new pup for you!\n"
            "image caption: a stuffed animal dog on a blanket\n"
            "visual query: stuffed dog blanket toy"
        ),
        score=0.88,
    )
    later_named_pet_turn = _pet_acquisition_item(
        item_id="later_named_pet_turn",
        source_id="locomo:conv-fixture:session_24:D24:4:turn",
        text=(
            "session_24 turn D24:4\n"
            "session_24 date: 8:15 pm on 3 November, 2022\n"
            "D24:4 Dana: The stuffed animal dog you gave me is named Pippa."
        ),
        score=0.98,
        distinctive_term_hits=9,
    )

    result = ContextPacker().pack(
        bundle_id="ctx_pet_gift_name_later",
        items=(*filler_items, later_named_pet_turn, date_anchor),
        token_budget=3500,
        query="When did Sam get Pippa for Dana?",
    )

    selected_source_ids = {
        ref.source_id for item in result.bundle.items for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_20:D20:2:turn" in selected_source_ids
    assert "locomo:conv-fixture:session_24:D24:4:turn" in selected_source_ids
