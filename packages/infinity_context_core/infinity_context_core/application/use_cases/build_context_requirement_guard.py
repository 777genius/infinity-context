"""Requirement guard and final trim policies for build-context."""

from __future__ import annotations

from infinity_context_core.application.context_diagnostics import diagnostic_retrieval_sources
from infinity_context_core.application.context_query_intent import QueryAnchorIntent
from infinity_context_core.application.context_requirement_coverage import (
    context_requirement_coverage,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.application.use_cases.build_context_item_projection import _provenance

_OBJECT_KIND_MISMATCH_RERANK_REASON = "object_kind_species_mismatch"
_OBJECT_KIND_MATCH_RERANK_REASON = "object_kind_match"
_RELATION_REQUIREMENT_MISMATCH_RERANK_REASONS = frozenset(
    {
        "relation_requirement_missing_relation",
        "relation_requirement_object_mismatch",
    }
)
_RELATION_REQUIREMENT_MATCH_RERANK_REASON = "relation_requirement_match"
_RELATION_REQUIREMENT_SUPPORT_RERANK_REASONS = frozenset(
    {
        "cause_awareness_exact_evidence",
        "inventory_list_exact_evidence",
    }
)
_ANSWER_SHAPE_MISSING_RERANK_REASON = "explicit_answer_shape_missing"


def _apply_explicit_requirement_guard(
    *,
    query: str,
    query_anchor_intent: QueryAnchorIntent,
    items: tuple[ContextItem, ...],
) -> tuple[tuple[ContextItem, ...], dict[str, object]]:
    coverage = context_requirement_coverage(
        query=query,
        query_anchor_intent=query_anchor_intent,
        items=items,
    )
    requested_anchor_kinds = set(_coverage_strings(coverage.get("requested_anchor_kinds")))
    missing_anchor_kinds = set(_coverage_strings(coverage.get("missing_anchor_kinds")))
    requested_answer_shapes = set(_coverage_strings(coverage.get("requested_answer_shapes")))
    missing_answer_shapes = set(_coverage_strings(coverage.get("missing_answer_shapes")))
    diagnostics: dict[str, object] = {
        "requirement_guard_items_considered": len(items),
        "requirement_guard_items_dropped": 0,
        "requirement_guard_object_kind_mismatch_drop_count": 0,
        "requirement_guard_relation_mismatch_drop_count": 0,
        "requirement_guard_count_answer_shape_missing_drop_count": 0,
    }
    if "project" in requested_anchor_kinds and "project" in missing_anchor_kinds:
        diagnostics.update(
            {
                "requirement_guard_status": "dropped_missing_project_anchor",
                "requirement_guard_items_dropped": len(items),
            }
        )
        return (), diagnostics
    kept_items = tuple(item for item in items if not _has_object_kind_mismatch(item))
    object_kind_mismatch_drop_count = len(items) - len(kept_items)
    if object_kind_mismatch_drop_count > 0:
        diagnostics["requirement_guard_items_dropped"] = object_kind_mismatch_drop_count
        diagnostics["requirement_guard_object_kind_mismatch_drop_count"] = (
            object_kind_mismatch_drop_count
        )
        diagnostics["requirement_guard_status"] = (
            "dropped_object_kind_mismatch" if not kept_items else "filtered_object_kind_mismatch"
        )
        return kept_items, diagnostics
    kept_items = tuple(item for item in items if not _has_relation_requirement_mismatch(item))
    relation_mismatch_drop_count = len(items) - len(kept_items)
    if relation_mismatch_drop_count > 0:
        diagnostics["requirement_guard_items_dropped"] = relation_mismatch_drop_count
        diagnostics["requirement_guard_relation_mismatch_drop_count"] = (
            relation_mismatch_drop_count
        )
        diagnostics["requirement_guard_status"] = (
            "dropped_relation_requirement_mismatch"
            if not kept_items
            else "filtered_relation_requirement_mismatch"
        )
        return kept_items, diagnostics
    if "count" in requested_answer_shapes and "count" in missing_answer_shapes:
        count_shape_missing_items = tuple(
            item for item in items if _has_explicit_answer_shape_missing(item)
        )
        if len(count_shape_missing_items) == len(items):
            diagnostics["requirement_guard_items_dropped"] = len(items)
            diagnostics["requirement_guard_count_answer_shape_missing_drop_count"] = len(items)
            diagnostics["requirement_guard_status"] = "dropped_missing_count_answer_shape"
            return (), diagnostics
    diagnostics["requirement_guard_status"] = "satisfied"
    return items, diagnostics


def _has_object_kind_mismatch(item: ContextItem) -> bool:
    reasons = _deterministic_rerank_reasons(item)
    return (
        _OBJECT_KIND_MISMATCH_RERANK_REASON in reasons
        and _OBJECT_KIND_MATCH_RERANK_REASON not in reasons
    )


def _has_relation_requirement_mismatch(item: ContextItem) -> bool:
    reasons = _deterministic_rerank_reasons(item)
    return (
        bool(_RELATION_REQUIREMENT_MISMATCH_RERANK_REASONS.intersection(reasons))
        and _RELATION_REQUIREMENT_MATCH_RERANK_REASON not in reasons
        and not _RELATION_REQUIREMENT_SUPPORT_RERANK_REASONS.intersection(reasons)
    )


def _has_explicit_answer_shape_missing(item: ContextItem) -> bool:
    return _ANSWER_SHAPE_MISSING_RERANK_REASON in _deterministic_rerank_reasons(item)


def _deterministic_rerank_reasons(item: ContextItem) -> frozenset[str]:
    provenance = _provenance(dict(item.diagnostics or {}))
    raw_reasons = provenance.get("deterministic_rerank_reasons")
    if not isinstance(raw_reasons, list | tuple):
        return frozenset()
    return frozenset(str(reason) for reason in raw_reasons if isinstance(reason, str))


def _trim_primary_fact_items(
    items: tuple[ContextItem, ...],
    *,
    max_facts: int,
) -> tuple[ContextItem, ...]:
    if max_facts <= 0:
        return tuple(item for item in items if not _is_primary_postgres_fact_item(item))
    primary_fact_count = 0
    selected: list[ContextItem] = []
    for item in items:
        if not _is_primary_postgres_fact_item(item):
            selected.append(item)
            continue
        if primary_fact_count >= max_facts:
            continue
        primary_fact_count += 1
        selected.append(item)
    return tuple(selected)


def _is_primary_postgres_fact_item(item: ContextItem) -> bool:
    return item.item_type == "fact" and diagnostic_retrieval_sources(item.diagnostics) == (
        "postgres_facts",
    )


def _coverage_strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str) and item)
