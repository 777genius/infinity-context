from infinity_context_core.application.context_evidence_priority import (
    apply_context_evidence_priority,
)
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_instruction_candidates_do_not_consume_the_eight_priority_slots() -> None:
    instruction = _item(
        "embedded-instruction",
        score=1.0,
        source_id="source-instruction",
        is_instruction=True,
    )
    safe_items = tuple(
        _item(
            f"safe-{index}",
            score=0.98 - index * 0.01,
            source_id=f"source-safe-{index}",
        )
        for index in range(8)
    )

    prioritized, diagnostics = apply_context_evidence_priority((instruction, *safe_items))

    assert _priority(instruction) is None
    assert (
        _priority(next(item for item in prioritized if item.item_id == instruction.item_id)) is None
    )
    assert all(
        _priority(next(item for item in prioritized if item.item_id == safe.item_id)) == 1
        for safe in safe_items
    )
    assert diagnostics["evidence_priority_items_eligible"] == 8
    assert diagnostics["evidence_priority_items_prioritized"] == 8
    assert diagnostics["evidence_priority_item_limit"] == 8

    packed = ContextPacker().pack(
        bundle_id="ctx-instruction-aware-priority",
        items=prioritized,
        token_budget=2000,
    )
    assert instruction.item_id not in {item.item_id for item in packed.bundle.items}
    assert {item.item_id for item in safe_items}.issubset(
        {item.item_id for item in packed.bundle.items}
    )


def test_duplicate_canonical_sources_cannot_starve_a_distinct_ninth_candidate() -> None:
    mirrored = tuple(
        _item(
            f"mirror-{index}",
            score=0.98 - index * 0.01,
            source_id="source-shared",
            chunk_id=f"chunk-shared-{index}",
        )
        for index in range(8)
    )
    distinct_ninth = _item(
        "distinct-ninth",
        score=0.7,
        source_id="source-distinct",
    )

    first, first_diagnostics = apply_context_evidence_priority((*mirrored, distinct_ninth))
    second, second_diagnostics = apply_context_evidence_priority(
        tuple(reversed((*mirrored, distinct_ninth)))
    )

    assert _prioritized_ids(first) == {"mirror-0", "distinct-ninth"}
    assert _prioritized_ids(second) == _prioritized_ids(first)
    assert first_diagnostics["evidence_priority_items_eligible"] == 9
    assert first_diagnostics["evidence_priority_items_prioritized"] == 2
    assert second_diagnostics == first_diagnostics
    assert next(item for item in first if item.item_id == "distinct-ninth").score == 0.99


def _item(
    item_id: str,
    *,
    score: float,
    source_id: str,
    chunk_id: str | None = None,
    is_instruction: bool = False,
) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=f"Bounded evidence candidate {item_id}.",
        score=score,
        source_refs=(
            SourceRef(
                source_type="synthetic",
                source_id=source_id,
                chunk_id=chunk_id or f"chunk-{item_id}",
            ),
        ),
        is_instruction=is_instruction,
        diagnostics={
            "memory_scope_id": "scope-priority",
            "score_signals": {"application_evidence_contract_tier": 1},
        },
    )


def _priority(item: ContextItem) -> object:
    diagnostics = item.diagnostics or {}
    signals = diagnostics.get("score_signals")
    return signals.get("application_evidence_priority") if isinstance(signals, dict) else None


def _prioritized_ids(items: tuple[ContextItem, ...]) -> set[str]:
    return {item.item_id for item in items if _priority(item) == 1}
