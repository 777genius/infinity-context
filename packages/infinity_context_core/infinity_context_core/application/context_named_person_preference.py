"""Named-person preference signals for deterministic memory reranking."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

from infinity_context_core.application.context_person_aliases import (
    person_alias_keys,
    person_labels_match,
)


class NamedPreferenceQueryKind(Enum):
    FAVORITE = "favorite"
    PREFERENCE = "preference"


class NamedPersonPreferenceSignal(NamedTuple):
    boost: float = 0.0
    penalty: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class _NamedPreferenceQuery:
    person_label: str
    kind: NamedPreferenceQueryKind
    domain_terms: frozenset[str]


_LABEL_RE = (
    r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
    r"(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}){0,2}"
)
_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё0-9_-]*")
_DIALOGUE_SPEAKER_RE = re.compile(
    rf"\bD\d+:\d+\s+(?P<speaker>{_LABEL_RE}):",
    re.IGNORECASE,
)
_LABEL_TOKEN_RE = re.compile(rf"\b{_LABEL_RE}\b")
_POSSESSIVE_FAVORITE_QUERY_RE = re.compile(
    rf"(?i:\bwhat\s+(?:is|was|are|were)\s+)(?P<person>{_LABEL_RE})"
    rf"(?:'s|s')?\s+(?i:favorite|favourite|preferred|preference)\b|"
    rf"\b(?P<person_direct>{_LABEL_RE})(?:'s|s')?\s+"
    rf"(?i:favorite|favourite|preferred|preference)\b",
)
_DOES_PERSON_PREFER_QUERY_RE = re.compile(
    r"(?i:\b(?:what|which|where|when|why|how)"
    r"(?:\s+[a-z][a-z0-9_-]{1,30}){0,3}\s+(?:does|did|would)\s+)"
    rf"(?P<person>{_LABEL_RE})\s+"
    r"(?i:like|likes|love|loves|enjoy|enjoys|prefer|prefers|want|wants)\b",
)
_PERSON_LIKES_QUERY_RE = re.compile(
    rf"\b(?P<person>{_LABEL_RE})\s+"
    r"(?i:like|likes|love|loves|enjoy|enjoys|prefer|prefers|favorite|favourite)\b",
)
_PREFERENCE_CUE_RE = re.compile(
    r"\b(?:favorite|favourite|likes?|loves?|enjoys?|prefers?|preferred|"
    r"fan\s+of|interested\s+in|into)\b",
    re.IGNORECASE,
)
_QUERY_LABEL_STOP_WORDS = frozenset(
    {
        "how",
        "what",
        "when",
        "where",
        "which",
        "why",
    }
)
_DOMAIN_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "did",
        "do",
        "does",
        "enjoy",
        "enjoys",
        "favorite",
        "favourite",
        "how",
        "is",
        "like",
        "likes",
        "love",
        "loves",
        "prefer",
        "preferred",
        "prefers",
        "preference",
        "the",
        "what",
        "when",
        "where",
        "which",
        "why",
        "would",
    }
)


def named_person_preference_signal(
    *,
    query: str,
    text: str,
) -> NamedPersonPreferenceSignal:
    """Return a bounded signal for named-person preference questions."""

    preference_query = _named_preference_query(query)
    if preference_query is None:
        return NamedPersonPreferenceSignal()
    text_has_preference = _PREFERENCE_CUE_RE.search(text) is not None
    if (
        text_has_preference
        and _text_mentions_person(preference_query.person_label, text)
        and _domain_terms_match(preference_query.domain_terms, text)
    ):
        return NamedPersonPreferenceSignal(
            boost=0.022,
            reason="named_person_preference_match",
        )
    if (
        text_has_preference
        and not _text_mentions_person(preference_query.person_label, text)
        and _text_mentions_other_person(preference_query.person_label, text)
    ):
        return NamedPersonPreferenceSignal(
            penalty=0.022,
            reason="named_person_preference_other_person",
        )
    return NamedPersonPreferenceSignal()


def _named_preference_query(query: str) -> _NamedPreferenceQuery | None:
    for pattern, kind in (
        (_POSSESSIVE_FAVORITE_QUERY_RE, NamedPreferenceQueryKind.FAVORITE),
        (_DOES_PERSON_PREFER_QUERY_RE, NamedPreferenceQueryKind.PREFERENCE),
        (_PERSON_LIKES_QUERY_RE, NamedPreferenceQueryKind.PREFERENCE),
    ):
        match = pattern.search(query)
        if match is None:
            continue
        person = (
            match.groupdict().get("person")
            or match.groupdict().get("person_direct")
            or ""
        ).strip(" :,.!?;")
        if not person_alias_keys(person) or person.casefold() in _QUERY_LABEL_STOP_WORDS:
            continue
        return _NamedPreferenceQuery(
            person_label=person,
            kind=kind,
            domain_terms=_domain_terms(query, person),
        )
    return None


def _domain_terms(query: str, person: str) -> frozenset[str]:
    person_alias_tokens = {
        token.casefold()
        for token in _TOKEN_RE.findall(person)
        if len(token) >= 2
    }
    terms: set[str] = set()
    for match in _TOKEN_RE.finditer(query):
        token = match.group(0).casefold()
        if len(token) < 3:
            continue
        if token in _DOMAIN_STOP_WORDS or token in person_alias_tokens:
            continue
        terms.add(token)
    return frozenset(terms)


def _domain_terms_match(domain_terms: frozenset[str], text: str) -> bool:
    if not domain_terms:
        return True
    normalized = text.casefold()
    return any(term in normalized for term in domain_terms)


def _text_mentions_person(person: str, text: str) -> bool:
    return any(
        person_labels_match(match.group("speaker"), person)
        for match in _DIALOGUE_SPEAKER_RE.finditer(text)
    ) or any(
        person_labels_match(match.group(0), person)
        for match in _LABEL_TOKEN_RE.finditer(text)
    )


def _text_mentions_other_person(person: str, text: str) -> bool:
    for match in _DIALOGUE_SPEAKER_RE.finditer(text):
        if not person_labels_match(match.group("speaker"), person):
            return True
    for match in _LABEL_TOKEN_RE.finditer(text):
        label = match.group(0)
        if person_labels_match(label, person):
            continue
        label_key = "".join(char for char in label.casefold() if char.isalnum())
        if label_key.startswith("d") and label_key[1:].isdigit():
            continue
        return True
    return False
