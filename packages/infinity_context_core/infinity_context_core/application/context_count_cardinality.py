"""Count/cardinality evidence helpers for context ranking."""

from __future__ import annotations

import re

_CARDINALITY_VALUE = (
    r"(?<![:\w])\d{1,3}(?![:\w])|"
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|couple|once|twice)\b"
)
_COUNT_NOUN = r"[A-Za-z][A-Za-z'_-]{2,}"
_VALUE_WITH_OBJECT_RE = re.compile(
    rf"(?:{_CARDINALITY_VALUE})\s+(?:{_COUNT_NOUN}\s+){{0,2}}{_COUNT_NOUN}",
    re.IGNORECASE,
)
_COUNT_LABEL_VALUE_RE = re.compile(
    rf"\b(?:answer|count|number|total|cardinality)\b"
    rf".{{0,32}}(?:{_CARDINALITY_VALUE})",
    re.IGNORECASE | re.DOTALL,
)


def has_exact_count_cardinality_evidence(text: str) -> bool:
    """Return true when text states a count, not only an enumerated list."""

    if not text.strip():
        return False
    return bool(
        _VALUE_WITH_OBJECT_RE.search(text)
        or _COUNT_LABEL_VALUE_RE.search(text)
    )
