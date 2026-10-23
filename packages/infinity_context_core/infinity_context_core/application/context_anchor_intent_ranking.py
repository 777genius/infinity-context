"""Anchor intent ranking policy; one implementation authority."""

from __future__ import annotations

from dataclasses import replace

from infinity_context_core.application.context_diagnostics import (
    normalize_context_diagnostics,
    safe_diagnostic_mapping,
    safe_score_signals,
)
from infinity_context_core.application.context_internal_diagnostics import (
    provenance_flag_is_true as _provenance_flag_is_true,
)
from infinity_context_core.application.context_query_intent import (
    QueryAnchorIntent,
    match_query_anchor_intent_to_text,
)
from infinity_context_core.application.dto import ContextItem

_QUERY_ANCHOR_INTENT_MAX_BOOST = 0.035


def apply_query_anchor_intent_boosts(
    items: tuple[ContextItem, ...],
    *,
    intent: QueryAnchorIntent,
    max_boost: float = _QUERY_ANCHOR_INTENT_MAX_BOOST,
) -> tuple[ContextItem, ...]:
    if not items or intent.empty or max_boost <= 0:
        return items
    return tuple(
        _with_query_anchor_intent_boost(
            item,
            match=match_query_anchor_intent_to_text(intent, item.text),
            max_boost=max_boost,
        )
        for item in items
    )


def _with_query_anchor_intent_boost(
    item: ContextItem,
    *,
    match: object,
    max_boost: float,
) -> ContextItem:
    if match is None or _query_anchor_intent_already_applied(item):
        return item
    try:
        raw_boost = float(getattr(match, "score_boost", 0.0))
    except (TypeError, ValueError):
        return item
    boost = min(max_boost, max(0.0, round(raw_boost, 4)))
    if boost <= 0:
        return item
    diagnostics = normalize_context_diagnostics(item.diagnostics)
    reasons = tuple(getattr(match, "reasons", ()) or ())
    matched_keys = tuple(getattr(match, "matched_keys", ()) or ())
    diagnostics["query_anchor_intent_reason"] = "query anchor identity matched context item text"
    diagnostics["score_signals"] = {
        **safe_score_signals(diagnostics.get("score_signals")),
        "query_anchor_intent_boost": boost,
        "query_anchor_intent_reason_count": len(reasons),
        "query_anchor_intent_matched_key_count": len(matched_keys),
    }
    diagnostics["provenance"] = {
        **safe_diagnostic_mapping(diagnostics.get("provenance")),
        "query_anchor_intent_applied": True,
        "query_anchor_intent_reasons": list(reasons[:8]),
        "query_anchor_intent_matched_keys": list(matched_keys[:8]),
    }
    return replace(
        item,
        score=min(0.99, round(item.score + boost, 4)),
        diagnostics=normalize_context_diagnostics(diagnostics),
    )


def _query_anchor_intent_already_applied(item: ContextItem) -> bool:
    return _provenance_flag_is_true(item.diagnostics, "query_anchor_intent_applied")

QUERY_ANCHOR_INTENT_MAX_BOOST = _QUERY_ANCHOR_INTENT_MAX_BOOST
