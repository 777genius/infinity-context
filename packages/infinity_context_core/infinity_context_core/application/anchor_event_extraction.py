"""Rule-based event anchor parsing helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from infinity_context_core.application.anchor_identity_normalization import (
    canonical_token,
    normalize_cyrillic_person_case,
    normalize_cyrillic_project_case,
)

_TERM_PATTERN = re.compile(r"[\w.@:/#-]+", re.UNICODE)
_HANDLE_PERSON_TOKEN = r"@[A-Za-z][A-Za-z0-9._-]{2,39}"
_EN_NUMBER_WORD = r"one|two|three|four|five|six"
_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
}
_TEMPORAL_PHRASE = (
    r"earlier today|this morning|this afternoon|this evening|"
    r"last week|previous week|yesterday|today|tomorrow|an hour ago|hour ago|"
    rf"(?:\d{{1,3}}|{_EN_NUMBER_WORD})\s+hours?\s+ago|"
    r"\d{1,3}\s+days?\s+ago|\d{1,2}\s+weeks?\s+ago|"
    r"ранее сегодня|сегодня утром|утром сегодня|"
    r"сегодня д[нн]ём|д[нн]ём сегодня|сегодня днем|днем сегодня|"
    r"сегодня вечером|вечером сегодня|"
    r"неделю назад|на прошлой неделе|прошлой неделе|прошлую неделю|"
    r"вчера|сегодня|завтра|час назад|"
    r"\d{1,3}\s+час(?:а|ов)?\s+назад|"
    r"\d{1,3}\s+д(?:ень|ня|ней)\s+назад|"
    r"\d{1,2}\s+недел[юи]\s+назад"
)
_EVENT_PERSON_TOKEN = (
    rf"{_HANDLE_PERSON_TOKEN}|"
    r"[A-Z][a-z][A-Za-z]{1,40}|[А-ЯЁ][а-яё]{2,40}|"
    r"[a-z][a-z0-9._-]{2,39}|[а-яё][а-яё0-9._-]{2,39}"
)
_EVENT_KEYWORDS = (
    r"call|meeting|review|sync|demo|chat|dm|direct message|message|conversation|"
    r"meet|met|wrote|sent|messaged|texted|said|told|"
    r"standup|planning|retro|retrospective|workshop|interview|presentation|release|launch|"
    r"звонок|созвон|позвонил|позвонила|звонил|звонила|"
    r"встреча|ревью|демо|переписка|переписывался|"
    r"написал|написала|сказал|сказала|рассказал|рассказала|"
    r"встретился|встретилась|встречался|встречалась|встречались|"
    r"разговор(?:а|е|ом)?|чат|планерка|планёрка|стендап|ретро|"
    r"интервью|воркшоп|релиз|запуск"
)
_LOWERCASE_PREFIX_EVENT_KEYWORDS = frozenset(
    {"dm", "message", "messaged", "said", "sent", "texted", "told", "wrote"}
)
_EVENT_PATTERN = re.compile(
    rf"\b({_EVENT_KEYWORDS})"
    r"(?:\s+(?:with|from|about|с|от|по|об|про|[A-Za-zА-Яа-яЁё0-9][\w.-]{1,40})){0,5}?"
    rf"(?:\s+({_TEMPORAL_PHRASE}))?",
    re.IGNORECASE,
)
_EVENT_PARTICIPANT_PATTERN = re.compile(
    r"\b(?P<prep>with|from|с|от)\s+"
    rf"(?P<label>{_EVENT_PERSON_TOKEN})\b"
)
_EVENT_DIRECT_PARTICIPANT_PATTERN = re.compile(
    rf"^\s+(?P<label>{_EVENT_PERSON_TOKEN})\b"
)
_EVENT_PROJECT_PATTERN = re.compile(
    r"\b(?P<prep>about|for|in|по|про|для|в)\s+"
    r"(?:(?:project|проект(?:у|е|а|ом)?)\s+)?"
    r"(?P<label>[A-Za-zА-Яа-яЁё0-9][\w.-]{1,80}"
    r"(?:\s+[A-Za-zА-Яа-яЁё0-9][\w.-]{1,80}){0,3})",
    re.IGNORECASE,
)
_EVENT_PREFIX_PARTICIPANT_PATTERN = re.compile(
    rf"(?P<label>{_EVENT_PERSON_TOKEN})\s*$"
)
_EVENT_KEYWORD_PATTERN = re.compile(rf"\b({_EVENT_KEYWORDS})\b", re.IGNORECASE)
_TEMPORAL_PATTERN = re.compile(rf"\b({_TEMPORAL_PHRASE})\b", re.IGNORECASE)

_EVENT_PERSON_STOP_WORDS = {
    "a",
    "about",
    "an",
    "api",
    "call",
    "chat",
    "confirmed",
    "content",
    "context",
    "covered",
    "daily",
    "demo",
    "dimensions",
    "direct",
    "discussed",
    "dm",
    "document",
    "documents",
    "duration",
    "format",
    "frontend",
    "backend",
    "image",
    "interview",
    "last",
    "launch",
    "meeting",
    "memory",
    "message",
    "monthly",
    "next",
    "notes",
    "open",
    "organization",
    "owns",
    "page",
    "planning",
    "previous",
    "project",
    "quick",
    "release",
    "review",
    "reviewed",
    "said",
    "says",
    "save",
    "sent",
    "shared",
    "sync",
    "team",
    "that",
    "the",
    "this",
    "today",
    "tomorrow",
    "tracks",
    "transcript",
    "user",
    "uses",
    "weekly",
    "workshop",
    "yearly",
    "yesterday",
    "встреча",
    "вчера",
    "завтра",
    "запуск",
    "звонок",
    "итог",
    "итоги",
    "мы",
    "написал",
    "написала",
    "неделя",
    "неделю",
    "он",
    "она",
    "переписка",
    "переписывался",
    "планерка",
    "планёрка",
    "проект",
    "разговор",
    "сегодня",
    "созвон",
    "час",
    "часа",
    "часов",
    "чат",
    "я",
}
_PROJECT_LABEL_STOP_WORDS = {
    "about",
    "after",
    "and",
    "belongs",
    "billing",
    "confirmed",
    "covered",
    "document",
    "documents",
    "docs",
    "from",
    "has",
    "invoice",
    "invoices",
    "is",
    "keeps",
    "meeting",
    "needs",
    "notes",
    "owns",
    "pricing",
    "said",
    "says",
    "shared",
    "timeline",
    "tracks",
    "update",
    "updates",
    "uses",
    "with",
    "документ",
    "документы",
    "заметка",
    "заметки",
    "по",
    "после",
    "про",
    "с",
}
_PROJECT_HINTS = {
    "backend",
    "docling",
    "frontend",
    "graphiti",
    "infinity context",
    "memo",
    "qdrant",
}


@dataclass(frozen=True)
class EventComponents:
    event_type: str
    participant_label: str
    participant_relation: str
    project_label: str
    project_relation: str
    temporal_phrase: str
    temporal_hint_code: str
    temporal_quantity: int | None
    temporal_unit: str


def event_project_labels(text: str) -> tuple[str, ...]:
    labels: list[str] = []
    for event_label in event_labels(text):
        project = event_components(event_label).project_label
        if project:
            labels.append(project)
    return tuple(labels)


def event_participant_labels(text: str) -> tuple[str, ...]:
    labels: list[str] = []
    for event_label in event_labels(text):
        participant = event_components(event_label).participant_label
        if participant:
            labels.append(participant)
    return tuple(labels)


def event_labels(text: str) -> tuple[str, ...]:
    labels: list[str] = []
    for match in _EVENT_PATTERN.finditer(text):
        event = match.group(1).strip()
        participant = (
            _event_participant_in_phrase(match.group(0))
            or _nearby_event_participant_before(
                text,
                match.start(),
                event_keyword=event,
            )
            or _nearby_event_participant(text, match.end())
        )
        project = _event_project_in_phrase(match.group(0)) or _nearby_event_project(
            text,
            match.end(),
        )
        temporal = (
            match.group(2)
            or _nearby_temporal_after(text, match.end())
            or _nearby_temporal_before(text, match.start())
        ).strip()
        label = " ".join(part for part in (event, participant, project, temporal) if part).strip()
        labels.append(label)
        generic_participant_label = " ".join(
            part for part in (event, participant, temporal) if part
        ).strip()
        if project and generic_participant_label != label:
            labels.append(generic_participant_label)
        generic_temporal_label = f"{event} {temporal}".strip()
        if participant and temporal and generic_temporal_label != label:
            labels.append(generic_temporal_label)
    return tuple(labels)


def structured_event_metadata(
    label: str,
    *,
    canonical_key: str,
) -> dict[str, object]:
    components = event_components(label)
    metadata: dict[str, object] = {
        "anchor_family": "event",
        "event_type": components.event_type,
        "event_type_canonical": canonical_anchor_key(components.event_type),
        "event_has_participant": bool(components.participant_label),
        "event_has_project": bool(components.project_label),
        "event_has_temporal": bool(components.temporal_phrase),
        "event_identity_terms": event_identity_terms(components),
    }
    if components.participant_label:
        metadata.update(
            {
                "event_participant_label": components.participant_label,
                "event_participant_relation": components.participant_relation,
                "event_participant_canonical_key": _canonical_person_key(
                    components.participant_label
                ),
            }
        )
    if components.project_label:
        project_canonical_key = _canonical_project_key(components.project_label)
        metadata.update(
            {
                "event_project_label": components.project_label,
                "event_project_relation": components.project_relation,
                "event_project_canonical_key": project_canonical_key,
                "project_canonical_key": project_canonical_key,
            }
        )
    if components.temporal_phrase:
        metadata["event_temporal_phrase"] = components.temporal_phrase
    if components.temporal_hint_code:
        metadata["event_temporal_hint_code"] = components.temporal_hint_code
    if components.temporal_quantity is not None:
        metadata["event_temporal_quantity"] = components.temporal_quantity
    if components.temporal_unit:
        metadata["event_temporal_unit"] = components.temporal_unit
    return metadata


def event_identity_terms(components: EventComponents) -> list[str]:
    terms = [canonical_anchor_key(components.event_type)]
    if components.participant_label:
        terms.append(_canonical_person_key(components.participant_label))
    if components.project_label:
        terms.append(_canonical_project_key(components.project_label))
    if components.temporal_hint_code:
        temporal = components.temporal_hint_code
        if components.temporal_quantity is not None and components.temporal_unit:
            temporal = f"{temporal}:{components.temporal_quantity}:{components.temporal_unit}"
        terms.append(temporal)
    return [term for term in terms if term]


def event_components(label: str) -> EventComponents:
    normalized = normalize_anchor_key(label)
    parts = normalized.split()
    event_type = parts[0] if parts else normalized
    temporal_phrase = _event_temporal_phrase(label)
    temporal_parts = set(normalize_anchor_key(temporal_phrase).split())
    participant_relation = ""
    participant_label = ""
    project_relation = ""
    project_label = ""
    for index, part in enumerate(parts):
        if part not in {"with", "from", "с", "от"}:
            continue
        participant_relation = part
        participant_tokens: list[str] = []
        for token in parts[index + 1 :]:
            if token in temporal_parts or token in {
                "about",
                "for",
                "in",
                "по",
                "про",
                "для",
                "в",
            }:
                break
            participant_tokens.append(token)
        participant_label = " ".join(participant_tokens).strip()
        break
    for index, part in enumerate(parts):
        if part not in {"about", "for", "in", "по", "про", "для", "в"}:
            continue
        project_relation = part
        project_tokens: list[str] = []
        for token in parts[index + 1 :]:
            if token in temporal_parts:
                break
            if token in {"project", "проект", "проекту", "проекте", "проекта", "проектом"}:
                continue
            project_tokens.append(token)
        project_label = _clean_project_label(" ".join(project_tokens)).casefold()
        break
    temporal_hint_code, temporal_quantity, temporal_unit = _temporal_hint_payload(temporal_phrase)
    return EventComponents(
        event_type=event_type,
        participant_label=participant_label,
        participant_relation=participant_relation,
        project_label=project_label,
        project_relation=project_relation,
        temporal_phrase=temporal_phrase,
        temporal_hint_code=temporal_hint_code,
        temporal_quantity=temporal_quantity,
        temporal_unit=temporal_unit,
    )


def canonical_event_key(label: str) -> str:
    normalized_parts: list[str] = []
    normalize_next_person = False
    normalize_next_project = False
    for part in normalize_anchor_key(label).split():
        if normalize_next_person:
            normalized_parts.append(normalize_cyrillic_person_case(part))
            normalize_next_person = False
        elif normalize_next_project:
            if part in {"project", "проект", "проекту", "проекте", "проекта", "проектом"}:
                continue
            normalized_parts.append(normalize_cyrillic_project_case(part))
            normalize_next_project = False
        else:
            normalized_parts.append(part)
        if part in {"with", "from", "с", "от"}:
            normalize_next_person = True
        if part in {"about", "for", "in", "по", "про", "для", "в"}:
            normalize_next_project = True
    return " ".join(canonical_token(part) for part in normalized_parts if part)


def normalize_anchor_key(label: str) -> str:
    parts = [part.strip("._-:/#()[]{}").lower() for part in _TERM_PATTERN.findall(label)]
    return " ".join(part for part in parts if part)


def canonical_anchor_key(label: str) -> str:
    normalized = normalize_anchor_key(label)
    return " ".join(canonical_token(part) for part in normalized.split())


def _event_temporal_phrase(label: str) -> str:
    matches = list(_TEMPORAL_PATTERN.finditer(label))
    if not matches:
        return ""
    return matches[-1].group(1).strip()


def _temporal_hint_payload(phrase: str) -> tuple[str, int | None, str]:
    normalized = normalize_anchor_key(phrase)
    if not normalized:
        return "", None, ""
    if normalized in {"today", "сегодня"}:
        return "today", 0, "day"
    if normalized in {"earlier today", "ранее сегодня"}:
        return "earlier_today", 0, "day"
    if normalized in {"this morning", "сегодня утром", "утром сегодня"}:
        return "today_morning", 0, "part_of_day"
    if normalized in {
        "this afternoon",
        "сегодня днем",
        "днем сегодня",
        "сегодня днём",
        "днём сегодня",
    }:
        return "today_afternoon", 0, "part_of_day"
    if normalized in {"this evening", "сегодня вечером", "вечером сегодня"}:
        return "today_evening", 0, "part_of_day"
    if normalized in {"yesterday", "вчера"}:
        return "yesterday", 1, "day"
    if normalized in {"tomorrow", "завтра"}:
        return "tomorrow", 1, "day"
    if normalized in {
        "last week",
        "previous week",
        "week ago",
        "1 week ago",
        "неделю назад",
        "на прошлой неделе",
        "прошлой неделе",
        "прошлую неделю",
    }:
        return "last_week", 1, "week"
    if normalized in {"an hour ago", "hour ago", "1 hour ago", "час назад"}:
        return "hours_ago", 1, "hour"
    if match := re.match(
        rf"(?P<count>\d{{1,3}}|{_EN_NUMBER_WORD}) hours? ago$",
        normalized,
    ):
        return "hours_ago", _temporal_count(match.group("count")), "hour"
    if match := re.match(r"(?P<count>\d{1,3}) час(?:а|ов)? назад$", normalized):
        return "hours_ago", int(match.group("count")), "hour"
    if match := re.match(r"(?P<count>\d{1,3}) days? ago$", normalized):
        return "days_ago", int(match.group("count")), "day"
    if match := re.match(r"(?P<count>\d{1,3}) д(?:ень|ня|ней) назад$", normalized):
        return "days_ago", int(match.group("count")), "day"
    if match := re.match(r"(?P<count>\d{1,2}) weeks? ago$", normalized):
        return "weeks_ago", int(match.group("count")), "week"
    if match := re.match(r"(?P<count>\d{1,2}) недел[юи] назад$", normalized):
        return "weeks_ago", int(match.group("count")), "week"
    return "relative_time", None, ""


def _temporal_count(value: str) -> int:
    if value.isdigit():
        return int(value)
    return _NUMBER_WORDS.get(value, 0)


def _nearby_temporal_after(text: str, start: int) -> str:
    tail = _nearby_clause(text[start : start + 80])
    match = _TEMPORAL_PATTERN.search(tail)
    return match.group(1) if match else ""


def _nearby_event_participant(text: str, start: int) -> str:
    tail = _nearby_clause(text[start : start + 80])
    if next_event := _EVENT_KEYWORD_PATTERN.search(tail):
        tail = tail[: next_event.start()]
    match = _EVENT_PARTICIPANT_PATTERN.search(tail)
    if match:
        label = _display_person_label(match.group("label"))
        prep = match.group("prep")
    else:
        direct_match = _EVENT_DIRECT_PARTICIPANT_PATTERN.search(tail)
        if not direct_match:
            return ""
        label = _display_person_label(direct_match.group("label"))
        prep = "с" if re.search(r"[А-Яа-яЁё]", label) else "with"
    if not _is_probable_person_label(label):
        return ""
    return f"{prep} {label}"


def _event_participant_in_phrase(text: str) -> str:
    if not (keyword_match := _EVENT_KEYWORD_PATTERN.search(text)):
        return ""
    tail = _nearby_clause(text[keyword_match.end() : keyword_match.end() + 80])
    if next_event := _EVENT_KEYWORD_PATTERN.search(tail):
        tail = tail[: next_event.start()]
    match = _EVENT_PARTICIPANT_PATTERN.search(tail)
    if match:
        label = _display_person_label(match.group("label"))
        prep = match.group("prep")
    else:
        direct_match = _EVENT_DIRECT_PARTICIPANT_PATTERN.search(tail)
        if not direct_match:
            return ""
        label = _display_person_label(direct_match.group("label"))
        prep = "с" if re.search(r"[А-Яа-яЁё]", label) else "with"
    if not _is_probable_person_label(label):
        return ""
    return f"{prep} {label}"


def _nearby_event_project(text: str, start: int) -> str:
    tail = _nearby_clause(text[start : start + 100])
    if next_event := _EVENT_KEYWORD_PATTERN.search(tail):
        tail = tail[: next_event.start()]
    return _event_project_in_phrase(tail)


def _event_project_in_phrase(text: str) -> str:
    match = _EVENT_PROJECT_PATTERN.search(text)
    if not match:
        return ""
    label = _clean_project_label(match.group("label"))
    if not _is_probable_event_project_label(label):
        return ""
    return f"{match.group('prep')} {label}"


def _nearby_event_participant_before(
    text: str,
    end: int,
    *,
    event_keyword: str,
) -> str:
    prefix = _nearby_clause_before(text[max(0, end - 80) : end])
    if re.search(r"(?:project|проект)\s+[A-Za-zА-Яа-яЁё0-9][\w.-]*\s*$", prefix, re.IGNORECASE):
        return ""
    match = _EVENT_PREFIX_PARTICIPANT_PATTERN.search(prefix)
    if not match:
        return ""
    raw_label = match.group("label")
    if _is_lowercase_person_token(raw_label) and (
        normalize_anchor_key(event_keyword) not in _LOWERCASE_PREFIX_EVENT_KEYWORDS
    ):
        return ""
    label = _display_person_label(raw_label)
    if not _is_probable_person_label(label):
        return ""
    prep = "с" if re.search(r"[А-Яа-яЁё]", label) else "with"
    return f"{prep} {label}"


def _is_lowercase_person_token(value: str) -> bool:
    stripped = value.strip()
    if not stripped or stripped.startswith("@"):
        return False
    return bool(re.match(r"[a-zа-яё]", stripped))


def _nearby_temporal_before(text: str, end: int) -> str:
    prefix = _nearby_clause_before(text[max(0, end - 80) : end])
    matches = list(_TEMPORAL_PATTERN.finditer(prefix))
    return matches[-1].group(1) if matches else ""


def _nearby_clause(value: str) -> str:
    return re.split(r"(?:[!?]\s*|\n|\.\s+)", value, maxsplit=1)[0]


def _nearby_clause_before(value: str) -> str:
    return re.split(r"(?:[!?]\s*|\n|\.\s+)", value)[-1]


def _is_probable_person_label(label: str) -> bool:
    if len(label) < 3 or len(label) > 80:
        return False
    normalized = normalize_anchor_key(label)
    if not normalized:
        return False
    if normalized in _EVENT_PERSON_STOP_WORDS:
        return False
    if normalized in _PROJECT_HINTS:
        return False
    first = normalized.split()[0]
    if first in _EVENT_PERSON_STOP_WORDS:
        return False
    if first in {"project", "repo", "service", "team"}:
        return False
    return any(char.isalpha() for char in normalized)


def _display_person_label(raw: str) -> str:
    value = raw.strip().lstrip("@")
    value = value.split("+", 1)[0]
    tokens = [
        token
        for token in re.split(r"[._-]+", value)
        if token and any(char.isalpha() for char in token)
    ]
    if not tokens:
        return raw.strip()
    return " ".join(token[:1].upper() + token[1:] for token in tokens[:3])


def _is_probable_event_project_label(label: str) -> bool:
    normalized = normalize_anchor_key(label)
    if len(normalized) < 2 or len(normalized) > 120:
        return False
    first = normalized.split()[0]
    if normalized in _PROJECT_HINTS or first in _PROJECT_HINTS:
        return True
    if normalized in _EVENT_PERSON_STOP_WORDS:
        return False
    if first in _PROJECT_LABEL_STOP_WORDS:
        return False
    return _looks_like_project_label_continuation(label.split()[0]) or (
        len(normalized.split()) == 1
        and len(normalized) <= 40
        and any(char.isalnum() for char in normalized)
    )


def _clean_project_label(label: str) -> str:
    raw_tokens = [token for token in label.split() if token.strip(".,:;()[]{}")]
    if not raw_tokens:
        return ""
    cleaned: list[str] = []
    for index, raw_token in enumerate(raw_tokens[:4]):
        token = raw_token.strip(".,:;()[]{}")
        normalized = normalize_anchor_key(token)
        if not normalized:
            continue
        if index > 0 and (
            normalized in _PROJECT_LABEL_STOP_WORDS
            or not _looks_like_project_label_continuation(token)
        ):
            break
        cleaned.append(token)
        if raw_token.rstrip().endswith((".", "!", "?", ";", ":")):
            break
    return " ".join(cleaned).strip(".,:;()[]{} ")


def _looks_like_project_label_continuation(token: str) -> bool:
    return bool(re.match(r"[A-ZА-ЯЁ0-9]", token)) or any(
        marker in token for marker in ("-", ".", "_")
    )


def _canonical_person_key(label: str) -> str:
    normalized = normalize_anchor_key(label)
    parts = [normalize_cyrillic_person_case(part) for part in normalized.split()]
    return " ".join(canonical_token(part) for part in parts if part)


def _canonical_project_key(label: str) -> str:
    normalized = normalize_anchor_key(label)
    parts = [normalize_cyrillic_project_case(part) for part in normalized.split()]
    return " ".join(canonical_token(part) for part in parts if part)
