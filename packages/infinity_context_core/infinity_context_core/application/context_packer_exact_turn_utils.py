"""Shared exact-turn helpers for context packing prepasses."""

from __future__ import annotations

import re
from dataclasses import replace

from infinity_context_core.application.context_packer_answer_support import (
    _answer_support_query_reason,
    _primary_exact_turn_source_id,
)
from infinity_context_core.application.context_packer_answer_support_slots import (
    _inventory_answer_slot,
)
from infinity_context_core.application.dto import ContextItem

_DIALOGUE_MARKER_RE = re.compile(r"\bD\d+[:-]\d+\b")


def _exact_cause_inventory_directness_rank(item: ContextItem) -> int:
    raw_query_reason = _answer_support_query_reason(item)
    query_reason = raw_query_reason.replace("_", "-")
    if query_reason == "cause-event-inventory-bridge":
        focused_text = _focused_primary_exact_turn_text(item)
        if _inventory_answer_slot(
            replace(item, text=focused_text),
            query_reason=raw_query_reason,
        ):
            return 0
        if _inventory_answer_slot(item, query_reason=raw_query_reason):
            return 1
        return 2
    focused_text = _focused_primary_exact_turn_text(item)
    focused_rank = _direct_cause_inventory_text_rank(
        focused_text,
        query_reason=query_reason,
    )
    if focused_rank <= 1:
        return focused_rank
    full_rank = _direct_cause_inventory_text_rank(item.text, query_reason=query_reason)
    return min(full_rank + 1, 2)


def _exact_cause_inventory_slot(item: ContextItem) -> str:
    raw_query_reason = _answer_support_query_reason(item)
    query_reason = raw_query_reason.replace("_", "-")
    if query_reason in {
        "cause-event-inventory-bridge",
        "cause-education-infrastructure-inventory-bridge",
        "cause-veterans-inventory-bridge",
    }:
        return _inventory_answer_slot(item, query_reason=raw_query_reason)
    return ""


def _direct_cause_inventory_text_rank(text: str, *, query_reason: str) -> int:
    normalized = text.casefold()
    if query_reason == "cause-education-infrastructure-inventory-bridge":
        has_slot = (
            re.search(r"\b(?:education|educational|schools?|students?)\b", normalized) is not None
            and re.search(r"\binfrastructure\b", normalized) is not None
        )
        if not has_slot:
            return 2
        if (
            re.search(
                r"\b(?:passionate|interesting|interested|focus(?:es|ing)?|"
                r"main\s+focus(?:es)?|recently|goal|goals?)\b",
                normalized,
            )
            is not None
        ):
            return 0
        return 1
    if query_reason == "cause-veterans-inventory-bridge":
        has_slot = (
            re.search(r"\b(?:veterans?|military)\b", normalized) is not None
            and re.search(
                r"\b(?:passionate|rights?|support(?:ing|ed)?|valued|"
                r"appreciation|petition)\b",
                normalized,
            )
            is not None
        )
        if not has_slot:
            return 2
        if re.search(r"\b(?:passionate|rights?|appreciation|petition)\b", normalized) is not None:
            return 0
        return 1
    return 2


def _focused_primary_exact_turn_text(item: ContextItem) -> str:
    source_id = _primary_exact_turn_source_id(item)
    marker_match = _DIALOGUE_MARKER_RE.search(source_id)
    if marker_match is None:
        return item.text
    marker = _canonical_dialogue_marker(marker_match.group(0))
    matches = tuple(re.finditer(_dialogue_marker_pattern(marker), item.text))
    if not matches:
        return item.text
    text_match = matches[0]
    for match in matches:
        following = item.text[match.end() : match.end() + 48]
        if re.match(r"\s+[A-Z][^:\n]{0,40}:", following):
            text_match = match
            break
    next_match = _DIALOGUE_MARKER_RE.search(item.text[text_match.end() :])
    end = text_match.end() + next_match.start() if next_match is not None else len(item.text)
    return item.text[text_match.start() : end].strip() or item.text


def _primary_exact_turn_marker(item: ContextItem) -> str:
    source_id = _primary_exact_turn_source_id(item)
    marker_match = _DIALOGUE_MARKER_RE.search(source_id)
    if marker_match is None:
        return ""
    return _canonical_dialogue_marker(marker_match.group(0))


def _dialogue_marker_pattern(marker: str) -> str:
    canonical_marker = _canonical_dialogue_marker(marker)
    if ":" not in canonical_marker:
        return rf"\b{re.escape(canonical_marker)}\b"
    dialogue, turn = canonical_marker.split(":", 1)
    return rf"\b{re.escape(dialogue)}[:-]{re.escape(turn)}\b"


def _canonical_dialogue_marker(value: str) -> str:
    match = re.fullmatch(r"D(?P<dialogue>\d+)[:-](?P<turn>\d+)", value.strip())
    if match is None:
        return value
    return f"D{match.group('dialogue')}:{match.group('turn')}"
