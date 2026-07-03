"""Person relation inventory signals for deterministic memory reranking."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

from infinity_context_core.application.context_person_aliases import (
    person_alias_keys,
    person_labels_match,
)


class PersonRelationKind(Enum):
    WORK = "work"
    FRIEND = "friend"
    FAMILY = "family"
    GENERIC = "generic"


class PersonRelationInventorySignal(NamedTuple):
    boost: float = 0.0
    penalty: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class _PersonRelationQuery:
    anchor_label: str
    kind: PersonRelationKind


_LABEL_RE = (
    r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
    r"(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}){0,2}"
)
_SENTENCE_RE = re.compile(r"[^.?!;\n]+")
_HONORIFIC_PERIOD_RE = re.compile(r"\b(Dr|Mr|Mrs|Ms|Prof|Sr|Jr)\.", re.IGNORECASE)
_DIALOGUE_SPEAKER_RE = re.compile(
    rf"\bD\d+:\d+\s+(?P<speaker>{_LABEL_RE}):",
    re.IGNORECASE,
)
_LABEL_TOKEN_RE = re.compile(rf"\b{_LABEL_RE}\b")
_WORK_WITH_QUERY_RE = re.compile(
    rf"\bwho\s+(?:works?|worked|collaborates?|collaborated|partners?|partnered)\s+"
    rf"(?:with|alongside)\s+(?P<anchor>{_LABEL_RE})\b|"
    rf"\bwho\s+(?:does|did)\s+(?P<anchor_alt>{_LABEL_RE})\s+"
    rf"(?:work|collaborate|partner|team\s+up)\s+(?:with|alongside)\b",
    re.IGNORECASE,
)
_POSSESSIVE_RELATION_QUERY_RE = re.compile(
    rf"\bwho\s+(?:are|were|is|was)\s+(?P<anchor>{_LABEL_RE})(?:'s|s')?\s+"
    rf"(?P<relation>friends?|family|relatives?|coworkers?|co-workers?|"
    rf"colleagues?|teammates?|team\s+members?|managers?|mentors?|boss|bosses|"
    rf"supervisors?|coach(?:es)?|trainers?|teachers?|tutors?|classmates?|"
    rf"schoolmates?|roommates?|"
    rf"neighbors?|neighbours?|doctors?|dentists?|therapists?|counsellors?|"
    rf"counselors?|partner|spouse|siblings?|parents?|children|kids)\b",
    re.IGNORECASE,
)
_OF_RELATION_QUERY_RE = re.compile(
    rf"\bwho\s+(?:is|are|was|were)\s+(?:the\s+)?"
    rf"(?P<relation>friends?|family|relatives?|coworkers?|co-workers?|"
    rf"colleagues?|teammates?|team\s+members?|managers?|mentors?|boss|bosses|"
    rf"supervisors?|coach(?:es)?|trainers?|teachers?|tutors?|classmates?|"
    rf"schoolmates?|roommates?|"
    rf"neighbors?|neighbours?|doctors?|dentists?|therapists?|counsellors?|"
    rf"counselors?|partner|spouse|siblings?|parents?|children|kids)\s+"
    rf"(?:with|of|to|for)\s+"
    rf"(?P<anchor>{_LABEL_RE})\b",
    re.IGNORECASE,
)
_GENERIC_RELATION_QUERY_RE = re.compile(
    rf"\bwho\s+(?:is|are|was|were)\s+(?P<anchor>{_LABEL_RE})\s+"
    rf"(?:connected|related|linked|associated)\s+(?:to|with)\b",
    re.IGNORECASE,
)
_KINSHIP_CUE_RE = re.compile(
    r"\b(?:family|relative|mother|father|mom|dad|parent|sister|brother|"
    r"sibling|daughter|son|child|kid|husband|wife|spouse|partner|cousin|"
    r"aunt|uncle|grandma|grandmother|grandpa|grandfather)\b",
    re.IGNORECASE,
)
_FRIEND_CUE_RE = re.compile(
    r"\b(?:friend|friends|bestie|buddy|pal|hangs?\s+out|spent\s+time|met)\b",
    re.IGNORECASE,
)
_WORK_CUE_RE = re.compile(
    r"\b(?:work(?:s|ed|ing)?\s+(?:with|alongside)|collaborat(?:es|ed|ing)?|"
    r"partner(?:s|ed|ing)?|coworker|co-worker|colleague|teammate|team\s+member|"
    r"manager|mentor|boss|reports?\s+to|supervisor)\b",
    re.IGNORECASE,
)
_GENERIC_CUE_RE = re.compile(
    r"\b(?:connected|related|linked|associated|relationship|knows?|met|"
    r"introduced|friend|family|coworker|colleague|teammate|coach|trainer|"
    r"teacher|tutor|classmate|schoolmate|roommate|neighbor|neighbour|doctor|"
    r"dentist|therapist|counsellor|counselor|partner)\b",
    re.IGNORECASE,
)
_QUERY_LABEL_STOP_WORDS = frozenset({"who", "what", "which", "where", "when", "the"})


def person_relation_inventory_signal(
    *,
    query: str,
    text: str,
) -> PersonRelationInventorySignal:
    """Return a bounded signal for questions asking who is related to a person."""

    relation_query = _person_relation_query(query)
    if relation_query is None:
        return PersonRelationInventorySignal()
    if _text_satisfies_relation_query(relation_query, text):
        return PersonRelationInventorySignal(
            boost=0.022,
            reason="person_relation_inventory_match",
        )
    if _text_mentions_anchor(relation_query.anchor_label, text):
        return PersonRelationInventorySignal(
            penalty=0.018,
            reason="person_relation_inventory_anchor_only",
        )
    return PersonRelationInventorySignal()


def _person_relation_query(query: str) -> _PersonRelationQuery | None:
    work_match = _WORK_WITH_QUERY_RE.search(query)
    if work_match is not None:
        anchor = _clean_label(
            work_match.group("anchor") or work_match.group("anchor_alt") or ""
        )
        return _query_for_anchor(anchor, PersonRelationKind.WORK)
    for pattern in (_POSSESSIVE_RELATION_QUERY_RE, _OF_RELATION_QUERY_RE):
        match = pattern.search(query)
        if match is None:
            continue
        kind = _kind_for_relation(match.group("relation"))
        relation_query = _query_for_anchor(_clean_label(match.group("anchor")), kind)
        if relation_query is not None:
            return relation_query
    generic_match = _GENERIC_RELATION_QUERY_RE.search(query)
    if generic_match is not None:
        return _query_for_anchor(
            _clean_label(generic_match.group("anchor")),
            PersonRelationKind.GENERIC,
        )
    return None


def _query_for_anchor(
    anchor: str,
    kind: PersonRelationKind,
) -> _PersonRelationQuery | None:
    if not anchor or _normalized_label(anchor) in _QUERY_LABEL_STOP_WORDS:
        return None
    return _PersonRelationQuery(anchor_label=anchor, kind=kind)


def _kind_for_relation(relation: str) -> PersonRelationKind:
    normalized = relation.casefold().replace("-", " ")
    if any(
        token in normalized
        for token in (
            "coworker",
            "co worker",
            "colleague",
            "teammate",
            "team",
            "manager",
            "mentor",
            "boss",
            "supervisor",
        )
    ):
        return PersonRelationKind.WORK
    if any(
        token in normalized
        for token in (
            "family",
            "relative",
            "sibling",
            "parent",
            "children",
            "kid",
            "spouse",
            "partner",
        )
    ):
        return PersonRelationKind.FAMILY
    if "friend" in normalized:
        return PersonRelationKind.FRIEND
    return PersonRelationKind.GENERIC


def _text_satisfies_relation_query(
    relation_query: _PersonRelationQuery,
    text: str,
) -> bool:
    normalized_text = _HONORIFIC_PERIOD_RE.sub(r"\1", text)
    for sentence_match in _SENTENCE_RE.finditer(normalized_text):
        sentence = sentence_match.group(0)
        if not _text_mentions_anchor(relation_query.anchor_label, sentence):
            continue
        if not _relation_cue(relation_query.kind).search(sentence):
            continue
        if _has_distinct_named_person(
            sentence,
            relation_query.anchor_label,
        ) or _has_kinship_common_person(sentence):
            return True
    return False


def _relation_cue(kind: PersonRelationKind) -> re.Pattern[str]:
    if kind is PersonRelationKind.WORK:
        return _WORK_CUE_RE
    if kind is PersonRelationKind.FRIEND:
        return _FRIEND_CUE_RE
    if kind is PersonRelationKind.FAMILY:
        return _KINSHIP_CUE_RE
    return _GENERIC_CUE_RE


def _text_mentions_anchor(anchor: str, text: str) -> bool:
    anchor_aliases = person_alias_keys(anchor)
    if not anchor_aliases:
        return False
    if any(
        anchor_aliases.intersection(person_alias_keys(match.group("speaker")))
        for match in _DIALOGUE_SPEAKER_RE.finditer(text)
    ):
        return True
    return any(
        person_labels_match(match.group(0), anchor)
        for match in _LABEL_TOKEN_RE.finditer(text)
    )


def _has_distinct_named_person(text: str, anchor: str) -> bool:
    for match in _LABEL_TOKEN_RE.finditer(text):
        label = match.group(0)
        if not person_alias_keys(label) or person_labels_match(label, anchor):
            continue
        label_key = _normalized_label(label)
        if label_key.startswith("d") and label_key[1:].isdigit():
            continue
        return True
    return False


def _has_kinship_common_person(text: str) -> bool:
    return _KINSHIP_CUE_RE.search(text) is not None


def _clean_label(value: str) -> str:
    return (value or "").strip(" :,.!?;")


def _normalized_label(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())
