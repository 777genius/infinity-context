"""Query anchor intent extraction policies."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from infinity_context_core.application.anchor_extraction import (
    ObservedAnchor,
    canonical_anchor_key_for_kind,
    extract_observed_anchors,
    structured_anchor_metadata_for_label,
)
from infinity_context_core.application.context_occupational_role_identity import (
    is_non_person_identity_label,
)
from infinity_context_core.application.context_query_intent_common import (
    _metadata_text,
    _normalized,
)
from infinity_context_core.application.context_query_intent_contracts import (
    QueryAnchorHint,
    QueryAnchorIntent,
    QueryAnchorLookupKey,
)
from infinity_context_core.application.context_query_intent_keys import (
    _storage_lookup_key_variants,
    _temporal_identity_keys,
)
from infinity_context_core.application.context_temporal_hints import temporal_hint_windows
from infinity_context_core.domain.entities import MemoryAnchorKind

_EVENTISH_QUERY_RE = re.compile(
    r"\b("
    r"call|meeting|review|sync|demo|chat|dm|message|conversation|"
    r"direct message|meet|met|wrote|sent|messaged|texted|said|told|"
    r"talked|spoke|chatted|discussed|"
    r"move|moved|moving|relocate|relocated|relocation|"
    r"attend|attended|join|joined|participate|participated|went|hike|hiked|hikes|hiking|"
    r"standup|planning|retro|retrospective|workshop|interview|interviews|release|launch|"
    r"звонок|созвона|созвон|встреча|ревью|демо|переписк(?:а|е|и|ой|у)|"
    r"переписывался|переписывалась|переписывались|"
    r"общался|общалась|общались|созванивался|созванивалась|созванивались|"
    r"переезд|переехал|переехала|переехали|переезжал|переезжала|переезжали|"
    r"позвонил|позвонила|звонил|звонила|написал|написала|написали|"
    r"ответил|ответила|ответили|сказал|сказала|сказали|"
    r"сообщил|сообщила|сообщили|скинул|скинула|скинули|"
    r"прислал|прислала|прислали|отправил|отправила|отправили|"
    r"рассказал|рассказала|рассказали|"
    r"встретился|встретилась|встречался|встречалась|"
    r"разговор|чат|планерка|планёрка|стендап|ретро|интервью|воркшоп|релиз|запуск"
    r")\b",
    re.IGNORECASE,
)

_RELATIVE_TIME_RE = re.compile(
    r"\b("
    r"earlier today|this morning|this afternoon|this evening|"
    r"this week|current week|earlier this week|"
    r"this month|current month|this quarter|current quarter|this year|current year|"
    r"next week|upcoming week|following week|"
    r"next month|upcoming month|following month|"
    r"next quarter|upcoming quarter|following quarter|"
    r"next year|upcoming year|following year|"
    r"last week|previous week|week ago|yesterday|today|tomorrow|an hour ago|hour ago|"
    r"last\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"previous\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"last month|previous month|month ago|last year|previous year|year ago|"
    r"(?:\d{1,3}|one|two|three|four|five|six)\s+hours?\s+ago|"
    r"(?:\d{1,3}|one|two|three|four|five|six)\s+days?\s+ago|"
    r"(?:\d{1,2}|one|two|three|four|five|six)\s+weeks?\s+ago|"
    r"(?:\d{1,2}|one|two|three|four|five|six)\s+months?\s+ago|"
    r"(?:\d{1,2}|one|two|three|four|five|six)\s+years?\s+ago|"
    r"ранее сегодня|сегодня утром|утром сегодня|"
    r"сегодня д[нн]ём|д[нн]ём сегодня|сегодня днем|днем сегодня|"
    r"сегодня вечером|вечером сегодня|"
    r"на этой неделе|в эту неделю|эта неделя|"
    r"в этом месяце|этот месяц|в этом квартале|этот квартал|в этом году|этот год|"
    r"на следующей неделе|в следующую неделю|следующая неделя|"
    r"в следующем месяце|на следующий месяц|следующий месяц|"
    r"в следующем квартале|на следующий квартал|следующий квартал|"
    r"в следующем году|на следующий год|следующий год|"
    r"неделю назад|на прошлой неделе|прошлой неделе|прошлую неделю|"
    r"месяц назад|в прошлом месяце|прошлый месяц|прошлом месяце|"
    r"год назад|в прошлом году|прошлый год|прошлом году|"
    r"вчера|сегодня|завтра|час назад|"
    r"(?:\d{1,3}|один|одна|два|две|три|четыре|пять|шесть)\s+час(?:а|ов)?\s+назад|"
    r"(?:\d{1,3}|один|одна|два|две|три|четыре|пять|шесть)\s+д(?:ень|ня|ней)\s+назад|"
    r"(?:\d{1,2}|один|одна|два|две|три|четыре|пять|шесть)\s+недел[юи]\s+назад|"
    r"(?:\d{1,2}|один|одна|два|две|три|четыре|пять|шесть)\s+месяц(?:а|ев)?\s+назад|"
    r"(?:\d{1,2}|один|одна|два|две|три|четыре|пять|шесть)\s+(?:год(?:а)?|лет)\s+назад"
    r")\b",
    re.IGNORECASE,
)

_ACTIVITY_STATE_QUERY_RE = re.compile(
    r"\b("
    r"how\s+long|how\s+often|duration|frequency|cadence|"
    r"как\s+долго|как\s+часто|сколько|частота"
    r")\b",
    re.IGNORECASE,
)

_ACTIVITY_STATE_EVENT_TYPE_RE = re.compile(
    r"\b("
    r"volunteer(?:s|ed|ing)?|work(?:s|ed|ing)?|live(?:s|d|ing)?|"
    r"play(?:s|ed|ing)?|run(?:s|ning)?|practice(?:s|d|ing)?|"
    r"train(?:s|ed|ing)?|"
    r"волонтерит|волонт[её]р(?:ит|ил|ила|или|ство)|работает|работал|работала|"
    r"жив[её]т|жил|жила|жили|играет|играл|играла|занимается|"
    r"тренируется|участвует"
    r")\b",
    re.IGNORECASE,
)

_LOWER_PERSON_HINT_RE = re.compile(
    r"\b(?P<prep>with|from|с|от)\s+"
    r"(?P<label>@?[a-zа-яё][a-zа-яё0-9._-]{2,39})\b",
    re.IGNORECASE,
)

_LOWER_PROJECT_HINT_RE = re.compile(
    r"\b(?P<prep>about|for|in|по|про|для|в)\s+"
    r"(?:(?:project|проект(?:у|е|а|ом)?)\s+)?"
    r"(?P<label>[a-zа-яё0-9][a-zа-яё0-9._-]{1,79})\b",
    re.IGNORECASE,
)

_RELATIVE_TIME_HINT_STOP_WORDS = frozenset(
    {
        "ago",
        "day",
        "days",
        "five",
        "four",
        "friday",
        "hour",
        "hours",
        "monday",
        "month",
        "months",
        "next",
        "one",
        "quarter",
        "saturday",
        "six",
        "sunday",
        "three",
        "thursday",
        "two",
        "tuesday",
        "week",
        "wednesday",
        "weeks",
        "year",
        "years",
        "два",
        "две",
        "день",
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
        "один",
        "одна",
        "пять",
        "следующей",
        "следующем",
        "следующий",
        "следующую",
        "три",
        "час",
        "часа",
        "часов",
        "четыре",
        "шесть",
    }
)

_PERSON_HINT_STOP_WORDS = frozenset(
    {
        "client",
        "customer",
        "from",
        "her",
        "him",
        "what",
        "when",
        "where",
        "who",
        "why",
        "after",
        "before",
        "following",
        "kiev",
        "kyiv",
        "later",
        "posle",
        "postgres",
        "since",
        "them",
        "then",
        "sweden",
        "team",
        "user",
        "chto",
        "gde",
        "kak",
        "kakaya",
        "kakie",
        "kakoe",
        "kakoi",
        "kogda",
        "kto",
        "pochemu",
        "zachem",
        "где",
        "зачем",
        "как",
        "какая",
        "какие",
        "какое",
        "какой",
        "когда",
        "киев",
        "киева",
        "команда",
        "командой",
        "клиент",
        "клиентом",
        "кто",
        "куда",
        "откуда",
        "перед",
        "после",
        "потом",
        "почему",
        "проект",
        "проектом",
        "пользователь",
        "раньше",
        "что",
        "затем",
        "was",
    }
).union(_RELATIVE_TIME_HINT_STOP_WORDS)

_PROJECT_HINT_STOP_WORDS = frozenset(
    {
        "call",
        "chat",
        "meeting",
        "message",
        "review",
        "sync",
        "the",
        "to",
        "звонок",
        "созвон",
        "созванивался",
        "созванивалась",
        "созванивались",
        "чат",
        "встреча",
        "переписка",
        "переписывался",
        "переписывалась",
        "переписывались",
    }
).union(_RELATIVE_TIME_HINT_STOP_WORDS)


def build_query_anchor_intent(query: str) -> QueryAnchorIntent:
    hints: list[QueryAnchorHint] = []
    seen: set[tuple[str, str]] = set()
    for observed in extract_observed_anchors(query):
        if observed.kind == MemoryAnchorKind.PERSON and is_non_person_identity_label(
            label=observed.label,
            text=query,
        ):
            continue
        _append_observed_hint(hints, seen, observed)
    _append_activity_state_event_type_hints(hints, seen, query)
    if _is_eventish_query(query):
        _append_lowercase_event_hints(hints, seen, query)
        if not _event_temporal_keys(hints):
            _append_temporal_event_hints(hints, seen, query)
    return QueryAnchorIntent(hints=_without_project_person_duplicates(tuple(hints))[:16])


def query_anchor_lookup_keys(intent: QueryAnchorIntent) -> tuple[QueryAnchorLookupKey, ...]:
    keys: list[QueryAnchorLookupKey] = []
    seen: set[tuple[str, str]] = set()
    for hint in intent.hints:
        if (
            hint.kind == MemoryAnchorKind.EVENT
            and _metadata_text(hint.reason) == "event query temporal hint"
        ):
            continue
        for raw_key in (hint.label, hint.canonical_key):
            if raw_key.startswith("event_temporal:"):
                continue
            for normalized_key in _storage_lookup_key_variants(hint.kind, raw_key):
                key = (hint.kind.value, normalized_key)
                if key in seen:
                    continue
                seen.add(key)
                keys.append(
                    QueryAnchorLookupKey(
                        kind=hint.kind,
                        normalized_key=normalized_key,
                    )
                )
                if len(keys) >= 32:
                    return tuple(keys)
    return tuple(keys)


def _without_project_person_duplicates(
    hints: tuple[QueryAnchorHint, ...],
) -> tuple[QueryAnchorHint, ...]:
    project_keys = {hint.canonical_key for hint in hints if hint.kind == MemoryAnchorKind.PROJECT}
    if not project_keys:
        return hints
    return tuple(
        hint
        for hint in hints
        if not (hint.kind == MemoryAnchorKind.PERSON and hint.canonical_key in project_keys)
    )


def _append_observed_hint(
    hints: list[QueryAnchorHint],
    seen: set[tuple[str, str]],
    observed: ObservedAnchor,
) -> None:
    canonical_key = _metadata_text(observed.metadata.get("canonical_key"))
    if not canonical_key:
        canonical_key = canonical_anchor_key_for_kind(observed.kind, observed.label)
    if observed.kind == MemoryAnchorKind.PROJECT and canonical_key in _PROJECT_HINT_STOP_WORDS:
        return
    if observed.kind == MemoryAnchorKind.PERSON and canonical_key in _PERSON_HINT_STOP_WORDS:
        return
    _append_hint(
        hints,
        seen,
        kind=observed.kind,
        canonical_key=canonical_key,
        label=observed.label,
        reason=observed.reason,
        metadata=observed.metadata,
    )


def _append_lowercase_event_hints(
    hints: list[QueryAnchorHint],
    seen: set[tuple[str, str]],
    query: str,
) -> None:
    for match in _LOWER_PERSON_HINT_RE.finditer(query):
        label = match.group("label").lstrip("@")
        if _normalized(label) in _PERSON_HINT_STOP_WORDS:
            continue
        _append_label_hint(
            hints,
            seen,
            kind=MemoryAnchorKind.PERSON,
            label=label,
            reason="event query participant hint",
        )
    for match in _LOWER_PROJECT_HINT_RE.finditer(query):
        label = match.group("label")
        if _normalized(label) in _PROJECT_HINT_STOP_WORDS:
            continue
        _append_label_hint(
            hints,
            seen,
            kind=MemoryAnchorKind.PROJECT,
            label=label,
            reason="event query project hint",
        )


def _append_temporal_event_hints(
    hints: list[QueryAnchorHint],
    seen: set[tuple[str, str]],
    query: str,
) -> None:
    for match in _RELATIVE_TIME_RE.finditer(query):
        phrase = match.group(1)
        metadata = structured_anchor_metadata_for_label(
            MemoryAnchorKind.EVENT,
            f"meeting {phrase}",
        )
        temporal_keys = _temporal_identity_keys(metadata)
        if not temporal_keys:
            metadata = _temporal_metadata_from_phrase(phrase)
            temporal_keys = _temporal_identity_keys(metadata)
        if not temporal_keys:
            continue
        strongest_key = sorted(temporal_keys, key=lambda value: (":" not in value, value))[-1]
        _append_hint(
            hints,
            seen,
            kind=MemoryAnchorKind.EVENT,
            canonical_key=f"event_temporal:{strongest_key}",
            label=phrase,
            reason="event query temporal hint",
            metadata={
                "extraction_reason": "event query temporal hint",
                "extractor": "context-query-intent-v1",
                **metadata,
            },
        )


def _append_activity_state_event_type_hints(
    hints: list[QueryAnchorHint],
    seen: set[tuple[str, str]],
    query: str,
) -> None:
    if not _ACTIVITY_STATE_QUERY_RE.search(query):
        return
    for match in _ACTIVITY_STATE_EVENT_TYPE_RE.finditer(query):
        label = match.group(1)
        canonical_key = canonical_anchor_key_for_kind(MemoryAnchorKind.EVENT, label)
        if not canonical_key:
            continue
        metadata = {
            "extraction_reason": "activity state event query hint",
            "extractor": "context-query-intent-v1",
            "canonical_key": canonical_key,
            "anchor_family": "event",
            "event_type": label.casefold(),
            "event_type_canonical": canonical_key,
            "event_identity_terms": [canonical_key],
        }
        _append_hint(
            hints,
            seen,
            kind=MemoryAnchorKind.EVENT,
            canonical_key=canonical_key,
            label=label,
            reason="activity state event query hint",
            metadata=metadata,
        )


def _temporal_metadata_from_phrase(phrase: str) -> dict[str, object]:
    hints = temporal_hint_windows(phrase)
    if not hints:
        return {}
    hint = hints[0]
    code = hint.canonical_code or hint.code
    metadata: dict[str, object] = {
        "event_temporal_hint_code": code,
        "event_identity_terms": [code],
    }
    match = re.fullmatch(
        r"(?P<count>\d+)_(?P<unit>hours|days|weeks|months|years)_ago",
        hint.code,
    )
    if match is not None:
        unit = {
            "hours": "hour",
            "days": "day",
            "weeks": "week",
            "months": "month",
            "years": "year",
        }[match.group("unit")]
        quantity = match.group("count")
        metadata["event_temporal_quantity"] = quantity
        metadata["event_temporal_unit"] = unit
        metadata["event_identity_terms"].append(f"{code}:{quantity}:{unit}")
    return metadata


def _append_label_hint(
    hints: list[QueryAnchorHint],
    seen: set[tuple[str, str]],
    *,
    kind: MemoryAnchorKind,
    label: str,
    reason: str,
) -> None:
    canonical_key = canonical_anchor_key_for_kind(kind, label)
    if not canonical_key:
        return
    _append_hint(
        hints,
        seen,
        kind=kind,
        canonical_key=canonical_key,
        label=label,
        reason=reason,
        metadata={
            "extraction_reason": reason,
            "extractor": "context-query-intent-v1",
            **structured_anchor_metadata_for_label(kind, label),
        },
    )


def _append_hint(
    hints: list[QueryAnchorHint],
    seen: set[tuple[str, str]],
    *,
    kind: MemoryAnchorKind,
    canonical_key: str,
    label: str,
    reason: str,
    metadata: Mapping[str, object],
) -> None:
    safe_key = _metadata_text(canonical_key)
    if not safe_key:
        return
    key = (kind.value, safe_key)
    if key in seen:
        return
    seen.add(key)
    hints.append(
        QueryAnchorHint(
            kind=kind,
            canonical_key=safe_key,
            label=_metadata_text(label),
            reason=_metadata_text(reason),
            metadata=dict(metadata),
        )
    )


def _event_temporal_keys(hints: Iterable[QueryAnchorHint]) -> frozenset[str]:
    keys: set[str] = set()
    for hint in hints:
        if hint.kind == MemoryAnchorKind.EVENT:
            keys.update(_temporal_identity_keys(hint.metadata))
    return frozenset(keys)


def _is_eventish_query(query: str) -> bool:
    return bool(_EVENTISH_QUERY_RE.search(query) or _RELATIVE_TIME_RE.search(query))
