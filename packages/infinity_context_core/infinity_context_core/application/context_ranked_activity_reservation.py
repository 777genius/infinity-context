"""Stable activity-inventory reservations for ranked evidence consumers."""

from __future__ import annotations

import re
from itertools import islice

from infinity_context_core.application.context_count_cardinality import (
    requests_list_aggregation,
)
from infinity_context_core.application.context_person_aliases import person_labels_match
from infinity_context_core.application.dto import ContextItem

_MAX_RESERVATIONS = 8
_MAX_ANALYZED_QUERY_CHARS = 512
_MAX_ANALYZED_ITEM_CHARS = 16_384
_MAX_DIALOGUE_TURNS = 32
_MAX_SPEAKER_HEADER_CHARS = 128

_WORD_RE = re.compile(r"\b[A-Za-z][A-Za-z'.-]{0,63}\b")
_TURN_MARKER_RE = re.compile(r"\bD[0-9]{1,6}[:-][0-9]{1,6}\s+")
_ACTIVITY_QUERY_RE = re.compile(
    r"\b(?:activities?|hobbies|pastimes?|sports?|exercises?|workouts?)\b",
    re.IGNORECASE,
)
_SHARING_IMAGE_QUERY_RE = re.compile(
    r"\[\s*sharing image\s*-\s*query\s*:\s*(?P<label>[^\].\r\n]{1,160})",
    re.IGNORECASE,
)
_SHARING_IMAGE_BLOCK_RE = re.compile(
    r"\[\s*sharing image\b[^\]]*(?:\]|$)",
    re.IGNORECASE,
)

_QUERY_STOP_LABELS = frozenset(
    {
        "All",
        "Activities",
        "Activity",
        "Did",
        "Does",
        "Done",
        "Has",
        "Have",
        "Hobbies",
        "Hobby",
        "List",
        "Name",
        "Show",
        "What",
        "Which",
    }
)
_CONTAINER_TERMS = frozenset(
    {
        "class",
        "classes",
        "club",
        "clubs",
        "course",
        "courses",
        "game",
        "games",
        "league",
        "leagues",
        "lesson",
        "lessons",
        "practice",
        "practices",
        "project",
        "projects",
        "session",
        "sessions",
        "team",
        "teams",
        "training",
        "trip",
        "trips",
        "workout",
        "workouts",
        "workshop",
        "workshops",
    }
)
_PARTICIPATION_ACTIONS = frozenset(
    {
        "attended",
        "began",
        "did",
        "do",
        "enjoy",
        "enjoyed",
        "go",
        "going",
        "joined",
        "learned",
        "love",
        "made",
        "make",
        "participated",
        "played",
        "practice",
        "practiced",
        "started",
        "take",
        "taking",
        "took",
        "tried",
        "went",
    }
)
_FIRST_PERSON_TERMS = frozenset({"i", "i'd", "i'll", "i'm", "i've", "we", "we're"})
_COMPLEMENT_SCAFFOLD = frozenset(
    {
        "a",
        "also",
        "an",
        "another",
        "at",
        "both",
        "in",
        "just",
        "my",
        "often",
        "on",
        "our",
        "recently",
        "sometimes",
        "the",
        "to",
        "up",
    }
)
_COMPLEMENT_ACTIONS = frozenset(
    {
        "attended",
        "began",
        "enjoy",
        "enjoyed",
        "go",
        "going",
        "love",
        "participated",
        "play",
        "played",
        "practice",
        "practiced",
        "started",
        "tried",
        "went",
    }
)
_SECONDARY_ACTIONS = frozenset(
    {
        "do",
        "go",
        "going",
        "participate",
        "participating",
        "play",
        "playing",
        "practice",
        "practicing",
        "take",
        "taking",
    }
)
_VISUAL_TERMS = frozenset({"image", "photo", "photograph", "pic", "picture", "snapshot"})
_VISUAL_SHARE_TERMS = frozenset({"posted", "sent", "shared", "sharing", "uploaded"})
_SLOT_LABEL_STOPWORDS = _COMPLEMENT_SCAFFOLD | frozenset(
    {"and", "from", "joined", "of", "started", "taking", "went"}
)


def reserve_activity_inventory_head(
    items: tuple[ContextItem, ...],
    *,
    query: str,
) -> tuple[ContextItem, ...]:
    """Move distinct direct activity evidence to a stable bounded head."""

    bounded_query = (query or "")[:_MAX_ANALYZED_QUERY_CHARS]
    if not _is_person_activity_inventory_query(bounded_query):
        return items
    owner_labels = _query_person_labels(bounded_query)
    if not owner_labels:
        return items

    reserved_indices: list[int] = []
    reserved_slots: set[str] = set()
    for index, item in enumerate(items):
        bounded_text = (item.text or "")[:_MAX_ANALYZED_ITEM_CHARS]
        if item.is_instruction or not item.source_refs or not bounded_text.strip():
            continue
        slot = _new_owned_activity_slot(
            bounded_text,
            owner_labels=owner_labels,
            reserved_slots=reserved_slots,
        )
        if not slot:
            continue
        reserved_indices.append(index)
        reserved_slots.add(slot)
        if len(reserved_indices) >= _MAX_RESERVATIONS:
            break
    if not reserved_indices:
        return items

    reserved_index_set = set(reserved_indices)
    return (
        *(items[index] for index in reserved_indices),
        *(item for index, item in enumerate(items) if index not in reserved_index_set),
    )


def activity_inventory_query_supported(query: str) -> bool:
    """Return whether direct person-owned activity evidence can be evaluated."""

    bounded_query = (query or "")[:_MAX_ANALYZED_QUERY_CHARS]
    return _is_person_activity_inventory_query(bounded_query) and bool(
        _query_person_labels(bounded_query)
    )


def activity_inventory_slot_key(label: str) -> str:
    """Normalize one activity answer label to the retrieval policy's slot key."""

    return _slot_key((label or "")[:_MAX_ANALYZED_QUERY_CHARS])


def activity_inventory_evidence_slots(*, query: str, text: str) -> tuple[str, ...]:
    """Extract bounded, directly owned activity slots from one evidence item."""

    bounded_query = (query or "")[:_MAX_ANALYZED_QUERY_CHARS]
    if not activity_inventory_query_supported(bounded_query):
        return ()
    owner_labels = _query_person_labels(bounded_query)
    bounded_text = (text or "")[:_MAX_ANALYZED_ITEM_CHARS]
    dialogue_text = _mask_sharing_image_caption(bounded_text)
    slots: list[str] = []
    for speaker, body in _dialogue_turns(dialogue_text):
        if not any(person_labels_match(speaker, owner) for owner in owner_labels):
            continue
        tokens = _word_tokens(_without_sharing_image_payload(body))
        if not _direct_participation_or_visual_share(body, tokens=tokens):
            continue
        for slot in _source_supported_activity_slots(body, tokens=tokens):
            if slot not in slots:
                slots.append(slot)
            if len(slots) >= _MAX_RESERVATIONS:
                return tuple(slots)
    return tuple(slots)


def _is_person_activity_inventory_query(query: str) -> bool:
    return bool(_ACTIVITY_QUERY_RE.search(query)) and requests_list_aggregation(query)


def _query_person_labels(query: str) -> tuple[str, ...]:
    activity_match = _ACTIVITY_QUERY_RE.search(query)
    if activity_match is None:
        return ()
    trailing = _capitalized_label_groups(query[activity_match.end() :])
    if trailing:
        return trailing[:1]
    leading = _capitalized_label_groups(query[: activity_match.start()])
    return leading[-1:]


def _capitalized_label_groups(value: str) -> tuple[str, ...]:
    labels: list[str] = []
    current: list[str] = []
    previous_end = 0
    for match in _WORD_RE.finditer(value):
        token = match.group(0)
        valid = token[0].isupper() and token not in _QUERY_STOP_LABELS
        joins_current = (
            bool(current) and value[previous_end : match.start()].isspace() and len(current) < 3
        )
        if not valid:
            if current:
                labels.append(" ".join(current))
                current = []
        elif joins_current:
            current.append(token)
        else:
            if current:
                labels.append(" ".join(current))
            current = [token]
        previous_end = match.end()
    if current:
        labels.append(" ".join(current))
    return tuple(labels)


def _mask_sharing_image_caption(text: str) -> str:
    def mask(match: re.Match[str]) -> str:
        block = match.group(0)
        query_match = _SHARING_IMAGE_QUERY_RE.search(block)
        if query_match is None:
            return " " * len(block)
        prefix = block[: query_match.end()]
        suffix = "]" if block.endswith("]") else ""
        return prefix + (" " * (len(block) - len(prefix) - len(suffix))) + suffix

    return _SHARING_IMAGE_BLOCK_RE.sub(mask, text)


def _without_sharing_image_payload(text: str) -> str:
    return _SHARING_IMAGE_BLOCK_RE.sub(
        lambda match: " " * len(match.group(0)),
        text,
    )


def _new_owned_activity_slot(
    text: str,
    *,
    owner_labels: tuple[str, ...],
    reserved_slots: set[str],
) -> str:
    dialogue_text = _mask_sharing_image_caption(text)
    for speaker, body in _dialogue_turns(dialogue_text):
        if not any(person_labels_match(speaker, owner) for owner in owner_labels):
            continue
        tokens = _word_tokens(body)
        if not _direct_participation_or_visual_share(body, tokens=tokens):
            continue
        for slot in _reservation_activity_slots(body, tokens=tokens):
            if slot not in reserved_slots:
                return slot
    return ""


def _reservation_activity_slots(
    body: str,
    *,
    tokens: tuple[tuple[int, str], ...],
) -> tuple[str, ...]:
    """Return source-backed slots, with a bounded pure-visual fallback."""

    supported = _source_supported_activity_slots(body, tokens=tokens)
    if supported:
        return supported
    if not _pure_visual_evidence_body(body):
        return ()
    return _activity_slots(body, tokens=tokens)


def _pure_visual_evidence_body(body: str) -> bool:
    if _SHARING_IMAGE_QUERY_RE.search(body) is None:
        return False
    return not _without_sharing_image_payload(body).strip()


def _dialogue_turns(text: str) -> tuple[tuple[str, str], ...]:
    marker_matches = tuple(islice(_TURN_MARKER_RE.finditer(text), _MAX_DIALOGUE_TURNS + 1))
    headers: list[tuple[int, int, str]] = []
    for marker in marker_matches:
        speaker_start = marker.end()
        speaker_limit = min(len(text), speaker_start + _MAX_SPEAKER_HEADER_CHARS)
        colon = text.find(":", speaker_start, speaker_limit)
        if colon < 0:
            continue
        speaker = text[speaker_start:colon].strip()
        if _valid_person_label(speaker):
            headers.append((marker.start(), colon + 1, speaker))
    if not headers:
        colon = text.find(":", 0, min(len(text), _MAX_SPEAKER_HEADER_CHARS))
        speaker = text[:colon].strip() if colon >= 0 else ""
        if _valid_person_label(speaker):
            headers.append((0, colon + 1, speaker))
    return tuple(
        (
            speaker,
            text[body_start : headers[index + 1][0] if index + 1 < len(headers) else len(text)],
        )
        for index, (_, body_start, speaker) in enumerate(headers[:_MAX_DIALOGUE_TURNS])
    )


def _valid_person_label(label: str) -> bool:
    parts = label.split()
    return 1 <= len(parts) <= 3 and all(
        part[0].isupper() and _WORD_RE.fullmatch(part) is not None for part in parts
    )


def _word_tokens(text: str) -> tuple[tuple[int, str], ...]:
    return tuple((match.start(), match.group(0).casefold()) for match in _WORD_RE.finditer(text))


def _direct_participation_or_visual_share(
    body: str,
    *,
    tokens: tuple[tuple[int, str], ...],
) -> bool:
    if _SHARING_IMAGE_QUERY_RE.search(body):
        return True
    words = tuple(token for _, token in tokens)
    if _has_first_person_action(words) or _has_first_person_possessive_container(words):
        return True
    has_visual = bool(_VISUAL_TERMS.intersection(words))
    has_share = bool(_VISUAL_SHARE_TERMS.intersection(words))
    lowered = body.casefold()
    return has_visual and (
        has_share or "here's" in lowered or "here is" in lowered or "take a look" in lowered
    )


def _has_first_person_action(words: tuple[str, ...]) -> bool:
    for index, word in enumerate(words):
        if word not in _FIRST_PERSON_TERMS:
            continue
        lookahead = words[index + 1 : index + 6]
        if any(candidate in _PARTICIPATION_ACTIONS for candidate in lookahead):
            return True
        direct = next(
            (candidate for candidate in lookahead if candidate not in _COMPLEMENT_SCAFFOLD),
            "",
        )
        if direct.endswith(("ed", "ing")):
            return True
    return False


def _has_first_person_possessive_container(words: tuple[str, ...]) -> bool:
    return any(
        words[index] == "my" and words[index + 2] in _CONTAINER_TERMS
        for index in range(max(0, len(words) - 2))
    )


def _activity_slots(
    body: str,
    *,
    tokens: tuple[tuple[int, str], ...],
) -> tuple[str, ...]:
    container_events = _container_slot_events(tokens)
    complement_events = () if container_events else _complement_slot_events(tokens)
    semantic_events = (*container_events, *complement_events)
    backed_slots = frozenset(slot for _, slot in semantic_events)

    events: list[tuple[int, str]] = list(semantic_events)
    for match in _SHARING_IMAGE_QUERY_RE.finditer(body):
        slot = _visual_slot_key(
            match.group("label"),
            backed_slots=backed_slots,
        )
        if slot:
            events.append((match.start(), slot))

    ordered: list[str] = []
    for _, slot in sorted(events, key=lambda event: event[0]):
        if slot not in ordered:
            ordered.append(slot)
    return tuple(ordered)


def _source_supported_activity_slots(
    body: str,
    *,
    tokens: tuple[tuple[int, str], ...],
) -> tuple[str, ...]:
    """Return slots with direct semantic or owner-grounded visual support."""

    container_events = _container_slot_events(tokens)
    complement_events = () if container_events else _complement_slot_events(tokens)
    semantic_events = (*container_events, *complement_events)
    backed_slots = frozenset(slot for _, slot in semantic_events)
    events: list[tuple[int, str]] = list(semantic_events)
    for match in _SHARING_IMAGE_QUERY_RE.finditer(body):
        slot = _visual_slot_key(match.group("label"), backed_slots=backed_slots)
        if slot and (
            slot in backed_slots
            or _visual_slot_has_owner_support(
                slot,
                tokens=tokens,
                visual_start=match.start(),
            )
        ):
            events.append((match.start(), slot))
    ordered: list[str] = []
    for _, slot in sorted(events, key=lambda event: event[0]):
        if slot not in ordered:
            ordered.append(slot)
    return tuple(ordered)


def _visual_slot_has_owner_support(
    slot: str,
    *,
    tokens: tuple[tuple[int, str], ...],
    visual_start: int,
) -> bool:
    words = tuple(token for position, token in tokens if position < visual_start)
    for index, word in enumerate(words):
        if word != slot:
            continue
        window = words[max(0, index - 7) : min(len(words), index + 8)]
        if index > 0 and words[index - 1] == "my":
            return True
        for owner_index, candidate in enumerate(window):
            if candidate not in _FIRST_PERSON_TERMS:
                continue
            if any(action in _PARTICIPATION_ACTIONS for action in window[owner_index + 1 :]):
                return True
    return False


def _container_slot_events(
    tokens: tuple[tuple[int, str], ...],
) -> tuple[tuple[int, str], ...]:
    events: list[tuple[int, str]] = []
    for index in range(1, len(tokens)):
        if tokens[index][1] not in _CONTAINER_TERMS:
            continue
        slot = _slot_key(tokens[index - 1][1])
        if slot:
            events.append((tokens[index - 1][0], slot))
    return tuple(events)


def _complement_slot_events(
    tokens: tuple[tuple[int, str], ...],
) -> tuple[tuple[int, str], ...]:
    words = tuple(token for _, token in tokens)
    events: list[tuple[int, str]] = []
    for index, word in enumerate(words):
        if word not in _FIRST_PERSON_TERMS:
            continue
        action_index = next(
            (
                candidate
                for candidate in range(index + 1, min(len(words), index + 6))
                if words[candidate] in _COMPLEMENT_ACTIONS
            ),
            -1,
        )
        if action_index < 0:
            continue
        for candidate in range(action_index + 1, min(len(words), action_index + 7)):
            label = words[candidate]
            if label in _COMPLEMENT_SCAFFOLD or label in _SECONDARY_ACTIONS:
                continue
            slot = _slot_key(label)
            if slot:
                events.append((tokens[candidate][0], slot))
            break
    return tuple(events)


def _slot_key(label: str) -> str:
    tokens = tuple(
        match.group(0).casefold()
        for match in _WORD_RE.finditer(label)
        if match.group(0).casefold() not in _SLOT_LABEL_STOPWORDS
    )
    return tokens[-1] if tokens else ""


def _visual_slot_key(
    label: str,
    *,
    backed_slots: frozenset[str],
) -> str:
    tokens = tuple(
        match.group(0).casefold()
        for match in _WORD_RE.finditer(label)
        if match.group(0).casefold() not in _SLOT_LABEL_STOPWORDS
    )
    activity_form = next(
        (token for token in tokens if len(token) >= 6 and token.endswith("ing")),
        "",
    )
    if activity_form:
        return activity_form
    return next((token for token in tokens if token in backed_slots), "")


__all__ = (
    "activity_inventory_evidence_slots",
    "activity_inventory_query_supported",
    "activity_inventory_slot_key",
    "reserve_activity_inventory_head",
)
