"""English textual date helpers for query expansion and evidence ranking."""

from __future__ import annotations

import re

_EN_MONTH_ALIASES = {
    "jan": "january",
    "january": "january",
    "feb": "february",
    "february": "february",
    "mar": "march",
    "march": "march",
    "apr": "april",
    "april": "april",
    "may": "may",
    "jun": "june",
    "june": "june",
    "jul": "july",
    "july": "july",
    "aug": "august",
    "august": "august",
    "sep": "september",
    "sept": "september",
    "september": "september",
    "oct": "october",
    "october": "october",
    "nov": "november",
    "november": "november",
    "dec": "december",
    "december": "december",
}
_EN_TEXTUAL_MONTH_YEAR_RE = re.compile(
    r"\b(?P<month>january|jan|february|feb|march|mar|april|apr|may|june|jun|"
    r"july|jul|august|aug|september|sep|sept|october|oct|november|nov|"
    r"december|dec)\.?\s*,?\s+(?P<year>(?:19|20)\d{2})\b",
    re.IGNORECASE,
)


def english_textual_month_year_terms(text: str) -> tuple[str, ...]:
    """Return canonical English month-year anchors such as ``may 2023``."""

    terms: list[str] = []
    seen: set[str] = set()
    for match in _EN_TEXTUAL_MONTH_YEAR_RE.finditer(text):
        month = _EN_MONTH_ALIASES[match.group("month").casefold()]
        term = f"{month} {match.group('year')}"
        if term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return tuple(terms)
