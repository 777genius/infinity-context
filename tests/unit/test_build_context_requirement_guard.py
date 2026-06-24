from infinity_context_core.application.context_query_intent import build_query_anchor_intent
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.application.use_cases.build_context import (
    _apply_explicit_requirement_guard,
)
from infinity_context_core.domain.entities import SourceRef


def test_requirement_guard_drops_object_kind_mismatch_evidence() -> None:
    item = _item(
        "cat_note",
        "I mentioned my cat Luna during the call.",
        deterministic_reasons=("object_kind_species_mismatch",),
    )

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query="What hamster did I mention?",
        query_anchor_intent=build_query_anchor_intent("What hamster did I mention?"),
        items=(item,),
    )

    assert guarded_items == ()
    assert diagnostics["requirement_guard_status"] == "dropped_object_kind_mismatch"
    assert diagnostics["requirement_guard_items_dropped"] == 1
    assert diagnostics["requirement_guard_object_kind_mismatch_drop_count"] == 1


def test_requirement_guard_keeps_object_kind_match_evidence() -> None:
    item = _item(
        "hamster_note",
        "I mentioned my hamster Pip during the call.",
        deterministic_reasons=("object_kind_match",),
    )

    guarded_items, diagnostics = _apply_explicit_requirement_guard(
        query="What hamster did I mention?",
        query_anchor_intent=build_query_anchor_intent("What hamster did I mention?"),
        items=(item,),
    )

    assert guarded_items == (item,)
    assert diagnostics["requirement_guard_status"] == "satisfied"
    assert diagnostics["requirement_guard_items_dropped"] == 0


def _item(
    item_id: str,
    text: str,
    *,
    deterministic_reasons: tuple[str, ...],
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=text,
        score=0.7,
        source_refs=(SourceRef(source_type="document", source_id="doc"),),
        diagnostics={
            "retrieval_source": "keyword_chunks",
            "retrieval_sources": ["keyword_chunks"],
            "provenance": {
                "deterministic_rerank_reasons": list(deterministic_reasons),
            },
        },
    )
