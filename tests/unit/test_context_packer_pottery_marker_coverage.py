from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def _pottery_item(
    *,
    item_id: str,
    text: str,
    source_refs: tuple[SourceRef, ...],
    score: float = 0.99,
    source_type: str = "locomo_turn",
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=source_refs,
        diagnostics={
            "memory_scope_id": "memory_scope_default",
            "retrieval_sources": ["keyword_source_sibling_chunks"],
            "source_type": source_type,
            "score_signals": {"query_expansion_reason": "pottery_type_bridge"},
        },
    )


def test_context_packer_keeps_compact_pottery_marker_companion_under_char_cap() -> None:
    inventory = _pottery_item(
        item_id="pottery_bowl_inventory",
        text="D12:1 Riley made a ceramic bowl in pottery class.",
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_12:D12:1:turn",
                chunk_id="pottery_bowl_inventory",
            ),
        ),
    )
    marker_coverage = _pottery_item(
        item_id="pottery_marker_coverage",
        text=(
            "D12:8 Riley finished another pottery project that was a source "
            "of happiness. Related turns: D12:1 D12:2. "
            + ("long context " * 35)
            + "D12:14 Riley appreciates the friendship too and says Morgan "
            "has always been there."
        ),
        source_refs=(
            SourceRef(
                source_type="locomo_observation",
                source_id="locomo:conv-fixture:session_12:observation",
                chunk_id="pottery_marker_coverage",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_12:D12:8:turn",
                chunk_id="pottery_marker_coverage",
            ),
            SourceRef(
                source_type="locomo_turn",
                source_id="locomo:conv-fixture:session_12:D12:14:turn",
                chunk_id="pottery_marker_coverage",
            ),
        ),
        score=0.91,
        source_type="locomo_observation",
    )

    result = ContextPacker().pack(
        bundle_id="ctx_pottery_marker_coverage_companion",
        items=(inventory, marker_coverage),
        token_budget=1000,
        query="What types of pottery has Riley made?",
        max_rendered_chars=1100,
    )

    selected_related_marker_source_ids = {
        ref.source_id
        for item in result.bundle.items
        if ":related_marker:" in item.item_id
        for ref in item.source_refs
    }
    rendered = result.bundle.rendered_text

    assert "D12:1" in rendered
    assert "D12:14" in rendered
    assert "long context long context" not in rendered
    assert (
        "locomo:conv-fixture:session_12:D12:14:turn"
        in selected_related_marker_source_ids
    )
