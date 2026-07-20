"""Bounded deterministic diagnostics for a real ContextPacker selection boundary."""

from __future__ import annotations

from typing import Any

from infinity_context_core.application import context_packer as context_packer_module
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.application.normalize import estimate_tokens

_MAX_REQUESTED_EVIDENCE_REFS = 20
_MAX_TARGET_CANDIDATES = 80
_MAX_SOURCE_IDS_PER_CANDIDATE = 12
_MAX_PREVIEW_CHARS = 240


def _bounded_unique_refs(refs: tuple[str, ...]) -> tuple[str, ...]:
    bounded: list[str] = []
    for value in refs:
        ref = str(value).strip()[:120]
        if ref and ref not in bounded:
            bounded.append(ref)
        if len(bounded) >= _MAX_REQUESTED_EVIDENCE_REFS:
            break
    return tuple(bounded)


def _copy_selection_state(state: Any, *, state_type: Any) -> Any:
    return state_type(
        selected=list(state.selected),
        selected_keys=set(state.selected_keys),
        selected_answer_support_families=set(state.selected_answer_support_families),
        selected_chunks_by_source=dict(state.selected_chunks_by_source),
        selected_source_capped_items_by_source=dict(
            state.selected_source_capped_items_by_source
        ),
        selected_art_style_items_by_source_group=dict(
            state.selected_art_style_items_by_source_group
        ),
        used_tokens=state.used_tokens,
    )


def _packing_boundary_capture(
    *,
    items: tuple[ContextItem, ...],
    requested_refs: tuple[str, ...],
    token_budget: int,
    max_rendered_chars: int,
    preselection_state: Any | None,
    selection_items: tuple[ContextItem, ...],
    result: Any,
    state_type: Any,
) -> dict[str, Any]:
    budget = max(64, token_budget)
    header_chars = context_packer_module._rendered_char_count(())
    char_budget = max(header_chars, max_rendered_chars)
    normalized_items = tuple(
        context_packer_module.normalize_context_item_diagnostics(item) for item in items
    )
    ordered_items = tuple(
        sorted(normalized_items, key=context_packer_module.context_rank_key)
    )
    guarded_rank_by_key = {
        context_packer_module._selection_key(item): rank
        for rank, item in enumerate(items, start=1)
    }
    packer_rank_by_key = {
        context_packer_module._selection_key(item): rank
        for rank, item in enumerate(ordered_items, start=1)
    }
    selection_rank_by_key = {
        context_packer_module._selection_key(item): rank
        for rank, item in enumerate(selection_items, start=1)
    }
    selected_keys = {
        context_packer_module._selection_key(item) for item in result.bundle.items
    }
    decisions, replay_selected_keys = _replay_final_selection(
        selection_items=selection_items,
        preselection_state=preselection_state,
        budget=budget,
        char_budget=char_budget,
        selected_keys=selected_keys,
        state_type=state_type,
    )

    matching_items = [
        item for item in ordered_items if _matching_item_refs(item, requested_refs)
    ]
    included_items = matching_items[:_MAX_TARGET_CANDIDATES]
    candidate_rows = [
        _packing_candidate_row(
            item=item,
            requested_refs=requested_refs,
            guarded_rank=guarded_rank_by_key.get(context_packer_module._selection_key(item)),
            packer_rank=packer_rank_by_key.get(context_packer_module._selection_key(item)),
            selection_rank=selection_rank_by_key.get(context_packer_module._selection_key(item)),
            selected_keys=selected_keys,
            decision=decisions.get(context_packer_module._selection_key(item)),
            header_chars=header_chars,
        )
        for item in included_items
    ]
    selected_output_by_ref = {
        ref: [
            item.item_id
            for item in result.bundle.items
            if ref in _matching_item_refs(item, (ref,))
        ][:_MAX_TARGET_CANDIDATES]
        for ref in requested_refs
    }
    return {
        "schema_version": "locomo-ranking-to-packing-audit-v1",
        "requested_evidence_refs": list(requested_refs),
        "bounds": {
            "max_requested_evidence_refs": _MAX_REQUESTED_EVIDENCE_REFS,
            "max_target_candidates": _MAX_TARGET_CANDIDATES,
            "max_source_ids_per_candidate": _MAX_SOURCE_IDS_PER_CANDIDATE,
            "max_preview_chars": _MAX_PREVIEW_CHARS,
        },
        "guarded_item_count": len(items),
        "packer_ordered_item_count": len(ordered_items),
        "final_selection_item_count": len(selection_items),
        "preselection_item_count": (
            len(preselection_state.selected) if preselection_state is not None else None
        ),
        "selected_item_count": len(result.bundle.items),
        "token_budget": budget,
        "max_rendered_chars": char_budget,
        "rendered_chars": len(result.bundle.rendered_text),
        "used_tokens": result.bundle.token_estimate,
        "packer_drops": {
            key: value
            for key, value in result.bundle.diagnostics.items()
            if key.startswith("dropped_by_")
        },
        "matching_candidate_count": len(matching_items),
        "matching_candidates_truncated": len(matching_items) > len(included_items),
        "candidate_item_ids_by_ref": {
            ref: [row["item_id"] for row in candidate_rows if ref in row["matched_refs"]]
            for ref in requested_refs
        },
        "selected_output_item_ids_by_ref": selected_output_by_ref,
        "candidates": candidate_rows,
        "replay_matches_actual_selected_keys": replay_selected_keys == selected_keys,
    }


def _replay_final_selection(
    *,
    selection_items: tuple[ContextItem, ...],
    preselection_state: Any | None,
    budget: int,
    char_budget: int,
    selected_keys: set[tuple[str, str]],
    state_type: Any,
) -> tuple[dict[tuple[str, str], dict[str, Any]], set[tuple[str, str]]]:
    if preselection_state is None:
        return {}, set()
    state = _copy_selection_state(preselection_state, state_type=state_type)
    preselected_keys = set(state.selected_keys)
    decisions: dict[tuple[str, str], dict[str, Any]] = {}
    for item in selection_items:
        key = context_packer_module._selection_key(item)
        reason = _selection_rejection_reason(
            state,
            item=item,
            budget=budget,
            char_budget=char_budget,
        )
        if reason is not None:
            decisions.setdefault(
                key,
                _selection_decision_row(
                    state,
                    item=item,
                    reason="preselection" if key in preselected_keys else reason,
                ),
            )
            continue
        item_tokens = estimate_tokens(item.text) + 16
        decisions.setdefault(key, _selection_decision_row(state, item=item, reason="selected"))
        context_packer_module._select_item(state, item=item, item_tokens=item_tokens)
    replay_keys = {context_packer_module._selection_key(item) for item in state.selected}
    for key in selected_keys - replay_keys:
        decisions.setdefault(key, {"boundary_decision": "preselection"})
    return decisions, replay_keys


def _selection_rejection_reason(
    state: Any,
    *,
    item: ContextItem,
    budget: int,
    char_budget: int,
) -> str | None:
    key = context_packer_module._selection_key(item)
    if key in state.selected_keys:
        return "duplicate"
    family = context_packer_module._answer_support_diversity_family(item)
    if (
        family
        and family in state.selected_answer_support_families
        and not context_packer_module._adds_answer_support_source_coverage(
            state.selected,
            item=item,
            answer_support_family=family,
        )
    ):
        return "family_duplicate"
    if context_packer_module._source_cap_applies(item):
        source_key = context_packer_module._source_key(item)
        if state.selected_source_capped_items_by_source.get(source_key, 0) >= (
            context_packer_module._MAX_ITEMS_PER_SOURCE
        ):
            return "source_cap"
        source_group_cap = context_packer_module._source_group_cap(item)
        if source_group_cap is not None:
            source_group_key = context_packer_module._source_group_key(item)
            if (
                state.selected_art_style_items_by_source_group.get(source_group_key, 0)
                >= source_group_cap
            ):
                return "source_cap"
    if state.used_tokens + estimate_tokens(item.text) + 16 > budget:
        return "token_cap"
    if context_packer_module._rendered_char_count((*state.selected, item)) > char_budget:
        return "char_cap"
    return None


def _selection_decision_row(
    state: Any,
    *,
    item: ContextItem,
    reason: str,
) -> dict[str, Any]:
    rendered_before = context_packer_module._rendered_char_count(tuple(state.selected))
    rendered_after = context_packer_module._rendered_char_count((*state.selected, item))
    item_tokens = estimate_tokens(item.text) + 16
    return {
        "boundary_decision": reason,
        "first_rejection_reason": (
            reason if reason not in {"selected", "preselection"} else None
        ),
        "state_before": {
            "selected_item_count": len(state.selected),
            "used_tokens": state.used_tokens,
            "rendered_chars": rendered_before,
        },
        "projected_state": {
            "used_tokens": state.used_tokens + item_tokens,
            "rendered_chars": rendered_after,
            "incremental_rendered_chars": rendered_after - rendered_before,
        },
    }


def _packing_candidate_row(
    *,
    item: ContextItem,
    requested_refs: tuple[str, ...],
    guarded_rank: int | None,
    packer_rank: int | None,
    selection_rank: int | None,
    selected_keys: set[tuple[str, str]],
    decision: dict[str, Any] | None,
    header_chars: int,
) -> dict[str, Any]:
    selection_key = context_packer_module._selection_key(item)
    answer_family = context_packer_module._answer_support_diversity_family(item)
    diversity_family = context_packer_module._diversity_family(item)
    source_ids = [ref.source_id[:180] for ref in item.source_refs if ref.source_id]
    row: dict[str, Any] = {
        "item_id": item.item_id,
        "item_type": item.item_type,
        "matched_refs": list(_matching_item_refs(item, requested_refs)),
        "guarded_input_rank": guarded_rank,
        "pre_pack_rank": packer_rank,
        "final_selection_rank": selection_rank,
        "score": item.score,
        "selection_key": list(selection_key),
        "source_key": context_packer_module._source_key(item),
        "source_group_key": context_packer_module._source_group_key(item),
        "family_key": answer_family or diversity_family or None,
        "answer_support_family_key": answer_family or None,
        "diversity_family_key": diversity_family or None,
        "source_ids": source_ids[:_MAX_SOURCE_IDS_PER_CANDIDATE],
        "source_ids_truncated": len(source_ids) > _MAX_SOURCE_IDS_PER_CANDIDATE,
        "estimated_token_cost": estimate_tokens(item.text) + 16,
        "estimated_char_cost": max(
            0,
            context_packer_module._rendered_char_count((item,)) - header_chars,
        ),
        "selected": selection_key in selected_keys,
        "text_preview": item.text[:_MAX_PREVIEW_CHARS],
    }
    if decision is None:
        row.update(
            {
                "boundary_decision": "duplicate",
                "first_rejection_reason": "duplicate",
            }
        )
    else:
        row.update(decision)
    return row


def _matching_item_refs(item: ContextItem, refs: tuple[str, ...]) -> tuple[str, ...]:
    searchable = "\n".join(
        (
            item.text,
            *(ref.source_id or "" for ref in item.source_refs),
            *(ref.quote_preview or "" for ref in item.source_refs),
        )
    )
    return tuple(ref for ref in refs if ref in searchable)
