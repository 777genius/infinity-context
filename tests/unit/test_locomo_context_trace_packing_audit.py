from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef

from scripts.locomo_context_trace import _PackingBoundaryTracer


def test_packing_boundary_trace_replays_actual_char_cap_decision_without_behavior_change() -> None:
    items = (
        _item(
            item_id="higher-ranked",
            score=0.99,
            source_id="source-higher",
            text="Higher-ranked evidence. " + "x" * 280,
        ),
        _item(
            item_id="museum-target",
            score=0.80,
            source_id="locomo:test:session_6:D6:4:turn",
            text="D6:4 Melanie went to the museum with her children. " + "y" * 280,
        ),
        _item(
            item_id="swimming-target",
            score=0.70,
            source_id="locomo:test:session_1:D1:18:turn",
            text="D1:18 Melanie went swimming with the kids. " + "z" * 280,
        ),
    )
    expected = ContextPacker().pack(
        bundle_id="ctx-audit-test",
        items=items,
        token_budget=4000,
        max_rendered_chars=650,
    )
    tracer = _PackingBoundaryTracer(
        ContextPacker(),
        requested_refs=("D6:4", "D1:18"),
    )

    actual = tracer.pack(
        bundle_id="ctx-audit-test",
        items=items,
        token_budget=4000,
        max_rendered_chars=650,
    )

    assert actual == expected
    assert tracer.capture is not None
    assert tracer.capture["guarded_item_count"] == 3
    assert tracer.capture["candidate_item_ids_by_ref"] == {
        "D6:4": ["museum-target"],
        "D1:18": ["swimming-target"],
    }
    candidates = {row["item_id"]: row for row in tracer.capture["candidates"]}
    for item_id, rank in (("museum-target", 2), ("swimming-target", 3)):
        row = candidates[item_id]
        assert row["guarded_input_rank"] == rank
        assert row["pre_pack_rank"] == rank
        assert row["score"] == items[rank - 1].score
        assert row["selection_key"] == ["chunk", item_id]
        assert row["source_key"].endswith(items[rank - 1].source_refs[0].source_id)
        assert row["estimated_token_cost"] > 16
        assert row["estimated_char_cost"] > 0
        assert row["selected"] is False
        assert row["boundary_decision"] == "char_cap"
        assert row["first_rejection_reason"] == "char_cap"
        assert row["projected_state"]["rendered_chars"] > 650
    assert tracer.capture["replay_matches_actual_selected_keys"] is True


def _item(*, item_id: str, score: float, source_id: str, text: str) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=score,
        source_refs=(
            SourceRef(
                source_type="locomo_turn",
                source_id=source_id,
                chunk_id=f"chunk-{item_id}",
            ),
        ),
        diagnostics={"memory_scope_id": "scope-audit"},
    )
