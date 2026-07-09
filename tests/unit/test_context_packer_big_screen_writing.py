from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _screenplay_count_item(
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
                "query_expansion_reason": "screenplay_count_bridge",
                "distinctive_term_hits": distinctive_term_hits,
            },
        },
    )


def test_context_packer_keeps_big_screen_writing_turns_for_count_query() -> None:
    filler_items = tuple(
        _screenplay_count_item(
            item_id=f"writing_context_{index}",
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:6:turn",
            text=(
                f"D{index}:6 Dana is writing another script and hopes it "
                "gets finished someday."
            ),
            score=0.99 - index * 0.001,
            distinctive_term_hits=8,
        )
        for index in range(1, 9)
    )
    first_big_screen = _screenplay_count_item(
        item_id="first_big_screen",
        source_id="locomo:conv-fixture:session_15:D15:1:turn",
        text=(
            "D15:1 Dana wrote a few bits for a screenplay that appeared "
            "on the big screen yesterday."
        ),
        score=0.84,
    )
    second_big_screen = _screenplay_count_item(
        item_id="second_big_screen",
        source_id="locomo:conv-fixture:session_25:D25:2:turn",
        text=(
            "D25:2 Another movie script Dana contributed to was shown on "
            "the big screen for the first time."
        ),
        score=0.83,
    )

    result = ContextPacker().pack(
        bundle_id="ctx_big_screen_writing_count",
        items=(*filler_items, first_big_screen, second_big_screen),
        token_budget=2200,
        query="How many of Dana's writing projects made it to the big screen?",
    )

    selected_source_ids = {
        ref.source_id for item in result.bundle.items for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_15:D15:1:turn" in selected_source_ids
    assert "locomo:conv-fixture:session_25:D25:2:turn" in selected_source_ids
