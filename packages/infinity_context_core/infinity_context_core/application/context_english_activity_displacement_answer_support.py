"""English exact-turn answer support for activity displacement questions."""

from __future__ import annotations

import re

from infinity_context_core.application.context_causal_reason_rerank import (
    yoga_delay_gaming_answer_rank,
)
from infinity_context_core.application.context_diagnostics import context_rank_key
from infinity_context_core.application.context_packer_answer_support import (
    _answer_support_family_item_key_for_query,
    _answer_support_query_reason,
)
from infinity_context_core.application.context_packer_answer_support_utils import (
    _has_any_exact_turn_source_ref,
)
from infinity_context_core.application.dto import ContextItem

_YOGA_DELAY_GAMING_REASON = "yoga-delay-gaming-bridge"
_YOGA_DELAY_GAMING_QUERY_RE = re.compile(
    r"\byoga\b(?=.{0,140}\b(?:put\s+off|postpon(?:e|ed|ing)|delay(?:ed|ing)?|"
    r"instead|why)\b)|"
    r"\b(?:put\s+off|postpon(?:e|ed|ing)|delay(?:ed|ing)?)\b"
    r"(?=.{0,140}\byoga\b)",
    re.IGNORECASE | re.DOTALL,
)
_DIALOGUE_MARKER_RE = re.compile(r"\bD\d+:\d+\b")
_MAX_YOGA_DELAY_GAMING_TURN_ITEMS = 3


def english_activity_displacement_turn_candidates(
    items: list[ContextItem],
    *,
    query: str,
    limit: int,
) -> tuple[ContextItem, ...]:
    """Return exact turns that directly answer an activity-displacement cause."""
    if limit <= 0:
        return ()
    ranked: list[tuple[tuple[object, ...], str, ContextItem]] = []
    for item in items:
        query_reason = _answer_support_query_reason(item).replace("_", "-")
        if not _is_yoga_delay_gaming_candidate(query=query, query_reason=query_reason):
            continue
        if not _has_any_exact_turn_source_ref(item):
            continue
        answer_rank = yoga_delay_gaming_answer_rank(item.text)
        if answer_rank > 1:
            continue
        marker = _direct_activity_displacement_marker(item)
        ranked.append(
            (
                (
                    answer_rank,
                    _exact_ref_specificity_rank(item),
                    _answer_support_family_item_key_for_query(item, query=query),
                    context_rank_key(item),
                ),
                marker,
                item,
            )
        )

    selected: list[ContextItem] = []
    selected_markers: set[str] = set()
    for _, marker, item in sorted(ranked, key=lambda value: value[0]):
        if len(selected) >= min(limit, _MAX_YOGA_DELAY_GAMING_TURN_ITEMS):
            break
        if marker and marker in selected_markers:
            continue
        selected.append(item)
        if marker:
            selected_markers.add(marker)
    return tuple(selected)


def _is_yoga_delay_gaming_candidate(*, query: str, query_reason: str) -> bool:
    return (
        query_reason == _YOGA_DELAY_GAMING_REASON
        or _YOGA_DELAY_GAMING_QUERY_RE.search(query) is not None
    )


def _exact_ref_specificity_rank(item: ContextItem) -> int:
    exact_refs = _exact_turn_source_ids(item)
    if len(item.source_refs) == 1 and len(exact_refs) == 1:
        return 0
    if exact_refs:
        return 1
    return 2


def _direct_activity_displacement_marker(item: ContextItem) -> str:
    for marker in _exact_turn_source_markers(item):
        focused = _focused_marker_text(item.text, marker=marker)
        if yoga_delay_gaming_answer_rank(focused) <= 1:
            return marker
    markers = _exact_turn_source_markers(item)
    return markers[0] if markers else ""


def _exact_turn_source_ids(item: ContextItem) -> tuple[str, ...]:
    return tuple(
        source_id
        for ref in item.source_refs
        if (source_id := str(ref.source_id)).casefold().endswith(":turn")
    )


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
