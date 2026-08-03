"""Strict retrieval policy for chronological museum-visit inventories."""

from __future__ import annotations

import re

_ORDERED_MUSEUM_QUERY_RE = re.compile(
    r"(?=.*\bmuseums?\b)"
    r"(?=.*\bvisit(?:ed|ing|s)?\b)"
    r"(?=.*\b(?:chronological(?:ly)?|earliest|latest|order(?:ed)?|sequence)\b)",
    re.IGNORECASE | re.DOTALL,
)
_DATED_SOURCE_RE = re.compile(
    r"\bsession-[0-9]+\s+date:\s+[0-9]{4}/[0-9]{2}/[0-9]{2}\b",
    re.IGNORECASE,
)
_MUSEUM_RE = re.compile(r"\b(?:museum|museums|gallery|galleries)\b", re.IGNORECASE)
_DIRECT_VISIT_RE = re.compile(
    r"\b(?:attended|explored|participated\s+in|saw|took|toured|visited|went\s+to)\b",
    re.IGNORECASE,
)
_VISIT_CONTEXT_RE = re.compile(
    r"\b(?:exhibit(?:ion)?|guided\s+tour|lecture|tour|workshop)\b",
    re.IGNORECASE,
)
_DIRECT_EVENT_TIME_RE = re.compile(
    r"\b(?:today|yesterday|this\s+(?:morning|afternoon|evening)|last\s+night)\b",
    re.IGNORECASE,
)
_PLANNED_ONLY_RE = re.compile(
    r"\b(?:hope|intend|plan(?:ning)?|want|would\s+like)\s+to\s+visit\b",
    re.IGNORECASE,
)


def ordered_museum_visit_query(query: str) -> bool:
    """Return whether the query requests a museum visit chronology."""

    return _ORDERED_MUSEUM_QUERY_RE.search(_bounded(query)) is not None


def strong_dated_museum_visit_evidence(*, query: str, text: str) -> bool:
    """Recognize source-dated first-person visit evidence, excluding plans."""

    if not ordered_museum_visit_query(query):
        return False
    bounded = _bounded(text, limit=8_000)
    if _DATED_SOURCE_RE.search(bounded) is None or _MUSEUM_RE.search(bounded) is None:
        return False
    direct_match = _DIRECT_VISIT_RE.search(bounded)
    event_time_match = _DIRECT_EVENT_TIME_RE.search(bounded)
    if (
        direct_match is None
        or event_time_match is None
        or abs(direct_match.start() - event_time_match.start()) > 300
    ):
        return False
    if _PLANNED_ONLY_RE.search(bounded) is not None and _VISIT_CONTEXT_RE.search(bounded) is None:
        return False
    museum_match = _MUSEUM_RE.search(bounded)
    assert museum_match is not None
    return abs(direct_match.start() - museum_match.start()) <= 360


def _bounded(value: str, *, limit: int = 1_000) -> str:
    return " ".join(str(value or "")[:limit].split())
