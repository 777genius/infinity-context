"""Rule-based event anchor parsing helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from infinity_context_core.application.anchor_identity_normalization import (
    canonical_token,
    normalize_cyrillic_person_case,
    normalize_cyrillic_project_case,
)
from infinity_context_core.application.context_lexical import date_tokens

_TERM_PATTERN = re.compile(r"[\w.@:/#-]+", re.UNICODE)
_HANDLE_PERSON_TOKEN = r"@[A-Za-z][A-Za-z0-9._-]{2,39}"
_EN_NUMBER_WORD = r"one|two|three|four|five|six"
_RU_NUMBER_WORD = r"один|одна|два|две|три|четыре|пять|шесть"
_EN_WEEKDAY = r"monday|tuesday|wednesday|thursday|friday|saturday|sunday"
_NUMBER_WORDS = {
    "один": 1,
    "одна": 1,
    "one": 1,
    "два": 2,
    "две": 2,
    "two": 2,
    "три": 3,
    "three": 3,
    "четыре": 4,
    "four": 4,
    "пять": 5,
    "five": 5,
    "шесть": 6,
    "six": 6,
}
_TEMPORAL_PHRASE = (
    r"earlier today|this morning|this afternoon|this evening|"
    r"this week(?!end)|current week(?!end)|earlier this week|"
    r"next week|upcoming week|following week|"
    r"this quarter|current quarter|last quarter|previous quarter|"
    r"next quarter|upcoming quarter|following quarter|"
    r"this month|current month|this year|current year|"
    r"next month|upcoming month|following month|next year|upcoming year|following year|"
    r"(?:19|20)\d{2}[-/.]\d{1,2}[-/.]\d{1,2}|"
    r"\d{1,2}[-/.]\d{1,2}[-/.](?:19|20)\d{2}|"
    r"last week|previous week|yesterday|today|tomorrow|an hour ago|hour ago|"
    r"this weekend|current weekend|last weekend|previous weekend|weekend ago|"
    rf"last\s+(?:{_EN_WEEKDAY})|previous\s+(?:{_EN_WEEKDAY})|"
    r"last month|previous month|month ago|last year|previous year|year ago|"
    rf"(?:\d{{1,3}}|{_EN_NUMBER_WORD})\s+hours?\s+ago|"
    rf"(?:\d{{1,3}}|{_EN_NUMBER_WORD})\s+days?\s+ago|"
    rf"(?:\d{{1,2}}|{_EN_NUMBER_WORD})\s+weeks?\s+ago|"
    rf"(?:\d{{1,2}}|{_EN_NUMBER_WORD})\s+weekends?\s+ago|"
    rf"(?:\d{{1,2}}|{_EN_NUMBER_WORD})\s+months?\s+ago|"
    rf"(?:\d{{1,2}}|{_EN_NUMBER_WORD})\s+years?\s+ago|"
    r"ранее сегодня|сегодня утром|утром сегодня|"
    r"сегодня д[нн]ём|д[нн]ём сегодня|сегодня днем|днем сегодня|"
    r"сегодня вечером|вечером сегодня|"
    r"на этой неделе|в эту неделю|эта неделя|"
    r"на следующей неделе|в следующую неделю|следующая неделя|"
    r"в этом квартале|этот квартал|в прошлом квартале|прошлый квартал|прошлом квартале|"
    r"в следующем квартале|на следующий квартал|следующий квартал|"
    r"в этом месяце|этот месяц|в этом году|этот год|"
    r"в следующем месяце|на следующий месяц|следующий месяц|"
    r"в следующем году|на следующий год|следующий год|"
    r"неделю назад|на прошлой неделе|прошлой неделе|прошлую неделю|"
    r"в эти выходные|на этих выходных|на прошлых выходных|"
    r"прошлые выходные|прошлых выходных|"
    r"месяц назад|в прошлом месяце|прошлый месяц|прошлом месяце|"
    r"год назад|в прошлом году|прошлый год|прошлом году|"
    r"вчера|сегодня|завтра|час назад|"
    rf"(?:\d{{1,3}}|{_RU_NUMBER_WORD})\s+час(?:а|ов)?\s+назад|"
    rf"(?:\d{{1,3}}|{_RU_NUMBER_WORD})\s+д(?:ень|ня|ней)\s+назад|"
    rf"(?:\d{{1,2}}|{_RU_NUMBER_WORD})\s+недел[юи]\s+назад|"
    rf"(?:\d{{1,2}}|{_RU_NUMBER_WORD})\s+выходн(?:ые|ых)\s+назад|"
    rf"(?:\d{{1,2}}|{_RU_NUMBER_WORD})\s+месяц(?:а|ев)?\s+назад|"
    rf"(?:\d{{1,2}}|{_RU_NUMBER_WORD})\s+(?:год(?:а)?|лет)\s+назад"
)
_EVENT_PERSON_TOKEN = (
    rf"{_HANDLE_PERSON_TOKEN}|"
    r"[A-Z][a-z][A-Za-z]{1,40}|[А-ЯЁ][а-яё]{2,40}|"
    r"[a-z][a-z0-9._-]{2,39}|[а-яё][а-яё0-9._-]{2,39}"
)
_EVENT_SUBJECT_PERSON_TOKEN = (
    rf"{_HANDLE_PERSON_TOKEN}|[A-Z][a-z][A-Za-z]{{1,40}}|[А-ЯЁ][а-яё]{{2,40}}"
)
_EVENT_KEYWORDS = (
    r"call|meeting|review|sync|demo|chat|dm|direct message|message|conversation|"
    r"meet|met|wrote|sent|messaged|texted|said|told|"
    r"talked|spoke|chatted|discussed|"
    r"move|moved|moving|relocate|relocated|relocation|"
    r"attend|attended|join|joined|participate|participated|went|hike|hiked|hikes|hiking|"
    r"standup|planning|retro|retrospective|workshop|interview|interviews|presentation|release|launch|"
    r"deadline|due|task|todo|reminder|milestone|deliverable|"
    r"звонок|созвона|созвон|позвонил|позвонила|звонил|звонила|"
    r"встреча|ревью|демо|переписк(?:а|е|и|ой|у)|"
    r"переписывался|переписывалась|переписывались|"
    r"общался|общалась|общались|созванивался|созванивалась|созванивались|"
    r"переезд|переехал|переехала|переехали|переезжал|переезжала|переезжали|"
    r"дедлайн|срок|задача|поручение|напоминание|майлстоун|"
    r"написал|написала|написали|ответил|ответила|ответили|"
    r"сказал|сказала|сказали|сообщил|сообщила|сообщили|"
    r"скинул|скинула|скинули|прислал|прислала|прислали|"
    r"отправил|отправила|отправили|рассказал|рассказала|рассказали|"
    r"встретился|встретилась|встречался|встречалась|встречались|"
    r"разговор(?:а|е|ом)?|чат|планерка|планёрка|стендап|ретро|"
    r"интервью|воркшоп|релиз|запуск"
)
_LOWERCASE_PREFIX_EVENT_KEYWORDS = frozenset(
    {
        "chatted",
        "discussed",
        "dm",
        "message",
        "messaged",
        "moved",
        "moving",
        "relocated",
        "said",
        "sent",
        "spoke",
        "talked",
        "texted",
        "told",
        "wrote",
        "написал",
        "написала",
        "написали",
        "ответил",
        "ответила",
        "ответили",
        "отправил",
        "отправила",
        "отправили",
        "прислал",
        "прислала",
        "прислали",
        "сказал",
        "сказала",
        "сказали",
        "сообщил",
        "сообщила",
        "сообщили",
        "скинул",
        "скинула",
        "скинули",
    }
)
_DIRECT_AFTER_EVENT_KEYWORDS = frozenset(
    {
        "call",
        "chat",
        "chatted",
        "discussed",
        "dm",
        "message",
        "messaged",
        "sent",
        "spoke",
        "talked",
        "texted",
        "wrote",
        "звонил",
        "звонила",
        "написал",
        "написала",
        "написали",
        "ответил",
        "ответила",
        "ответили",
        "отправил",
        "отправила",
        "отправили",
        "переписка",
        "позвонил",
        "позвонила",
        "прислал",
        "прислала",
        "прислали",
        "сказал",
        "сказала",
        "сказали",
        "сообщил",
        "сообщила",
        "сообщили",
        "созвон",
        "скинул",
        "скинула",
        "скинули",
        "чат",
    }
)
_RELOCATION_EVENT_KEYWORDS = frozenset(
    {
        "move",
        "moved",
        "moving",
        "relocate",
        "relocated",
        "relocation",
        "переезд",
        "переехал",
        "переехала",
        "переехали",
        "переезжал",
        "переезжала",
        "переезжали",
    }
)
_ACTIVITY_EVENT_KEYWORDS = frozenset(
    {
        "attend",
        "attended",
        "hike",
        "hiked",
        "hikes",
        "hiking",
        "join",
        "joined",
        "participate",
        "participated",
        "went",
    }
)
_WORKFLOW_EVENT_KEYWORDS = frozenset(
    {
        "deadline",
        "deliverable",
        "due",
        "milestone",
        "reminder",
        "task",
        "todo",
        "дедлайн",
        "задача",
        "майлстоун",
        "напоминание",
        "поручение",
        "срок",
    }
)
_EVENT_DISPLAY_NORMALIZATIONS = {
    "due": "deadline",
    "созвона": "созвон",
}
_EVENT_PATTERN = re.compile(
    rf"\b({_EVENT_KEYWORDS})\b"
    r"(?:\s+(?:with|from|about|с|от|по|об|про|[A-Za-zА-Яа-яЁё0-9][\w.-]{1,40})){0,5}?"
    rf"(?:\s+({_TEMPORAL_PHRASE}))?",
    re.IGNORECASE,
)
_EVENT_PARTICIPANT_PATTERN = re.compile(
    r"\b(?P<prep>with|from|с|от)\s+"
    rf"(?P<label>{_EVENT_PERSON_TOKEN})\b"
)
_EVENT_DIRECT_PARTICIPANT_PATTERN = re.compile(rf"^\s+(?P<label>{_EVENT_PERSON_TOKEN})\b")
_EVENT_PROJECT_PATTERN = re.compile(
    r"\b(?P<prep>about|for|in|по|про|для|в)\s+"
    r"(?:(?:project|проект(?:у|е|а|ом)?)\s+)?"
    r"(?P<label>[A-Za-zА-Яа-яЁё0-9][\w.-]{1,80}"
    r"(?:\s+[A-Za-zА-Яа-яЁё0-9][\w.-]{1,80}){0,3})",
    re.IGNORECASE,
)
_EVENT_PREFIX_PARTICIPANT_PATTERN = re.compile(rf"(?P<label>{_EVENT_PERSON_TOKEN})\s*$")
_EVENT_PREFIX_PROJECT_PATTERN = re.compile(
    r"\b(?:(?:project|проект(?:у|е|а|ом)?)\s+)?"
    r"(?P<label>[A-Za-zА-Яа-яЁё0-9][\w.-]{1,80}"
    r"(?:\s+[A-Za-zА-Яа-яЁё0-9][\w.-]{1,80}){0,3})\s*$",
    re.IGNORECASE,
)
_EVENT_INTERVIEW_SUBJECT_PATTERN = re.compile(
    rf"\b(?P<label>{_EVENT_SUBJECT_PERSON_TOKEN})\s+"
    r"(?:passed|had|scheduled|finished|completed|cleared)\b"
)
_EVENT_KEYWORD_PATTERN = re.compile(rf"\b({_EVENT_KEYWORDS})\b", re.IGNORECASE)
_TEMPORAL_PATTERN = re.compile(rf"\b({_TEMPORAL_PHRASE})\b", re.IGNORECASE)
_DURATION_EVENT_KEYWORDS = (
    r"volunteer(?:s|ed|ing)?|work(?:s|ed|ing)?|live(?:s|d|ing)?|"
    r"use(?:s|d|ing)?|play(?:s|ed|ing)?|run(?:s|ning)?|"
    r"practice(?:s|d|ing)?|train(?:s|ed|ing)?|"
    r"волонтерит|волонт[её]р(?:ит|ил|ила|или|ство)|работает|работал|работала|"
    r"жив[её]т|жил|жила|жили|играет|играл|играла|использует|использовал|"
    r"использовала|занимается|тренируется|участвует"
)
_DURATION_PHRASE = (
    r"for\s+(?:about\s+|roughly\s+|nearly\s+|almost\s+|over\s+)?"
    rf"(?:\d{{1,2}}|{_EN_NUMBER_WORD})\s+"
    r"(?:years?|months?|weeks?|days?)|"
    r"since\s+(?:19|20)\d{2}|"
    r"с\s+(?:19|20)\d{2}|"
    rf"(?:\d{{1,2}}|{_RU_NUMBER_WORD})\s+"
    r"(?:лет|года|год|месяц(?:ев|а)?|недель|недели|дней)(?!\s+назад)"
)
_RECURRENCE_PHRASE = (
    r"every\s+(?:day|night|morning|afternoon|evening|weekday|weekend|week|"
    r"month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"daily|weekly|monthly|yearly|annually|regularly|usually|often|"
    rf"(?:once|twice|{_EN_NUMBER_WORD}|\d{{1,2}})\s+times?\s+"
    r"(?:a|per)\s+(?:day|week|month|year)|"
    r"(?:once|twice)\s+(?:a|per)\s+(?:day|week|month|year)|"
    r"кажд\w+\s+(?:день|недел\w*|месяц|год|утро|вечер|выходн\w*)|"
    r"ежедневно|еженедельно|ежемесячно|ежегодно|регулярно|обычно|часто|"
    rf"(?:\d{{1,2}}|{_RU_NUMBER_WORD})\s+раз(?:а)?\s+в\s+"
    r"(?:день|недел\w*|месяц|год)"
)
_SUBJECT_DURATION_EVENT_PATTERN = re.compile(
    rf"\b(?P<subject>{_EVENT_SUBJECT_PERSON_TOKEN})\s+"
    r"(?:has\s+been\s+|have\s+been\s+|has\s+|have\s+|"
    r"started\s+|began\s+)?"
    rf"(?P<event>{_DURATION_EVENT_KEYWORDS})\b"
    rf"(?P<tail>[^.!?\n]{{0,120}}?)\b(?P<duration>{_DURATION_PHRASE})\b",
    re.IGNORECASE | re.DOTALL,
)
_SUBJECT_RECURRENCE_EVENT_PATTERN = re.compile(
    rf"\b(?P<subject>{_EVENT_SUBJECT_PERSON_TOKEN})\s+"
    r"(?:has\s+been\s+|have\s+been\s+|has\s+|have\s+)?"
    rf"(?P<event>{_DURATION_EVENT_KEYWORDS})\b"
    rf"(?P<tail>[^.!?\n]{{0,120}}?)\b(?P<recurrence>{_RECURRENCE_PHRASE})\b",
    re.IGNORECASE | re.DOTALL,
)
_DURATION_PATTERN = re.compile(rf"\b({_DURATION_PHRASE})\b", re.IGNORECASE)
_RECURRENCE_PATTERN = re.compile(rf"\b({_RECURRENCE_PHRASE})\b", re.IGNORECASE)

_TEMPORAL_PERSON_STOP_WORDS = frozenset(
    {
        "afternoon",
        "ago",
        "day",
        "days",
        "evening",
        "friday",
        "hour",
        "hours",
        "monday",
        "month",
        "months",
        "morning",
        "next",
        "saturday",
        "sunday",
        "thursday",
        "tuesday",
        "week",
        "wednesday",
        "weeks",
        "year",
        "years",
        "вечером",
        "день",
        "днем",
        "днём",
        "дней",
        "дня",
        "год",
        "года",
        "году",
        "лет",
        "месяц",
        "месяца",
        "месяцев",
        "месяце",
        "назад",
        "недели",
        "неделя",
        "неделю",
        "следующей",
        "следующем",
        "следующий",
        "следующую",
        "выходные",
        "выходных",
        "утром",
    }
)
_EVENT_PERSON_STOP_WORDS = (
    {
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
        "deadline",
        "dimensions",
        "direct",
        "discussed",
        "dm",
        "document",
        "documents",
        "due",
        "duration",
        "format",
        "for",
        "from",
        "frontend",
        "backend",
        "image",
        "interview",
        "in",
        "kiev",
        "kyiv",
        "last",
        "launch",
        "meeting",
        "memory",
        "message",
        "milestone",
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
        "sweden",
        "sync",
        "team",
        "that",
        "the",
        "this",
        "today",
        "tomorrow",
        "tracks",
        "transcript",
        "task",
        "todo",
        "user",
        "uses",
        "weekly",
        "with",
        "workshop",
        "yearly",
        "yesterday",
        "в",
        "аудио",
        "встреча",
        "вчера",
        "видео",
        "завтра",
        "запуск",
        "звонок",
        "дедлайн",
        "для",
        "документ",
        "документа",
        "документом",
        "заметка",
        "заметки",
        "заметку",
        "изображение",
        "изображения",
        "итог",
        "итоги",
        "картинка",
        "картинки",
        "картинку",
        "киев",
        "киева",
        "мы",
        "написал",
        "написала",
        "написали",
        "об",
        "неделя",
        "неделю",
        "ответил",
        "ответила",
        "ответили",
        "от",
        "отправил",
        "отправила",
        "отправили",
        "поручение",
        "он",
        "она",
        "переписка",
        "переписывался",
        "планерка",
        "планёрка",
        "проект",
        "прислал",
        "прислала",
        "прислали",
        "про",
        "по",
        "разговор",
        "ссылка",
        "ссылки",
        "ссылку",
        "сказал",
        "сказала",
        "сказали",
        "сообщил",
        "сообщила",
        "сообщили",
        "сегодня",
        "созвон",
        "срок",
        "скинул",
        "скинула",
        "скинули",
        "с",
        "скриншот",
        "скриншота",
        "скриншотом",
        "транскрипт",
        "транскрипта",
        "час",
        "часа",
        "часов",
        "чат",
        "файл",
        "файла",
        "файлом",
        "фото",
        "я",
    }
    | set(_NUMBER_WORDS)
    | _TEMPORAL_PERSON_STOP_WORDS
)
_PROJECT_LABEL_STOP_WORDS = {
    "about",
    "after",
    "and",
    "belongs",
    "billing",
    "confirmed",
    "covered",
    "deadline",
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
    "milestone",
    "needs",
    "notes",
    "owns",
    "pricing",
    "said",
    "says",
    "shared",
    "task",
    "timeline",
    "tracks",
    "update",
    "updates",
    "uses",
    "with",
    "документ",
    "документы",
    "дедлайн",
    "заметка",
    "заметки",
    "по",
    "после",
    "поручение",
    "про",
    "с",
    "срок",
}
_PREFIX_PROJECT_LEADING_STOP_WORDS = {
    "what",
    "when",
    "which",
    "who",
    "whose",
    "какая",
    "какие",
    "какой",
    "кто",
    "чей",
    "чья",
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
    duration_phrase: str = ""
    duration_hint_code: str = ""
    duration_quantity: int | None = None
    duration_unit: str = ""
    recurrence_phrase: str = ""
    recurrence_hint_code: str = ""
    recurrence_quantity: int | None = None
    recurrence_unit: str = ""


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
        event = _display_event_type(match.group(1).strip())
        event_tail_start = match.end(1)
        normalized_event = normalize_anchor_key(event)
        is_relocation = normalized_event in _RELOCATION_EVENT_KEYWORDS
        is_activity = normalized_event in _ACTIVITY_EVENT_KEYWORDS
        is_workflow = normalized_event in _WORKFLOW_EVENT_KEYWORDS
        allow_direct_after = normalized_event in _DIRECT_AFTER_EVENT_KEYWORDS
        prefix_participant = (
            ""
            if is_workflow
            else _nearby_event_participant_before(
                text,
                match.start(),
                event_keyword=event,
            )
        )
        if is_activity:
            participant = prefix_participant
        elif is_workflow:
            participant = ""
        else:
            participant = (
                _event_participant_in_phrase(
                    match.group(0),
                    allow_origin_preps=not is_relocation,
                )
                or _nearby_event_participant(
                    text,
                    event_tail_start,
                    allow_direct=allow_direct_after,
                    allow_origin_preps=not is_relocation,
                )
                or prefix_participant
            )
        project = (
            _event_project_in_phrase(match.group(0))
            or _nearby_event_project(
                text,
                event_tail_start,
            )
            or (_nearby_event_project_before(text, match.start()) if is_workflow else "")
        )
        temporal = (
            match.group(2)
            or _nearby_temporal_after(text, event_tail_start)
            or _nearby_temporal_before(text, match.start())
        ).strip()
        label = " ".join(part for part in (event, participant, project, temporal) if part).strip()
        labels.append(label)
        if (
            prefix_participant
            and participant
            and prefix_participant != participant
            and not is_activity
            and not is_workflow
        ):
            prefix_label = " ".join(
                part for part in (event, prefix_participant, project, temporal) if part
            ).strip()
            if prefix_label and prefix_label != label:
                labels.append(prefix_label)
        generic_participant_label = " ".join(
            part for part in (event, participant, temporal) if part
        ).strip()
        if project and generic_participant_label != label:
            labels.append(generic_participant_label)
        if (
            project
            and prefix_participant
            and participant
            and prefix_participant != participant
            and not is_activity
            and not is_workflow
        ):
            prefix_generic_participant_label = " ".join(
                part for part in (event, prefix_participant, temporal) if part
            ).strip()
            if prefix_generic_participant_label not in {label, generic_participant_label}:
                labels.append(prefix_generic_participant_label)
        generic_temporal_label = f"{event} {temporal}".strip()
        if participant and temporal and generic_temporal_label != label:
            labels.append(generic_temporal_label)
    labels.extend(_duration_event_labels(text))
    return tuple(labels)


def _duration_event_labels(text: str) -> tuple[str, ...]:
    labels: list[str] = []
    for match in _SUBJECT_DURATION_EVENT_PATTERN.finditer(text):
        event = _display_event_type(match.group("event").strip())
        subject = match.group("subject").strip()
        duration = match.group("duration").strip()
        prep = "с" if re.search(r"[А-Яа-яЁё]", subject) else "with"
        labels.append(f"{event} {prep} {subject} {duration}")
    for match in _SUBJECT_RECURRENCE_EVENT_PATTERN.finditer(text):
        event = _display_event_type(match.group("event").strip())
        subject = match.group("subject").strip()
        recurrence = match.group("recurrence").strip()
        prep = "с" if re.search(r"[А-Яа-яЁё]", subject) else "with"
        labels.append(f"{event} {prep} {subject} {recurrence}")
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
        if components.temporal_hint_code.startswith("date_"):
            metadata["event_date"] = components.temporal_hint_code.removeprefix("date_").replace(
                "_", "-"
            )
    if components.temporal_quantity is not None:
        metadata["event_temporal_quantity"] = components.temporal_quantity
    if components.temporal_unit:
        metadata["event_temporal_unit"] = components.temporal_unit
    if components.duration_phrase:
        metadata["event_duration_phrase"] = components.duration_phrase
    if components.duration_hint_code:
        metadata["event_duration_hint_code"] = components.duration_hint_code
    if components.duration_quantity is not None:
        metadata["event_duration_quantity"] = components.duration_quantity
    if components.duration_unit:
        metadata["event_duration_unit"] = components.duration_unit
    if components.recurrence_phrase:
        metadata["event_recurrence_phrase"] = components.recurrence_phrase
    if components.recurrence_hint_code:
        metadata["event_recurrence_hint_code"] = components.recurrence_hint_code
    if components.recurrence_quantity is not None:
        metadata["event_recurrence_quantity"] = components.recurrence_quantity
    if components.recurrence_unit:
        metadata["event_recurrence_unit"] = components.recurrence_unit
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
    if components.duration_hint_code:
        duration = components.duration_hint_code
        if components.duration_quantity is not None and components.duration_unit:
            duration = (
                f"{duration}:{components.duration_quantity}:{components.duration_unit}"
            )
        terms.append(duration)
    if components.recurrence_hint_code:
        recurrence = components.recurrence_hint_code
        if components.recurrence_quantity is not None and components.recurrence_unit:
            recurrence = (
                f"{recurrence}:{components.recurrence_quantity}:"
                f"{components.recurrence_unit}"
            )
        terms.append(recurrence)
    return [term for term in terms if term]


def event_components(label: str) -> EventComponents:
    normalized = normalize_anchor_key(label)
    parts = normalized.split()
    event_type = parts[0] if parts else normalized
    temporal_phrase = _event_temporal_phrase(label)
    duration_phrase = _event_duration_phrase(label)
    recurrence_phrase = _event_recurrence_phrase(label)
    temporal_parts = set(normalize_anchor_key(temporal_phrase).split())
    temporal_parts.update(normalize_anchor_key(duration_phrase).split())
    temporal_parts.update(normalize_anchor_key(recurrence_phrase).split())
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
    duration_hint_code, duration_quantity, duration_unit = _duration_hint_payload(
        duration_phrase
    )
    recurrence_hint_code, recurrence_quantity, recurrence_unit = _recurrence_hint_payload(
        recurrence_phrase
    )
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
        duration_phrase=duration_phrase,
        duration_hint_code=duration_hint_code,
        duration_quantity=duration_quantity,
        duration_unit=duration_unit,
        recurrence_phrase=recurrence_phrase,
        recurrence_hint_code=recurrence_hint_code,
        recurrence_quantity=recurrence_quantity,
        recurrence_unit=recurrence_unit,
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


def _event_duration_phrase(label: str) -> str:
    matches = list(_DURATION_PATTERN.finditer(label))
    if not matches:
        return ""
    return matches[-1].group(1).strip()


def _event_recurrence_phrase(label: str) -> str:
    matches = list(_RECURRENCE_PATTERN.finditer(label))
    if not matches:
        return ""
    return matches[-1].group(1).strip()


def _temporal_hint_payload(phrase: str) -> tuple[str, int | None, str]:
    normalized = normalize_anchor_key(phrase)
    if not normalized:
        return "", None, ""
    if dates := date_tokens(phrase):
        return dates[0], None, "date"
    if normalized in {"today", "сегодня"}:
        return "today", 0, "day"
    if normalized in {
        "this week",
        "current week",
        "earlier this week",
        "на этой неделе",
        "в эту неделю",
        "эта неделя",
    }:
        return "this_week", 0, "week"
    if normalized in {
        "this quarter",
        "current quarter",
        "в этом квартале",
        "этот квартал",
    }:
        return "this_quarter", 0, "quarter"
    if normalized in {"this month", "current month", "в этом месяце", "этот месяц"}:
        return "this_month", 0, "month"
    if normalized in {"this year", "current year", "в этом году", "этот год"}:
        return "this_year", 0, "year"
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
        "next week",
        "upcoming week",
        "following week",
        "на следующей неделе",
        "в следующую неделю",
        "следующая неделя",
    }:
        return "next_week", 1, "week"
    if normalized in {
        "next month",
        "upcoming month",
        "following month",
        "в следующем месяце",
        "на следующий месяц",
        "следующий месяц",
    }:
        return "next_month", 1, "month"
    if normalized in {
        "next quarter",
        "upcoming quarter",
        "following quarter",
        "в следующем квартале",
        "на следующий квартал",
        "следующий квартал",
    }:
        return "next_quarter", 1, "quarter"
    if normalized in {
        "next year",
        "upcoming year",
        "following year",
        "в следующем году",
        "на следующий год",
        "следующий год",
    }:
        return "next_year", 1, "year"
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
    if normalized in {"this weekend", "current weekend", "в эти выходные", "на этих выходных"}:
        return "this_weekend", 0, "weekend"
    if normalized in {
        "last weekend",
        "previous weekend",
        "weekend ago",
        "1 weekend ago",
        "на прошлых выходных",
        "прошлые выходные",
        "прошлых выходных",
    }:
        return "last_weekend", 1, "weekend"
    if weekday_match := re.match(r"(?:last|previous) (?P<weekday>[a-z]+)$", normalized):
        weekday = weekday_match.group("weekday")
        if weekday in {
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        }:
            return f"last_{weekday}", 1, "weekday"
    if normalized in {
        "last month",
        "previous month",
        "month ago",
        "1 month ago",
        "месяц назад",
        "в прошлом месяце",
        "прошлый месяц",
        "прошлом месяце",
    }:
        return "last_month", 1, "month"
    if normalized in {
        "last quarter",
        "previous quarter",
        "в прошлом квартале",
        "прошлый квартал",
        "прошлом квартале",
    }:
        return "last_quarter", 1, "quarter"
    if normalized in {
        "last year",
        "previous year",
        "year ago",
        "1 year ago",
        "год назад",
        "в прошлом году",
        "прошлый год",
        "прошлом году",
    }:
        return "last_year", 1, "year"
    if normalized in {"an hour ago", "hour ago", "1 hour ago", "час назад"}:
        return "hours_ago", 1, "hour"
    if match := re.match(
        rf"(?P<count>\d{{1,3}}|{_EN_NUMBER_WORD}) hours? ago$",
        normalized,
    ):
        return "hours_ago", _temporal_count(match.group("count")), "hour"
    if match := re.match(
        rf"(?P<count>\d{{1,3}}|{_RU_NUMBER_WORD}) час(?:а|ов)? назад$",
        normalized,
    ):
        return "hours_ago", _temporal_count(match.group("count")), "hour"
    if match := re.match(
        rf"(?P<count>\d{{1,3}}|{_EN_NUMBER_WORD}) days? ago$",
        normalized,
    ):
        return "days_ago", _temporal_count(match.group("count")), "day"
    if match := re.match(
        rf"(?P<count>\d{{1,3}}|{_RU_NUMBER_WORD}) д(?:ень|ня|ней) назад$",
        normalized,
    ):
        return "days_ago", _temporal_count(match.group("count")), "day"
    if match := re.match(
        rf"(?P<count>\d{{1,2}}|{_EN_NUMBER_WORD}) weeks? ago$",
        normalized,
    ):
        return "weeks_ago", _temporal_count(match.group("count")), "week"
    if match := re.match(
        rf"(?P<count>\d{{1,2}}|{_RU_NUMBER_WORD}) недел[юи] назад$",
        normalized,
    ):
        return "weeks_ago", _temporal_count(match.group("count")), "week"
    if match := re.match(
        rf"(?P<count>\d{{1,2}}|{_EN_NUMBER_WORD}) weekends? ago$",
        normalized,
    ):
        count = _temporal_count(match.group("count"))
        return ("last_weekend" if count == 1 else "weekends_ago"), count, "weekend"
    if match := re.match(
        rf"(?P<count>\d{{1,2}}|{_RU_NUMBER_WORD}) выходн(?:ые|ых) назад$",
        normalized,
    ):
        count = _temporal_count(match.group("count"))
        return ("last_weekend" if count == 1 else "weekends_ago"), count, "weekend"
    if match := re.match(
        rf"(?P<count>\d{{1,2}}|{_EN_NUMBER_WORD}) months? ago$",
        normalized,
    ):
        count = _temporal_count(match.group("count"))
        return ("last_month" if count == 1 else "months_ago"), count, "month"
    if match := re.match(
        rf"(?P<count>\d{{1,2}}|{_RU_NUMBER_WORD}) месяц(?:а|ев)? назад$",
        normalized,
    ):
        count = _temporal_count(match.group("count"))
        return ("last_month" if count == 1 else "months_ago"), count, "month"
    if match := re.match(
        rf"(?P<count>\d{{1,2}}|{_EN_NUMBER_WORD}) years? ago$",
        normalized,
    ):
        count = _temporal_count(match.group("count"))
        return ("last_year" if count == 1 else "years_ago"), count, "year"
    if match := re.match(
        rf"(?P<count>\d{{1,2}}|{_RU_NUMBER_WORD}) (?:год(?:а)?|лет) назад$",
        normalized,
    ):
        count = _temporal_count(match.group("count"))
        return ("last_year" if count == 1 else "years_ago"), count, "year"
    return "relative_time", None, ""


def _duration_hint_payload(phrase: str) -> tuple[str, int | None, str]:
    normalized = normalize_anchor_key(phrase)
    if not normalized:
        return "", None, ""
    if match := re.match(
        rf"for (?:(?:about|roughly|nearly|almost|over) )?"
        rf"(?P<count>\d{{1,2}}|{_EN_NUMBER_WORD}) "
        r"(?P<unit>years?|months?|weeks?|days?)$",
        normalized,
    ):
        return "duration_for", _temporal_count(match.group("count")), _singular_unit(
            match.group("unit")
        )
    if match := re.match(
        rf"(?P<count>\d{{1,2}}|{_RU_NUMBER_WORD}) "
        r"(?P<unit>лет|года|год|месяц(?:ев|а)?|недель|недели|дней)$",
        normalized,
    ):
        return "duration_for", _temporal_count(match.group("count")), _singular_unit(
            match.group("unit")
        )
    if match := re.match(r"since (?P<year>(?:19|20)\d{2})$", normalized):
        return "duration_since_year", int(match.group("year")), "year"
    if match := re.match(r"с (?P<year>(?:19|20)\d{2})$", normalized):
        return "duration_since_year", int(match.group("year")), "year"
    return "duration", None, ""


def _recurrence_hint_payload(phrase: str) -> tuple[str, int | None, str]:
    normalized = normalize_anchor_key(phrase)
    if not normalized:
        return "", None, ""
    if match := re.match(r"every (?P<unit>[a-z]+)$", normalized):
        return "recurrence_every", 1, _singular_unit(match.group("unit"))
    if match := re.match(r"кажд\w* (?P<unit>[а-яё]+)$", normalized):
        return "recurrence_every", 1, _singular_unit(match.group("unit"))
    if normalized in {"daily", "ежедневно"}:
        return "recurrence_every", 1, "day"
    if normalized in {"weekly", "еженедельно"}:
        return "recurrence_every", 1, "week"
    if normalized in {"monthly", "ежемесячно"}:
        return "recurrence_every", 1, "month"
    if normalized in {"yearly", "annually", "ежегодно"}:
        return "recurrence_every", 1, "year"
    if match := re.match(
        rf"(?P<count>once|twice|{_EN_NUMBER_WORD}|\d{{1,2}}) "
        r"(?:times? )?(?:a|per) (?P<unit>day|week|month|year)$",
        normalized,
    ):
        return "recurrence_per", _recurrence_count(match.group("count")), _singular_unit(
            match.group("unit")
        )
    if match := re.match(
        rf"(?P<count>\d{{1,2}}|{_RU_NUMBER_WORD}) раз(?:а)? в "
        r"(?P<unit>день|недел\w*|месяц|год)$",
        normalized,
    ):
        return "recurrence_per", _temporal_count(match.group("count")), _singular_unit(
            match.group("unit")
        )
    if normalized in {"regularly", "usually", "often", "регулярно", "обычно", "часто"}:
        return "recurrence_regular", None, ""
    return "recurrence", None, ""


def _temporal_count(value: str) -> int:
    if value.isdigit():
        return int(value)
    return _NUMBER_WORDS.get(value, 0)


def _recurrence_count(value: str) -> int:
    if value == "once":
        return 1
    if value == "twice":
        return 2
    return _temporal_count(value)


def _singular_unit(value: str) -> str:
    normalized = value.casefold()
    if normalized in {
        "day",
        "days",
        "день",
        "дней",
        "дня",
    }:
        return "day"
    if normalized in {
        "week",
        "weeks",
        "недел",
        "недели",
        "неделю",
        "недель",
    } or normalized.startswith("недел"):
        return "week"
    if normalized in {"weekday", "weekdays"}:
        return "weekday"
    if normalized in {"weekend", "weekends", "выходн", "выходные", "выходных"}:
        return "weekend"
    if normalized.startswith("выходн"):
        return "weekend"
    if normalized in {"month", "months", "месяц", "месяца", "месяцев"}:
        return "month"
    if normalized in {"year", "years", "год", "года", "лет"}:
        return "year"
    if normalized in {"morning", "afternoon", "evening", "night", "утро", "вечер"}:
        return "part_of_day"
    return normalized.rstrip("s")


def _nearby_temporal_after(text: str, start: int) -> str:
    tail = _nearby_clause(text[start : start + 80])
    match = _TEMPORAL_PATTERN.search(tail)
    return match.group(1) if match else ""


def _nearby_event_participant(
    text: str,
    start: int,
    *,
    allow_direct: bool = True,
    allow_origin_preps: bool = True,
) -> str:
    tail = _nearby_clause(text[start : start + 80])
    if next_event := _EVENT_KEYWORD_PATTERN.search(tail):
        tail = tail[: next_event.start()]
    if match := _event_participant_match(tail, allow_origin_preps=allow_origin_preps):
        label = _display_person_label(match.group("label"))
        prep = match.group("prep")
    elif direct_match := _direct_event_participant_match(tail, allow_direct=allow_direct):
        label = _display_person_label(direct_match.group("label"))
        prep = "с" if re.search(r"[А-Яа-яЁё]", label) else "with"
    else:
        return ""
    if not _is_probable_person_label(label):
        return ""
    return f"{prep} {label}"


def _event_participant_in_phrase(
    text: str,
    *,
    allow_origin_preps: bool = True,
) -> str:
    if not (keyword_match := _EVENT_KEYWORD_PATTERN.search(text)):
        return ""
    tail = _nearby_clause(text[keyword_match.end() : keyword_match.end() + 80])
    if next_event := _EVENT_KEYWORD_PATTERN.search(tail):
        tail = tail[: next_event.start()]
    if match := _event_participant_match(tail, allow_origin_preps=allow_origin_preps):
        label = _display_person_label(match.group("label"))
        prep = match.group("prep")
    elif direct_match := _direct_event_participant_match(tail):
        label = _display_person_label(direct_match.group("label"))
        prep = "с" if re.search(r"[А-Яа-яЁё]", label) else "with"
    else:
        return ""
    if not _is_probable_person_label(label):
        return ""
    return f"{prep} {label}"


def _event_participant_match(
    text: str,
    *,
    allow_origin_preps: bool,
) -> re.Match[str] | None:
    for match in _EVENT_PARTICIPANT_PATTERN.finditer(text):
        prep = normalize_anchor_key(match.group("prep"))
        if not allow_origin_preps and prep in {"from", "от"}:
            continue
        return match
    return None


def _direct_event_participant_match(
    text: str,
    *,
    allow_direct: bool = True,
) -> re.Match[str] | None:
    if not allow_direct:
        return None
    return _EVENT_DIRECT_PARTICIPANT_PATTERN.search(text)


def _nearby_event_project(text: str, start: int) -> str:
    tail = _nearby_clause(text[start : start + 100])
    if next_event := _EVENT_KEYWORD_PATTERN.search(tail):
        tail = tail[: next_event.start()]
    return _event_project_in_phrase(tail)


def _nearby_event_project_before(text: str, end: int) -> str:
    prefix = _nearby_clause_before(text[max(0, end - 100) : end])
    match = _EVENT_PREFIX_PROJECT_PATTERN.search(prefix)
    if not match:
        return ""
    label = _clean_prefix_project_label(match.group("label"))
    if not _is_probable_event_project_label(label):
        return ""
    prep = "по" if re.search(r"[А-Яа-яЁё]", label) else "for"
    return f"{prep} {label}"


def _clean_prefix_project_label(label: str) -> str:
    tokens = [token for token in label.split() if token.strip(".,:;()[]{}")]
    while tokens and normalize_anchor_key(tokens[0]) in _PREFIX_PROJECT_LEADING_STOP_WORDS:
        tokens.pop(0)
    return _clean_project_label(" ".join(tokens))


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
    subject = _event_interview_subject_participant_before(prefix, event_keyword=event_keyword)
    if subject:
        return subject
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


def _event_interview_subject_participant_before(prefix: str, *, event_keyword: str) -> str:
    if normalize_anchor_key(event_keyword) not in {"interview", "interviews"}:
        return ""
    matches = list(_EVENT_INTERVIEW_SUBJECT_PATTERN.finditer(prefix))
    for match in reversed(matches):
        label = _display_person_label(match.group("label"))
        if not _is_probable_person_label(label):
            continue
        prep = "с" if re.search(r"[А-Яа-яЁё]", label) else "with"
        return f"{prep} {label}"
    return ""


def _is_lowercase_person_token(value: str) -> bool:
    stripped = value.strip()
    if not stripped or stripped.startswith("@"):
        return False
    return bool(re.match(r"[a-zа-яё]", stripped))


def _display_event_type(raw: str) -> str:
    normalized = normalize_anchor_key(raw)
    return _EVENT_DISPLAY_NORMALIZATIONS.get(normalized, raw)


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
    return _looks_like_project_label_continuation(label.split()[0])


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
        if index == 0 and normalized in _PROJECT_LABEL_STOP_WORDS:
            return ""
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
