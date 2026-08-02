"""Question-only requirements for two-endpoint temporal interval retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass

from infinity_context_core.application.context_lexical import query_terms

_MAX_ENDPOINTS = 2
_MAX_ENDPOINT_CHARS = 180
_INTERVAL_PREFIX = (
    r"\bhow\s+(?:(?:many\s+days?)|(?:much\s+time))\s+"
    r"(?:(?:has|had)\s+)?passed\b"
)
_BETWEEN_RE = re.compile(
    rf"{_INTERVAL_PREFIX}\s+between\s+"
    r"(?P<first>[^?!.]{1,180}?)\s+and\s+(?P<second>[^?!.]{1,180}?)(?:[?!.]|$)",
    re.IGNORECASE,
)
_FROM_TO_RE = re.compile(
    rf"{_INTERVAL_PREFIX}\s+from\s+"
    r"(?P<first>[^?!.]{1,180}?)\s+(?:to|until)\s+"
    r"(?P<second>[^?!.]{1,180}?)(?:[?!.]|$)",
    re.IGNORECASE,
)
_ENDPOINT_STOP_TERMS = frozenset(
    {
        "and",
        "between",
        "day",
        "days",
        "from",
        "last",
        "the",
        "time",
        "to",
        "until",
    }
)


@dataclass(frozen=True, slots=True)
class TemporalIntervalEndpoint:
    """One explicit question-derived temporal interval boundary."""

    slot_id: str
    query: str


@dataclass(frozen=True, slots=True)
class TemporalIntervalRequirements:
    """At most two independent boundaries without answer-side state."""

    endpoints: tuple[TemporalIntervalEndpoint, ...] = ()

    @property
    def explicit(self) -> bool:
        return len(self.endpoints) == _MAX_ENDPOINTS


def temporal_interval_requirements(query: str) -> TemporalIntervalRequirements:
    """Recognize only explicit how-many-days/time-passed endpoint pairs."""

    if not isinstance(query, str) or not query.strip():
        return TemporalIntervalRequirements()
    match = _BETWEEN_RE.search(query) or _FROM_TO_RE.search(query)
    if match is None:
        return TemporalIntervalRequirements()
    values = _validated_endpoints((match.group("first"), match.group("second")))
    if len(values) != _MAX_ENDPOINTS:
        return TemporalIntervalRequirements()
    return TemporalIntervalRequirements(
        endpoints=tuple(
            TemporalIntervalEndpoint(
                slot_id=f"decomposition_temporal_interval_endpoint_{index}",
                query=value,
            )
            for index, value in enumerate(values, start=1)
        )
    )


def _validated_endpoints(values: tuple[str, str]) -> tuple[str, ...]:
    selected: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = " ".join(raw.strip(" \t\r\n,;:.!?-").split())[:_MAX_ENDPOINT_CHARS].rstrip()
        key = value.casefold()
        informative_terms = tuple(
            term
            for term in query_terms(value, min_chars=2, max_terms=16)
            if term.raw.casefold() not in _ENDPOINT_STOP_TERMS
        )
        if not value or key in seen or len(informative_terms) < 2:
            continue
        selected.append(value)
        seen.add(key)
    return tuple(selected[:_MAX_ENDPOINTS])


__all__ = (
    "TemporalIntervalEndpoint",
    "TemporalIntervalRequirements",
    "temporal_interval_requirements",
)

