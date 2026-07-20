"""Requirement guard policy for context candidate bundles."""

from __future__ import annotations

import re

from infinity_context_core.application.context_diagnostics import diagnostic_retrieval_sources
from infinity_context_core.application.context_distinct_set_evidence import (
    project_distinct_set_evidence,
)
from infinity_context_core.application.context_food_inventory_exact_turns import (
    food_inventory_answer_support_applies,
    food_inventory_answer_support_rank,
    food_inventory_role_alignment_rank,
)
from infinity_context_core.application.context_packer_answer_support_patterns import (
    _RECOGNITION_CERTIFICATE_QUERY_RE,
    _RECOGNITION_CERTIFICATE_VISUAL_ANSWER_RE,
)
from infinity_context_core.application.context_query_intent import QueryAnchorIntent
from infinity_context_core.application.context_requirement_coverage import (
    context_requirement_coverage,
)
from infinity_context_core.application.context_source_sibling_answer_evidence_repair import (
    _score_signal_truthy,
)
from infinity_context_core.application.context_source_sibling_place_evidence import (
    country_destination_answer_support_rank,
)
from infinity_context_core.application.dto import ContextItem

_TEMPORAL_SOURCE_SIBLING_SUPPORT_RE = re.compile(
    r"\b(?:"
    r"yesterday|tomorrow|last\s+(?:night|week|month|year|mon(?:day)?|tue(?:sday)?|"
    r"wed(?:nesday)?|thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)|"
    r"next\s+(?:week|month|year|mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|"
    r"thu(?:rsday)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)|"
    r"(?:one|two|three|four|five|six|seven|\d+)\s+days?\s+ago|"
    r"(?:one|two|three|four|five|six|seven|\d+)\s+weeks?\s+ago"
    r")\b",
    re.IGNORECASE,
)

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
_ACTIVITY_COMPANION_QUERY_RE = re.compile(
    r"\bwho\b(?=.{0,140}\b(?:with|alongside|together)\b)"
    r"(?=.{0,200}\b(?:go|went|attend(?:ed|ing)?|join(?:ed|ing)?|"
    r"start(?:ed|ing)?|try|tried|trying|class(?:es)?|lesson|practice|"
    r"camp(?:ed|ing)?|hik(?:e|ed|ing)|travel(?:ed|led|ing)?|trip|"
    r"visit(?:ed|ing)?|yoga|workout|exercise)\b)",
    re.IGNORECASE | re.DOTALL,
)
_ACTIVITY_COMPANION_ACTIVITY_RE = re.compile(
    r"\b(?:yoga|class(?:es)?|lesson|practice|workout|exercise|fitness|"
    r"training|kickboxing|taekwondo|boxing|running|hiking|camping|trip)\b",
    re.IGNORECASE,
)
_ACTIVITY_COMPANION_WITH_RE = re.compile(
    r"\b(?:with|alongside|together\s+with|joined\s+by|accompanied\s+by)\b"
    r".{0,90}\b(?:(?:my|his|her|their|our|a|an|the)\s+|"
    r"one\s+of\s+(?:my|his|her|their|our)\s+)?"
    r"(?:family|kids?|children|friends?|parents?|partner|spouse|team|group|"
    r"colleagues?|co-?workers?|workmates?|classmates?|teammates?|neighbou?rs?)\b|"
    r"\b(?:(?:my|his|her|their|our)\s+)?"
    r"(?:colleagues?|co-?workers?|workmates?|friends?|classmates?|teammates?|"
    r"neighbou?rs?)\b(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39})?"
    r".{0,90}\binvited\b.{0,120}\b(?:me|him|her|them|us)?\s*(?:to|for)\b|"
    r"\binvited\b.{0,120}\b(?:to|for)\b.{0,160}\bby\s+"
    r"(?:(?:my|his|her|their|our)\s+)?"
    r"(?:colleagues?|co-?workers?|workmates?|friends?|classmates?|teammates?|"
    r"neighbou?rs?)\b",
    re.IGNORECASE | re.DOTALL,
)
_CONTENT_TOKEN_RE = re.compile(r"[^\W_]{3,}", re.UNICODE)
_COUNT_SOURCE_SIBLING_QUERY_STOP_TERMS = frozenset(
    {
        "are",
        "count",
        "did",
        "does",
        "for",
        "had",
        "has",
        "have",
        "her",
        "him",
        "his",
        "how",
        "many",
        "much",
        "number",
        "she",
        "the",
        "their",
        "them",
        "they",
        "times",
        "total",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)


def _provenance(diagnostics: dict[str, object]) -> dict[str, object]:
    value = diagnostics.get("provenance")
    return dict(value) if isinstance(value, dict) else {}


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
    if (
        "project" in requested_anchor_kinds
        and "project" in missing_anchor_kinds
        and _requires_explicit_project_anchor(query_anchor_intent)
    ):
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
    kept_items = tuple(
        item
        for item in items
        if not _has_relation_requirement_mismatch(item, query=query)
        or _is_precise_list_source_sibling_answer_support(
            item,
            requested_answer_shapes=requested_answer_shapes,
        )
        or _is_precise_food_inventory_exact_turn_support(
            item,
            query=query,
            requested_answer_shapes=requested_answer_shapes,
        )
        or _is_precise_country_destination_source_sibling_answer_support(
            item,
            query=query,
        )
        or _is_precise_temporal_source_sibling_answer_support(
            item,
            requested_answer_shapes=requested_answer_shapes,
        )
        or _is_precise_count_source_sibling_answer_support(
            item,
            requested_answer_shapes=requested_answer_shapes,
            query=query,
        )
        or _is_precise_activity_companion_source_sibling_answer_support(
            item,
            query=query,
        )
        or _is_precise_visual_certificate_source_sibling_answer_support(
            item,
            query=query,
        )
    )
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


def _requires_explicit_project_anchor(query_anchor_intent: QueryAnchorIntent) -> bool:
    return any(
        hint.kind.value == "project" and hint.reason != "known project/tool reference"
        for hint in query_anchor_intent.hints
    )


def _has_object_kind_mismatch(item: ContextItem) -> bool:
    reasons = _deterministic_rerank_reasons(item)
    return (
        _OBJECT_KIND_MISMATCH_RERANK_REASON in reasons
        and _OBJECT_KIND_MATCH_RERANK_REASON not in reasons
    )


def _has_relation_requirement_mismatch(item: ContextItem, *, query: str) -> bool:
    reasons = _deterministic_rerank_reasons(item)
    projection_covers_missing_relation = (
        "relation_requirement_missing_relation" in reasons
        and "relation_requirement_object_mismatch" not in reasons
        and project_distinct_set_evidence(query=query, text=item.text).present
    )
    return (
        bool(_RELATION_REQUIREMENT_MISMATCH_RERANK_REASONS.intersection(reasons))
        and _RELATION_REQUIREMENT_MATCH_RERANK_REASON not in reasons
        and not _RELATION_REQUIREMENT_SUPPORT_RERANK_REASONS.intersection(reasons)
        and not projection_covers_missing_relation
    )


def _is_precise_list_source_sibling_answer_support(
    item: ContextItem,
    *,
    requested_answer_shapes: set[str],
) -> bool:
    if "list" not in requested_answer_shapes:
        return False
    if "keyword_source_sibling_chunks" not in diagnostic_retrieval_sources(item.diagnostics):
        return False
    if not any(str(ref.source_id).casefold().endswith(":turn") for ref in item.source_refs):
        return False
    if _score_signal_truthy(item, "source_sibling_answer_evidence"):
        return True
    score_signals = item.diagnostics.get("score_signals") if item.diagnostics else None
    if not isinstance(score_signals, dict):
        return False
    return (
        _numeric_score_signal(score_signals.get("query_expansion_reason_priority")) >= 3
        and _numeric_score_signal(score_signals.get("distinctive_term_hits")) >= 4
        and _numeric_score_signal(score_signals.get("unique_term_hits")) >= 4
    )


def _is_precise_food_inventory_exact_turn_support(
    item: ContextItem,
    *,
    query: str,
    requested_answer_shapes: set[str],
) -> bool:
    del requested_answer_shapes
    if not query:
        return False
    query_reason = _item_query_reason(item)
    if not food_inventory_answer_support_applies(query=query, query_reason=query_reason):
        return False
    if not any(str(ref.source_id).casefold().endswith(":turn") for ref in item.source_refs):
        return False
    if food_inventory_role_alignment_rank(
        text=item.text,
        query=query,
        query_reason=query_reason,
    ) > 1:
        return False
    return (
        food_inventory_answer_support_rank(
            text=item.text,
            query=query,
            query_reason=query_reason,
            has_exact_turn=True,
        )
        <= 1
    )


def _is_precise_country_destination_source_sibling_answer_support(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    if not query:
        return False
    if "keyword_source_sibling_chunks" not in diagnostic_retrieval_sources(item.diagnostics):
        return False
    if not any(str(ref.source_id).casefold().endswith(":turn") for ref in item.source_refs):
        return False
    if not _score_signal_truthy(item, "source_sibling_answer_evidence"):
        return False
    return (
        country_destination_answer_support_rank(
            expansion_query=query,
            text=item.text,
            has_exact_turn=True,
        )
        == 0
    )


def _item_query_reason(item: ContextItem) -> str:
    diagnostics = item.diagnostics or {}
    reason = str(diagnostics.get("query_expansion_reason") or "")
    if reason:
        return reason
    score_signals = diagnostics.get("score_signals")
    if isinstance(score_signals, dict):
        return str(score_signals.get("query_expansion_reason") or "")
    return ""


def _is_precise_temporal_source_sibling_answer_support(
    item: ContextItem,
    *,
    requested_answer_shapes: set[str],
) -> bool:
    if not {"temporal", "when"}.intersection(requested_answer_shapes):
        return False
    if "keyword_source_sibling_chunks" not in diagnostic_retrieval_sources(item.diagnostics):
        return False
    if not any(str(ref.source_id).casefold().endswith(":turn") for ref in item.source_refs):
        return False
    if _score_signal_truthy(item, "source_sibling_answer_evidence"):
        return True
    if _TEMPORAL_SOURCE_SIBLING_SUPPORT_RE.search(item.text) is None:
        return False
    score_signals = item.diagnostics.get("score_signals") if item.diagnostics else None
    if not isinstance(score_signals, dict):
        return False
    return (
        _numeric_score_signal(score_signals.get("distinctive_term_hits")) >= 2
        or _numeric_score_signal(score_signals.get("unique_term_hits")) >= 2
        or _numeric_score_signal(score_signals.get("source_sibling_closeness")) >= 3
    )


def _is_precise_count_source_sibling_answer_support(
    item: ContextItem,
    *,
    requested_answer_shapes: set[str],
    query: str,
) -> bool:
    if "count" not in requested_answer_shapes:
        return False
    if "keyword_source_sibling_chunks" not in diagnostic_retrieval_sources(item.diagnostics):
        return False
    if not any(str(ref.source_id).casefold().endswith(":turn") for ref in item.source_refs):
        return False
    if not (
        _score_signal_truthy(item, "source_sibling_answer_evidence")
        or _has_strong_count_source_sibling_signals(item)
    ):
        return False
    return _count_query_object_overlap(query, item.text) >= 2


def _has_strong_count_source_sibling_signals(item: ContextItem) -> bool:
    score_signals = item.diagnostics.get("score_signals") if item.diagnostics else None
    if not isinstance(score_signals, dict):
        return False
    return (
        _numeric_score_signal(score_signals.get("query_expansion_reason_priority")) >= 3
        and _numeric_score_signal(score_signals.get("distinctive_term_hits")) >= 3
        and _numeric_score_signal(score_signals.get("unique_term_hits")) >= 3
    )


def _count_query_object_overlap(query: str, text: str) -> int:
    query_terms = _count_source_sibling_content_terms(query)
    if not query_terms:
        return 0
    text_terms = _count_source_sibling_content_terms(text)
    return len(query_terms.intersection(text_terms))


def _count_source_sibling_content_terms(text: str) -> frozenset[str]:
    terms: set[str] = set()
    for token in _CONTENT_TOKEN_RE.findall(text.casefold()):
        term = _normalized_count_source_sibling_term(token)
        if term and term not in _COUNT_SOURCE_SIBLING_QUERY_STOP_TERMS:
            terms.add(term)
    return frozenset(terms)


def _normalized_count_source_sibling_term(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _is_precise_activity_companion_source_sibling_answer_support(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    if _ACTIVITY_COMPANION_QUERY_RE.search(query) is None:
        return False
    if "keyword_source_sibling_chunks" not in diagnostic_retrieval_sources(item.diagnostics):
        return False
    if not any(str(ref.source_id).casefold().endswith(":turn") for ref in item.source_refs):
        return False
    return (
        _score_signal_truthy(item, "source_sibling_answer_evidence")
        and _ACTIVITY_COMPANION_ACTIVITY_RE.search(item.text) is not None
        and _ACTIVITY_COMPANION_WITH_RE.search(item.text) is not None
    )


def _is_precise_visual_certificate_source_sibling_answer_support(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    if _RECOGNITION_CERTIFICATE_QUERY_RE.search(query) is None:
        return False
    if "keyword_source_sibling_chunks" not in diagnostic_retrieval_sources(item.diagnostics):
        return False
    if not any(str(ref.source_id).casefold().endswith(":turn") for ref in item.source_refs):
        return False
    return (
        _score_signal_truthy(item, "source_sibling_answer_evidence")
        and _RECOGNITION_CERTIFICATE_VISUAL_ANSWER_RE.search(item.text) is not None
    )


def _numeric_score_signal(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _has_explicit_answer_shape_missing(item: ContextItem) -> bool:
    return _ANSWER_SHAPE_MISSING_RERANK_REASON in _deterministic_rerank_reasons(item)


def _deterministic_rerank_reasons(item: ContextItem) -> frozenset[str]:
    provenance = _provenance(dict(item.diagnostics or {}))
    raw_reasons = provenance.get("deterministic_rerank_reasons")
    if not isinstance(raw_reasons, list | tuple):
        return frozenset()
    return frozenset(str(reason) for reason in raw_reasons if isinstance(reason, str))

def _coverage_strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str) and item)
