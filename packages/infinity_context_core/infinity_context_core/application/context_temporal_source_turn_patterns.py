"""Regex catalog for source-turn temporal query parsing."""

from __future__ import annotations

import re

_SOURCE_TURN_LABEL_PATTERN = r"D\d{1,4}[:-]\d{1,4}"
_SOURCE_TURN_RE = re.compile(
    r"\bD(?P<dialogue>\d{1,4})[:-](?P<turn>\d{1,4})\b",
    re.IGNORECASE,
)
_SOURCE_TURN_IDENTITY_RE = re.compile(rf"\b{_SOURCE_TURN_LABEL_PATTERN}\b", re.IGNORECASE)
_SOURCE_TURN_REF_TOKEN = rf"[^\s]*{_SOURCE_TURN_LABEL_PATTERN}[^\s]*"
_TURN_RADIUS_TOKEN = r"\d{1,2}|one|two|three|four|five|(?:a\s+)?couple(?:\s+of)?"


def _source_turn_regex(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


_SOURCE_SCOPE_PATTERN = (
    r"\s+(?:in|from|for|within)\s+(?:the\s+)?"
    r"(?:(?:source\s+)?(?:ref|reference)|source|conversation|conv)\s+"
    r"(?P<scope>[^\s]+)"
)
_QUERY_SOURCE_SCOPE_RE = _source_turn_regex(
    r"\b(?:in|from|for|within)\s+(?:the\s+)?"
    r"(?:(?:source\s+)?(?:ref|reference)|source|conversation|conv)\s+"
    r"(?P<scope>[^\s]+)"
)
_QUERY_DIRECT_SOURCE_SCOPE_RE = _source_turn_regex(
    r"\b(?:in|from|for|within)\s+(?P<scope>[^\s]+)"
)
_AFTER_SOURCE_TURN_PATTERN = (
    r"\b(?:right\s+after|immediately\s+after|shortly\s+after|after|following|since)"
    r"\s+(?:the\s+)?(?:(?:source\s+)?(?:ref|reference)\s+)?"
    r"(?:source\s+)?(?:turn\s+)?"
    rf"(?P<ref>{_SOURCE_TURN_REF_TOKEN})"
)
_BEFORE_SOURCE_TURN_PATTERN = (
    r"\b(?:right\s+before|immediately\s+before|shortly\s+before|before|prior\s+to|"
    r"until|up\s+to)\s+(?:the\s+)?(?:(?:source\s+)?(?:ref|reference)\s+)?"
    r"(?:source\s+)?(?:turn\s+)?"
    rf"(?P<ref>{_SOURCE_TURN_REF_TOKEN})"
)
_BETWEEN_SOURCE_TURN_PATTERN = (
    r"\b(?:between|from)\s+(?:the\s+)?(?:(?:source\s+)?(?:ref|reference)s?\s+)?"
    r"(?:source\s+)?(?:turn\s+)?"
    rf"(?P<after_ref>{_SOURCE_TURN_REF_TOKEN})"
    r"\s+(?:and|to|through|until)\s+(?:the\s+)?"
    r"(?:(?:source\s+)?(?:ref|reference)\s+)?(?:source\s+)?(?:turn\s+)?"
    rf"(?P<before_ref>{_SOURCE_TURN_REF_TOKEN})"
)
_NEAR_SOURCE_TURN_PATTERN = (
    r"\b(?:around|near|nearby|close\s+to|adjacent\s+to|same\s+turn\s+as)"
    r"\s+(?:the\s+)?(?:(?:source\s+)?(?:ref|reference)\s+)?"
    r"(?:source\s+)?(?:turn\s+)?"
    rf"(?P<ref>{_SOURCE_TURN_REF_TOKEN})"
)
_WITHIN_SOURCE_TURN_PATTERN = (
    rf"\bwithin\s+(?P<radius>{_TURN_RADIUS_TOKEN})\s+"
    r"(?:source\s+)?turns?\s+(?:of|around|near)\s+"
    r"(?:the\s+)?(?:(?:source\s+)?(?:ref|reference)\s+)?"
    r"(?:source\s+)?(?:turn\s+)?"
    rf"(?P<ref>{_SOURCE_TURN_REF_TOKEN})"
)
_WITHIN_AFTER_SOURCE_TURN_PATTERN = (
    rf"\bwithin\s+(?P<radius>{_TURN_RADIUS_TOKEN})\s+"
    r"(?:source\s+)?turns?\s+"
    r"(?:right\s+after|immediately\s+after|shortly\s+after|after|following)\s+"
    r"(?:the\s+)?(?:(?:source\s+)?(?:ref|reference)\s+)?"
    r"(?:source\s+)?(?:turn\s+)?"
    rf"(?P<ref>{_SOURCE_TURN_REF_TOKEN})"
)
_WITHIN_BEFORE_SOURCE_TURN_PATTERN = (
    rf"\bwithin\s+(?P<radius>{_TURN_RADIUS_TOKEN})\s+"
    r"(?:source\s+)?turns?\s+"
    r"(?:right\s+before|immediately\s+before|shortly\s+before|before|prior\s+to)\s+"
    r"(?:the\s+)?(?:(?:source\s+)?(?:ref|reference)\s+)?"
    r"(?:source\s+)?(?:turn\s+)?"
    rf"(?P<ref>{_SOURCE_TURN_REF_TOKEN})"
)
_NEXT_AFTER_SOURCE_TURN_PATTERN = (
    rf"\b(?:next|following)\s+(?P<radius>{_TURN_RADIUS_TOKEN})\s+"
    r"(?:source\s+)?turns?\s+"
    r"(?:right\s+after|immediately\s+after|shortly\s+after|after|following)\s+"
    r"(?:the\s+)?(?:(?:source\s+)?(?:ref|reference)\s+)?"
    r"(?:source\s+)?(?:turn\s+)?"
    rf"(?P<ref>{_SOURCE_TURN_REF_TOKEN})"
)
_PREVIOUS_BEFORE_SOURCE_TURN_PATTERN = (
    rf"\b(?:previous|prior|preceding)\s+(?P<radius>{_TURN_RADIUS_TOKEN})\s+"
    r"(?:source\s+)?turns?\s+"
    r"(?:right\s+before|immediately\s+before|shortly\s+before|before|prior\s+to)\s+"
    r"(?:the\s+)?(?:(?:source\s+)?(?:ref|reference)\s+)?"
    r"(?:source\s+)?(?:turn\s+)?"
    rf"(?P<ref>{_SOURCE_TURN_REF_TOKEN})"
)
_NEXT_ONE_AFTER_SOURCE_TURN_PATTERN = (
    r"\b(?:next|following)\s+(?:source\s+)?turn\s+"
    r"(?:right\s+after|immediately\s+after|shortly\s+after|after|following)\s+"
    r"(?:the\s+)?(?:(?:source\s+)?(?:ref|reference)\s+)?"
    r"(?:source\s+)?(?:turn\s+)?"
    rf"(?P<ref>{_SOURCE_TURN_REF_TOKEN})"
)
_PREVIOUS_ONE_BEFORE_SOURCE_TURN_PATTERN = (
    r"\b(?:previous|prior|preceding)\s+(?:source\s+)?turn\s+"
    r"(?:right\s+before|immediately\s+before|shortly\s+before|before|prior\s+to)\s+"
    r"(?:the\s+)?(?:(?:source\s+)?(?:ref|reference)\s+)?"
    r"(?:source\s+)?(?:turn\s+)?"
    rf"(?P<ref>{_SOURCE_TURN_REF_TOKEN})"
)
_AFTER_SOURCE_TURN_RE = _source_turn_regex(_AFTER_SOURCE_TURN_PATTERN)
_AFTER_SCOPED_SOURCE_TURN_RE = _source_turn_regex(
    _AFTER_SOURCE_TURN_PATTERN + _SOURCE_SCOPE_PATTERN
)
_BEFORE_SOURCE_TURN_RE = _source_turn_regex(_BEFORE_SOURCE_TURN_PATTERN)
_BEFORE_SCOPED_SOURCE_TURN_RE = _source_turn_regex(
    _BEFORE_SOURCE_TURN_PATTERN + _SOURCE_SCOPE_PATTERN
)
_BETWEEN_SOURCE_TURN_RE = _source_turn_regex(_BETWEEN_SOURCE_TURN_PATTERN)
_BETWEEN_SCOPED_SOURCE_TURN_RE = _source_turn_regex(
    _BETWEEN_SOURCE_TURN_PATTERN + _SOURCE_SCOPE_PATTERN
)
_NEAR_SOURCE_TURN_RE = _source_turn_regex(_NEAR_SOURCE_TURN_PATTERN)
_NEAR_SCOPED_SOURCE_TURN_RE = _source_turn_regex(
    _NEAR_SOURCE_TURN_PATTERN + _SOURCE_SCOPE_PATTERN
)
_WITHIN_SOURCE_TURN_RE = _source_turn_regex(_WITHIN_SOURCE_TURN_PATTERN)
_WITHIN_SCOPED_SOURCE_TURN_RE = _source_turn_regex(
    _WITHIN_SOURCE_TURN_PATTERN + _SOURCE_SCOPE_PATTERN
)
_WITHIN_AFTER_SOURCE_TURN_RE = _source_turn_regex(_WITHIN_AFTER_SOURCE_TURN_PATTERN)
_WITHIN_AFTER_SCOPED_SOURCE_TURN_RE = _source_turn_regex(
    _WITHIN_AFTER_SOURCE_TURN_PATTERN + _SOURCE_SCOPE_PATTERN
)
_WITHIN_BEFORE_SOURCE_TURN_RE = _source_turn_regex(_WITHIN_BEFORE_SOURCE_TURN_PATTERN)
_WITHIN_BEFORE_SCOPED_SOURCE_TURN_RE = _source_turn_regex(
    _WITHIN_BEFORE_SOURCE_TURN_PATTERN + _SOURCE_SCOPE_PATTERN
)
_NEXT_AFTER_SOURCE_TURN_RE = _source_turn_regex(_NEXT_AFTER_SOURCE_TURN_PATTERN)
_NEXT_AFTER_SCOPED_SOURCE_TURN_RE = _source_turn_regex(
    _NEXT_AFTER_SOURCE_TURN_PATTERN + _SOURCE_SCOPE_PATTERN
)
_PREVIOUS_BEFORE_SOURCE_TURN_RE = _source_turn_regex(
    _PREVIOUS_BEFORE_SOURCE_TURN_PATTERN
)
_PREVIOUS_BEFORE_SCOPED_SOURCE_TURN_RE = _source_turn_regex(
    _PREVIOUS_BEFORE_SOURCE_TURN_PATTERN + _SOURCE_SCOPE_PATTERN
)
_NEXT_ONE_AFTER_SOURCE_TURN_RE = _source_turn_regex(_NEXT_ONE_AFTER_SOURCE_TURN_PATTERN)
_NEXT_ONE_AFTER_SCOPED_SOURCE_TURN_RE = _source_turn_regex(
    _NEXT_ONE_AFTER_SOURCE_TURN_PATTERN + _SOURCE_SCOPE_PATTERN
)
_PREVIOUS_ONE_BEFORE_SOURCE_TURN_RE = _source_turn_regex(
    _PREVIOUS_ONE_BEFORE_SOURCE_TURN_PATTERN
)
_PREVIOUS_ONE_BEFORE_SCOPED_SOURCE_TURN_RE = _source_turn_regex(
    _PREVIOUS_ONE_BEFORE_SOURCE_TURN_PATTERN + _SOURCE_SCOPE_PATTERN
)
