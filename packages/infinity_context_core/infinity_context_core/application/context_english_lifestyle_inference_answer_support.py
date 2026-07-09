"""English exact-turn support for lifestyle inference questions."""

from __future__ import annotations

import re
from dataclasses import replace

from infinity_context_core.application.context_diagnostics import context_rank_key
from infinity_context_core.application.context_english_lifestyle_inference import (
    english_lifestyle_answer_slot_and_rank,
    english_lifestyle_query_kind,
)
from infinity_context_core.application.context_packer_answer_support import (
    _answer_support_family_item_key_for_query,
)
from infinity_context_core.application.context_packer_answer_support_utils import (
    _has_any_exact_turn_source_ref,
)
from infinity_context_core.application.dto import ContextItem

_DIALOGUE_MARKER_RE = re.compile(r"\bD\d+:\d+\b")
_STRESS_LIVING_WORK_CONSTRAINT_RE = re.compile(
    r"\b(?:work(?:'s)?|job|work[-\s]?life)\b"
    r"(?=.{0,220}\b(?:stress(?:ful|ed)?|piling\s+up|stuck\s+inside|"
    r"backseat|balance|challenging)\b)"
    r"(?=.{0,260}\b(?:hike|hiking|outdoors?|outdoor\s+activities|"
    r"peace|freedom|backseat|balance|stuck\s+inside)\b)|"
    r"\b(?:stress(?:ful|ed)?|piling\s+up|stuck\s+inside|backseat|balance)\b"
    r"(?=.{0,220}\b(?:work(?:'s)?|job|work[-\s]?life)\b)"
    r"(?=.{0,260}\b(?:hike|hiking|outdoors?|outdoor\s+activities|"
    r"peace|freedom|backseat|balance)\b)",
    re.IGNORECASE | re.DOTALL,
)
_STRESS_LIVING_CITY_CONSTRAINT_RE = re.compile(
    r"\b(?:city|living\s+here)\b"
    r"(?=.{0,220}\bopen\s+spaces?\b)"
    r"(?=.{0,260}\b(?:hard|challenging|difficult|hike|hiking|"
    r"work[-\s]?life|balance|outdoors?)\b)|"
    r"\bopen\s+spaces?\b"
    r"(?=.{0,220}\b(?:city|living\s+here)\b)"
    r"(?=.{0,260}\b(?:hard|challenging|difficult|hike|hiking|"
    r"work[-\s]?life|balance|outdoors?)\b)|"
    r"\bwork[-\s]?life\s+balance\b"
    r"(?=.{0,260}\b(?:city|open\s+spaces?|hike|hiking|outdoors?)\b)",
    re.IGNORECASE | re.DOTALL,
)
_MAX_LIFESTYLE_INFERENCE_TURN_ITEMS = 6


def english_lifestyle_inference_turn_candidates(
    items: list[ContextItem],
    *,
    query: str,
    limit: int,
) -> tuple[ContextItem, ...]:
    """Return exact turns that supply complementary lifestyle inference evidence."""
    if limit <= 0:
        return ()
    query_kind = _lifestyle_query_kind(query)
    if not query_kind:
        return ()

    ranked: list[tuple[tuple[object, ...], str, str, ContextItem]] = []
    for item in items:
        if not (_has_any_exact_turn_source_ref(item) or _DIALOGUE_MARKER_RE.search(item.text)):
            continue
        marker_candidates = _marker_level_lifestyle_candidates(
            item,
            query=query,
            query_kind=query_kind,
        )
        if marker_candidates:
            ranked.extend(marker_candidates)
            continue
        if _has_multiple_exact_turn_markers(item):
            continue
        slot, answer_rank = _lifestyle_answer_slot_and_rank(item.text, query_kind=query_kind)
        if not slot or answer_rank > 0:
            continue
        marker = _direct_lifestyle_marker(item, query_kind=query_kind)
        ranked.append(
            (
                (
                    answer_rank,
                    _lifestyle_answer_selection_rank(
                        item.text,
                        query_kind=query_kind,
                        slot=slot,
                    ),
                    _exact_ref_specificity_rank(item),
                    _answer_support_family_item_key_for_query(item, query=query),
                    context_rank_key(item),
                ),
                slot,
                marker,
                item,
            )
        )

    selected: list[ContextItem] = []
    selected_markers: set[str] = set()
    selected_slots: dict[str, int] = {}
    for _, slot, marker, item in sorted(ranked, key=lambda value: value[0]):
        if len(selected) >= min(limit, _MAX_LIFESTYLE_INFERENCE_TURN_ITEMS):
            break
        if marker and marker in selected_markers:
            continue
        if selected_slots.get(slot, 0) >= _slot_limit(query_kind=query_kind, slot=slot):
            continue
        selected.append(item)
        if marker:
            selected_markers.add(marker)
        selected_slots[slot] = selected_slots.get(slot, 0) + 1
    return tuple(selected)


def _lifestyle_query_kind(query: str) -> str:
    return english_lifestyle_query_kind(query)


def _lifestyle_answer_slot_and_rank(text: str, *, query_kind: str) -> tuple[str, int]:
    return english_lifestyle_answer_slot_and_rank(text, query_kind=query_kind)


def _slot_limit(*, query_kind: str, slot: str) -> int:
    if query_kind == "animal_nature_career" and slot == "nature_affinity":
        return 3
    if query_kind == "stress_living_outdoor" and slot == "work_stress_outdoor":
        return 2
    return 2


def _exact_ref_specificity_rank(item: ContextItem) -> int:
    exact_refs = _exact_turn_source_ids(item)
    if len(item.source_refs) == 1 and len(exact_refs) == 1:
        return 0
    if exact_refs:
        return 1
    return 2


def _marker_level_lifestyle_candidates(
    item: ContextItem,
    *,
    query: str,
    query_kind: str,
) -> tuple[tuple[tuple[object, ...], str, str, ContextItem], ...]:
    ranked: list[tuple[tuple[object, ...], str, str, ContextItem]] = []
    for ref, marker in _exact_turn_source_ref_markers(item):
        if re.search(rf"\b{re.escape(marker)}\b", item.text) is None:
            continue
        focused = _focused_marker_text(item.text, marker=marker)
        slot, answer_rank = _lifestyle_answer_slot_and_rank(
            focused,
            query_kind=query_kind,
        )
        if not slot or answer_rank > 0:
            continue
        focused_item = _focused_marker_context_item(
            item,
            ref=ref,
            marker=marker,
            focused_text=focused,
        )
        ranked.append(
            (
                (
                    answer_rank,
                    _lifestyle_answer_selection_rank(
                        focused,
                        query_kind=query_kind,
                        slot=slot,
                    ),
                    _exact_ref_specificity_rank(focused_item),
                    _answer_support_family_item_key_for_query(focused_item, query=query),
                    context_rank_key(focused_item),
                ),
                slot,
                marker,
                focused_item,
            )
        )
    return tuple(ranked)


def _lifestyle_answer_selection_rank(
    text: str,
    *,
    query_kind: str,
    slot: str,
) -> int:
    if query_kind == "stress_living_outdoor":
        if slot == "work_stress_outdoor":
            return 0 if _STRESS_LIVING_WORK_CONSTRAINT_RE.search(text) is not None else 2
        if slot == "city_outdoor_space":
            return 0 if _STRESS_LIVING_CITY_CONSTRAINT_RE.search(text) is not None else 2
    return 0


def _focused_marker_context_item(
    item: ContextItem,
    *,
    ref: object,
    marker: str,
    focused_text: str,
) -> ContextItem:
    if len(item.source_refs) == 1 and item.source_refs[0] == ref and item.text == focused_text:
        return item
    diagnostics = dict(item.diagnostics or {})
    score_signals = diagnostics.get("score_signals")
    if isinstance(score_signals, dict):
        diagnostics["score_signals"] = {
            **score_signals,
            "lifestyle_marker_focus_pack": 1,
        }
    else:
        diagnostics["score_signals"] = {"lifestyle_marker_focus_pack": 1}
    return replace(
        item,
        item_id=f"{item.item_id}:lifestyle_marker:{_marker_item_id_suffix(marker)}",
        text=focused_text,
        source_refs=(ref,),
        diagnostics=diagnostics,
    )


def _marker_item_id_suffix(marker: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", marker).strip("_")[:80] or "turn"


def _direct_lifestyle_marker(item: ContextItem, *, query_kind: str) -> str:
    for marker in _exact_turn_source_markers(item):
        focused = _focused_marker_text(item.text, marker=marker)
        slot, answer_rank = _lifestyle_answer_slot_and_rank(focused, query_kind=query_kind)
        if slot and answer_rank == 0:
            return marker
    markers = _exact_turn_source_markers(item)
    if markers:
        return markers[0]
    match = _DIALOGUE_MARKER_RE.search(item.text)
    return match.group(0) if match is not None else ""


def _has_multiple_exact_turn_markers(item: ContextItem) -> bool:
    return len(_exact_turn_source_markers(item)) > 1


def _exact_turn_source_ids(item: ContextItem) -> tuple[str, ...]:
    return tuple(
        source_id
        for ref in item.source_refs
        if (source_id := str(ref.source_id)).casefold().endswith(":turn")
    )


def _exact_turn_source_ref_markers(item: ContextItem) -> tuple[tuple[object, str], ...]:
    ref_markers: list[tuple[object, str]] = []
    seen_markers: set[str] = set()
    for ref in item.source_refs:
        source_id = str(ref.source_id)
        if not source_id.casefold().endswith(":turn"):
            continue
        match = _DIALOGUE_MARKER_RE.search(source_id)
        if match is None:
            continue
        marker = match.group(0)
        if marker in seen_markers:
            continue
        seen_markers.add(marker)
        ref_markers.append((ref, marker))
    return tuple(ref_markers)


def _exact_turn_source_markers(item: ContextItem) -> tuple[str, ...]:
    markers: list[str] = []
    for source_id in _exact_turn_source_ids(item):
        match = _DIALOGUE_MARKER_RE.search(source_id)
        if match is not None and match.group(0) not in markers:
            markers.append(match.group(0))
    return tuple(markers)


def _focused_marker_text(text: str, *, marker: str) -> str:
    pattern = re.compile(
        rf"\b{re.escape(marker)}\b.*?(?=\bD\d+:\d+\b|$)",
        re.IGNORECASE | re.DOTALL,
    )
    matches = tuple(match.group(0) for match in pattern.finditer(text))
    if not matches:
        return text
    return max(matches, key=len)
