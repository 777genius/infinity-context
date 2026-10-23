"""Geographical and residence answer-evidence policies."""

from __future__ import annotations

import re

from infinity_context_core.application.context_packer_answer_support_patterns import (
    _PLACE_AREA_DIRECT_LOCATION_RE,
    _PLACE_AREA_LANDMARK_LOCATION_RE,
    _PLACE_AREA_STATE_FUTURE_RE,
    _PLACE_AREA_STATE_QUERY_RE,
    _PLACE_AREA_STATE_VISIT_RE,
)
from infinity_context_core.application.context_packer_answer_support_slots import (
    _inventory_answer_slot,
)
from infinity_context_core.application.context_packer_answer_support_utils import (
    _answer_support_query_reason,
    _diversity_family_base,
    _has_any_exact_turn_source_ref,
)
from infinity_context_core.application.context_source_sibling_place_evidence import (
    country_destination_answer_support_rank,
    is_country_destination_source_sibling_answer_evidence,
    is_place_inference_source_sibling_answer_evidence,
    is_query_destination_source_sibling_anchor,
    query_destination_places,
)
from infinity_context_core.application.context_state_residence_inference import (
    state_residence_inference_signal,
)
from infinity_context_core.application.dto import ContextItem


def _is_exact_place_inference_answer_support_item(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    if not query or not _has_any_exact_turn_source_ref(item):
        return False
    query_reason = _answer_support_query_reason(item)
    return is_place_inference_source_sibling_answer_evidence(
        expansion_query=query,
        expansion_reason=query_reason,
        text=item.text,
    )

def _is_exact_query_destination_answer_support_item(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    if not query or not _has_any_exact_turn_source_ref(item):
        return False
    query_reason = _answer_support_query_reason(item).replace("_", "-")
    if query_reason not in {
        "decomposition-inference-support",
        "original-query",
        "place-area-inventory-bridge",
        "themed-location-destination-anchor-bridge",
        "themed-location-destination-bridge",
        "travel-country-inventory-bridge",
        "trip-destination-bridge",
    }:
        return False
    if not query_destination_places(query):
        return False
    return is_query_destination_source_sibling_anchor(
        expansion_query=query,
        expansion_reason=query_reason,
        text=item.text,
    )

def _is_exact_country_destination_answer_support_item(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    if not query or not _has_any_exact_turn_source_ref(item):
        return False
    return is_country_destination_source_sibling_answer_evidence(
        expansion_query=query,
        expansion_reason=_answer_support_query_reason(item),
        text=item.text,
    )

def _country_destination_answer_support_rank(
    item: ContextItem,
    *,
    query: str,
) -> int:
    if not query:
        return 5
    return country_destination_answer_support_rank(
        expansion_query=query,
        text=item.text,
        has_exact_turn=_has_any_exact_turn_source_ref(item),
    )

def _is_exact_place_area_state_answer_support_item(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    query_reason = _answer_support_query_reason(item)
    if _is_state_residence_geo_answer_support_item(item, query=query):
        return True
    return (
        _place_area_state_query_applies(query=query, query_reason=query_reason)
        and _has_any_exact_turn_source_ref(item)
        and _place_area_state_answer_support_rank(
            item,
            query=query,
            query_reason=query_reason,
        )
        == 0
    )

def _place_area_state_answer_support_rank(
    item: ContextItem,
    *,
    query: str,
    query_reason: str,
) -> int:
    if not _place_area_state_query_applies(query=query, query_reason=query_reason):
        return 0
    slot = _inventory_answer_slot(item, query_reason=query_reason)
    if not (
        slot.startswith("state_")
        or slot in {"country", "travel_place", "travel_place_realized"}
    ):
        return 3
    has_direct_location = (
        _PLACE_AREA_DIRECT_LOCATION_RE.search(item.text) is not None
        or _PLACE_AREA_LANDMARK_LOCATION_RE.search(item.text) is not None
    )
    has_state_visit = _PLACE_AREA_STATE_VISIT_RE.search(item.text) is not None
    if (
        _has_any_exact_turn_source_ref(item)
        and (slot.endswith("_realized") or has_state_visit)
        and _PLACE_AREA_STATE_FUTURE_RE.search(item.text) is None
        and not (
            _place_area_state_query_wants_concrete_state(query)
            and slot in {"state_east_coast", "state_pacific_northwest"}
        )
    ):
        return 0
    if (
        _has_any_exact_turn_source_ref(item)
        and has_direct_location
        and _PLACE_AREA_STATE_FUTURE_RE.search(item.text) is None
    ):
        return 1
    if (
        _place_area_state_query_wants_concrete_state(query)
        and slot
        in {"state_east_coast", "state_pacific_northwest", "travel_place"}
    ):
        return 2
    if _has_any_exact_turn_source_ref(item):
        return 1
    return 2

def _place_area_state_query_applies(*, query: str, query_reason: str) -> bool:
    if not query or _PLACE_AREA_STATE_QUERY_RE.search(query) is None:
        return False
    return query_reason.replace("_", "-") in {
        "decomposition-inventory-list",
        "place-area-inventory-bridge",
        "trip-destination-bridge",
    }

def _place_area_state_query_wants_concrete_state(query: str) -> bool:
    return re.search(r"\bstates?\b", query, re.IGNORECASE) is not None

_STATE_RESIDENCE_ANSWER_EVIDENCE_REASONS = frozenset(
    {
        "inference_state_residence_city_state_evidence",
        "inference_state_residence_named_state_evidence",
        "inference_state_residence_geo_evidence",
    }
)

_STATE_RESIDENCE_MAP_TRAIL_RE = re.compile(
    r"\bmap\b(?=.{0,160}\btrails?\b)|\btrails?\b(?=.{0,160}\bmap\b)",
    re.IGNORECASE | re.DOTALL,
)

def _state_residence_answer_support_rank(
    item: ContextItem,
    *,
    query: str,
    query_reason: str,
) -> int:
    if query_reason != "state_residence_inference_bridge" or not query:
        return 0
    signal = state_residence_inference_signal(query=query, text=item.text)
    if signal.reason == "inference_state_residence_geo_evidence":
        has_map_trail = _STATE_RESIDENCE_MAP_TRAIL_RE.search(item.text) is not None
        if has_map_trail and _has_any_exact_turn_source_ref(item):
            return 0
        if has_map_trail:
            return 1
        if _has_any_exact_turn_source_ref(item):
            return 2
        return 3
    if signal.reason in _STATE_RESIDENCE_ANSWER_EVIDENCE_REASONS:
        if _has_any_exact_turn_source_ref(item):
            return 1
        return 2
    if signal.penalty > 0:
        return 5
    if _has_any_exact_turn_source_ref(item):
        return 4
    return 5

def _is_state_residence_geo_answer_support_item(
    item: ContextItem,
    *,
    query: str,
) -> bool:
    query_reason = _answer_support_query_reason(item)
    if query_reason != "state_residence_inference_bridge" or not query:
        return False
    return (
        _state_residence_answer_support_rank(
            item,
            query=query,
            query_reason=query_reason,
        )
        == 0
    )

def _is_direct_place_area_state_answer_support_item(
    item: ContextItem,
    *,
    query: str,
    family: str,
) -> bool:
    query_reason = _answer_support_query_reason(item)
    if not _place_area_state_query_applies(query=query, query_reason=query_reason):
        return False
    if _diversity_family_base(family) not in {
        "query_reason_inventory_slot",
        "query_reason_inventory_slot_source_group",
    }:
        return False
    return (
        _place_area_state_answer_support_rank(
            item,
            query=query,
            query_reason=query_reason,
        )
        == 0
    )
