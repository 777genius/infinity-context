"""Explicit context requirement ranking policy."""

from __future__ import annotations

from dataclasses import replace

from infinity_context_core.application.context_diagnostics import (
    normalize_context_diagnostics,
    normalize_context_item_diagnostics,
    safe_diagnostic_mapping,
    safe_score_signals,
)
from infinity_context_core.application.context_query_intent import QueryAnchorIntent
from infinity_context_core.application.context_requirement_coverage import (
    context_requirement_coverage,
)
from infinity_context_core.application.dto import ContextItem

CONTEXT_REQUIREMENT_MAX_BOOST = 0.04
_CONTEXT_REQUIREMENT_ANCHOR_BOOST = 0.008
_CONTEXT_REQUIREMENT_MODALITY_BOOST = 0.022
_CONTEXT_REQUIREMENT_FEATURE_BOOST = 0.014
_CONTEXT_REQUIREMENT_ANSWER_SHAPE_BOOST = 0.012
GENERIC_BOOSTABLE_ANSWER_SHAPES = frozenset((
    "causal",
    "choice",
    "commonality",
    "commitment",
    "constraint",
    "conversation_participant",
    "conversation_topic",
    "count",
    "existence",
    "gotcha",
    "inference",
    "list",
    "location",
    "ordinal",
    "preference",
    "relationship",
    "speaker",
    "summary",
    "temporal",
))


def apply_context_requirement_boosts(
    items: tuple[ContextItem, ...],
    *,
    query: str,
    query_anchor_intent: QueryAnchorIntent,
    max_boost: float = CONTEXT_REQUIREMENT_MAX_BOOST,
) -> tuple[ContextItem, ...]:
    if not items or max_boost <= 0:
        return items
    requested = context_requirement_coverage(
        query=query,
        query_anchor_intent=query_anchor_intent,
        items=(),
    )
    requested_anchor_kinds = _coverage_value_set(requested.get("requested_anchor_kinds"))
    requested_modalities = _coverage_value_set(requested.get("requested_modalities"))
    requested_features = _coverage_value_set(requested.get("requested_evidence_features"))
    requested_answer_shapes = _coverage_value_set(requested.get("requested_answer_shapes"))
    if (
        not requested_anchor_kinds
        and not requested_modalities
        and not requested_features
        and not requested_answer_shapes
    ):
        return items
    return tuple(
        _with_context_requirement_boost(
            item,
            query=query,
            query_anchor_intent=query_anchor_intent,
            requested_anchor_kinds=requested_anchor_kinds,
            requested_modalities=requested_modalities,
            requested_features=requested_features,
            requested_answer_shapes=requested_answer_shapes,
            max_boost=max_boost,
        )
        for item in items
    )


def _with_context_requirement_boost(
    item: ContextItem,
    *,
    query: str,
    query_anchor_intent: QueryAnchorIntent,
    requested_anchor_kinds: frozenset[str],
    requested_modalities: frozenset[str],
    requested_features: frozenset[str],
    requested_answer_shapes: frozenset[str],
    max_boost: float,
) -> ContextItem:
    if _context_requirement_boost_already_applied(item):
        return item
    normalized_item = normalize_context_item_diagnostics(item)
    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=query_anchor_intent,
        items=(normalized_item,),
    )
    matched_anchor_kinds = _sorted_coverage_matches(
        requested_anchor_kinds,
        coverage.get("covered_anchor_kinds"),
    )
    matched_modalities = _sorted_coverage_matches(
        requested_modalities,
        coverage.get("covered_modalities"),
    )
    matched_features = _sorted_coverage_matches(
        requested_features,
        coverage.get("covered_evidence_features"),
    )
    matched_answer_shapes = _sorted_coverage_matches(
        requested_answer_shapes,
        coverage.get("covered_answer_shapes"),
    )
    score_boosted_answer_shapes = tuple(
        shape for shape in matched_answer_shapes if shape in GENERIC_BOOSTABLE_ANSWER_SHAPES
    )
    raw_boost = (
        len(matched_anchor_kinds) * _CONTEXT_REQUIREMENT_ANCHOR_BOOST
        + len(matched_modalities) * _CONTEXT_REQUIREMENT_MODALITY_BOOST
        + len(matched_features) * _CONTEXT_REQUIREMENT_FEATURE_BOOST
        + len(score_boosted_answer_shapes) * _CONTEXT_REQUIREMENT_ANSWER_SHAPE_BOOST
    )
    boost = min(max_boost, round(raw_boost, 4))
    if boost <= 0:
        return item
    diagnostics = normalize_context_diagnostics(normalized_item.diagnostics)
    diagnostics["context_requirement_reason"] = "explicit query requirement matched item evidence"
    diagnostics["score_signals"] = {
        **safe_score_signals(diagnostics.get("score_signals")),
        "context_requirement_boost": boost,
        "context_requirement_matched_anchor_kind_count": len(matched_anchor_kinds),
        "context_requirement_matched_modality_count": len(matched_modalities),
        "context_requirement_matched_feature_count": len(matched_features),
        "context_requirement_matched_answer_shape_count": len(score_boosted_answer_shapes),
    }
    diagnostics["provenance"] = {
        **safe_diagnostic_mapping(diagnostics.get("provenance")),
        "context_requirement_boost_applied": True,
        "context_requirement_matched_anchor_kinds": list(matched_anchor_kinds),
        "context_requirement_matched_modalities": list(matched_modalities),
        "context_requirement_matched_evidence_features": list(matched_features),
        "context_requirement_matched_answer_shapes": list(matched_answer_shapes),
    }
    return replace(
        normalized_item,
        score=min(0.99, round(normalized_item.score + boost, 4)),
        diagnostics=normalize_context_diagnostics(diagnostics),
    )


def _context_requirement_boost_already_applied(item: ContextItem) -> bool:
    return _provenance_flag_is_true(item.diagnostics, "context_requirement_boost_applied")


def _coverage_value_set(value: object) -> frozenset[str]:
    if not isinstance(value, list | tuple):
        return frozenset()
    return frozenset(
        text for item in value if isinstance(item, str) and (text := item.strip().casefold())
    )


def _sorted_coverage_matches(
    requested: frozenset[str],
    covered: object,
) -> tuple[str, ...]:
    return tuple(sorted(requested & _coverage_value_set(covered)))


def _provenance_flag_is_true(diagnostics: object, flag: str) -> bool:
    normalized_diagnostics = normalize_context_diagnostics(diagnostics)
    provenance = safe_diagnostic_mapping(normalized_diagnostics.get("provenance"))
    return provenance.get(flag) is True
