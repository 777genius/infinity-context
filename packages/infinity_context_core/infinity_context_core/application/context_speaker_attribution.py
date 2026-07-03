"""Speaker attribution signals for deterministic memory reranking."""

from __future__ import annotations

import re

from infinity_context_core.application.context_person_aliases import (
    person_alias_keys,
    person_labels_match,
)

_SPEAKER_LABEL_RE = (
    r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}"
    r"(?:\s+[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё._-]{1,39}){0,2}"
)
_DIALOGUE_SPEAKER_RE = re.compile(
    rf"\bD\d+:\d+\s+(?P<speaker>{_SPEAKER_LABEL_RE}):",
    re.IGNORECASE,
)
_QUERY_PERSON_LABEL_RE = re.compile(rf"\b(?P<label>{_SPEAKER_LABEL_RE})\b")
_SPEAKER_ATTRIBUTION_QUERY_RE = re.compile(
    rf"\b(?P<speaker>{_SPEAKER_LABEL_RE})\s+"
    r"(?:say|said|tell|told|think|thinks|describe|describes|"
    r"сказал|сказала|рассказал|рассказала|упомянул|упомянула|"
    r"думает|считает|описал|описала)\s+"
    rf"(?P<subject>{_SPEAKER_LABEL_RE})\b",
    re.IGNORECASE,
)
_SPEAKER_ONLY_ATTRIBUTION_QUERY_RE = re.compile(
    r"\b(?:what\s+did\s+|did\s+|what\s+does\s+|does\s+|has\s+|have\s+)?"
    rf"(?P<speaker>{_SPEAKER_LABEL_RE})\s+"
    r"(?:ever\s+|previously\s+|already\s+)?"
    r"(?:say|said|tell|told|mention|mentioned|think|thinks|"
    r"describe|describes|сказал|сказала|рассказал|рассказала|"
    r"упомянул|упомянула|думает|считает|описал|описала)\b",
    re.IGNORECASE,
)
_SPEAKER_ONLY_INVERTED_ATTRIBUTION_QUERY_RE = re.compile(
    r"\b(?:что|чего|о\s+ч[её]м)\s+"
    r"(?:сказал|сказала|рассказал|рассказала|упомянул|упомянула|"
    r"думает|считает|описал|описала)\s+"
    rf"(?P<speaker>{_SPEAKER_LABEL_RE})\b",
    re.IGNORECASE,
)
_ACCORDING_TO_SPEAKER_QUERY_RE = re.compile(
    rf"\baccording\s+to\s+(?P<speaker>{_SPEAKER_LABEL_RE})\b",
    re.IGNORECASE,
)
_SPEAKER_PERSPECTIVE_QUERY_RE = re.compile(
    rf"\b(?:from|in)\s+(?P<speaker>{_SPEAKER_LABEL_RE})(?:'s|s')?\s+"
    r"(?:view|opinion|perspective)\b",
    re.IGNORECASE,
)
_RU_ACCORDING_TO_SPEAKER_QUERY_RE = re.compile(
    rf"\bпо\s+словам\s+(?P<speaker>{_SPEAKER_LABEL_RE})\b",
    re.IGNORECASE,
)
_ATTRIBUTION_QUERY_LABEL_STOP_WORDS = frozenset(
    {
        "about",
        "already",
        "did",
        "does",
        "ever",
        "had",
        "has",
        "have",
        "may",
        "might",
        "previously",
        "project",
        "traits",
        "what",
        "who",
        "where",
        "when",
        "which",
        "according",
        "from",
        "in",
        "opinion",
        "perspective",
        "view",
        "по",
        "что",
        "кто",
        "где",
        "когда",
        "какой",
        "какая",
        "какие",
    }
)
_QUERY_LABEL_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё._-]*")
_SPEAKER_ATTRIBUTION_MATCH_BOOST = 0.024
_SPEAKER_ATTRIBUTION_SUBJECT_SELF_REPORT_PENALTY = 0.034
_SPEAKER_ATTRIBUTION_OTHER_SPEAKER_PENALTY = 0.024


def speaker_attribution_signal(*, query: str, text: str) -> tuple[float, float, str]:
    """Return bounded signal for attributed-speaker questions."""

    match = _SPEAKER_ATTRIBUTION_QUERY_RE.search(query)
    attributed_speaker, attributed_subject = _attributed_speaker_and_subject(match)
    if not attributed_speaker:
        attributed_speaker = _attributed_speaker_from_query(query)
    if not attributed_speaker:
        return 0.0, 0.0, ""
    if not attributed_subject:
        attributed_subject = _attributed_subject_from_query(
            query,
            speaker=attributed_speaker,
        )
    speakers = _dialogue_speaker_labels(text)
    if not speakers:
        return 0.0, 0.0, ""
    if any(person_labels_match(attributed_speaker, speaker) for speaker in speakers):
        return (
            _SPEAKER_ATTRIBUTION_MATCH_BOOST,
            0.0,
            "speaker_attribution_match",
        )
    if attributed_subject and any(
        person_labels_match(attributed_subject, speaker) for speaker in speakers
    ):
        return (
            0.0,
            _SPEAKER_ATTRIBUTION_SUBJECT_SELF_REPORT_PENALTY,
            "speaker_attribution_subject_self_report",
        )
    return (
        0.0,
        _SPEAKER_ATTRIBUTION_OTHER_SPEAKER_PENALTY,
        "speaker_attribution_other_speaker",
    )


def _attributed_speaker_and_subject(
    match: re.Match[str] | None,
) -> tuple[str, str]:
    if match is None:
        return "", ""
    speaker = _clean_query_person_label(match.group("speaker"), prefer_last=True)
    subject = _clean_query_person_label(match.group("subject"), prefer_last=False)
    if (
        not person_alias_keys(speaker)
        or person_labels_match(speaker, subject)
        or speaker.casefold() in _ATTRIBUTION_QUERY_LABEL_STOP_WORDS
    ):
        return "", ""
    return speaker, subject


def _attributed_speaker_from_query(query: str) -> str:
    for pattern in (
        _ACCORDING_TO_SPEAKER_QUERY_RE,
        _SPEAKER_PERSPECTIVE_QUERY_RE,
        _RU_ACCORDING_TO_SPEAKER_QUERY_RE,
        _SPEAKER_ONLY_INVERTED_ATTRIBUTION_QUERY_RE,
        _SPEAKER_ONLY_ATTRIBUTION_QUERY_RE,
    ):
        match = pattern.search(query)
        if match is not None:
            speaker = _clean_query_person_label(
                match.group("speaker"),
                prefer_last=True,
            )
            if (
                speaker.casefold() not in _ATTRIBUTION_QUERY_LABEL_STOP_WORDS
                and person_alias_keys(speaker)
            ):
                return speaker
    return ""


def _attributed_subject_from_query(query: str, *, speaker: str) -> str:
    for match in _QUERY_PERSON_LABEL_RE.finditer(query):
        label = match.group("label").strip()
        label = _clean_query_person_label(label, prefer_last=False)
        if not person_alias_keys(label):
            continue
        if label.casefold() in _ATTRIBUTION_QUERY_LABEL_STOP_WORDS:
            continue
        if person_labels_match(label, speaker):
            continue
        return label
    return ""


def _clean_query_person_label(label: str, *, prefer_last: bool) -> str:
    tokens = tuple(
        token
        for token in _QUERY_LABEL_TOKEN_RE.findall(label or "")
        if token.casefold() not in _ATTRIBUTION_QUERY_LABEL_STOP_WORDS
        and token[:1].isupper()
    )
    if not tokens:
        return ""
    if not prefer_last or len(tokens) > 1:
        return " ".join(tokens)
    return tokens[-1]


def _dialogue_speaker_labels(text: str) -> frozenset[str]:
    return frozenset(
        match.group("speaker")
        for match in _DIALOGUE_SPEAKER_RE.finditer(text)
    )
