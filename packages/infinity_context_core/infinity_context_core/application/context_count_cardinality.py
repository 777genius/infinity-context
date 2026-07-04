"""Count/cardinality evidence helpers for context ranking."""

from __future__ import annotations

import re

_CARDINALITY_VALUE = (
    r"(?<![:\w])\d{1,3}(?![:\w])|"
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|couple|once|twice)\b"
)
_COUNT_OBJECT_VALUE = (
    r"(?<![:\w])\d{1,3}(?![:\w])|"
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|couple)\b"
)
_COUNT_NOUN = r"[A-Za-z][A-Za-z'_-]{2,}"
_VALUE_WITH_OBJECT_RE = re.compile(
    rf"(?:{_COUNT_OBJECT_VALUE})\s+(?:{_COUNT_NOUN}\s+){{0,2}}{_COUNT_NOUN}",
    re.IGNORECASE,
)
_COUNT_TIMES_RE = re.compile(
    rf"(?:{_CARDINALITY_VALUE})\s+times?\b",
    re.IGNORECASE,
)
_COUNT_ADVERB_RE = re.compile(
    r"\b(?:once|twice)\b(?!\s+(?:a|per|daily|weekly|monthly|yearly|annually)\b)",
    re.IGNORECASE,
)
_COUNT_RANGE_RE = re.compile(r"\bonce\s+or\s+twice\b", re.IGNORECASE)
_COUNT_LABEL_VALUE_RE = re.compile(
    rf"\b(?:answer|count|number|total|cardinality)\b"
    rf".{{0,32}}(?:{_CARDINALITY_VALUE})",
    re.IGNORECASE | re.DOTALL,
)
_BOTH_PAIR_RE = re.compile(
    r"\bboth\s+"
    r"(?!before\b|after\b|during\b)"
    r"[A-Za-z][A-Za-z'_-]{1,40}(?:\s+[A-Za-z][A-Za-z'_-]{1,40}){0,3}"
    r"\s+and\s+"
    r"(?!before\b|after\b|during\b|then\b)"
    r"[A-Za-z][A-Za-z'_-]{1,40}(?:\s+[A-Za-z][A-Za-z'_-]{1,40}){0,3}\b",
    re.IGNORECASE,
)


def has_exact_count_cardinality_evidence(text: str) -> bool:
    """Return true when text states a count, not only an enumerated list."""

    if not text.strip():
        return False
    has_standalone_count_adverb = bool(_COUNT_ADVERB_RE.search(text)) and not bool(
        _COUNT_RANGE_RE.search(text)
    )
    return bool(
        _VALUE_WITH_OBJECT_RE.search(text)
        or _COUNT_TIMES_RE.search(text)
        or has_standalone_count_adverb
        or _COUNT_LABEL_VALUE_RE.search(text)
        or _BOTH_PAIR_RE.search(text)
    )
