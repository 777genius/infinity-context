"""Named-person residence signals for deterministic memory reranking."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

from infinity_context_core.application.context_person_aliases import (
    person_alias_keys,
    person_labels_match,
)


class PersonResidenceQueryKind(Enum):
    CURRENT_RESIDENCE = "current_residence"
    ORIGIN = "origin"
    RELOCATION_DESTINATION = "relocation_destination"
    RELOCATION_ORIGIN = "relocation_origin"


class PersonResidenceSignal(NamedTuple):
    boost: float = 0.0
    penalty: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class _PersonResidenceQuery:
    person_label: str
    kind: PersonResidenceQueryKind


_LABEL_RE = (
    r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
    r"(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}){0,2}"
)
_DIALOGUE_SPEAKER_RE = re.compile(rf"\bD\d+:\d+\s+(?P<speaker>{_LABEL_RE}):")
_LABEL_TOKEN_RE = re.compile(rf"\b{_LABEL_RE}\b")
_WHERE_LIVE_QUERY_RE = re.compile(
    rf"(?i:\bwhere\s+(?:does|do|did)\s+)(?P<person>{_LABEL_RE})"
    rf"(?i:\s+(?:live|lives|reside|resides|stay|stays)\b)|"
    rf"(?i:\bwhere\s+is\s+)(?P<person_based>{_LABEL_RE})"
    rf"(?i:\s+(?:living|based|located)\b)|"
    rf"(?i:\bwhat\s+(?:is|was)\s+)(?P<person_home>{_LABEL_RE})"
    rf"(?:'s|s')?\s+(?i:current\s+)?(?i:home|residence|city|town)\b",
)
_RELOCATION_DESTINATION_QUERY_RE = re.compile(
    rf"(?i:\bwhere\s+did\s+)(?P<person>{_LABEL_RE})"
    rf"(?i:\s+(?:move|relocate)\s+to\b)|"
    rf"(?i:\bwhere\s+is\s+)(?P<person_moving>{_LABEL_RE})"
    rf"(?i:\s+moving\s+to\b)",
)
_RELOCATION_ORIGIN_QUERY_RE = re.compile(
    rf"(?i:\bwhere\s+did\s+)(?P<person>{_LABEL_RE})"
    rf"(?i:\s+(?:move|relocate)\s+from\b)|"
    rf"(?i:\bwhere\s+is\s+)(?P<person_moving>{_LABEL_RE})"
    rf"(?i:\s+moving\s+from\b)",
)
_ORIGIN_QUERY_RE = re.compile(
    rf"(?i:\bwhere\s+(?:is|was)\s+)(?P<person>{_LABEL_RE})"
    rf"(?i:\s+from\b)|"
    rf"(?i:\bwhat\s+(?:is|was)\s+)(?P<person_hometown>{_LABEL_RE})"
    rf"(?:'s|s')?\s+(?i:hometown|birthplace|home\s+country)\b|"
    rf"(?i:\bwhat\s+(?:city|country|place)\s+(?:is|was)\s+)"
    rf"(?P<person_origin>{_LABEL_RE})"
    rf"(?i:\s+(?:originally\s+)?from\b)",
)
_RESIDENCE_EVIDENCE_RE = re.compile(
    r"\b(?:live|lives|living|reside|resides|stays|home|current\s+city|"
    r"based\s+in|located\s+in|moved\s+to|relocated\s+to|settled\s+in)\b",
    re.IGNORECASE,
)
_RELOCATION_EVIDENCE_RE = re.compile(
    r"\b(?:moved\s+to|moving\s+to|relocated\s+to|relocating\s+to|"
    r"settled\s+in|new\s+(?:city|home|place))\b",
    re.IGNORECASE,
)
_RELOCATION_ORIGIN_EVIDENCE_RE = re.compile(
    r"\b(?:moved\s+from|moving\s+from|relocated\s+from|relocating\s+from|"
    r"left\s+(?:home|town|city|country)|came\s+from)\b",
    re.IGNORECASE,
)
_ORIGIN_EVIDENCE_RE = re.compile(
    r"\b(?:originally\s+from|born\s+in|birthplace|hometown|home\s+country|"
    r"native\s+(?:city|country|town)|grew\s+up\s+in|raised\s+in|"
    r"came\s+from|am\s+from|is\s+from|was\s+from)\b",
    re.IGNORECASE,
)
_QUERY_LABEL_STOP_WORDS = frozenset({"what", "where"})


def person_residence_signal(*, query: str, text: str) -> PersonResidenceSignal:
    """Return bounded evidence signal for named-person residence questions."""

    residence_query = _person_residence_query(query)
    if residence_query is None:
        return PersonResidenceSignal()
    cue = _residence_cue(residence_query.kind)
    if (
        _text_mentions_person(residence_query.person_label, text)
        and cue.search(text) is not None
    ):
        return PersonResidenceSignal(boost=0.022, reason="person_residence_match")
    if (
        cue.search(text) is not None
        and not _text_mentions_person(residence_query.person_label, text)
        and _text_mentions_other_person(residence_query.person_label, text)
    ):
        return PersonResidenceSignal(
            penalty=0.022,
            reason="person_residence_other_person",
        )
    return PersonResidenceSignal()


def _person_residence_query(query: str) -> _PersonResidenceQuery | None:
    relocation_origin_match = _RELOCATION_ORIGIN_QUERY_RE.search(query)
    if relocation_origin_match is not None:
        person = _matched_person(relocation_origin_match)
        if _valid_label(person):
            return _PersonResidenceQuery(
                person_label=person,
                kind=PersonResidenceQueryKind.RELOCATION_ORIGIN,
            )
    relocation_match = _RELOCATION_DESTINATION_QUERY_RE.search(query)
    if relocation_match is not None:
        person = _matched_person(relocation_match)
        if _valid_label(person):
            return _PersonResidenceQuery(
                person_label=person,
                kind=PersonResidenceQueryKind.RELOCATION_DESTINATION,
            )
    origin_match = _ORIGIN_QUERY_RE.search(query)
    if origin_match is not None:
        person = _matched_person(origin_match)
        if _valid_label(person):
            return _PersonResidenceQuery(
                person_label=person,
                kind=PersonResidenceQueryKind.ORIGIN,
            )
    residence_match = _WHERE_LIVE_QUERY_RE.search(query)
    if residence_match is not None:
        person = _matched_person(residence_match)
        if _valid_label(person):
            return _PersonResidenceQuery(
                person_label=person,
                kind=PersonResidenceQueryKind.CURRENT_RESIDENCE,
            )
    return None


def _residence_cue(kind: PersonResidenceQueryKind) -> re.Pattern[str]:
    if kind is PersonResidenceQueryKind.RELOCATION_DESTINATION:
        return _RELOCATION_EVIDENCE_RE
    if kind is PersonResidenceQueryKind.RELOCATION_ORIGIN:
        return _RELOCATION_ORIGIN_EVIDENCE_RE
    if kind is PersonResidenceQueryKind.ORIGIN:
        return _ORIGIN_EVIDENCE_RE
    return _RESIDENCE_EVIDENCE_RE


def _matched_person(match: re.Match[str]) -> str:
    for value in match.groupdict().values():
        if value:
            return value.strip(" :,.!?;")
    return ""


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
