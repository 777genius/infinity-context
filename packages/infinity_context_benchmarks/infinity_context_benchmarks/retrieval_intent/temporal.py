"""Benchmark-owned temporal policy."""

from __future__ import annotations

import re


def infer_time_intent_kind(
    *,
    is_temporal: bool,
    temporal_terms: tuple[str, ...],
    temporal_surface_terms: tuple[str, ...],
) -> str:
    if not is_temporal:
        return "none"
    temporal_term_set = set(temporal_terms)
    if {"how long", "long", "duration"} & temporal_term_set:
        return "duration"
    if {
        "before",
        "beforehand",
        "after",
        "afterward",
        "afterwards",
        "since",
    } & temporal_term_set:
        return "temporal_sequence"
    if _RELATIVE_TIME_TERMS & temporal_term_set or _has_ordinal_event_term(temporal_terms):
        return "relative_time"
    if temporal_surface_terms:
        return "explicit_time"
    return "temporal_lookup"


_RELATIVE_WEEKDAY_TERMS = frozenset(
    f"{modifier} {weekday}"
    for modifier in ("last", "next", "this")
    for weekday in (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    )
)


_RELATIVE_ORDINAL_PERIOD_TERMS = frozenset(
    f"{ordinal} {period}"
    for ordinal in ("first", "second", "third", "fourth", "last")
    for period in ("weekend", "week", "half", "quarter", "month")
)


_RELATIVE_SEASON_TERMS = frozenset(
    f"{modifier} {season}"
    for modifier in ("last", "next", "this")
    for season in ("spring", "summer", "fall", "autumn", "winter")
)


_SEASON_TERMS = frozenset({"spring", "summer", "fall", "autumn", "winter"})


_ORDINAL_EVENT_TERM_RE = re.compile(
    r"\b(?:first|second|third|fourth|fifth|last|latest)\s+"
    r"(?:(?!(?:at|for|in|of|on|place|the)\b)[a-z0-9-]+\s+){0,3}"
    r"(?:call-?out|competition|event|game|project|screenplay|script|"
    r"tournament|tourney|trip)\b"
)


_RELATIVE_TIME_TERMS = (
    frozenset(
        {
            "ago",
            "again",
            "earlier",
            "earlier today",
            "earliest event",
            "early",
            "end",
            "first half",
            "last night",
            "last quarter",
            "last week",
            "last weekend",
            "last month",
            "last year",
            "later",
            "late",
            "latest event",
            "long ago",
            "next month",
            "next quarter",
            "next week",
            "next weekend",
            "next year",
            "previous",
            "recent",
            "second half",
            "since",
            "soon",
            "start",
            "this month",
            "this afternoon",
            "this evening",
            "this morning",
            "this quarter",
            "this week",
            "this weekend",
            "this year",
            "today",
            "tonight",
            "currently",
            "tomorrow afternoon",
            "tomorrow evening",
            "tomorrow morning",
            "tomorrow",
            "upcoming",
            "upcoming event",
            "yesterday afternoon",
            "yesterday evening",
            "yesterday morning",
            "yesterday",
        }
    )
    | _RELATIVE_WEEKDAY_TERMS
    | _RELATIVE_ORDINAL_PERIOD_TERMS
    | _RELATIVE_SEASON_TERMS
    | _SEASON_TERMS
)


def _has_ordinal_event_term(temporal_terms: tuple[str, ...]) -> bool:
    return any(_ORDINAL_EVENT_TERM_RE.search(term) for term in temporal_terms)
