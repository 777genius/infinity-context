"""Speaker attribution signals for deterministic memory reranking."""

from __future__ import annotations

import re
from dataclasses import dataclass

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
_DIALOGUE_TURN_RE = re.compile(
    rf"\bD\d+:\d+\s+(?P<speaker>{_SPEAKER_LABEL_RE}):\s*"
    r"(?P<content>.*?)(?=\bD\d+:\d+\s+"
    rf"{_SPEAKER_LABEL_RE}:|$)",
    re.IGNORECASE | re.DOTALL,
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
_COMMUNICATION_DIRECTION_MATCH_BOOST = 0.032
_COMMUNICATION_DIRECTION_UNGROUNDED_PENALTY = 0.035
_COMMUNICATION_VERB_RE = (
    r"tell|tells|told|ask|asks|asked|remind|reminds|reminded|"
    r"invite|invites|invited|warn|warns|warned|message|messages|messaged|"
    r"text|texts|texted|call|calls|called|send|sends|sent"
)
_COMMUNICATION_VERB_SURFACE_RE = re.compile(
    rf"\b(?:{_COMMUNICATION_VERB_RE})\b",
    re.IGNORECASE,
)
_WHO_COMMUNICATION_SPEAKER_QUERY_RE = re.compile(
    rf"\bwho\s+(?P<verb>{_COMMUNICATION_VERB_RE})\s+"
    rf"(?P<addressee>{_SPEAKER_LABEL_RE})\b",
    re.IGNORECASE,
)
_WHO_COMMUNICATION_ADDRESSEE_QUERY_RE = re.compile(
    rf"\bwho\s+did\s+(?P<speaker>{_SPEAKER_LABEL_RE})\s+"
    rf"(?P<verb>{_COMMUNICATION_VERB_RE})\b",
    re.IGNORECASE,
)
_WHO_PASSIVE_COMMUNICATION_ADDRESSEE_QUERY_RE = re.compile(
    rf"\bwho\s+(?:was|were)\s+(?P<verb>{_COMMUNICATION_VERB_RE})\b"
    rf".{{0,100}}\bby\s+(?P<speaker>{_SPEAKER_LABEL_RE})\b",
    re.IGNORECASE | re.DOTALL,
)
_FIRST_PERSON_COMMUNICATION_RE = re.compile(
    rf"\b(?:I|we)\s+(?:{_COMMUNICATION_VERB_RE})\b",
    re.IGNORECASE,
)
_RECIPIENT_AFTER_COMMUNICATION_RE = re.compile(
    rf"\b(?:{_COMMUNICATION_VERB_RE})\s+(?:that\s+)?"
    rf"(?P<recipient>{_SPEAKER_LABEL_RE}|her|him|me|them|us|you|"
    r"my\s+(?:brother|child|daughter|father|friend|manager|mother|"
    r"parent|partner|sibling|sister|son|spouse|teacher|team|wife|husband)|"
    r"the\s+(?:client|doctor|group|manager|teacher|team))\b",
    re.IGNORECASE,
)
_NAMED_ACTOR_COMMUNICATION_RE = re.compile(
    rf"\b(?P<actor>{_SPEAKER_LABEL_RE})\s+(?P<verb>{_COMMUNICATION_VERB_RE})\s+"
    rf"(?P<recipient>{_SPEAKER_LABEL_RE}|her|him|me|them|us|you)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SpeakerAttributionMatch:
    attributed_speaker: str
    matched_speaker: str
    exact_name_match: bool
    alias_only_match: bool


@dataclass(frozen=True)
class CommunicationDirectionGrounding:
    query_direction: str
    speaker: str
    addressee: str
    grounded: bool
    ungrounded: bool


def speaker_attribution_signal(*, query: str, text: str) -> tuple[float, float, str]:
    """Return bounded signal for attributed-speaker questions."""

    attribution_match = speaker_attribution_match(query=query, text=text)
    if attribution_match is not None:
        return (
            _SPEAKER_ATTRIBUTION_MATCH_BOOST,
            0.0,
            "speaker_attribution_match",
        )
    attributed_speaker, attributed_subject = _attributed_speaker_query_parts(query)
    if not attributed_speaker:
        return 0.0, 0.0, ""
    speakers = _dialogue_speaker_labels(text)
    if not speakers:
        return 0.0, 0.0, ""
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


def communication_direction_grounding(
    *,
    query: str,
    text: str,
) -> CommunicationDirectionGrounding:
    """Return grounding for who-communication questions with directional roles."""

    direction, speaker, addressee = _communication_query_parts(query)
    if not direction:
        return CommunicationDirectionGrounding("", "", "", False, False)
    grounded = _communication_direction_is_grounded(
        text=text,
        direction=direction,
        speaker=speaker,
        addressee=addressee,
    )
    ungrounded = bool(
        not grounded
        and _communication_query_names_present(
            text=text,
            speaker=speaker,
            addressee=addressee,
        )
    )
    return CommunicationDirectionGrounding(
        query_direction=direction,
        speaker=speaker,
        addressee=addressee,
        grounded=grounded,
        ungrounded=ungrounded,
    )


def communication_direction_signal(*, query: str, text: str) -> tuple[float, float, str]:
    """Return bounded rerank signal for who-told/who-asked direction grounding."""

    grounding = communication_direction_grounding(query=query, text=text)
    if grounding.grounded:
        return (
            _COMMUNICATION_DIRECTION_MATCH_BOOST,
            0.0,
            "communication_direction_grounded",
        )
    if grounding.ungrounded:
        return (
            0.0,
            _COMMUNICATION_DIRECTION_UNGROUNDED_PENALTY,
            "communication_direction_ungrounded",
        )
    return 0.0, 0.0, ""


def speaker_attribution_match(
    *,
    query: str,
    text: str,
) -> SpeakerAttributionMatch | None:
    """Return the matched dialogue speaker for attributed-speaker questions."""

    attributed_speaker, _ = _attributed_speaker_query_parts(query)
    if not attributed_speaker:
        return None
    speakers = _dialogue_speaker_labels(text)
    if not speakers:
        return None
    attributed_exact_key = _normalized_label(attributed_speaker)
    matched_speakers = tuple(
        speaker
        for speaker in sorted(speakers)
        if person_labels_match(attributed_speaker, speaker)
    )
    if not matched_speakers:
        return None
    for speaker in matched_speakers:
        exact_name_match = _normalized_label(speaker) == attributed_exact_key
        if exact_name_match:
            return SpeakerAttributionMatch(
                attributed_speaker=attributed_speaker,
                matched_speaker=speaker,
                exact_name_match=True,
                alias_only_match=False,
            )
    return SpeakerAttributionMatch(
        attributed_speaker=attributed_speaker,
        matched_speaker=matched_speakers[0],
        exact_name_match=False,
        alias_only_match=True,
    )


def _attributed_speaker_query_parts(query: str) -> tuple[str, str]:
    match = _SPEAKER_ATTRIBUTION_QUERY_RE.search(query)
    attributed_speaker, attributed_subject = _attributed_speaker_and_subject(match)
    if not attributed_speaker:
        attributed_speaker = _attributed_speaker_from_query(query)
    if not attributed_speaker:
        return "", ""
    if not attributed_subject:
        attributed_subject = _attributed_subject_from_query(
            query,
            speaker=attributed_speaker,
        )
    return attributed_speaker, attributed_subject


def _communication_query_parts(query: str) -> tuple[str, str, str]:
    if match := _WHO_COMMUNICATION_ADDRESSEE_QUERY_RE.search(query):
        speaker = _clean_query_person_label(match.group("speaker"), prefer_last=False)
        if _valid_query_person(speaker):
            return "ask_addressee", speaker, ""
    if match := _WHO_PASSIVE_COMMUNICATION_ADDRESSEE_QUERY_RE.search(query):
        speaker = _clean_query_person_label(match.group("speaker"), prefer_last=False)
        if _valid_query_person(speaker):
            return "ask_addressee", speaker, ""
    if match := _WHO_COMMUNICATION_SPEAKER_QUERY_RE.search(query):
        addressee = _clean_query_person_label(
            match.group("addressee"),
            prefer_last=False,
        )
        if _valid_query_person(addressee):
            return "ask_speaker", "", addressee
    return "", "", ""


def _communication_direction_is_grounded(
    *,
    text: str,
    direction: str,
    speaker: str,
    addressee: str,
) -> bool:
    for turn_speaker, content in _dialogue_turns(text):
        if direction == "ask_speaker" and addressee:
            if (
                not person_labels_match(turn_speaker, addressee)
                and _first_person_message_to_entity(content, addressee)
            ):
                return True
            if _named_actor_message_to_entity(
                content,
                addressee,
                speaker_context=turn_speaker,
            ):
                return True
        if direction == "ask_addressee" and speaker:
            if (
                person_labels_match(turn_speaker, speaker)
                and _first_person_message_to_recipient(content)
            ):
                return True
            if _named_actor_message_to_recipient(
                content,
                speaker,
                speaker_context=turn_speaker,
            ):
                return True
    if _dialogue_turns(text):
        return False
    if direction == "ask_speaker" and addressee:
        return _named_actor_message_to_entity(text, addressee, speaker_context="")
    if direction == "ask_addressee" and speaker:
        return _named_actor_message_to_recipient(text, speaker, speaker_context="")
    return False


def _first_person_message_to_entity(content: str, entity: str) -> bool:
    if not _FIRST_PERSON_COMMUNICATION_RE.search(content):
        return False
    return _recipient_after_communication_matches(
        content,
        entity=entity,
        speaker_context="",
    )


def _first_person_message_to_recipient(content: str) -> bool:
    return bool(
        _FIRST_PERSON_COMMUNICATION_RE.search(content)
        and _RECIPIENT_AFTER_COMMUNICATION_RE.search(content)
    )


def _named_actor_message_to_entity(
    content: str,
    entity: str,
    *,
    speaker_context: str,
) -> bool:
    for match in _NAMED_ACTOR_COMMUNICATION_RE.finditer(content):
        actor = _clean_query_person_label(match.group("actor"), prefer_last=False)
        recipient = match.group("recipient")
        if person_labels_match(actor, entity):
            continue
        if _recipient_matches_entity(
            recipient,
            entity=entity,
            speaker_context=speaker_context,
        ):
            return True
    return False


def _named_actor_message_to_recipient(
    content: str,
    speaker: str,
    *,
    speaker_context: str,
) -> bool:
    for match in _NAMED_ACTOR_COMMUNICATION_RE.finditer(content):
        actor = _clean_query_person_label(match.group("actor"), prefer_last=False)
        recipient = match.group("recipient")
        if not person_labels_match(actor, speaker):
            continue
        if _recipient_is_present(recipient, speaker_context=speaker_context):
            return True
    return False


def _recipient_after_communication_matches(
    content: str,
    *,
    entity: str,
    speaker_context: str,
) -> bool:
    return any(
        _recipient_matches_entity(
            match.group("recipient"),
            entity=entity,
            speaker_context=speaker_context,
        )
        for match in _RECIPIENT_AFTER_COMMUNICATION_RE.finditer(content)
    )


def _recipient_matches_entity(
    recipient: str,
    *,
    entity: str,
    speaker_context: str,
) -> bool:
    normalized = recipient.casefold().strip()
    if normalized in {"me", "us"}:
        return bool(speaker_context and person_labels_match(speaker_context, entity))
    return person_labels_match(recipient, entity)


def _recipient_is_present(recipient: str, *, speaker_context: str) -> bool:
    normalized = recipient.casefold().strip()
    if normalized in {"me", "us", "you", "her", "him", "them"}:
        return True
    if re.search(
        r"\b(?:my|his|her|their|our)\s+"
        r"(?:brother|child|daughter|father|friend|manager|mother|"
        r"parent|partner|sibling|sister|son|spouse|teacher|team|wife|husband)\b"
        r"|\bthe\s+(?:client|doctor|group|manager|teacher|team)\b",
        recipient,
        re.IGNORECASE,
    ):
        return True
    if speaker_context and person_labels_match(recipient, speaker_context):
        return True
    return bool(person_alias_keys(_clean_query_person_label(recipient, prefer_last=False)))


def _communication_query_names_present(
    *,
    text: str,
    speaker: str,
    addressee: str,
) -> bool:
    target = speaker or addressee
    if not target:
        return False
    return _label_in_text(text, target)


def _dialogue_turns(text: str) -> tuple[tuple[str, str], ...]:
    return tuple(
        (match.group("speaker"), match.group("content"))
        for match in _DIALOGUE_TURN_RE.finditer(text)
    )


def _valid_query_person(label: str) -> bool:
    return bool(
        label
        and label.casefold() not in _ATTRIBUTION_QUERY_LABEL_STOP_WORDS
        and person_alias_keys(label)
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


def _normalized_label(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


def _label_in_text(text: str, label: str) -> bool:
    return any(
        re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])",
            text,
            re.IGNORECASE,
        )
        for alias in person_alias_keys(label)
    )
