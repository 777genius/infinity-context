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
    CLASS = "class"


class PersonTeamMembershipSignal(NamedTuple):
    boost: float = 0.0
    penalty: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class _PersonTeamQuery:
    person_label: str
    kind: TeamMembershipKind
    requires_current: bool = False


_LABEL_RE = (
    r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
    r"(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}){0,2}"
)
_DIALOGUE_SPEAKER_RE = re.compile(rf"\bD\d+:\d+\s+(?P<speaker>{_LABEL_RE}):")
_LABEL_TOKEN_RE = re.compile(rf"\b{_LABEL_RE}\b")
_SENTENCE_RE = re.compile(r"[^.?!;\n]+")
_TEAM_QUERY_RE = re.compile(
    rf"(?i:\bwhat\s+)(?P<kind>team|club|group|class)\s+"
    rf"(?i:(?:is|was)\s+)(?P<person>{_LABEL_RE})\s+"
    rf"(?i:(?:on|in|part\s+of)\b)|"
    rf"(?i:\bwhich\s+)(?P<which_kind>team|club|group|class)\s+"
    rf"(?i:(?:is|was)\s+)(?P<which_person>{_LABEL_RE})\s+"
    rf"(?i:(?:on|in|part\s+of)\b)|"
    rf"(?i:\b(?:what|which)\s+)(?P<belongs_kind>team|club|group|class)\s+"
    rf"(?i:(?:does|did)\s+)(?P<belongs_person>{_LABEL_RE})\s+"
    rf"(?i:(?:belong\s+to|join)\b)|"
    rf"(?i:\b(?:what|which)\s+)(?P<member_kind>team|club|group|class)\s+"
    rf"(?i:(?:is|was)\s+)(?P<member_person>{_LABEL_RE})\s+"
    rf"(?i:(?:a\s+)?member\s+of\b)|"
    rf"(?i:\bwhat\s+)(?P<person_possessive>{_LABEL_RE})(?:'s|s')?\s+"
    rf"(?P<possessive_kind>team|club|group|class)\b",
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
_CLASS_CUE_RE = re.compile(
    r"\b(?:class|classes|course|courses|member\s+of|part\s+of|joined|"
    r"enrolled|signed\s+up|taking|in\s+the\s+class)\b",
    re.IGNORECASE,
)
_QUERY_LABEL_STOP_WORDS = frozenset({"what", "which"})
_STALE_MEMBERSHIP_CUE_RE = re.compile(
    r"\b(?:former|formerly|previously|used\s+to\s+be|used\s+to\s+belong\s+to|"
    r"used\s+to\s+be\s+(?:on|in|part\s+of)|no\s+longer|not\s+anymore|"
    r"left|quit|dropped\s+out\s+of|withdrew\s+from|graduated\s+from)\b",
    re.IGNORECASE,
)
_PAST_MEMBERSHIP_QUERY_RE = re.compile(
    r"\b(?:was|were|did|former|formerly|previously|used\s+to|no\s+longer|"
    r"left|quit|dropped\s+out|withdrew|graduated)\b",
    re.IGNORECASE,
)


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
    if _text_has_membership_match(team_query, text, cue=cue):
        return PersonTeamMembershipSignal(
            boost=0.022,
            reason="person_team_membership_match",
        )
    if _text_has_stale_membership(team_query, text, cue=cue):
        return PersonTeamMembershipSignal(
            penalty=0.032,
            reason="person_team_membership_stale_membership",
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
        requires_current=_requires_current_membership_answer(query),
    )


def _requires_current_membership_answer(query: str) -> bool:
    return _PAST_MEMBERSHIP_QUERY_RE.search(query) is None


def _team_kind(value: str) -> TeamMembershipKind:
    normalized = value.casefold()
    if normalized == "class":
        return TeamMembershipKind.CLASS
    if normalized == "club":
        return TeamMembershipKind.CLUB
    if normalized == "group":
        return TeamMembershipKind.GROUP
    return TeamMembershipKind.TEAM


def _membership_cue(kind: TeamMembershipKind) -> re.Pattern[str]:
    if kind is TeamMembershipKind.CLASS:
        return _CLASS_CUE_RE
    if kind in {TeamMembershipKind.CLUB, TeamMembershipKind.GROUP}:
        return _CLUB_CUE_RE
    return _TEAM_CUE_RE


def _text_has_membership_match(
    team_query: _PersonTeamQuery,
    text: str,
    *,
    cue: re.Pattern[str],
) -> bool:
    for sentence_match in _SENTENCE_RE.finditer(text):
        sentence = sentence_match.group(0)
        if not _text_mentions_person(team_query.person_label, sentence):
            continue
        if cue.search(sentence) is None:
            continue
        if not _has_membership_direction(team_query, sentence):
            continue
        if team_query.requires_current and _STALE_MEMBERSHIP_CUE_RE.search(sentence):
            continue
        return True
    return False


def _has_membership_direction(
    team_query: _PersonTeamQuery,
    sentence: str,
) -> bool:
    for person_pattern in _person_label_alias_patterns(team_query.person_label):
        if team_query.kind is TeamMembershipKind.CLASS:
            membership_noun = r"class|course"
            joined_phrase = (
                r"(?:joined|signed\s+up\s+for|enrolled\s+in|taking|in|"
                r"used\s+to\s+(?:take|be\s+in))"
            )
        elif team_query.kind is TeamMembershipKind.CLUB:
            membership_noun = r"club"
            joined_phrase = (
                r"(?:joined|belong(?:s|ed)?\s+to|member\s+of|part\s+of|in|"
                r"used\s+to\s+(?:belong\s+to|be\s+(?:in|part\s+of)))"
            )
        elif team_query.kind is TeamMembershipKind.GROUP:
            membership_noun = r"group"
            joined_phrase = (
                r"(?:joined|belong(?:s|ed)?\s+to|member\s+of|part\s+of|in|"
                r"used\s+to\s+(?:belong\s+to|be\s+(?:in|part\s+of)))"
            )
        else:
            membership_noun = r"team"
            joined_phrase = (
                r"(?:joined|on|member\s+of|part\s+of|belong(?:s|ed)?\s+to|"
                r"used\s+to\s+(?:belong\s+to|be\s+(?:on|part\s+of)))"
            )
        patterns = (
            rf"\bD\d+:\d+\s+{person_pattern}:\s*.{{0,120}}\b"
            rf"I\s+{joined_phrase}\s+(?:the\s+|a\s+|an\s+)?"
            rf"(?:[A-Za-zА-Яа-яЁё0-9_.-]{{1,40}}\s+){{0,4}}"
            rf"(?:{membership_noun})\b",
            rf"\bD\d+:\d+\s+{person_pattern}:\s*.{{0,120}}\b"
            rf"I\s+(?:am|was)\s+(?:a\s+)?(?:member|part)\s+of\s+"
            rf"(?:the\s+|a\s+|an\s+)?"
            rf"(?:[A-Za-zА-Яа-яЁё0-9_.-]{{1,40}}\s+){{0,4}}"
            rf"(?:{membership_noun})\b",
            rf"\b{person_pattern}\s+{joined_phrase}\s+(?:the\s+|a\s+|an\s+)?"
            rf"(?:[A-Za-zА-Яа-яЁё0-9_.-]{{1,40}}\s+){{0,4}}"
            rf"(?:{membership_noun})\b",
            rf"\b{person_pattern}\s+(?:is|was)\s+(?:a\s+)?(?:member|part)\s+"
            rf"of\s+(?:the\s+|a\s+|an\s+)?"
            rf"(?:[A-Za-zА-Яа-яЁё0-9_.-]{{1,40}}\s+){{0,4}}"
            rf"(?:{membership_noun})\b",
            rf"\b{person_pattern}(?:'s|s')\s+(?:{membership_noun})\s+"
            r"(?:is|was)\b",
        )
        if any(re.search(pattern, sentence, re.IGNORECASE | re.DOTALL) for pattern in patterns):
            return True
    return False


def _text_has_stale_membership(
    team_query: _PersonTeamQuery,
    text: str,
    *,
    cue: re.Pattern[str],
) -> bool:
    if not team_query.requires_current:
        return False
    for sentence_match in _SENTENCE_RE.finditer(text):
        sentence = sentence_match.group(0)
        if not _text_mentions_person(team_query.person_label, sentence):
            continue
        if cue.search(sentence) is None:
            continue
        if _STALE_MEMBERSHIP_CUE_RE.search(sentence) is not None:
            return True
    return False


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


def _person_label_alias_patterns(person_label: str) -> tuple[str, ...]:
    labels = [person_label]
    tokens = person_label.strip(" :,.!?;").split()
    if len(tokens) > 1:
        labels.append(tokens[0])
    return tuple(
        re.escape(label)
        for label in dict.fromkeys(label.strip(" :,.!?;") for label in labels)
        if person_alias_keys(label)
    )


def _valid_label(label: str) -> bool:
    return bool(person_alias_keys(label)) and label.casefold() not in _QUERY_LABEL_STOP_WORDS
