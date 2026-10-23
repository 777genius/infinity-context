"""Temporal eligibility, date-anchor and source-span answer evidence."""

from __future__ import annotations

import re

from infinity_context_core.application.context_packer_answer_support_patterns import (
    _DEGREE_COMPLETION_TEMPORAL_QUERY_RE,
    _PET_ACQUISITION_DATE_ANCHOR_SUPPORT_RE,
    _PET_ACQUISITION_OBJECT_ANCHOR_RE,
    _QUERY_OBJECT_TOKEN_RE,
    _TEMPORAL_ANSWER_SUPPORT_QUERY_RE,
    _TEMPORAL_ANSWER_SUPPORT_REASONS,
    _TEMPORAL_DIRECT_ANSWER_RE,
    _TEMPORAL_QUERY_OBJECT_STOPWORDS,
)
from infinity_context_core.application.context_packer_answer_support_slots import (
    _business_commonality_answer_slot,
    _degree_policy_answer_slot,
    _inventory_answer_slot,
    _is_community_participation_reason,
)
from infinity_context_core.application.context_packer_answer_support_utils import (
    _answer_support_exact_query_object_hits,
    _answer_support_query_reason,
    _diagnostic_score_signals,
    _diversity_family_base,
    _has_any_exact_turn_source_ref,
    _has_primary_exact_turn_source_ref,
    _numeric_signal,
)
from infinity_context_core.application.dto import ContextItem


def _is_exact_temporal_query_object_family(
    family: str,
    *,
    item: ContextItem,
    query: str,
) -> bool:
    query_reason = _answer_support_query_reason(item)
    base = _diversity_family_base(family)
    if _is_degree_completion_temporal_answer_support_item(item, query=query):
        return True
    if (
        base
        in {
            "query_reason_source_group",
            "query_reason_activity_slot_source_group",
            "query_reason_inventory_slot_source_group",
        }
        and _answer_support_exact_query_object_hits(item, query=query) > 0
        and _has_any_exact_turn_source_ref(item)
    ):
        return True
    return (
        _TEMPORAL_ANSWER_SUPPORT_QUERY_RE.search(query) is not None
        and base in {
            "temporal_source_sibling_marker",
            "temporal_source_sibling_marker_source_group",
            "query_reason_source_group",
        }
        and _temporal_answer_support_query_object_hits(
            item,
            query=query,
            query_reason=query_reason,
        )
        > 0
        and _has_any_exact_turn_source_ref(item)
    )

def _is_degree_completion_temporal_answer_support_item(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    if not query:
        return False
    if _DEGREE_COMPLETION_TEMPORAL_QUERY_RE.search(query) is None:
        return False
    if _answer_support_query_reason(item) != "degree_policy_inference_bridge":
        return False
    if _degree_policy_answer_slot(item.text) != "degree_completion_context":
        return False
    return _has_any_exact_turn_source_ref(item)

def _degree_completion_temporal_answer_support_rank(
    item: ContextItem,
    *,
    query: str,
) -> int:
    return 0 if _is_degree_completion_temporal_answer_support_item(item, query=query) else 1

def _pet_acquisition_date_anchor_answer_support_rank(
    item: ContextItem,
    *,
    query_reason: str,
) -> int:
    return 0 if _is_pet_acquisition_date_anchor_answer_support_item(item) else 1

def _is_pet_acquisition_date_anchor_answer_support_item(item: ContextItem) -> bool:
    query_reason = _answer_support_query_reason(item)
    text = item.text
    signals = _diagnostic_score_signals(item)
    signal_reason = str(signals.get("query_expansion_reason") or "").strip()
    if (
        query_reason == "pet_acquisition_date_bridge"
        and _numeric_signal(signals.get("exact_source_repair_date_anchor")) > 0
        and _is_temporal_answer_support_item(item, query_reason=query_reason)
    ):
        return True
    if (
        query_reason == "pet_acquisition_date_bridge"
        and _is_temporal_answer_support_item(item, query_reason=query_reason)
        and _PET_ACQUISITION_DATE_ANCHOR_SUPPORT_RE.search(text) is not None
    ):
        return True
    return (
        query_reason in {"pet_acquisition_date_bridge", "decomposition_temporal_answer"}
        and (
            signal_reason == "pet_acquisition_date_bridge"
            or _PET_ACQUISITION_OBJECT_ANCHOR_RE.search(text) is not None
        )
        and _is_temporal_answer_support_item(item, query_reason=query_reason)
        and _PET_ACQUISITION_DATE_ANCHOR_SUPPORT_RE.search(text) is not None
    )

def _temporal_answer_support_source_span_rank(item: ContextItem, *, query_reason: str) -> int:
    if not _is_temporal_answer_support_item(item, query_reason=query_reason):
        return 0
    if _has_primary_exact_turn_source_ref(item) and len(item.source_refs) == 1:
        return 0
    if _has_primary_exact_turn_source_ref(item):
        return 1
    if _has_any_exact_turn_source_ref(item) and len(item.source_refs) == 1:
        return 2
    if _has_any_exact_turn_source_ref(item):
        return 3
    return 4

def _temporal_answer_support_query_object_hits(
    item: ContextItem,
    *,
    query: str,
    query_reason: str,
) -> int:
    if not query or not _is_temporal_answer_support_item(item, query_reason=query_reason):
        return 0
    query_tokens = tuple(
        dict.fromkeys(
            token.casefold()
            for token in _QUERY_OBJECT_TOKEN_RE.findall(query)
            if len(token) >= 3
            and token.casefold() not in _TEMPORAL_QUERY_OBJECT_STOPWORDS
            and not token[:1].isupper()
        )
    )
    if not query_tokens:
        return 0
    text = item.text.casefold()
    return sum(1 for token in query_tokens if re.search(rf"\b{re.escape(token)}\b", text))

def _is_temporal_answer_support_item(item: ContextItem, *, query_reason: str) -> bool:
    if _numeric_signal(_diagnostic_score_signals(item).get("source_sibling_answer_evidence")) <= 0:
        return False
    if not _has_any_exact_turn_source_ref(item):
        return False
    if (
        query_reason in {"business_commonality_bridge", "business_start_reason_bridge"}
        and _business_commonality_answer_slot(item.text)
    ):
        return False
    signals = _diagnostic_score_signals(item)
    if _numeric_signal(signals.get("exact_source_repair_date_anchor")) > 0:
        return True
    normalized_reason = query_reason.replace("_", "-")
    if normalized_reason in _TEMPORAL_ANSWER_SUPPORT_REASONS:
        return True
    if query_reason == "outdoor_activity_inventory_bridge" or (
        _is_community_participation_reason(query_reason)
        and _inventory_answer_slot(item, query_reason=query_reason)
    ):
        return False
    if normalized_reason in {"place-area-inventory-bridge", "trip-destination-bridge"} and (
        _inventory_answer_slot(item, query_reason=query_reason)
    ):
        return False
    return _TEMPORAL_DIRECT_ANSWER_RE.search(item.text) is not None
