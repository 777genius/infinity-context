"""Named-person team membership signals for deterministic memory reranking."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

from infinity_context_core.application.context_person_aliases import (
    person_alias_keys,
    person_labels_match,
)


class TeamMembershipKind(Enum):
    TEAM = "team"
    CLUB = "club"
    GROUP = "group"


class PersonTeamMembershipSignal(NamedTuple):
    boost: float = 0.0
    penalty: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class _PersonTeamQuery:
    person_label: str
    kind: TeamMembershipKind


_LABEL_RE = (
    r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
    r"(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}){0,2}"
)
_DIALOGUE_SPEAKER_RE = re.compile(rf"\bD\d+:\d+\s+(?P<speaker>{_LABEL_RE}):")
_LABEL_TOKEN_RE = re.compile(rf"\b{_LABEL_RE}\b")
_TEAM_QUERY_RE = re.compile(
    rf"(?i:\bwhat\s+)(?P<kind>team|club|group)\s+"
    rf"(?i:(?:is|was)\s+)(?P<person>{_LABEL_RE})\s+"
    rf"(?i:(?:on|in|part\s+of)\b)|"
    rf"(?i:\bwhich\s+)(?P<which_kind>team|club|group)\s+"
    rf"(?i:(?:is|was)\s+)(?P<which_person>{_LABEL_RE})\s+"
    rf"(?i:(?:on|in|part\s+of)\b)|"
    rf"(?i:\b(?:what|which)\s+)(?P<belongs_kind>team|club|group)\s+"
    rf"(?i:(?:does|did)\s+)(?P<belongs_person>{_LABEL_RE})\s+"
    rf"(?i:(?:belong\s+to|join)\b)|"
    rf"(?i:\b(?:what|which)\s+)(?P<member_kind>team|club|group)\s+"
    rf"(?i:(?:is|was)\s+)(?P<member_person>{_LABEL_RE})\s+"
    rf"(?i:(?:a\s+)?member\s+of\b)|"
    rf"(?i:\bwhat\s+)(?P<person_possessive>{_LABEL_RE})(?:'s|s')?\s+"
    rf"(?P<possessive_kind>team|club|group)\b",
)
_TEAM_CUE_RE = re.compile(
    r"\b(?:team|club|group|teammates?|team\s+members?|member\s+of|"
    r"part\s+of|belongs?\s+to|joined|on\s+the\s+team|in\s+the\s+club)\b",
    re.IGNORECASE,
)
_CLUB_CUE_RE = re.compile(
    r"\b(?:club|group|member\s+of|part\s+of|belongs?\s+to|joined|in\s+the\s+club)\b",
    re.IGNORECASE,
)
_QUERY_LABEL_STOP_WORDS = frozenset({"what", "which"})


def person_team_membership_signal(
    *,
    query: str,
    text: str,
) -> PersonTeamMembershipSignal:
    """Return bounded evidence signal for named-person team/club questions."""

    team_query = _person_team_query(query)
    if team_query is None:
        return PersonTeamMembershipSignal()
    cue = _membership_cue(team_query.kind)
    if _text_mentions_person(team_query.person_label, text) and cue.search(text) is not None:
        return PersonTeamMembershipSignal(
            boost=0.022,
            reason="person_team_membership_match",
        )
    if (
        cue.search(text) is not None
        and not _text_mentions_person(team_query.person_label, text)
        and _text_mentions_other_person(team_query.person_label, text)
    ):
        return PersonTeamMembershipSignal(
            penalty=0.022,
            reason="person_team_membership_other_person",
        )
    return PersonTeamMembershipSignal()


def _person_team_query(query: str) -> _PersonTeamQuery | None:
    match = _TEAM_QUERY_RE.search(query)
    if match is None:
        return None
    groups = match.groupdict()
    person = (
        groups.get("person")
        or groups.get("which_person")
        or groups.get("belongs_person")
        or groups.get("member_person")
        or groups.get("person_possessive")
        or ""
    ).strip(" :,.!?;")
    raw_kind = (
        groups.get("kind")
        or groups.get("which_kind")
        or groups.get("belongs_kind")
        or groups.get("member_kind")
        or groups.get("possessive_kind")
        or "team"
    )
    if not _valid_label(person):
        return None
    return _PersonTeamQuery(
        person_label=person,
        kind=_team_kind(raw_kind),
    )


def _team_kind(value: str) -> TeamMembershipKind:
    normalized = value.casefold()
    if normalized == "club":
        return TeamMembershipKind.CLUB
    if normalized == "group":
        return TeamMembershipKind.GROUP
    return TeamMembershipKind.TEAM


def _membership_cue(kind: TeamMembershipKind) -> re.Pattern[str]:
    if kind in {TeamMembershipKind.CLUB, TeamMembershipKind.GROUP}:
        return _CLUB_CUE_RE
    return _TEAM_CUE_RE


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
