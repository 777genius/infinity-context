"""Bounded, query-derived temporal ordering intent."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from infinity_context_core.application.context_lexical import query_terms

_MAX_ENDPOINTS = 4


class TemporalOrderingKind(StrEnum):
    ORDER = "order"
    RECENCY = "recency"


@dataclass(frozen=True)
class TemporalEndpoint:
    slot_id: str
    query: str


@dataclass(frozen=True)
class TemporalOrderingIntent:
    kind: TemporalOrderingKind | None = None
    endpoints: tuple[TemporalEndpoint, ...] = ()

    @property
    def explicit(self) -> bool:
        return self.kind is not None


_ORDER_RE = re.compile(
    r"\b(?:in\s+(?:what|which)\s+order|chronological(?:ly)?|timeline|"
    r"from\s+(?:first|earliest)\s+to\s+(?:last|latest)|"
    r"(?:which|what)(?:\s+event)?\s+(?:happened|occurred|came|was)\s+"
    r"(?:first|earlier|last|latest)|(?:happened|occurred|came)\s+"
    r"(?:first|earlier|last|latest))\b",
    re.IGNORECASE,
)
_RECENCY_RE = re.compile(
    r"\b(?:which|what)(?:\s+event)?\s+(?:happened|occurred|was|is)\s+"
    r"(?:later|more\s+recent(?:ly)?|most\s+recent(?:ly)?)\b",
    re.IGNORECASE,
)
_BEFORE_AFTER_RE = re.compile(
    r"^(?:did\s+.+?|was\s+.+?)\s+(?:before|after)\s+.+?[?.!]*$",
    re.IGNORECASE | re.DOTALL,
)
_COMPARISON_BODY_RE = re.compile(
    r"\b(?:which|what)(?:\s+event)?\s+(?:happened|occurred|came|was|is)\s+"
    r"(?:first|earlier|last|latest|later|more\s+recent(?:ly)?|most\s+recent(?:ly)?)"
    r"\s*[,;:\-]?\s*(?P<body>.+?)(?:[?.!]|$)",
    re.IGNORECASE | re.DOTALL,
)
_BEFORE_AFTER_BODY_RE = re.compile(
    r"^(?:did\s+)?(?P<first>.+?)\s+(?:happen\s+|was\s+)?"
    r"(?:before|after)\s+(?P<second>.+?)(?:[?.!]|$)",
    re.IGNORECASE | re.DOTALL,
)
_ORDER_BODY_RE = re.compile(
    r"\bin\s+(?:what|which)\s+order\s+did\s+(?P<body>.+?)\s+"
    r"(?:happen|occur)(?:[?.!]|$)",
    re.IGNORECASE | re.DOTALL,
)
_ALTERNATIVE_RE = re.compile(r"\s+(?:or|versus|vs\.?)\s+", re.IGNORECASE)
_ORDER_ITEM_RE = re.compile(r"\s*(?:,|;|\band\b)\s*", re.IGNORECASE)
_STOP_TERMS = frozenset(
    {
        "and",
        "did",
        "event",
        "first",
        "happen",
        "happened",
        "last",
        "later",
        "latest",
        "more",
        "most",
        "occurred",
        "or",
        "recent",
        "recently",
        "the",
        "what",
        "which",
    }
)


def temporal_ordering_intent(query: str) -> TemporalOrderingIntent:
    """Recognize only explicit ordering relations and question-stated endpoints."""

    kind = _kind(query)
    if kind is None:
        return TemporalOrderingIntent()
    values = _endpoint_values(query)
    endpoints = tuple(
        TemporalEndpoint(f"decomposition_temporal_endpoint_{index}", value)
        for index, value in enumerate(values[:_MAX_ENDPOINTS], start=1)
    )
    return TemporalOrderingIntent(kind=kind, endpoints=endpoints)


def _kind(query: str) -> TemporalOrderingKind | None:
    if _RECENCY_RE.search(query):
        return TemporalOrderingKind.RECENCY
    if _ORDER_RE.search(query) or _BEFORE_AFTER_RE.search(query):
        return TemporalOrderingKind.ORDER
    return None


def _endpoint_values(query: str) -> tuple[str, ...]:
    match = _COMPARISON_BODY_RE.search(query)
    if match:
        values = _ALTERNATIVE_RE.split(match.group("body"))
        return _validated(values) if len(values) >= 2 else ()
    match = _BEFORE_AFTER_BODY_RE.search(query)
    if match:
        return _validated((match.group("first"), match.group("second")))
    match = _ORDER_BODY_RE.search(query)
    if match:
        values = [value for value in _ORDER_ITEM_RE.split(match.group("body")) if value]
        return _validated(values) if len(values) >= 2 else ()
    return ()


def _validated(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    selected: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = " ".join(raw.strip(" \t\r\n,;:.!?-").split())
        key = value.casefold()
        informative = {
            variant.casefold()
            for term in query_terms(value, min_chars=2, max_terms=16)
            for variant in term.variants
            if variant.casefold() not in _STOP_TERMS
        }
        if value and key not in seen and len(informative) >= 2:
            selected.append(value)
            seen.add(key)
    return tuple(selected)
