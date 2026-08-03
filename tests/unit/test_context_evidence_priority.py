from dataclasses import replace

from infinity_context_core.application.context_evidence_priority import (
    apply_context_evidence_priority,
    has_unresolved_rerank_rejection,
)
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_precise_temporal_evidence import (
    with_precise_temporal_evidence_contracts,
)
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


def test_verified_exact_projection_is_not_vetoed_by_generic_subject_mismatch() -> None:
    projected = _item(
        "verified-projection",
        score=0.8,
        source_id="source-projection",
    )
    diagnostics = dict(projected.diagnostics or {})
    diagnostics["score_signals"] = {
        **diagnostics["score_signals"],
        "distinct_set_projection_verified": 1,
        "keyword_aggregation_distinct_member_support": 1,
    }
    diagnostics["provenance"] = {
        "distinct_set_projection_verified": True,
        "deterministic_rerank_applied": True,
        "deterministic_rerank_reasons": ["aggregation_subject_mismatch"],
    }
    projected = replace(projected, diagnostics=diagnostics)

    assert has_unresolved_rerank_rejection(projected) is False
    prioritized, diagnostics = apply_context_evidence_priority((projected,))
    assert prioritized[0].score == 0.99
    assert diagnostics["evidence_priority_items_prioritized"] == 1


def test_verified_exact_projection_does_not_override_a_real_anchor_conflict() -> None:
    projected = _item(
        "conflicting-projection",
        score=0.8,
        source_id="source-conflict",
    )
    diagnostics = dict(projected.diagnostics or {})
    diagnostics["score_signals"] = {
        **diagnostics["score_signals"],
        "distinct_set_projection_verified": 1,
        "keyword_aggregation_distinct_member_support": 1,
    }
    diagnostics["provenance"] = {
        "distinct_set_projection_verified": True,
        "deterministic_rerank_applied": True,
        "deterministic_rerank_reasons": ["query_anchor_conflict"],
    }
    projected = replace(projected, diagnostics=diagnostics)

    assert has_unresolved_rerank_rejection(projected) is True
    prioritized, diagnostics = apply_context_evidence_priority((projected,))
    assert prioritized[0].score == 0.8
    assert diagnostics["evidence_priority_items_prioritized"] == 0


def test_precise_temporal_contract_respects_source_diversity_and_eight_slot_cap() -> None:
    candidates = tuple(
        _temporal_item(
            f"temporal-{index}",
            source_id=f"locomo:fixture:session_{index}:D{index}:6:turn",
            score=0.8 - index * 0.01,
        )
        for index in range(10)
    )
    shared_source = _temporal_item(
        "temporal-shared-source",
        source_id="locomo:fixture:session_0:D0:6:turn",
        score=0.79,
    )

    contracted = with_precise_temporal_evidence_contracts(
        (*candidates, shared_source),
        query="When did Andrew adopt Scout?",
    )
    prioritized, diagnostics = apply_context_evidence_priority(contracted)

    prioritized_items = tuple(item for item in prioritized if _priority(item) == 1)
    assert len(prioritized_items) == 8
    assert (
        sum(
            item.source_refs[0].source_id == "locomo:fixture:session_0:D0:6:turn"
            for item in prioritized_items
        )
        == 1
    )
    assert diagnostics["evidence_priority_items_eligible"] == 11
    assert diagnostics["evidence_priority_items_prioritized"] == 8
    assert diagnostics["evidence_priority_item_limit"] == 8


def test_precise_temporal_contract_never_overrides_wrong_object_mismatch() -> None:
    wrong_object = _temporal_item(
        "wrong-object",
        source_id="locomo:fixture:session_9:D9:4:turn",
        score=0.8,
    )
    diagnostics = dict(wrong_object.diagnostics or {})
    diagnostics["provenance"] = {
        "deterministic_rerank_reasons": [
            "relation_requirement_object_mismatch",
            "temporal_answer_evidence",
        ],
    }
    wrong_object = replace(wrong_object, diagnostics=diagnostics)

    contracted = with_precise_temporal_evidence_contracts(
        (wrong_object,),
        query="When did Andrew adopt Scout?",
    )
    prioritized, priority_diagnostics = apply_context_evidence_priority(contracted)

    signals = contracted[0].diagnostics["score_signals"]
    assert "precise_temporal_answer_evidence" not in signals
    assert has_unresolved_rerank_rejection(contracted[0]) is True
    assert _priority(prioritized[0]) is None
    assert priority_diagnostics["evidence_priority_items_prioritized"] == 0


def _temporal_item(item_id: str, *, source_id: str, score: float) -> ContextItem:
    return ContextItem(
        item_id=item_id,
        item_type="chunk",
        text=(
            "session_9 date: 9:02 am on 22 November, 2023\n"
            "D9:6 Andrew: I adopted another dog the other day. "
            "image query: puppy Scout new bundle of joy."
        ),
        score=score,
        source_refs=(SourceRef(source_type="locomo_turn", source_id=source_id),),
        diagnostics={
            "query_expansion_reason": "pet_acquisition_date_bridge",
            "score_signals": {
                "query_expansion_reason": "pet_acquisition_date_bridge",
                "distinctive_term_hits": 8,
                "unique_term_hits": 9,
            },
            "provenance": {
                "deterministic_rerank_reasons": [
                    "relation_requirement_missing_relation",
                    "temporal_answer_evidence",
                ],
            },
        },
    )


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
