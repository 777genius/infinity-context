"""Named-person kinship signals for deterministic memory reranking."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

from infinity_context_core.application.context_person_aliases import (
    person_alias_keys,
    person_labels_match,
)


class KinshipRelationKind(Enum):
    FAMILY = "family"
    PARENT = "parent"
    SIBLING = "sibling"
    CHILD = "child"
    PARTNER = "partner"


class PersonKinshipSignal(NamedTuple):
    boost: float = 0.0
    penalty: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class _PersonKinshipQuery:
    person_label: str
    kind: KinshipRelationKind


_LABEL_RE = (
    r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
    r"(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}){0,2}"
)
_KINSHIP_TERMS_RE = (
    r"family|relatives?|mother|mom|father|dad|parents?|sisters?|brothers?|"
    r"siblings?|children|kids|sons?|daughters?|spouse|partner|wife|husband|"
    r"grandmother|grandma|grandfather|grandpa"
)
_DIALOGUE_SPEAKER_RE = re.compile(rf"\bD\d+:\d+\s+(?P<speaker>{_LABEL_RE}):")
_LABEL_TOKEN_RE = re.compile(rf"\b{_LABEL_RE}\b")
_POSSESSIVE_KINSHIP_QUERY_RE = re.compile(
    rf"(?i:\bwho\s+(?:is|are|was|were)\s+)(?P<person>{_LABEL_RE})"
    rf"(?:'s|s')?\s+(?P<relation>{_KINSHIP_TERMS_RE})\b|"
    rf"(?i:\bwhat\s+(?:is|was|are|were)\s+)(?P<person_name>{_LABEL_RE})"
    rf"(?:'s|s')?\s+(?P<relation_name>{_KINSHIP_TERMS_RE})(?:'s|s')?"
    rf"\s+(?i:names?)\b|"
    rf"(?i:\bwho\s+(?:is|are|was|were)\s+)(?P<relation_first>{_KINSHIP_TERMS_RE})"
    rf"(?i:\s+(?:of|for|to)\s+)(?P<person_after>{_LABEL_RE})\b",
)
_KINSHIP_EVIDENCE_RE = re.compile(rf"\b(?:{_KINSHIP_TERMS_RE})\b", re.IGNORECASE)
_SIBLING_FALSE_POSITIVE_RE = re.compile(
    r"\b(?:sister|brother)\s+(?:city|company|school|team|project|"
    r"organization|organisation|brand)\b",
    re.IGNORECASE,
)
_PARTNER_FALSE_POSITIVE_RE = re.compile(
    r"\b(?:accountability|business|lab|project|research|study|training)\s+"
    r"partner\b|\bpartner\s+(?:company|deal|organization|organisation|program)\b",
    re.IGNORECASE,
)
_QUERY_LABEL_STOP_WORDS = frozenset({"who"})


def person_kinship_signal(*, query: str, text: str) -> PersonKinshipSignal:
    """Return bounded evidence signal for named-person family relation questions."""

    kinship_query = _person_kinship_query(query)
    if kinship_query is None:
        return PersonKinshipSignal()
    if (
        _text_mentions_person(kinship_query.person_label, text)
        and _has_kinship_evidence(kinship_query.kind, text)
    ):
        return PersonKinshipSignal(boost=0.022, reason="person_kinship_match")
    if (
        _has_kinship_evidence(kinship_query.kind, text)
        and not _text_mentions_person(kinship_query.person_label, text)
        and _text_mentions_other_person(kinship_query.person_label, text)
    ):
        return PersonKinshipSignal(
            penalty=0.022,
            reason="person_kinship_other_person",
        )
    return PersonKinshipSignal()


def _person_kinship_query(query: str) -> _PersonKinshipQuery | None:
    match = _POSSESSIVE_KINSHIP_QUERY_RE.search(query)
    if match is None:
        return None
    person = (
        match.groupdict().get("person")
        or match.groupdict().get("person_name")
        or match.groupdict().get("person_after")
        or ""
    ).strip(" :,.!?;")
    relation = (
        match.groupdict().get("relation")
        or match.groupdict().get("relation_name")
        or match.groupdict().get("relation_first")
        or ""
    )
    if not _valid_label(person):
        return None
    return _PersonKinshipQuery(
        person_label=person,
        kind=_kinship_kind(relation),
    )


def _kinship_kind(relation: str) -> KinshipRelationKind:
    normalized = relation.casefold()
    if any(token in normalized for token in ("mother", "mom", "father", "dad", "parent")):
        return KinshipRelationKind.PARENT
    if any(token in normalized for token in ("sister", "brother", "sibling")):
        return KinshipRelationKind.SIBLING
    if any(token in normalized for token in ("child", "children", "kid", "son", "daughter")):
        return KinshipRelationKind.CHILD
    if any(token in normalized for token in ("spouse", "partner", "wife", "husband")):
        return KinshipRelationKind.PARTNER
    return KinshipRelationKind.FAMILY


def _kinship_cue(kind: KinshipRelationKind) -> re.Pattern[str]:
    if kind is KinshipRelationKind.PARENT:
        return re.compile(r"\b(?:mother|mom|father|dad|parents?)\b", re.IGNORECASE)
    if kind is KinshipRelationKind.SIBLING:
        return re.compile(r"\b(?:sisters?|brothers?|siblings?)\b", re.IGNORECASE)
    if kind is KinshipRelationKind.CHILD:
        return re.compile(r"\b(?:children|kids|sons?|daughters?)\b", re.IGNORECASE)
    if kind is KinshipRelationKind.PARTNER:
        return re.compile(r"\b(?:spouse|partner|wife|husband)\b", re.IGNORECASE)
    return _KINSHIP_EVIDENCE_RE


def _has_kinship_evidence(kind: KinshipRelationKind, text: str) -> bool:
    for match in _kinship_cue(kind).finditer(text):
        if not _is_false_positive_kinship_match(kind, text, match):
            return True
    return False


def _is_false_positive_kinship_match(
    kind: KinshipRelationKind,
    text: str,
    match: re.Match[str],
) -> bool:
    window_start = max(0, match.start() - 24)
    window_end = min(len(text), match.end() + 32)
    window = text[window_start:window_end]
    if kind is KinshipRelationKind.SIBLING:
        return _SIBLING_FALSE_POSITIVE_RE.search(window) is not None
    if kind is KinshipRelationKind.PARTNER:
        return _PARTNER_FALSE_POSITIVE_RE.search(window) is not None
    return False


def _text_mentions_person(person: str, text: str) -> bool:
    person_aliases = person_alias_keys(person)
    return any(
        person_aliases.intersection(person_alias_keys(match.group("speaker")))
        for match in _DIALOGUE_SPEAKER_RE.finditer(text)
    ) or any(
        person_labels_match(match.group(0), person)
        for match in _LABEL_TOKEN_RE.finditer(text)
    )


def _text_mentions_other_person(person: str, text: str) -> bool:
    for match in _DIALOGUE_SPEAKER_RE.finditer(text):
        if person_labels_match(match.group("speaker"), person):
            continue
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


def _valid_label(label: str) -> bool:
    return bool(person_alias_keys(label)) and label.casefold() not in _QUERY_LABEL_STOP_WORDS
