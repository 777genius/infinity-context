from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _event_item(
    *,
    item_id: str,
    source_id: str,
    text: str,
    score: float,
    visual_reference: bool = False,
) -> ContextItem:
    score_signals: dict[str, object] = {
        "query_expansion_reason": "transgender_youth_center_event_bridge",
        "distinctive_term_hits": 5,
    }
    if visual_reference:
        score_signals["source_sibling_dialogue_visual_reference"] = 1
        score_signals["source_sibling_answer_evidence"] = 1
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
            "score_signals": score_signals,
        },
    )


def test_context_packer_keeps_youth_center_event_visual_reference_turn() -> None:
    distractors = tuple(
        _event_item(
            item_id=f"event_noise_{index}",
            source_id=f"locomo:conv-fixture:session_{index}:D{index}:1:turn",
            text=(
                f"D{index}:1 Jordan talked generally about transgender events, "
                "advocacy, community, and supportive people."
            ),
            score=0.99 - index * 0.001,
        )
        for index in range(1, 8)
    )
    visual_event_reference = _event_item(
        item_id="youth_center_band_reference",
        source_id="locomo:conv-fixture:session_15:D15:13:turn",
        text="D15:13 Jordan: Wow! Did you see that band?",
        score=0.72,
        visual_reference=True,
    )

    result = ContextPacker().pack(
        bundle_id="ctx_youth_center_event_visual",
        items=(*distractors, visual_event_reference),
        token_budget=1200,
        query="What transgender-specific events has Jordan attended?",
    )

    selected_source_ids = {
        ref.source_id for item in result.bundle.items for ref in item.source_refs
    }
    assert "locomo:conv-fixture:session_15:D15:13:turn" in selected_source_ids
