"""Select the final context rendering policy after shared ranking."""

from __future__ import annotations

from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.context_packer_selection import PackResult
from infinity_context_core.application.context_ranked_evidence_selection import (
    RankedEvidenceBudget,
    select_ranked_evidence,
)
from infinity_context_core.application.dto import BuildContextQuery, ContextItem
from infinity_context_core.ports.ids import IdGeneratorPort

_PROMPT_CONTEXT_MODE = "prompt_context"
_RANKED_EVIDENCE_MODE = "ranked_evidence"


def pack_final_context_items(
    *,
    packer: ContextPacker,
    ids: IdGeneratorPort,
    query: BuildContextQuery,
    items: tuple[ContextItem, ...],
) -> PackResult:
    """Pack ranked candidates for the explicitly requested consumer mode."""

    if query.selection_mode == _PROMPT_CONTEXT_MODE:
        return packer.pack(
            bundle_id=ids.new_id("ctx"),
            items=items,
            token_budget=query.token_budget,
            query=query.query,
            max_rendered_chars=query.max_rendered_chars,
        )
    if query.selection_mode != _RANKED_EVIDENCE_MODE:
        raise ValueError(f"Unsupported context selection mode: {query.selection_mode}")

    item_limit = (
        query.selection_item_limit
        if query.selection_item_limit is not None
        else query.max_evidence_items
    )
    selection = select_ranked_evidence(
        bundle_id=ids.new_id("ctx"),
        items=items,
        query=query.query,
        budget=RankedEvidenceBudget(
            max_items=item_limit,
            max_tokens=query.token_budget,
            max_chars=query.max_rendered_chars,
        ),
    )
    return PackResult(
        bundle=selection.bundle,
        dropped_count=selection.dropped_count,
    )


__all__ = ("pack_final_context_items",)
