"""Named-person residence signals for deterministic memory reranking."""

from __future__ import annotations

import re
from collections.abc import Callable
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


@dataclass(frozen=True)
class _LocalResidenceSegment:
    body: str
    speaker: str = ""


_LABEL_RE = (
    r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
    r"(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}){0,2}"
)
_DIALOGUE_SPEAKER_RE = re.compile(rf"\bD\d+:\d+\s+(?P<speaker>{_LABEL_RE}):")
_LABEL_TOKEN_RE = re.compile(rf"\b{_LABEL_RE}\b")
_LOCAL_SEGMENT_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+|[\n\r]+")
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
_RELOCATION_PLACE_SURFACE = (
    r"(?:(?-i:[A-ZА-ЯЁ])[A-Za-zА-Яа-яЁё0-9_.-]{1,40}"
    r"(?:\s+(?-i:[A-ZА-ЯЁ])[A-Za-zА-Яа-яЁё0-9_.-]{1,40}){0,3}|"
    r"(?:a\s+|an\s+|the\s+)?(?:city|country|town|village|suburbs|coast|"
    r"mountains?|neighborhood|neighbourhood)|"
    r"(?:new|current|home)\s+(?:city|country|home|place|town))"
)
_RELOCATION_EVIDENCE_RE = re.compile(
    r"\b(?:(?:moved|moving|relocated|relocating)\s+from\b.{0,80}\bto\s+"
    + _RELOCATION_PLACE_SURFACE
    + r"|(?:moved|moving|relocated|relocating)\s+to\s+"
    + _RELOCATION_PLACE_SURFACE
    + r"|settled\s+in|new\s+(?:city|home|place))\b",
    re.IGNORECASE | re.DOTALL,
)
_RELOCATION_ORIGIN_EVIDENCE_RE = re.compile(
    r"\b(?:(?:moved|moving|relocated|relocating)\s+to\s+"
    + _RELOCATION_PLACE_SURFACE
    + r"\b.{0,80}\bfrom\b|"
    r"moved\s+from|moving\s+from|relocated\s+from|relocating\s+from|"
    r"left\s+(?:home|town|city|country)|came\s+from)\b",
    re.IGNORECASE | re.DOTALL,
)
_ORIGIN_EVIDENCE_RE = re.compile(
    r"\b(?:originally\s+from|born\s+in|birthplace|hometown|home\s+country|"
    r"native\s+(?:city|country|town)|grew\s+up\s+in|raised\s+in|"
    r"came\s+from|am\s+from|is\s+from|was\s+from)\b",
    re.IGNORECASE,
)
_FIRST_PERSON_RESIDENCE_EVIDENCE_RE = re.compile(
    r"\b(?:i|we)\s+(?:"
    r"live|lived|reside|resided|stay|stayed|"
    r"moved|moving|relocated|relocating|settled|"
    r"came\s+from|grew\s+up|was\s+born|am\s+from|"
    r"am\s+originally\s+from|was\s+originally\s+from"
    r")\b|"
    r"\bi(?:'m| am)\s+(?:living|based|located|originally\s+from)\b|"
    r"\bmy\s+(?:home|residence|hometown|birthplace|current\s+city|"
    r"city|town|home\s+country)\b",
    re.IGNORECASE,
)
_QUERY_LABEL_STOP_WORDS = frozenset({"what", "where"})


def person_residence_signal(*, query: str, text: str) -> PersonResidenceSignal:
    """Return bounded evidence signal for named-person residence questions."""

    residence_query = _person_residence_query(query)
    if residence_query is None:
        return PersonResidenceSignal()
    cue = _residence_cue(residence_query.kind)
    if _has_person_grounded_residence_cue(
        residence_query.person_label,
        text,
        cue=cue,
    ):
        return PersonResidenceSignal(boost=0.022, reason="person_residence_match")
    if _has_other_person_grounded_residence_cue(
        residence_query.person_label,
        text,
        cue=cue,
    ):
        return PersonResidenceSignal(
            penalty=0.034,
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


def _has_person_grounded_residence_cue(
    person: str,
    text: str,
    *,
    cue: re.Pattern[str],
) -> bool:
    return any(
        _segment_has_person_grounded_cue(person, segment, cue=cue)
        for segment in _local_residence_segments(text)
    )


def _has_other_person_grounded_residence_cue(
    person: str,
    text: str,
    *,
    cue: re.Pattern[str],
) -> bool:
    return any(
        _segment_has_other_person_grounded_cue(person, segment, cue=cue)
        for segment in _local_residence_segments(text)
    )


def _segment_has_person_grounded_cue(
    person: str,
    segment: _LocalResidenceSegment,
    *,
    cue: re.Pattern[str],
) -> bool:
    if cue.search(segment.body) is None:
        return False
    if _body_has_person_grounded_cue(person, segment.body, cue=cue):
        return True
    if not segment.speaker or not person_labels_match(segment.speaker, person):
        return False
    if _FIRST_PERSON_RESIDENCE_EVIDENCE_RE.search(segment.body):
        return True
    return not _body_mentions_other_person(person, segment.body)


def _segment_has_other_person_grounded_cue(
    person: str,
    segment: _LocalResidenceSegment,
    *,
    cue: re.Pattern[str],
) -> bool:
    if cue.search(segment.body) is None:
        return False
    if _body_has_other_person_grounded_cue(person, segment.body, cue=cue):
        return True
    if not segment.speaker or person_labels_match(segment.speaker, person):
        return False
    if _body_has_person_grounded_cue(person, segment.body, cue=cue):
        return False
    return (
        _FIRST_PERSON_RESIDENCE_EVIDENCE_RE.search(segment.body) is not None
        or not _body_mentions_person(person, segment.body)
    )


def _body_has_person_grounded_cue(
    person: str,
    body: str,
    *,
    cue: re.Pattern[str],
) -> bool:
    return _body_has_label_grounded_cue(
        body,
        cue=cue,
        matches_label=lambda label: person_labels_match(label, person),
    )


def _body_has_other_person_grounded_cue(
    person: str,
    body: str,
    *,
    cue: re.Pattern[str],
) -> bool:
    return _body_has_label_grounded_cue(
        body,
        cue=cue,
        matches_label=lambda label: not person_labels_match(label, person),
    )


def _body_has_label_grounded_cue(
    body: str,
    *,
    cue: re.Pattern[str],
    matches_label: Callable[[str], bool],
) -> bool:
    label_matches = tuple(_LABEL_TOKEN_RE.finditer(body))
    cue_matches = tuple(cue.finditer(body))
    for label_match in label_matches:
        label = label_match.group(0)
        if _label_is_dialogue_marker(label) or not matches_label(label):
            continue
        for cue_match in cue_matches:
            if cue_match.start() < label_match.end():
                continue
            if cue_match.start() - label_match.end() > 100:
                continue
            if _has_intervening_other_label(
                label_matches,
                start=label_match.end(),
                end=cue_match.start(),
                label=label,
            ):
                continue
            return True
    return False


def _has_intervening_other_label(
    matches: tuple[re.Match[str], ...],
    *,
    start: int,
    end: int,
    label: str,
) -> bool:
    for match in matches:
        if match.start() < start or match.start() >= end:
            continue
        candidate = match.group(0)
        if _label_is_dialogue_marker(candidate):
            continue
        if not person_labels_match(candidate, label):
            return True
    return False


def _local_residence_segments(text: str) -> tuple[_LocalResidenceSegment, ...]:
    dialogue_matches = tuple(_DIALOGUE_SPEAKER_RE.finditer(text))
    if not dialogue_matches:
        return tuple(
            _LocalResidenceSegment(body=segment)
            for segment in _split_local_bodies(text)
        )
    segments: list[_LocalResidenceSegment] = []
    if dialogue_matches[0].start() > 0:
        segments.extend(
            _LocalResidenceSegment(body=segment)
            for segment in _split_local_bodies(text[: dialogue_matches[0].start()])
        )
    for index, match in enumerate(dialogue_matches):
        end = (
            dialogue_matches[index + 1].start()
            if index + 1 < len(dialogue_matches)
            else len(text)
        )
        speaker = match.group("speaker")
        body = text[match.end() : end]
        segments.extend(
            _LocalResidenceSegment(body=segment, speaker=speaker)
            for segment in _split_local_bodies(body)
        )
    return tuple(segments)


def _split_local_bodies(text: str) -> tuple[str, ...]:
    return tuple(
        segment.strip(" \t:")
        for segment in _LOCAL_SEGMENT_SPLIT_RE.split(text)
        if segment.strip(" \t:")
    )


def _body_mentions_person(person: str, body: str) -> bool:
    return any(
        person_labels_match(match.group(0), person)
        for match in _LABEL_TOKEN_RE.finditer(body)
        if not _label_is_dialogue_marker(match.group(0))
    )


def _body_mentions_other_person(person: str, body: str) -> bool:
    for match in _LABEL_TOKEN_RE.finditer(body):
        label = match.group(0)
        if _label_is_dialogue_marker(label):
            continue
        if not person_labels_match(label, person):
            return True
    return False


def _label_is_dialogue_marker(label: str) -> bool:
    label_key = "".join(char for char in label.casefold() if char.isalnum())
    return label_key.startswith("d") and label_key[1:].isdigit()


def _valid_label(label: str) -> bool:
    return bool(person_alias_keys(label)) and label.casefold() not in _QUERY_LABEL_STOP_WORDS
