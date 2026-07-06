"""Source-turn order helpers for temporal context retrieval."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from infinity_context_core.application.context_diagnostics import safe_diagnostic_mapping
from infinity_context_core.application.dto import ContextItem


@dataclass(frozen=True, order=True)
class SourceTurnRef:
    dialogue: int
    turn: int

    def label(self) -> str:
        return f"D{self.dialogue}:{self.turn}"


@dataclass(frozen=True)
class SourceTurnSequenceRequest:
    after_turns: tuple[SourceTurnRef, ...] = ()
    before_turns: tuple[SourceTurnRef, ...] = ()

    @property
    def empty(self) -> bool:
        return not self.after_turns and not self.before_turns


@dataclass(frozen=True)
class SourceTurnSequenceSignal:
    boost: float = 0.0
    reason: str = ""
    code: str = ""

    @property
    def empty(self) -> bool:
        return self.boost == 0.0


_SOURCE_TURN_LABEL_PATTERN = r"D\d{1,4}[:-]\d{1,4}"
_SOURCE_TURN_RE = re.compile(
    r"\bD(?P<dialogue>\d{1,4})[:-](?P<turn>\d{1,4})\b",
    re.IGNORECASE,
)
_AFTER_SOURCE_TURN_RE = re.compile(
    r"\b(?:right\s+after|immediately\s+after|shortly\s+after|after|following|since)"
    r"\s+(?:the\s+)?(?:(?:source\s+)?(?:ref|reference)\s+)?"
    r"(?:source\s+)?(?:turn\s+)?"
    rf"(?P<ref>(?:[^\s:]+:)*{_SOURCE_TURN_LABEL_PATTERN}(?::turn)?)\b",
    re.IGNORECASE,
)
_BEFORE_SOURCE_TURN_RE = re.compile(
    r"\b(?:right\s+before|immediately\s+before|shortly\s+before|before|prior\s+to|"
    r"until|up\s+to)\s+(?:the\s+)?(?:(?:source\s+)?(?:ref|reference)\s+)?"
    r"(?:source\s+)?(?:turn\s+)?"
    rf"(?P<ref>(?:[^\s:]+:)*{_SOURCE_TURN_LABEL_PATTERN}(?::turn)?)\b",
    re.IGNORECASE,
)


def source_turn_sequence_request(query: str) -> SourceTurnSequenceRequest:
    """Return explicit before/after source-turn boundaries from a query."""

    return SourceTurnSequenceRequest(
        after_turns=_source_turns_for_regex(_AFTER_SOURCE_TURN_RE, query),
        before_turns=_source_turns_for_regex(_BEFORE_SOURCE_TURN_RE, query),
    )


def source_turn_sequence_boost_signal(
    item: ContextItem,
    *,
    request: SourceTurnSequenceRequest,
) -> SourceTurnSequenceSignal:
    """Score item source turns against explicit query source-turn boundaries."""

    if request.empty:
        return SourceTurnSequenceSignal()
    item_turns = source_turn_refs_from_item(item)
    if not item_turns:
        return SourceTurnSequenceSignal()
    if request.after_turns:
        return _source_turn_direction_signal(
            item_turns=item_turns,
            boundaries=request.after_turns,
            direction="after",
        )
    return _source_turn_direction_signal(
        item_turns=item_turns,
        boundaries=request.before_turns,
        direction="before",
    )


def source_turn_refs_from_item(item: ContextItem) -> tuple[SourceTurnRef, ...]:
    values: list[str] = [item.item_id, item.text]
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    metadata = safe_diagnostic_mapping(diagnostics.get("metadata"))
    for mapping in (diagnostics, provenance, metadata):
        values.extend(_string_values(mapping))
    for ref in item.source_refs:
        values.extend(
            str(value)
            for value in (
                ref.source_id,
                ref.chunk_id,
                ref.quote_preview,
            )
            if value
        )
    return _source_turns_from_values(tuple(values))


def _source_turn_direction_signal(
    *,
    item_turns: tuple[SourceTurnRef, ...],
    boundaries: tuple[SourceTurnRef, ...],
    direction: str,
) -> SourceTurnSequenceSignal:
    if direction == "after":
        if any(item_turn > boundary for item_turn in item_turns for boundary in boundaries):
            return SourceTurnSequenceSignal(
                boost=0.04,
                reason="query asks for after source turn and item source turn follows boundary",
                code="after_source_turn_match",
            )
        if any(item_turn <= boundary for item_turn in item_turns for boundary in boundaries):
            return SourceTurnSequenceSignal(
                boost=-0.026,
                reason="query asks for after source turn and item source turn precedes boundary",
                code="after_source_turn_conflict",
            )
    if any(item_turn < boundary for item_turn in item_turns for boundary in boundaries):
        return SourceTurnSequenceSignal(
            boost=0.04,
            reason="query asks for before source turn and item source turn precedes boundary",
            code="before_source_turn_match",
        )
    if any(item_turn >= boundary for item_turn in item_turns for boundary in boundaries):
        return SourceTurnSequenceSignal(
            boost=-0.026,
            reason="query asks for before source turn and item source turn follows boundary",
            code="before_source_turn_conflict",
        )
    return SourceTurnSequenceSignal()


def _source_turns_for_regex(regex: re.Pattern[str], text: str) -> tuple[SourceTurnRef, ...]:
    seen: dict[SourceTurnRef, None] = {}
    for match in regex.finditer(text):
        if source_turn := _source_turn_from_label(match.group("ref")):
            seen.setdefault(source_turn, None)
    return tuple(seen)


def _source_turns_from_values(values: tuple[str, ...]) -> tuple[SourceTurnRef, ...]:
    seen: dict[SourceTurnRef, None] = {}
    for value in values:
        for match in _SOURCE_TURN_RE.finditer(value):
            seen.setdefault(
                SourceTurnRef(
                    dialogue=int(match.group("dialogue")),
                    turn=int(match.group("turn")),
                ),
                None,
            )
    return tuple(seen)


def _source_turn_from_label(value: str) -> SourceTurnRef | None:
    match = _SOURCE_TURN_RE.search(value.strip())
    if match is None:
        return None
    return SourceTurnRef(
        dialogue=int(match.group("dialogue")),
        turn=int(match.group("turn")),
    )


def _string_values(mapping: Mapping[str, object]) -> tuple[str, ...]:
    values: list[str] = []
    for value in mapping.values():
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, (list, tuple)):
            values.extend(str(item) for item in value if isinstance(item, str))
    return tuple(values)
