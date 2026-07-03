"""Named-person occupation signals for deterministic memory reranking."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

from infinity_context_core.application.context_person_aliases import (
    person_alias_keys,
    person_labels_match,
)


class PersonOccupationQueryKind(Enum):
    ROLE = "role"
    WORKPLACE = "workplace"


class PersonOccupationSignal(NamedTuple):
    boost: float = 0.0
    penalty: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class _PersonOccupationQuery:
    person_label: str
    kind: PersonOccupationQueryKind


_LABEL_RE = (
    r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
    r"(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}){0,2}"
)
_DIALOGUE_SPEAKER_RE = re.compile(rf"\bD\d+:\d+\s+(?P<speaker>{_LABEL_RE}):")
_LABEL_TOKEN_RE = re.compile(rf"\b{_LABEL_RE}\b")
_WORK_ROLE_QUERY_RE = re.compile(
    rf"(?i:\bwhat\s+(?:does|do)\s+)(?P<person>{_LABEL_RE})"
    rf"(?i:\s+do\s+for\s+work\b)|"
    rf"(?i:\bwhat\s+is\s+)(?P<person_job>{_LABEL_RE})"
    rf"(?:'s|s')?\s+(?i:job|occupation|profession|role|title)\b|"
    rf"(?i:\bwhat\s+does\s+)(?P<person_as>{_LABEL_RE})"
    rf"(?i:\s+work\s+as\b)",
)
_WORKPLACE_QUERY_RE = re.compile(
    rf"(?i:\bwhere\s+(?:does|do|did)\s+)(?P<person>{_LABEL_RE})"
    rf"(?i:\s+work\b)|"
    rf"(?i:\bwho\s+(?:does|did)\s+)(?P<person_employer>{_LABEL_RE})"
    rf"(?i:\s+work\s+for\b)|"
    rf"(?i:\bwhat\s+(?:company|organization|organisation|employer|workplace)\s+)"
    rf"(?i:(?:does|did)\s+)(?P<person_company>{_LABEL_RE})"
    rf"(?i:\s+work\s+(?:for|at)\b)|"
    rf"(?i:\b(?:who|what)\s+(?:is|was)\s+)(?P<person_owner>{_LABEL_RE})"
    rf"(?:'s|s')?\s+(?i:employer|workplace|company|organization|organisation)\b|"
    rf"(?i:\bwhere\s+(?:is|was)\s+)(?P<person_employed>{_LABEL_RE})"
    rf"(?i:\s+employed\b)"
)
_ROLE_EVIDENCE_RE = re.compile(
    r"\b(?:work(?:s|ed|ing)?\s+as|job\s+(?:is|was)|occupation|profession|"
    r"role|title|career|employed\s+as|is\s+a|is\s+an|as\s+a|as\s+an)\b",
    re.IGNORECASE,
)
_WORKPLACE_EVIDENCE_RE = re.compile(
    r"\b(?:work(?:s|ed|ing)?\s+(?:at|for|with)|employed\s+(?:at|by)|"
    r"employer|workplace|company|office|firm|studio|school|hospital|clinic|"
    r"agency|startup)\b",
    re.IGNORECASE,
)
_QUERY_LABEL_STOP_WORDS = frozenset({"what", "where"})


def person_occupation_signal(*, query: str, text: str) -> PersonOccupationSignal:
    """Return bounded evidence signal for named-person occupation questions."""

    occupation_query = _person_occupation_query(query)
    if occupation_query is None:
        return PersonOccupationSignal()
    if (
        _text_mentions_person(occupation_query.person_label, text)
        and _occupation_cue(occupation_query.kind).search(text) is not None
    ):
        return PersonOccupationSignal(boost=0.022, reason="person_occupation_match")
    if (
        _occupation_cue(occupation_query.kind).search(text) is not None
        and not _text_mentions_person(occupation_query.person_label, text)
        and _text_mentions_other_person(occupation_query.person_label, text)
    ):
        return PersonOccupationSignal(
            penalty=0.022,
            reason="person_occupation_other_person",
        )
    return PersonOccupationSignal()


def _person_occupation_query(query: str) -> _PersonOccupationQuery | None:
    role_match = _WORK_ROLE_QUERY_RE.search(query)
    if role_match is not None:
        person = _matched_person(role_match)
        if _valid_label(person):
            return _PersonOccupationQuery(
                person_label=person,
                kind=PersonOccupationQueryKind.ROLE,
            )
    workplace_match = _WORKPLACE_QUERY_RE.search(query)
    if workplace_match is not None:
        person = _matched_person(workplace_match)
        if _valid_label(person):
            return _PersonOccupationQuery(
                person_label=person,
                kind=PersonOccupationQueryKind.WORKPLACE,
            )
    return None


def _occupation_cue(kind: PersonOccupationQueryKind) -> re.Pattern[str]:
    if kind is PersonOccupationQueryKind.WORKPLACE:
        return _WORKPLACE_EVIDENCE_RE
    return _ROLE_EVIDENCE_RE


def _matched_person(match: re.Match[str]) -> str:
    groups = match.groupdict()
    return (
        groups.get("person")
        or groups.get("person_job")
        or groups.get("person_as")
        or groups.get("person_employer")
        or groups.get("person_company")
        or groups.get("person_owner")
        or groups.get("person_employed")
        or ""
    ).strip(" :,.!?;")


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
