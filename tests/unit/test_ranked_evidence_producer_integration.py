from __future__ import annotations

import pytest
from infinity_context_core.application.context_diagnostics import (
    normalize_context_bundle_diagnostics,
)
from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import BuildContextQuery, ContextItem
from infinity_context_core.application.use_cases.build_context_final_packing import (
    pack_final_context_items,
)
from infinity_context_core.domain.entities import SourceRef

_RANKED_DIAGNOSTIC_KEYS = (
    "ranked_evidence_candidate_count",
    "ranked_evidence_projection_candidate_count",
    "ranked_evidence_selectable_candidate_count",
    "ranked_evidence_eligible_candidate_count",
    "ranked_evidence_returned_count",
    "ranked_evidence_compact_projection_count",
    "ranked_evidence_source_diversity_count",
    "ranked_evidence_budget_drop_count",
    "ranked_evidence_item_budget_drop_count",
    "ranked_evidence_token_budget_drop_count",
    "ranked_evidence_char_budget_drop_count",
    "ranked_evidence_instruction_drop_count",
    "ranked_evidence_unsafe_source_drop_count",
    "ranked_evidence_source_dedupe_drop_count",
    "ranked_evidence_temporal_interval_reservation_count",
)


class _Ids:
    def new_id(self, prefix: str) -> str:
        return f"{prefix}-fixed"


def _query(**overrides: object) -> BuildContextQuery:
    values: dict[str, object] = {
        "space_id": "space-1",
        "memory_scope_ids": ("scope-1",),
        "query": "What happened?",
        "token_budget": 1_000,
        "max_rendered_chars": 10_000,
    }
    values.update(overrides)
    return BuildContextQuery(**values)


def _item(index: int) -> ContextItem:
    return ContextItem(
        item_id=f"item-{index}",
        item_type="chunk",
        text=f"D1:{index} Riley: evidence {index}",
        score=1.0 - index / 100,
        source_refs=(
            SourceRef(
                source_type="episode",
                source_id=f"session:D1:{index}",
            ),
        ),
    )


def test_prompt_context_mode_preserves_existing_packer_result() -> None:
    query = _query(selection_item_limit=1)
    items = (_item(1), _item(2))

    expected = ContextPacker().pack(
        bundle_id="ctx-fixed",
        items=items,
        token_budget=query.token_budget,
        query=query.query,
        max_rendered_chars=query.max_rendered_chars,
    )

    assert pack_final_context_items(
        packer=ContextPacker(),
        ids=_Ids(),
        query=query,
        items=items,
    ) == expected


def test_ranked_evidence_mode_uses_explicit_item_limit_and_emits_all_counters() -> None:
    result = pack_final_context_items(
        packer=ContextPacker(),
        ids=_Ids(),
        query=_query(
            selection_mode="ranked_evidence",
            selection_item_limit=1,
        ),
        items=(_item(1), _item(2)),
    )

    assert result.bundle.bundle_id == "ctx-fixed"
    assert [item.item_id for item in result.bundle.items] == ["item-1"]
    assert result.bundle.rendered_text == "D1:1 Riley: evidence 1"
    assert result.dropped_count == 1
    assert set(_RANKED_DIAGNOSTIC_KEYS) <= result.bundle.diagnostics.keys()


def test_unknown_selection_mode_fails_closed_before_generating_a_bundle_id() -> None:
    class _UnexpectedIds:
        def new_id(self, prefix: str) -> str:
            raise AssertionError(f"unexpected id generation for {prefix}")

    with pytest.raises(ValueError, match="Unsupported context selection mode: unknown"):
        pack_final_context_items(
            packer=ContextPacker(),
            ids=_UnexpectedIds(),
            query=_query(selection_mode="unknown"),
            items=(),
        )


def test_ranked_diagnostics_survive_core_normalization_before_public_truncation() -> None:
    result = pack_final_context_items(
        packer=ContextPacker(),
        ids=_Ids(),
        query=_query(
            selection_mode="ranked_evidence",
            selection_item_limit=1,
        ),
        items=(_item(1), _item(2)),
    )
    raw_diagnostics = {
        **{f"noise_{index}": index for index in range(600)},
        **result.bundle.diagnostics,
    }

    normalized = normalize_context_bundle_diagnostics(
        raw_diagnostics,
        items=result.bundle.items,
    )

    assert normalized["diagnostics_truncated"] is True
    assert {
        key: normalized[key] for key in _RANKED_DIAGNOSTIC_KEYS
    } == {
        key: result.bundle.diagnostics[key] for key in _RANKED_DIAGNOSTIC_KEYS
    }
