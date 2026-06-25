"""Travel place evidence detectors shared by retrieval and reranking."""

from __future__ import annotations

import re

_TRAVEL_PLACE_EVIDENCE_RE = re.compile(
    r"\b(?:england|spain|france|italy|germany|portugal|ireland|sweden|"
    r"rome|paris|london|madrid|berlin|lisbon|dublin|stockholm|"
    r"(?:been|trip|travel(?:ed|led)?|journey|vacation)\s+"
    r"(?:only\s+|once\s+|recently\s+|last\s+\w+\s+|short\s+)?"
    r"(?:to|in)\s+"
    r"(?!country|countries|place|places|area|areas|city|cities|there\b)"
    r"[A-Z][A-Za-z]+|"
    r"(?:visited|went\s+to)\s+"
    r"(?!country|countries|place|places|area|areas|city|cities|there\b)"
    r"[A-Z][A-Za-z]+)\b",
    re.IGNORECASE,
)


def has_travel_place_inventory_evidence(text: str) -> bool:
    return _TRAVEL_PLACE_EVIDENCE_RE.search(text) is not None
