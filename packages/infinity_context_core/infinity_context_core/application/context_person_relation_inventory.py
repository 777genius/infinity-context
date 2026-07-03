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
    target_label: str | None = None
    relation_role: str | None = None


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
    rf"counselors?|partner|spouse|husband|wife|siblings?|parents?|children|kids)\b",
    re.IGNORECASE,
)
_OF_RELATION_QUERY_RE = re.compile(
    rf"\bwho\s+(?:is|are|was|were)\s+(?:the\s+)?"
    rf"(?P<relation>friends?|family|relatives?|coworkers?|co-workers?|"
    rf"colleagues?|teammates?|team\s+members?|managers?|mentors?|boss|bosses|"
    rf"supervisors?|coach(?:es)?|trainers?|teachers?|tutors?|classmates?|"
    rf"schoolmates?|roommates?|"
    rf"neighbors?|neighbours?|doctors?|dentists?|therapists?|counsellors?|"
    rf"counselors?|partner|spouse|husband|wife|siblings?|parents?|children|kids)\s+"
    rf"(?:with|of|to|for)\s+"
    rf"(?P<anchor>{_LABEL_RE})\b",
    re.IGNORECASE,
)
_TARGET_POSSESSIVE_RELATION_QUERY_RE = re.compile(
    rf"(?<!who\s)\b(?:is|are|was|were)\s+(?P<target>{_LABEL_RE})\s+"
    rf"(?P<anchor>{_LABEL_RE})(?:'s|s')?\s+"
    rf"(?P<relation>friends?|family|relatives?|coworkers?|co-workers?|"
    rf"colleagues?|teammates?|team\s+members?|managers?|mentors?|boss|bosses|"
    rf"supervisors?|coach(?:es)?|trainers?|teachers?|tutors?|classmates?|"
    rf"schoolmates?|roommates?|"
    rf"neighbors?|neighbours?|doctors?|dentists?|therapists?|counsellors?|"
    rf"counselors?|partner|spouse|husband|wife|siblings?|parents?|children|kids)\b",
    re.IGNORECASE,
)
_TARGET_OF_RELATION_QUERY_RE = re.compile(
    rf"(?<!who\s)\b(?:is|are|was|were)\s+(?P<target>{_LABEL_RE})\s+(?:the\s+)?"
    rf"(?P<relation>friends?|family|relatives?|coworkers?|co-workers?|"
    rf"colleagues?|teammates?|team\s+members?|managers?|mentors?|boss|bosses|"
    rf"supervisors?|coach(?:es)?|trainers?|teachers?|tutors?|classmates?|"
    rf"schoolmates?|roommates?|"
    rf"neighbors?|neighbours?|doctors?|dentists?|therapists?|counsellors?|"
    rf"counselors?|partner|spouse|husband|wife|siblings?|parents?|children|kids)\s+"
    rf"(?:with|of|to|for)\s+(?P<anchor>{_LABEL_RE})\b",
    re.IGNORECASE,
)
_TARGET_WORK_WITH_QUERY_RE = re.compile(
    rf"\b(?:does|did)\s+(?P<anchor>{_LABEL_RE})\s+"
    rf"(?:work|collaborate|partner|team\s+up)\s+(?:with|alongside)\s+"
    rf"(?P<target>{_LABEL_RE})\b",
    re.IGNORECASE,
)
_TARGET_GENERIC_RELATION_QUERY_RE = re.compile(
    rf"\bwhat\s+(?:is|was|are|were)\s+(?P<anchor>{_LABEL_RE})(?:'s|s')?\s+"
    rf"(?:relationship|relation|connection)\s+(?:to|with)\s+"
    rf"(?P<target>{_LABEL_RE})\b|"
    rf"\bhow\s+(?:is|are|was|were)\s+(?P<anchor_alt>{_LABEL_RE})\s+"
    rf"(?:connected|related|linked|associated)\s+(?:to|with)\s+"
    rf"(?P<target_alt>{_LABEL_RE})\b",
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
    r"\b(?:work(?:s|ed|ing)?\s+(?:with|alongside)|collaborat(?:e|es|ed|ing)|"
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
_WORK_PEER_CUE_RE = re.compile(
    r"\b(?:work(?:s|ed|ing)?\s+(?:with|alongside)|collaborat(?:e|es|ed|ing)|"
    r"partner(?:s|ed|ing)?|coworker|co-worker|colleague|teammate|team\s+member)\b",
    re.IGNORECASE,
)
_WORK_AUTHORITY_CUE_RE = re.compile(
    r"\b(?:manager|mentor|boss|reports?\s+to|supervisor)\b",
    re.IGNORECASE,
)
_FRIEND_ROLE_CUE_RE = re.compile(
    r"\b(?:friend|friends|bestie|buddy|pal|hangs?\s+out|spent\s+time|met)\b",
    re.IGNORECASE,
)
_FAMILY_ROLE_CUE_RE = re.compile(
    r"\b(?:family|relative|mother|father|mom|dad|parent|sister|brother|"
    r"sibling|daughter|son|child|kid|cousin|aunt|uncle|grandma|grandmother|"
    r"grandpa|grandfather)\b",
    re.IGNORECASE,
)
_SPOUSE_ROLE_CUE_RE = re.compile(
    r"\b(?:spouse|husband|wife|partner|life\s+partner)\b",
    re.IGNORECASE,
)
_ROOMMATE_ROLE_CUE_RE = re.compile(r"\broommates?\b", re.IGNORECASE)
_NEIGHBOR_ROLE_CUE_RE = re.compile(r"\bneighbou?rs?\b", re.IGNORECASE)
_MEDICAL_ROLE_CUE_RE = re.compile(
    r"\b(?:doctor|dentist|therapist|counsellor|counselor)\b",
    re.IGNORECASE,
)
_COACH_ROLE_CUE_RE = re.compile(r"\b(?:coach(?:es)?|trainer)\b", re.IGNORECASE)
_EDUCATION_ROLE_CUE_RE = re.compile(
    r"\b(?:teacher|tutor|classmate|schoolmate)\b",
    re.IGNORECASE,
)
_ANY_PERSON_RELATION_ROLE_CUE_RE = re.compile(
    r"\b(?:work(?:s|ed|ing)?\s+(?:with|alongside)|collaborat(?:e|es|ed|ing)|"
    r"partner(?:s|ed|ing)?|coworker|co-worker|colleague|teammate|team\s+member|"
    r"manager|mentor|boss|reports?\s+to|supervisor|"
    r"friend|friends|bestie|buddy|pal|hangs?\s+out|spent\s+time|met|"
    r"family|relative|mother|father|mom|dad|parent|sister|brother|sibling|"
    r"daughter|son|child|kid|cousin|aunt|uncle|grandma|grandmother|"
    r"grandpa|grandfather|spouse|husband|wife|partner|life\s+partner|"
    r"roommates?|neighbou?rs?|doctor|dentist|therapist|counsellor|counselor|"
    r"coach(?:es)?|trainer|teacher|tutor|classmate|schoolmate)\b",
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
            boost=0.03 if relation_query.target_label else 0.022,
            reason="person_relation_inventory_match",
        )
    if relation_query.target_label and _text_mentions_anchor_relation_without_target(
        relation_query,
        text,
    ):
        return PersonRelationInventorySignal(
            penalty=0.04,
            reason="person_relation_inventory_target_mismatch",
        )
    if _text_mentions_anchor_wrong_relation_role(relation_query, text):
        return PersonRelationInventorySignal(
            penalty=0.04,
            reason="person_relation_inventory_role_mismatch",
        )
    if _text_mentions_anchor(relation_query.anchor_label, text):
        return PersonRelationInventorySignal(
            penalty=0.018,
            reason="person_relation_inventory_anchor_only",
        )
    return PersonRelationInventorySignal()


def _person_relation_query(query: str) -> _PersonRelationQuery | None:
    work_target_match = _TARGET_WORK_WITH_QUERY_RE.search(query)
    if work_target_match is not None:
        return _query_for_anchor(
            _clean_label(work_target_match.group("anchor")),
            PersonRelationKind.WORK,
            target=_clean_label(work_target_match.group("target")),
            role="work_peer",
        )
    for pattern in (_TARGET_POSSESSIVE_RELATION_QUERY_RE, _TARGET_OF_RELATION_QUERY_RE):
        match = pattern.search(query)
        if match is None:
            continue
        relation = match.group("relation")
        relation_query = _query_for_anchor(
            _clean_label(match.group("anchor")),
            _kind_for_relation(relation),
            target=_clean_label(match.group("target")),
            role=_role_for_relation(relation),
        )
        if relation_query is not None:
            return relation_query
    generic_target_match = _TARGET_GENERIC_RELATION_QUERY_RE.search(query)
    if generic_target_match is not None:
        return _query_for_anchor(
            _clean_label(
                generic_target_match.group("anchor")
                or generic_target_match.group("anchor_alt")
                or ""
            ),
            PersonRelationKind.GENERIC,
            target=_clean_label(
                generic_target_match.group("target")
                or generic_target_match.group("target_alt")
                or ""
            ),
        )
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
        relation = match.group("relation")
        kind = _kind_for_relation(relation)
        relation_query = _query_for_anchor(
            _clean_label(match.group("anchor")),
            kind,
            role=_role_for_relation(relation),
        )
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
    *,
    target: str | None = None,
    role: str | None = None,
) -> _PersonRelationQuery | None:
    if not anchor or _normalized_label(anchor) in _QUERY_LABEL_STOP_WORDS:
        return None
    cleaned_target = _clean_label(target or "")
    if cleaned_target and (
        _normalized_label(cleaned_target) in _QUERY_LABEL_STOP_WORDS
        or person_labels_match(cleaned_target, anchor)
    ):
        cleaned_target = ""
    return _PersonRelationQuery(
        anchor_label=anchor,
        kind=kind,
        target_label=cleaned_target or None,
        relation_role=role,
    )


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
            "husband",
            "wife",
            "partner",
        )
    ):
        return PersonRelationKind.FAMILY
    if "friend" in normalized:
        return PersonRelationKind.FRIEND
    return PersonRelationKind.GENERIC


def _role_for_relation(relation: str) -> str | None:
    normalized = relation.casefold().replace("-", " ")
    if any(token in normalized for token in ("coworker", "co worker", "colleague")):
        return "work_peer"
    if any(
        token in normalized
        for token in ("teammate", "team member", "team members")
    ):
        return "work_peer"
    if any(
        token in normalized
        for token in ("manager", "mentor", "boss", "supervisor")
    ):
        return "work_authority"
    if "friend" in normalized:
        return "friend"
    if any(token in normalized for token in ("spouse", "husband", "wife", "partner")):
        return "spouse"
    if any(
        token in normalized
        for token in (
            "family",
            "relative",
            "sibling",
            "parent",
            "children",
            "kid",
        )
    ):
        return "family"
    if "roommate" in normalized:
        return "roommate"
    if "neighbor" in normalized or "neighbour" in normalized:
        return "neighbor"
    if any(
        token in normalized
        for token in ("doctor", "dentist", "therapist", "counsellor", "counselor")
    ):
        return "medical"
    if "coach" in normalized or "trainer" in normalized:
        return "coach"
    if any(
        token in normalized
        for token in ("teacher", "tutor", "classmate", "schoolmate")
    ):
        return "education"
    return None


def _text_satisfies_relation_query(
    relation_query: _PersonRelationQuery,
    text: str,
) -> bool:
    normalized_text = _HONORIFIC_PERIOD_RE.sub(r"\1", text)
    for sentence_match in _SENTENCE_RE.finditer(normalized_text):
        sentence = sentence_match.group(0)
        if not _text_mentions_anchor(relation_query.anchor_label, sentence):
            continue
        if not _required_relation_cue(relation_query).search(sentence):
            continue
        if relation_query.target_label is not None:
            return _text_mentions_anchor(relation_query.target_label, sentence)
        if _has_distinct_named_person(
            sentence,
            relation_query.anchor_label,
        ) or _has_kinship_common_person(sentence):
            return True
    return False


def _text_mentions_anchor_relation_without_target(
    relation_query: _PersonRelationQuery,
    text: str,
) -> bool:
    if relation_query.target_label is None:
        return False
    normalized_text = _HONORIFIC_PERIOD_RE.sub(r"\1", text)
    for sentence_match in _SENTENCE_RE.finditer(normalized_text):
        sentence = sentence_match.group(0)
        if not _text_mentions_anchor(relation_query.anchor_label, sentence):
            continue
        if not _required_relation_cue(relation_query).search(sentence):
            continue
        if _text_mentions_anchor(relation_query.target_label, sentence):
            continue
        return True
    return False


def _text_mentions_anchor_wrong_relation_role(
    relation_query: _PersonRelationQuery,
    text: str,
) -> bool:
    if relation_query.relation_role is None:
        return False
    normalized_text = _HONORIFIC_PERIOD_RE.sub(r"\1", text)
    required_relation_cue = _required_relation_cue(relation_query)
    for sentence_match in _SENTENCE_RE.finditer(normalized_text):
        sentence = sentence_match.group(0)
        if not _text_mentions_anchor(relation_query.anchor_label, sentence):
            continue
        if relation_query.target_label is not None and not _text_mentions_anchor(
            relation_query.target_label,
            sentence,
        ):
            continue
        if not _ANY_PERSON_RELATION_ROLE_CUE_RE.search(sentence):
            continue
        if required_relation_cue.search(sentence):
            continue
        if relation_query.target_label is not None or _has_distinct_named_person(
            sentence,
            relation_query.anchor_label,
        ):
            return True
    return False


def _required_relation_cue(relation_query: _PersonRelationQuery) -> re.Pattern[str]:
    if relation_query.relation_role is None:
        return _relation_cue(relation_query.kind)
    return _role_relation_cue(relation_query.relation_role)


def _role_relation_cue(role: str) -> re.Pattern[str]:
    if role == "work_peer":
        return _WORK_PEER_CUE_RE
    if role == "work_authority":
        return _WORK_AUTHORITY_CUE_RE
    if role == "friend":
        return _FRIEND_ROLE_CUE_RE
    if role == "family":
        return _FAMILY_ROLE_CUE_RE
    if role == "spouse":
        return _SPOUSE_ROLE_CUE_RE
    if role == "roommate":
        return _ROOMMATE_ROLE_CUE_RE
    if role == "neighbor":
        return _NEIGHBOR_ROLE_CUE_RE
    if role == "medical":
        return _MEDICAL_ROLE_CUE_RE
    if role == "coach":
        return _COACH_ROLE_CUE_RE
    if role == "education":
        return _EDUCATION_ROLE_CUE_RE
    return _GENERIC_CUE_RE


def _relation_cue(kind: PersonRelationKind) -> re.Pattern[str]:
    if kind is PersonRelationKind.WORK:
        return _WORK_CUE_RE
    if kind is PersonRelationKind.FRIEND:
        return _FRIEND_CUE_RE
    if kind is PersonRelationKind.FAMILY:
        return _KINSHIP_CUE_RE
    return _GENERIC_CUE_RE


def _text_mentions_anchor(anchor: str, text: str) -> bool:
    if not person_alias_keys(anchor):
        return False
    if any(
        person_labels_match(match.group("speaker"), anchor)
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
