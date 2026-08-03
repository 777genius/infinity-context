"""State transition query helpers for current-vs-previous retrieval."""

from __future__ import annotations

import re

_STATE_TRANSITION_QUERY_RE = re.compile(
    r"\b(?:switch(?:ed|ing)?|migrat(?:e|ed|ing)|transition(?:ed|ing)?|"
    r"replac(?:e|ed|ing))\b"
    r"(?=.{0,100}\b(?:from|to|with|by|instead\s+of)\b)|"
    r"\bchanged?\b(?=.{0,100}\b(?:from|to)\b)|"
    r"\b(?:from|previous|old|stale|superseded)\b"
    r"(?=.{0,100}\b(?:to|current|new|active|replacement|replaced\s+by)\b)|"
    r"\b(?:what|which)\b(?=.{0,120}\b(?:replaced|superseded|took\s+over|"
    r"switched\s+to|migrated\s+to)\b)|"
    r"\b(?:что|какой|какая|какое|какие)\b"
    r"(?=.{0,120}\b(?:заменил\w*|сменил\w*|переш[её]л\w*|"
    r"мигрировал\w*)\b)|"
    r"\b(?:заменил\w*|сменил\w*|переключил\w*|переш[её]л\w*|"
    r"мигрировал\w*)\b(?=.{0,100}\b(?:с|со|на|вместо)\b)",
    re.IGNORECASE | re.DOTALL,
)

_STATE_TRANSITION_QUERY_VARIANTS = frozenset(
    {
        "state_transition_request",
    }
)
_DIRECTIONAL_ALTERNATIVES_RE = re.compile(
    r"\b(?:more|less|higher|lower|increase|decrease)\b"
    r".{0,100}\b(?:or|versus|vs\.?)\b.{0,100}"
    r"\b(?:more|less|higher|lower|increase|decrease)\b",
    re.IGNORECASE | re.DOTALL,
)


def state_transition_query_variants(query: str) -> frozenset[str]:
    if not _STATE_TRANSITION_QUERY_RE.search(query):
        return frozenset()
    return _STATE_TRANSITION_QUERY_VARIANTS


def state_transition_requires_pair(query: str) -> bool:
    """Recognize an explicit directional switch that needs old and new evidence."""

    return bool(
        isinstance(query, str)
        and _STATE_TRANSITION_QUERY_RE.search(query)
        and _DIRECTIONAL_ALTERNATIVES_RE.search(query)
    )


__all__ = ("state_transition_query_variants", "state_transition_requires_pair")
