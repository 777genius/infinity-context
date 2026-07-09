from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _movie_seen_item(
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
                "query_expansion_reason": "commonality_interest_bridge",
                "distinctive_term_hits": distinctive_term_hits,
            },
        },
    )


def test_context_packer_prefers_watched_movie_title_turns_over_question_prompts() -> None:
    question_fillers = tuple(
        _movie_seen_item(
            item_id=f"movie_question_filler_{index}",
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:1:turn",
            text=f"D{index}:1 Dana: Seen any good movies lately?",
            score=0.99 - index * 0.001,
            distinctive_term_hits=8,
        )
        for index in range(1, 10)
    )
    first_seen = _movie_seen_item(
        item_id="first_watched_title",
        source_id="locomo:conv-fixture:session_20:D20:1:turn",
        text='D20:1 Dana: I watched "Moon Garden" last night and loved the story.',
        score=0.85,
    )
    second_seen = _movie_seen_item(
        item_id="second_watched_title",
        source_id="locomo:conv-fixture:session_21:D21:8:turn",
        text='D21:8 Sam: I watched "Moon Garden" recently; the acting was great.',
        score=0.84,
    )

    result = ContextPacker().pack(
        bundle_id="ctx_movie_seen_titles",
        items=(*question_fillers, first_seen, second_seen),
        token_budget=2200,
        query="What movies have both Sam and Dana seen?",
    )

    selected_source_ids = {
        ref.source_id for item in result.bundle.items for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_20:D20:1:turn" in selected_source_ids
    assert "locomo:conv-fixture:session_21:D21:8:turn" in selected_source_ids
