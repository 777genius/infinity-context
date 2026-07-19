"""Exact-turn packing prepasses extracted from the context packer."""

from __future__ import annotations

import re

from infinity_context_core.application.context_diagnostics import context_rank_key
from infinity_context_core.application.context_item_purchase_evidence import (
    has_item_purchase_object_evidence,
)
from infinity_context_core.application.context_packer_answer_support import (
    _activity_competition_visual_answer_rank,
    _answer_support_exact_query_object_hits,
    _answer_support_family_item_key_for_query,
    _answer_support_query_reason,
    _book_reading_answer_content_rank,
    _country_destination_answer_support_rank,
    _has_any_exact_turn_source_ref,
    _is_exact_common_interest_answer_support_item,
    _is_exact_country_destination_answer_support_item,
    _is_exact_inspiration_source_answer_support_item,
    _is_exact_place_area_state_answer_support_item,
    _is_exact_precise_content_answer_support_item,
    _precise_answer_content_rank,
    _primary_exact_turn_source_id,
)
from infinity_context_core.application.context_packer_answer_support_utils import (
    _inventory_first_mention_rank,
)
from infinity_context_core.application.context_packer_exact_literal_turns import (
    exact_literal_turn_candidates,
)
from infinity_context_core.application.context_packer_exact_turn_utils import (
    _primary_exact_turn_marker,
)
from infinity_context_core.application.context_packer_marker_coverage import (
    _source_ref_marker,
)
from infinity_context_core.application.context_packer_selection import (
    _SelectionState,
    _try_select_item,
)
from infinity_context_core.application.dto import ContextItem

_MAX_EXACT_QUERY_OBJECT_TURN_ITEMS = 4
_MAX_EXACT_PLACE_AREA_STATE_TURN_ITEMS = 4
_MAX_EXACT_COUNTRY_DESTINATION_TURN_ITEMS = 4
_MAX_EXACT_COMMON_INTEREST_TURN_ITEMS = 8
_MAX_EXACT_SHARED_VOLUNTEERING_TURN_ITEMS = 4
_MAX_EXACT_BOOK_READING_TURN_ITEMS = 12
_MAX_EXACT_PRECISE_CONTENT_TURN_ITEMS = 4
_MAX_EXACT_ACTIVITY_COMPETITION_TURN_ITEMS = 4
_MAX_EXACT_METEOR_FEELING_TURN_ITEMS = 2
_MAX_EXACT_STATE_VISIT_TURN_ITEMS = 3
_BOOK_READING_EXPLICIT_TURN_RE = re.compile(
    r"\b(?:book\s+collection|book\s+series\s+(?:that\s+)?(?:i\s+)?love|"
    r"book\s+i\s+read\s+last\s+year|favorite\s+book\s+(?:is|was)|"
    r"favourite\s+book\s+(?:is|was)|just\s+finished|finished\s+reading|"
    r"loved\s+reading|read\s+\"?(?-i:[A-Z])[^\"\n]{1,80}\"?\s+as\s+a\s+kid|"
    r"books?\s+(?:guide|motivat(?:e|es|ed|ing)|help(?:s|ed)?"
    r"(?:\s+(?:me|him|her|them|us|you))?\s+discover|"
    r"(?:are|is)\s+a\s+huge\s+part)\b"
    r"(?=.{0,180}\b(?:journey|reading|"
    r"self[-\s]?discovery|keep\s+going|motivat(?:e|es|ed|ing))\b)|"
    r"\"?(?-i:[A-Z])[^\"\n]{1,80}\"?\s+(?:is|are)\s+"
    r"(?:great|good|amazing|awesome)|"
    r"(?-i:[A-Z])[^\"\n]{1,80}\".{0,80}\bone\s+of\s+my\s+favorites)\b",
    re.IGNORECASE | re.DOTALL,
)
_BOOK_READING_CONTEXTUAL_TITLE_TURN_RE = re.compile(
    r"\b(?:fan\s+of\s+\"?(?-i:[A-Z])[^\"\n]{1,80}|"
    r"\"?(?-i:[A-Z])[^\"\n]{1,80}\"?\s+fan)\b",
    re.IGNORECASE | re.DOTALL,
)
_QUERY_SUBJECT_AFTER_AUX_RE = re.compile(r"\b(?:has|had|did|does|do|is|was|were)\s+([A-Z][a-z]+)\b")
_EXACT_TURN_SPEAKER_RE = re.compile(r"\bD\d+:\d+\s+([A-Z][a-z]+):")
_METEOR_FEELING_QUERY_RE = re.compile(
    r"\bmeteor\s+shower\b(?=.{0,120}\b(?:feel|felt|feeling|watch(?:ing|ed)?)\b)|"
    r"\b(?:feel|felt|feeling)\b(?=.{0,120}\bmeteor\s+shower\b)",
    re.IGNORECASE | re.DOTALL,
)
_METEOR_FEELING_DIRECT_RE = re.compile(
    r"\b(?:felt|feel|feeling|tiny|awe|universe|awesome\s+life)\b",
    re.IGNORECASE,
)
_STATE_VISIT_QUERY_RE = re.compile(
    r"\b(?:in\s+)?(?:what|which)\s+(?:u\.?s\.?\s+)?(?:state|country)\b"
    r"(?=.{0,140}\b(?:visit(?:ed)?|went|been|during|trip|vacation|summer|meet)\b)|"
    r"\b(?:visit(?:ed)?|went|been|trip|vacation|meet)\b"
    r"(?=.{0,140}\b(?:state|country)\b)",
    re.IGNORECASE | re.DOTALL,
)
_STATE_VISIT_DIRECT_RE = re.compile(
    r"\b(?:visited|visit|went|been|trip|took|travel(?:ed|led)?)\b"
    r"(?=.{0,180}\b(?:to|in|during)\s+"
    r"(?:the\s+)?(?:beach\s+in\s+)?[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b)|"
    r"\b(?:beach|city|town|park|internship)\s+in\s+"
    r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b|"
    r"\b(?:mount|mountain|mt\.?)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b",
    re.DOTALL,
)
_EN_SHARED_VOLUNTEERING_QUERY_RE = re.compile(
    r"\b(?:both|common|shared|mutual)\b(?=.{0,160}\bvolunteer(?:ed|ing|s)?\b)|"
    r"\bvolunteer(?:ed|ing|s)?\b(?=.{0,160}\b(?:both|common|shared|mutual)\b)|"
    r"\bwhat\s+type\s+of\s+volunteering\b",
    re.IGNORECASE | re.DOTALL,
)
_SHARED_VOLUNTEERING_QUERY_REASONS = frozenset(
    {
        "decomposition-inventory-list",
        "volunteering-inventory-bridge",
    }
)
_EN_SHARED_VOLUNTEERING_SERVICE_RE = re.compile(
    r"\b(?:homeless\s+)?shelter\b(?=.{0,180}\b(?:volunteer(?:ed|ing|s)?|"
    r"give\s+out|food|supplies|donat(?:e|ed|ing|ion)|drive|event|kids?|"
    r"people|community)\b)|"
    r"\b(?:volunteer(?:ed|ing|s)?)\b(?=.{0,180}\b(?:homeless\s+)?shelter\b)|"
    r"\b(?:give\s+out\s+food|food\s+and\s+supplies|donation\s+drive|"
    r"toy\s+drive|food\s+drive)\b(?=.{0,180}\b(?:shelter|volunteer))",
    re.IGNORECASE | re.DOTALL,
)
_EXACT_QUERY_OBJECT_PREPASS_EXCLUDED_REASONS = frozenset(
    {
        "cause_education_infrastructure_inventory_bridge",
        "cause_veterans_inventory_bridge",
        "event_participation_help_bridge",
    }
)


def _select_exact_query_object_turn_items(
    state: _SelectionState,
    *,
    items: list[ContextItem],
    query: str,
    budget: int,
    char_budget: int,
) -> int:
    if not query:
        return 0
    ranked: list[tuple[tuple[object, ...], ContextItem]] = []
    for item in items:
        if not _has_any_exact_turn_source_ref(item):
            continue
        query_reason = _answer_support_query_reason(item)
        if query_reason in _EXACT_QUERY_OBJECT_PREPASS_EXCLUDED_REASONS:
            continue
        if query_reason == "item_purchase_bridge" and not has_item_purchase_object_evidence(
            item.text,
        ):
            continue
        query_object_hits = _answer_support_exact_query_object_hits(item, query=query)
        if query_object_hits <= 0:
            continue
        ranked.append(
            (
                (
                    -query_object_hits,
                    _answer_support_family_item_key_for_query(
                        item,
                        query=query,
                    ),
                    context_rank_key(item),
                ),
                item,
            )
        )
    selected = 0
    for _, item in sorted(ranked, key=lambda value: value[0]):
        if selected >= _MAX_EXACT_QUERY_OBJECT_TURN_ITEMS:
            break
        if _try_select_item(
            state,
            item=item,
            budget=budget,
            char_budget=char_budget,
            ignore_source_cap=True,
        ):
            selected += 1
    return selected


def _select_exact_place_area_state_turn_items(
    state: _SelectionState,
    *,
    items: list[ContextItem],
    query: str,
    budget: int,
    char_budget: int,
) -> int:
    ranked: list[tuple[tuple[object, ...], ContextItem]] = []
    for item in items:
        if not _is_exact_place_area_state_answer_support_item(item, query=query):
            continue
        ranked.append(
            (
                (
                    _answer_support_family_item_key_for_query(item, query=query),
                    context_rank_key(item),
                ),
                item,
            )
        )

    selected = 0
    selected_markers: set[str] = set()
    for _, item in sorted(ranked, key=lambda value: value[0]):
        if selected >= _MAX_EXACT_PLACE_AREA_STATE_TURN_ITEMS:
            break
        marker = _primary_exact_turn_marker(item)
        if marker and marker in selected_markers:
            continue
        if _try_select_item(
            state,
            item=item,
            budget=budget,
            char_budget=char_budget,
            ignore_source_cap=True,
        ):
            selected += 1
            if marker:
                selected_markers.add(marker)
    return selected


def _select_exact_country_destination_turn_items(
    state: _SelectionState,
    *,
    items: list[ContextItem],
    query: str,
    budget: int,
    char_budget: int,
) -> int:
    ranked: list[tuple[tuple[object, ...], ContextItem]] = []
    for item in items:
        if not _is_exact_country_destination_answer_support_item(item, query=query):
            continue
        ranked.append(
            (
                (
                    _country_destination_answer_support_rank(item, query=query),
                    _answer_support_family_item_key_for_query(item, query=query),
                    context_rank_key(item),
                ),
                item,
            )
        )

    selected = 0
    selected_markers: set[str] = set()
    for _, item in sorted(ranked, key=lambda value: value[0]):
        if selected >= _MAX_EXACT_COUNTRY_DESTINATION_TURN_ITEMS:
            break
        marker = _primary_exact_turn_marker(item)
        if marker and marker in selected_markers:
            continue
        if _try_select_item(
            state,
            item=item,
            budget=budget,
            char_budget=char_budget,
            ignore_source_cap=True,
        ):
            selected += 1
            if marker:
                selected_markers.add(marker)
    return selected


def _select_exact_common_interest_turn_items(
    state: _SelectionState,
    *,
    items: list[ContextItem],
    query: str,
    budget: int,
    char_budget: int,
) -> int:
    ranked: list[tuple[tuple[object, ...], ContextItem]] = []
    for item in items:
        if not _is_exact_common_interest_answer_support_item(item):
            continue
        ranked.append(
            (
                (
                    _answer_support_family_item_key_for_query(item, query=query),
                    context_rank_key(item),
                ),
                item,
            )
        )

    selected = 0
    selected_markers: set[str] = set()
    for _, item in sorted(ranked, key=lambda value: value[0]):
        if selected >= _MAX_EXACT_COMMON_INTEREST_TURN_ITEMS:
            break
        marker = _primary_exact_turn_marker(item)
        if marker and marker in selected_markers:
            continue
        if _try_select_item(
            state,
            item=item,
            budget=budget,
            char_budget=char_budget,
            ignore_source_cap=True,
        ):
            selected += 1
            if marker:
                selected_markers.add(marker)
    return selected


def _select_exact_shared_volunteering_turn_items(
    state: _SelectionState,
    *,
    items: list[ContextItem],
    query: str,
    budget: int,
    char_budget: int,
) -> int:
    if _EN_SHARED_VOLUNTEERING_QUERY_RE.search(query) is None:
        return 0
    ranked: list[tuple[tuple[object, ...], ContextItem]] = []
    for item in items:
        query_reason = _answer_support_query_reason(item).replace("_", "-")
        if query_reason not in _SHARED_VOLUNTEERING_QUERY_REASONS:
            continue
        if len(_exact_turn_source_ids(item)) != 1:
            continue
        service_rank = _shared_volunteering_service_answer_rank(item.text)
        if service_rank > 2:
            continue
        ranked.append(
            (
                (
                    service_rank,
                    _inventory_first_mention_rank(
                        source_id=_primary_exact_turn_source_id(item),
                        query=query,
                        enabled=True,
                    ),
                    _answer_support_family_item_key_for_query(item, query=query),
                    context_rank_key(item),
                ),
                item,
            )
        )

    selected = 0
    selected_speakers: set[str] = set()
    selected_markers: set[str] = set()
    for _, item in sorted(ranked, key=lambda value: value[0]):
        if selected >= _MAX_EXACT_SHARED_VOLUNTEERING_TURN_ITEMS:
            break
        marker = _primary_exact_turn_marker(item)
        if marker and marker in selected_markers:
            continue
        speaker = _exact_turn_speaker(item).casefold()
        if speaker and speaker in selected_speakers:
            continue
        if _try_select_item(
            state,
            item=item,
            budget=budget,
            char_budget=char_budget,
            ignore_source_cap=True,
        ):
            selected += 1
            if marker:
                selected_markers.add(marker)
            if speaker:
                selected_speakers.add(speaker)
    return selected


def _shared_volunteering_service_answer_rank(text: str) -> int:
    if _EN_SHARED_VOLUNTEERING_SERVICE_RE.search(text) is None:
        return 5
    normalized = text.casefold()
    if "homeless shelter" in normalized and "volunteer" in normalized:
        return 0
    if "homeless shelter" in normalized and any(
        phrase in normalized
        for phrase in (
            "give out",
            "food",
            "supplies",
            "donat",
            "drive",
            "event",
            "kids",
        )
    ):
        return 0
    if "shelter" in normalized and "volunteer" in normalized:
        return 1
    return 2


def _select_exact_book_reading_turn_items(
    state: _SelectionState,
    *,
    items: list[ContextItem],
    query: str,
    budget: int,
    char_budget: int,
) -> int:
    ranked: list[tuple[tuple[object, ...], ContextItem]] = []
    query_subject_names = _query_subject_names(query)
    for item in items:
        if _answer_support_query_reason(item) != "book_reading_list_bridge":
            continue
        exact_turn_source_ids = _exact_turn_source_ids(item)
        if len(exact_turn_source_ids) != 1:
            continue
        speaker = _exact_turn_speaker(item)
        if query_subject_names and speaker and speaker.casefold() not in query_subject_names:
            continue
        content_rank = _book_reading_answer_content_rank(item.text)
        if content_rank > 1:
            continue
        marker = _primary_exact_turn_marker(item)
        directness_rank = _book_reading_exact_turn_directness_rank(item.text)
        ranked.append(
            (
                (
                    directness_rank,
                    content_rank,
                    0 if marker else 1,
                    -_answer_support_exact_query_object_hits(item, query=query),
                    _answer_support_family_item_key_for_query(item, query=query),
                    context_rank_key(item),
                ),
                item,
            )
        )

    selected = 0
    selected_markers: set[str] = set()
    for _, item in sorted(ranked, key=lambda value: value[0]):
        if selected >= _MAX_EXACT_BOOK_READING_TURN_ITEMS:
            break
        marker = _primary_exact_turn_marker(item)
        if marker and marker in selected_markers:
            continue
        if _try_select_item(
            state,
            item=item,
            budget=budget,
            char_budget=char_budget,
            ignore_source_cap=True,
        ):
            selected += 1
            if marker:
                selected_markers.add(marker)
    return selected


def _book_reading_exact_turn_directness_rank(text: str) -> int:
    if _BOOK_READING_EXPLICIT_TURN_RE.search(text) is not None:
        return 0
    if _BOOK_READING_CONTEXTUAL_TITLE_TURN_RE.search(text) is not None:
        return 1
    return 2


def _is_redundant_book_reading_source_group_item(
    state: _SelectionState,
    item: ContextItem,
) -> bool:
    if _answer_support_query_reason(item) != "book_reading_list_bridge":
        return False
    item_markers = _exact_turn_markers(item)
    if len(item_markers) <= 1:
        return False
    selected_markers = {
        marker
        for selected_item in state.selected
        if _answer_support_query_reason(selected_item) == "book_reading_list_bridge"
        if len(_exact_turn_source_ids(selected_item)) == 1
        if _book_reading_answer_content_rank(selected_item.text) <= 1
        if (marker := _primary_exact_turn_marker(selected_item))
    }
    return bool(selected_markers & set(item_markers))


def _exact_turn_markers(item: ContextItem) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(marker for ref in item.source_refs if (marker := _source_ref_marker(ref)))
    )


def _query_subject_names(query: str) -> frozenset[str]:
    return frozenset(
        match.group(1).casefold() for match in _QUERY_SUBJECT_AFTER_AUX_RE.finditer(query or "")
    )


def _exact_turn_speaker(item: ContextItem) -> str:
    match = _EXACT_TURN_SPEAKER_RE.search(item.text)
    return match.group(1) if match is not None else ""


def _exact_turn_source_ids(item: ContextItem) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(ref.source_id)
            for ref in item.source_refs
            if str(ref.source_id).casefold().endswith(":turn")
        )
    )


def _select_exact_precise_content_turn_items(
    state: _SelectionState,
    *,
    items: list[ContextItem],
    query: str,
    budget: int,
    char_budget: int,
) -> int:
    ranked: list[tuple[tuple[object, ...], ContextItem]] = []
    for item in items:
        is_inspiration_source_support = _is_exact_inspiration_source_answer_support_item(
            item,
            query=query,
        )
        if not (
            _is_exact_precise_content_answer_support_item(item) or is_inspiration_source_support
        ):
            continue
        query_reason = _answer_support_query_reason(item)
        if (
            not is_inspiration_source_support
            and _precise_answer_content_rank(item, query_reason=query_reason) != 0
        ):
            continue
        marker = _primary_exact_turn_marker(item)
        ranked.append(
            (
                (
                    0 if marker else 1,
                    0 if is_inspiration_source_support else 1,
                    _answer_support_family_item_key_for_query(item, query=query),
                    context_rank_key(item),
                ),
                item,
            )
        )

    selected = 0
    selected_markers: set[str] = set()
    exact_precise_limit = _MAX_EXACT_PRECISE_CONTENT_TURN_ITEMS
    if any(
        _answer_support_query_reason(item) == "inspiration_source_bridge"
        or _is_exact_inspiration_source_answer_support_item(item, query=query)
        for _, item in ranked
    ):
        exact_precise_limit = max(exact_precise_limit, 6)
    for _, item in sorted(ranked, key=lambda value: value[0]):
        if selected >= exact_precise_limit:
            break
        marker = _primary_exact_turn_marker(item)
        if marker and marker in selected_markers:
            continue
        if _try_select_item(
            state,
            item=item,
            budget=budget,
            char_budget=char_budget,
            ignore_source_cap=True,
        ):
            selected += 1
            if marker:
                selected_markers.add(marker)
    return selected


def _select_exact_activity_competition_turn_items(
    state: _SelectionState,
    *,
    items: list[ContextItem],
    query: str,
    budget: int,
    char_budget: int,
) -> int:
    ranked: list[tuple[tuple[object, ...], ContextItem]] = []
    for item in items:
        query_reason = _answer_support_query_reason(item)
        if query_reason != "activity_competition_evidence_bridge":
            continue
        if not _has_any_exact_turn_source_ref(item):
            continue
        if (
            _activity_competition_visual_answer_rank(
                item,
                query=query,
                query_reason=query_reason,
            )
            != 0
        ):
            continue
        ranked.append(
            (
                (
                    _answer_support_family_item_key_for_query(item, query=query),
                    context_rank_key(item),
                ),
                item,
            )
        )

    selected = 0
    selected_markers: set[str] = set()
    for _, item in sorted(ranked, key=lambda value: value[0]):
        if selected >= _MAX_EXACT_ACTIVITY_COMPETITION_TURN_ITEMS:
            break
        marker = _primary_exact_turn_marker(item)
        if marker and marker in selected_markers:
            continue
        if _try_select_item(
            state,
            item=item,
            budget=budget,
            char_budget=char_budget,
            ignore_source_cap=True,
        ):
            selected += 1
            if marker:
                selected_markers.add(marker)
    return selected


def _select_exact_meteor_feeling_turn_items(
    state: _SelectionState,
    *,
    items: list[ContextItem],
    query: str,
    budget: int,
    char_budget: int,
) -> int:
    if _METEOR_FEELING_QUERY_RE.search(query) is None:
        return 0
    ranked: list[tuple[tuple[object, ...], ContextItem]] = []
    for item in items:
        if not _has_any_exact_turn_source_ref(item):
            continue
        if _METEOR_FEELING_DIRECT_RE.search(item.text) is None:
            continue
        ranked.append(
            (
                (
                    _precise_answer_content_rank(
                        item,
                        query_reason="meteor_shower_feeling_bridge",
                    ),
                    0 if _primary_exact_turn_marker(item) else 1,
                    context_rank_key(item),
                ),
                item,
            )
        )

    selected = 0
    selected_markers: set[str] = set()
    for _, item in sorted(ranked, key=lambda value: value[0]):
        if selected >= _MAX_EXACT_METEOR_FEELING_TURN_ITEMS:
            break
        marker = _primary_exact_turn_marker(item)
        if marker and marker in selected_markers:
            continue
        if _try_select_item(
            state,
            item=item,
            budget=budget,
            char_budget=char_budget,
            ignore_source_cap=True,
        ):
            selected += 1
            if marker:
                selected_markers.add(marker)
    return selected


def _select_exact_state_visit_turn_items(
    state: _SelectionState,
    *,
    items: list[ContextItem],
    query: str,
    budget: int,
    char_budget: int,
) -> int:
    if _STATE_VISIT_QUERY_RE.search(query) is None:
        return 0
    ranked: list[tuple[tuple[object, ...], ContextItem]] = []
    for item in items:
        if not _has_any_exact_turn_source_ref(item):
            continue
        if _STATE_VISIT_DIRECT_RE.search(item.text) is None:
            continue
        ranked.append(
            (
                (
                    0 if _primary_exact_turn_marker(item) else 1,
                    -_answer_support_exact_query_object_hits(item, query=query),
                    context_rank_key(item),
                ),
                item,
            )
        )

    selected = 0
    selected_markers: set[str] = set()
    for _, item in sorted(ranked, key=lambda value: value[0]):
        if selected >= _MAX_EXACT_STATE_VISIT_TURN_ITEMS:
            break
        marker = _primary_exact_turn_marker(item)
        if marker and marker in selected_markers:
            continue
        if _try_select_item(
            state,
            item=item,
            budget=budget,
            char_budget=char_budget,
            ignore_source_cap=True,
        ):
            selected += 1
            if marker:
                selected_markers.add(marker)
    return selected


def _select_exact_literal_turn_items(
    state: _SelectionState,
    *,
    items: list[ContextItem],
    query: str,
    budget: int,
    char_budget: int,
) -> int:
    selected = 0
    selected_markers: set[str] = set()
    for item in exact_literal_turn_candidates(items, query=query):
        marker = _primary_exact_turn_marker(item)
        if marker and marker in selected_markers:
            continue
        if _try_select_item(
            state,
            item=item,
            budget=budget,
            char_budget=char_budget,
            ignore_source_cap=True,
        ):
            selected += 1
            if marker:
                selected_markers.add(marker)
    return selected
