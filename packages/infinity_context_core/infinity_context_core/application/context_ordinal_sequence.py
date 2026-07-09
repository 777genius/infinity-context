"""Ordinal sequence evidence signals for deterministic context rerank."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class OrdinalSequenceSignal:
    boost: float = 0.0
    penalty: float = 0.0
    reason: str = ""


_ORDINAL_VALUES: dict[str, int | str] = {
    "first": 1,
    "1st": 1,
    "one": 1,
    "second": 2,
    "2nd": 2,
    "two": 2,
    "third": 3,
    "3rd": 3,
    "three": 3,
    "fourth": 4,
    "4th": 4,
    "four": 4,
    "fifth": 5,
    "5th": 5,
    "five": 5,
    "last": "last",
    "final": "last",
}
_ORDINAL_TOKEN_RE = r"first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|last|final"
_SEQUENCE_TARGET_RE = r"steps?|stops?|events?|items?"
_SEQUENCE_CONTEXT_RE = re.compile(
    r"\b(?:sequence|ordered|order|list|route|itinerary|timeline|checklist|process|"
    r"workflow|procedure|plan|agenda)\b",
    re.IGNORECASE,
)
_QUERY_ORDINAL_TARGET_RE = re.compile(
    rf"\b(?P<ordinal>{_ORDINAL_TOKEN_RE})\s+"
    rf"(?:(?:\w+)\s+){{0,3}}(?P<target>{_SEQUENCE_TARGET_RE})\b",
    re.IGNORECASE,
)
_QUERY_TARGET_ORDINAL_RE = re.compile(
    rf"\b(?P<target>{_SEQUENCE_TARGET_RE})\b"
    rf"(?=.{{0,60}}\b(?P<ordinal>{_ORDINAL_TOKEN_RE})\b)",
    re.IGNORECASE | re.DOTALL,
)
_EVIDENCE_ORDINAL_TARGET_RE = re.compile(
    rf"\b(?P<ordinal>{_ORDINAL_TOKEN_RE}|[1-9])\s*"
    rf"(?:[.)#:-]\s*)?(?:(?:\w+)\s+){{0,3}}(?P<target>{_SEQUENCE_TARGET_RE})\b",
    re.IGNORECASE,
)
_EVIDENCE_TARGET_ORDINAL_RE = re.compile(
    rf"\b(?P<target>{_SEQUENCE_TARGET_RE})\s*(?:#|number|no\.?)?\s*"
    rf"(?P<ordinal>{_ORDINAL_TOKEN_RE}|[1-9])\b",
    re.IGNORECASE,
)
_EVIDENCE_LIST_MARKER_RE = re.compile(
    rf"(?m)^\s*(?P<ordinal>[1-9]|{_ORDINAL_TOKEN_RE})[\s.)#:-]+",
    re.IGNORECASE,
)


def ordinal_sequence_rerank_signal(*, query: str, text: str) -> OrdinalSequenceSignal:
    request = _ordinal_sequence_request(query)
    if request is None:
        return OrdinalSequenceSignal()
    requested_ordinal, target = request
    evidence_ordinals = _evidence_ordinals(text, target=target)
    if requested_ordinal in evidence_ordinals:
        return OrdinalSequenceSignal(
            boost=0.04,
            reason="ordinal_sequence_exact_evidence",
        )
    if evidence_ordinals and requested_ordinal not in evidence_ordinals:
        return OrdinalSequenceSignal(
            penalty=0.1,
            reason="ordinal_sequence_order_conflict",
        )
    return OrdinalSequenceSignal()


def _ordinal_sequence_request(query: str) -> tuple[int | str, str] | None:
    normalized = " ".join(str(query or "").casefold().split())
    match = _QUERY_ORDINAL_TARGET_RE.search(normalized)
    if match is None:
        match = _QUERY_TARGET_ORDINAL_RE.search(normalized)
    if match is None:
        return None
    ordinal = _ordinal_value(match.group("ordinal"))
    target = _singular_target(match.group("target"))
    if ordinal is None:
        return None
    if target == "event" and ordinal == "last" and not _SEQUENCE_CONTEXT_RE.search(normalized):
        return None
    return ordinal, target


def _evidence_ordinals(text: str, *, target: str) -> frozenset[int | str]:
    normalized = " ".join(str(text or "").casefold().split())
    ordinals: set[int | str] = set()
    target_re = _target_regex(target)
    for regex in (_EVIDENCE_ORDINAL_TARGET_RE, _EVIDENCE_TARGET_ORDINAL_RE):
        for match in regex.finditer(normalized):
            if not target_re.fullmatch(match.group("target")):
                continue
            if ordinal := _ordinal_value(match.group("ordinal")):
                ordinals.add(ordinal)
    if target_re.search(normalized):
        for match in _EVIDENCE_LIST_MARKER_RE.finditer(str(text or "")):
            if ordinal := _ordinal_value(match.group("ordinal")):
                ordinals.add(ordinal)
    return frozenset(ordinals)


def _ordinal_value(value: str) -> int | str | None:
    token = value.casefold().strip()
    if token.isdigit():
        parsed = int(token)
        return parsed if 1 <= parsed <= 9 else None
    return _ORDINAL_VALUES.get(token)


def _singular_target(value: str) -> str:
    target = value.casefold().strip()
    return target[:-1] if target.endswith("s") else target


def _target_regex(target: str) -> re.Pattern[str]:
    return re.compile(rf"{re.escape(target)}s?", re.IGNORECASE)
