"""Relationship-status evidence helpers for context assembly."""

from __future__ import annotations

import re

RELATIONSHIP_STATUS_REASONS = frozenset(
    {
        "relationship_status_bridge",
        "decomposition_relationship_status",
    }
)

_RELATIONSHIP_STATUS_WORK_PARTNER_RE = re.compile(
    r"\b(?:accountability|business|class|cofounder|co-founder|conversation|"
    r"dance|founder|gym|lab|project|research|running|school|sparring|startup|"
    r"study|team|training|volunteer|work)\s+partners?\b|"
    r"\bpartners?\s+(?:on|for|in)\s+"
    r"(?:business|class|gym|lab|project|research|running|school|startup|study|"
    r"team|training|volunteer|work)\b",
    re.IGNORECASE,
)
_RELATIONSHIP_STATUS_EXACT_RE = re.compile(
    r"\b(?:relationship\s+status|single\s+parent|single\b|not\s+dating|"
    r"dating|boyfriend|girlfriend|fianc[eé]e?|romantic\s+partner|"
    r"life\s+partner|spouse|husband|wife|married|marriage|wedding|"
    r"got\s+married|divorced|separated|widow(?:ed|er)?|breakup|"
    r"broke\s+up|split\s+up|in\s+a\s+relationship)\b",
    re.IGNORECASE,
)
_RELATIONSHIP_STATUS_PRIMARY_RE = re.compile(
    r"\b(?:spouse|husband|wife|married|marriage|wedding|got\s+married)\b",
    re.IGNORECASE,
)
_RELATIONSHIP_STATUS_ROMANTIC_RE = re.compile(
    r"\b(?:dating|boyfriend|girlfriend|fianc[eé]e?|romantic\s+partner|"
    r"life\s+partner|in\s+a\s+relationship)\b",
    re.IGNORECASE,
)
_RELATIONSHIP_STATUS_NEGATIVE_RE = re.compile(
    r"\b(?:single\s+parent|single\b|not\s+dating|divorced|separated|"
    r"widow(?:ed|er)?|breakup|broke\s+up|split\s+up)\b",
    re.IGNORECASE,
)


def is_relationship_status_reason(reason: str) -> bool:
    return reason in RELATIONSHIP_STATUS_REASONS or reason.replace("-", "_") in (
        "relationship_status_bridge",
        "decomposition_relationship_status",
    )


def is_relationship_status_answer_evidence(
    *,
    expansion_reason: str,
    text: str,
) -> bool:
    if not is_relationship_status_reason(expansion_reason):
        return False
    if _RELATIONSHIP_STATUS_WORK_PARTNER_RE.search(text) is not None:
        return False
    return _RELATIONSHIP_STATUS_EXACT_RE.search(text) is not None


def relationship_status_answer_rank(text: str) -> int:
    if _RELATIONSHIP_STATUS_WORK_PARTNER_RE.search(text) is not None:
        return 9
    if _RELATIONSHIP_STATUS_PRIMARY_RE.search(text) is not None:
        return 0
    if _RELATIONSHIP_STATUS_ROMANTIC_RE.search(text) is not None:
        return 1
    if _RELATIONSHIP_STATUS_NEGATIVE_RE.search(text) is not None:
        return 2
    return 9


__all__ = (
    "RELATIONSHIP_STATUS_REASONS",
    "is_relationship_status_answer_evidence",
    "is_relationship_status_reason",
    "relationship_status_answer_rank",
)
