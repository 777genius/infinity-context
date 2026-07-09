from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _submission_item(
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
                "query_expansion_reason": "creative_work_submission_bridge",
                "distinctive_term_hits": distinctive_term_hits,
            },
        },
    )


def test_context_packer_keeps_work_submission_destinations() -> None:
    filler_items = tuple(
        _submission_item(
            item_id=f"submission_noise_{index}",
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:4:turn",
            text=f"D{index}:4 Dana talked about work and recent writing progress.",
            score=0.99 - index * 0.001,
            distinctive_term_hits=8,
        )
        for index in range(1, 9)
    )
    festival_submission = _submission_item(
        item_id="festival_submission",
        source_id="locomo:conv-fixture:session_2:D2:7:turn",
        text=(
            "D2:7 Dana will submit the project to film festivals so producers "
            "and directors can check it out."
        ),
        score=0.85,
    )
    contest_submission = _submission_item(
        item_id="contest_submission",
        source_id="locomo:conv-fixture:session_16:D16:1:turn",
        text="D16:1 Dana submitted a recent screenplay to a film contest.",
        score=0.84,
    )

    result = ContextPacker().pack(
        bundle_id="ctx_work_submission_destinations",
        items=(*filler_items, festival_submission, contest_submission),
        token_budget=2200,
        query="What places has Dana submitted her work to?",
    )

    selected_source_ids = {
        ref.source_id for item in result.bundle.items for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_2:D2:7:turn" in selected_source_ids
    assert "locomo:conv-fixture:session_16:D16:1:turn" in selected_source_ids
