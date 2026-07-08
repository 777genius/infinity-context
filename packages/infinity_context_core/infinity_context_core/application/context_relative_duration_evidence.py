"""Relative-duration evidence helpers for temporal answer grounding."""

from __future__ import annotations

import re

_HOW_LONG_AGO_QUERY_RE = re.compile(
    r"\bhow\s+long\s+ago\b|"
    r"\bhow\s+many\s+(?:years?|months?|weeks?|days?)\s+ago\b",
    re.IGNORECASE,
)
_RELATIVE_DURATION_EVENT_QUERY_RE = re.compile(
    r"\b(?:birthday|anniversary)\b",
    re.IGNORECASE,
)
_RELATIVE_DURATION_EVENT_EVIDENCE_RE = re.compile(
    r"\b(?:birthday|anniversary)\b",
    re.IGNORECASE,
)
_RELATIVE_DURATION_SURFACE_RE = re.compile(
    r"\b(?:"
    r"\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
    r"nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
    r")\s+(?:years?|months?|weeks?|days?)\s+ago\b|"
    r"\b(?:a|one)\s+decade\s+ago\b",
    re.IGNORECASE,
)
_RELATIVE_DURATION_EVENT_REASONS = frozenset(
    {
        "age_birthday_bridge",
        "decomposition_temporal_answer",
    }
)


def has_relative_duration_event_evidence(
    *,
    query: str,
    query_reason: str,
    text: str,
) -> bool:
    """Return true when text directly answers a how-long-ago event question."""

    if not _requests_relative_duration_event(query=query, query_reason=query_reason):
        return False
    return (
        _RELATIVE_DURATION_EVENT_EVIDENCE_RE.search(text) is not None
        and _RELATIVE_DURATION_SURFACE_RE.search(text) is not None
    )


def _requests_relative_duration_event(*, query: str, query_reason: str) -> bool:
    if _HOW_LONG_AGO_QUERY_RE.search(query) is None:
        return False
    if (
        query_reason not in _RELATIVE_DURATION_EVENT_REASONS
        and _RELATIVE_DURATION_EVENT_QUERY_RE.search(query) is None
    ):
        return False
    return _RELATIVE_DURATION_EVENT_QUERY_RE.search(query) is not None
