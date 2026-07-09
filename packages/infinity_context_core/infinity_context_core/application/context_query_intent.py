"""Structured query intent for anchor-aware context retrieval."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from infinity_context_core.application.anchor_extraction import (
    ObservedAnchor,
    canonical_anchor_key_for_kind,
    extract_observed_anchors,
    normalize_anchor_key,
    structured_anchor_metadata_for_label,
)
from infinity_context_core.application.anchor_identity_normalization import (
    canonical_token,
    normalize_cyrillic_person_case,
    normalize_cyrillic_project_case,
)
from infinity_context_core.application.context_temporal_hints import temporal_hint_windows
from infinity_context_core.application.safe_payload import safe_metadata_text
from infinity_context_core.domain.entities import MemoryAnchor, MemoryAnchorKind

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
_RELOCATION_ORIGIN_EVIDENCE_RE = re.compile(
    r"\b(?:move|moved|moving|relocate|relocated)\s+from\b|"
    r"\b(?:home country|country of origin|native country|previous country|former country|"
    r"birth country|roots|origin|origins)\b|"
    r"\b(?:родн(?:ая|ой|ую)\s+стран|страна\s+происхождения|корни|переехал[аи]?\s+из)\b",
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
        "am",
        "are",
        "be",
        "been",
        "being",
        "did",
        "do",
        "does",
        "from",
        "had",
        "has",
        "have",
        "he",
        "her",
        "him",
        "his",
        "i",
        "is",
        "it",
        "me",
        "my",
        "our",
        "she",
        "their",
        "theirs",
        "what",
        "when",
        "where",
        "who",
        "why",
        "after",
        "before",
        "following",
        "graphiti",
        "kiev",
        "kyiv",
        "later",
        "postgres",
        "posle",
        "qdrant",
        "since",
        "them",
        "then",
        "they",
        "sweden",
        "team",
        "us",
        "user",
        "was",
        "we",
        "were",
        "you",
        "your",
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
        "a",
        "an",
        "the",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "their",
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
_EVENT_TYPE_GROUPS: Mapping[str, frozenset[str]] = {
    "call": frozenset(
        {
            "call",
            "zvonok",
            "sozvon",
            "sozvona",
            "sozvanivalas",
            "sozvanivalis",
            "sozvanivalsya",
            "pozvonil",
            "pozvonila",
            "zvonil",
            "zvonila",
        }
    ),
    "relocation": frozenset(
        {
            "move",
            "moved",
            "moving",
            "relocate",
            "relocated",
            "relocation",
            "pereehala",
            "pereehali",
            "pereehal",
            "pereezd",
            "pereezzhala",
            "pereezzhali",
            "pereezzhal",
        }
    ),
    "activity": frozenset(
        {
            "attend",
            "attended",
            "hike",
            "hiked",
            "hikes",
            "hiking",
            "join",
            "joined",
            "live",
            "lived",
            "lives",
            "living",
            "participate",
            "participated",
            "play",
            "played",
            "playing",
            "practice",
            "practiced",
            "practicing",
            "rabotaet",
            "rabotal",
            "rabotala",
            "run",
            "running",
            "runs",
            "train",
            "trained",
            "training",
            "uchastvuet",
            "volunteer",
            "volunteered",
            "volunteering",
            "volunteers",
            "work",
            "worked",
            "working",
            "works",
            "went",
            "zhila",
            "zhili",
            "zhil",
            "zhivet",
        }
    ),
    "message": frozenset(
        {
            "chat",
            "chatted",
            "conversation",
            "discussed",
            "dm",
            "direct message",
            "message",
            "messaged",
            "obschalas",
            "obschalis",
            "obschalsya",
            "sent",
            "spoke",
            "talked",
            "texted",
            "wrote",
            "napisal",
            "napisala",
            "napisali",
            "otpravil",
            "otpravila",
            "otpravili",
            "otvetil",
            "otvetila",
            "otvetili",
            "perepiska",
            "perepiske",
            "perepiski",
            "perepisku",
            "perepiskoi",
            "perepisyvalas",
            "perepisyvalis",
            "perepisyvalsya",
            "razgovor",
            "rasskazal",
            "rasskazala",
            "rasskazali",
            "said",
            "skinul",
            "skinula",
            "skinuli",
            "skazal",
            "skazala",
            "skazali",
            "soobschil",
            "soobschila",
            "soobschili",
            "told",
            "prislal",
            "prislala",
            "prislali",
        }
    ),
    "meeting": frozenset(
        {
            "meeting",
            "meet",
            "met",
            "vstrecha",
            "vstretilsya",
            "vstretilas",
            "vstrechalsya",
            "vstrechalas",
            "vstrechalis",
        }
    ),
    "review": frozenset({"review", "revyu"}),
    "sync": frozenset(
        {
            "sync",
            "standup",
            "planning",
            "planerka",
            "stendap",
            "retro",
            "retrospective",
        }
    ),
    "demo": frozenset({"demo", "presentation", "prezentatsiya"}),
    "workshop": frozenset({"workshop", "vorkshop", "interview", "interviews", "intervyu"}),
    "launch": frozenset({"launch", "release", "zapusk", "reliz"}),
    "workflow": frozenset(
        {
            "deadline",
            "deliverable",
            "due",
            "milestone",
            "reminder",
            "task",
            "todo",
            "dedlain",
            "mailstoun",
            "napominanie",
            "poruchenie",
            "srok",
            "zadacha",
        }
    ),
}
_EVENT_TYPE_TO_GROUP = {
    value: group for group, values in _EVENT_TYPE_GROUPS.items() for value in values
}
_BROAD_CONVERSATION_EVENT_TYPES = frozenset({"conversation"})
_CONVERSATIONAL_EVENT_GROUP_KEYS = frozenset(
    {"group:call", "group:meeting", "group:message", "group:sync"}
)


@dataclass(frozen=True)
class QueryAnchorHint:
    kind: MemoryAnchorKind
    canonical_key: str
    label: str
    reason: str
    metadata: Mapping[str, object]


@dataclass(frozen=True)
class QueryAnchorIntent:
    hints: tuple[QueryAnchorHint, ...]

    @property
    def empty(self) -> bool:
        return not self.hints

    def keys_for_kind(self, kind: MemoryAnchorKind) -> frozenset[str]:
        return frozenset(hint.canonical_key for hint in self.hints if hint.kind == kind)

    def temporal_keys(self) -> frozenset[str]:
        keys: set[str] = set()
        for hint in self.hints:
            if hint.kind != MemoryAnchorKind.EVENT:
                continue
            keys.update(_temporal_identity_keys(hint.metadata))
        return frozenset(keys)

    def event_type_keys(self) -> frozenset[str]:
        keys: set[str] = set()
        for hint in self.hints:
            if hint.kind != MemoryAnchorKind.EVENT:
                continue
            keys.update(_event_type_identity_keys(hint.metadata))
        return frozenset(keys)

    def diagnostics(self) -> dict[str, object]:
        counts = {
            kind.value: sum(1 for hint in self.hints if hint.kind == kind)
            for kind in MemoryAnchorKind
        }
        return {
            "query_anchor_intent_status": "empty" if self.empty else "available",
            "query_anchor_hint_count": len(self.hints),
            "query_anchor_person_hint_count": counts[MemoryAnchorKind.PERSON.value],
            "query_anchor_event_hint_count": counts[MemoryAnchorKind.EVENT.value],
            "query_anchor_project_hint_count": counts[MemoryAnchorKind.PROJECT.value],
            "query_anchor_organization_hint_count": counts[MemoryAnchorKind.ORGANIZATION.value],
            "query_anchor_temporal_hint_count": len(self.temporal_keys()),
            "query_anchor_event_type_hint_count": len(self.event_type_keys()),
            "query_anchor_hint_reasons": _bounded_unique(hint.reason for hint in self.hints),
        }


@dataclass(frozen=True)
class QueryAnchorMatch:
    score_boost: float
    reasons: tuple[str, ...]
    matched_keys: tuple[str, ...]

    def diagnostics(self) -> dict[str, object]:
        return {
            "query_anchor_match_score_boost": self.score_boost,
            "query_anchor_match_reasons": list(self.reasons),
            "query_anchor_match_keys": list(self.matched_keys),
        }


@dataclass(frozen=True)
class QueryAnchorLookupKey:
    kind: MemoryAnchorKind
    normalized_key: str


def build_query_anchor_intent(query: str) -> QueryAnchorIntent:
    hints: list[QueryAnchorHint] = []
    seen: set[tuple[str, str]] = set()
    for observed in extract_observed_anchors(query):
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


def match_query_anchor_intent(
    intent: QueryAnchorIntent,
    anchor: MemoryAnchor,
) -> QueryAnchorMatch | None:
    if intent.empty:
        return None
    if anchor.kind == MemoryAnchorKind.EVENT:
        return _match_event_anchor(intent, anchor)
    anchor_keys = _anchor_identity_keys(anchor)
    query_keys = intent.keys_for_kind(anchor.kind)
    shared = _compatible_identity_matches(anchor_keys, query_keys)
    if not shared:
        return None
    return QueryAnchorMatch(
        score_boost=0.055,
        reasons=(f"query_{anchor.kind.value}_identity_match",),
        matched_keys=tuple(shared[:4]),
    )


def match_query_anchor_intent_to_text(
    intent: QueryAnchorIntent,
    text: str,
) -> QueryAnchorMatch | None:
    if intent.empty:
        return None
    anchors = _text_intent_observed_anchors(text)
    if not anchors:
        return None
    if _observed_anchor_conflicts_intent(intent, anchors, text=text):
        return None
    reasons: list[str] = []
    matched_keys: list[str] = []
    score_boost = 0.0
    for anchor in anchors:
        if anchor.kind == MemoryAnchorKind.EVENT:
            match = _match_observed_event_anchor(intent, anchor)
            if match is None:
                continue
            reasons.extend(match.reasons)
            matched_keys.extend(match.matched_keys)
            score_boost += match.score_boost
            continue
        query_keys = intent.keys_for_kind(anchor.kind)
        if not query_keys:
            continue
        shared = _compatible_identity_matches(
            _observed_anchor_identity_keys(anchor),
            query_keys,
        )
        if not shared:
            continue
        reasons.append(f"query_{anchor.kind.value}_identity_match")
        matched_keys.extend(shared[:4])
        score_boost += 0.025
    if not reasons:
        return None
    return QueryAnchorMatch(
        score_boost=min(0.055, round(score_boost, 4)),
        reasons=tuple(_bounded_unique(reasons)),
        matched_keys=tuple(_bounded_unique(matched_keys, limit=8)),
    )


def query_anchor_intent_conflicts(
    intent: QueryAnchorIntent,
    anchor: MemoryAnchor,
) -> bool:
    if intent.empty:
        return False
    if anchor.kind == MemoryAnchorKind.EVENT:
        return _event_anchor_conflicts_intent(intent, anchor)
    query_keys = intent.keys_for_kind(anchor.kind)
    if not query_keys:
        return False
    return not _compatible_identity_matches(_anchor_identity_keys(anchor), query_keys)


def query_anchor_intent_text_conflicts(
    intent: QueryAnchorIntent,
    text: str,
) -> bool:
    """Return True when observed text anchors contradict explicit query anchors."""

    if intent.empty:
        return False
    anchors = _text_intent_observed_anchors(text)
    return bool(anchors and _observed_anchor_conflicts_intent(intent, anchors, text=text))


def _text_intent_observed_anchors(text: str) -> tuple[ObservedAnchor, ...]:
    return tuple(
        anchor
        for anchor in extract_observed_anchors(text)
        if not _observed_anchor_is_text_intent_noise(anchor)
    )


def _observed_anchor_is_text_intent_noise(anchor: ObservedAnchor) -> bool:
    canonical_key = _metadata_text(anchor.metadata.get("canonical_key"))
    if not canonical_key:
        canonical_key = canonical_anchor_key_for_kind(anchor.kind, anchor.label)
    normalized_label = _normalized(anchor.label)
    if anchor.kind == MemoryAnchorKind.PERSON:
        return (
            canonical_key in _PERSON_HINT_STOP_WORDS
            or normalized_label in _PERSON_HINT_STOP_WORDS
        )
    if anchor.kind == MemoryAnchorKind.PROJECT:
        return (
            canonical_key in _PROJECT_HINT_STOP_WORDS
            or normalized_label in _PROJECT_HINT_STOP_WORDS
        )
    return False


def _append_observed_hint(
    hints: list[QueryAnchorHint],
    seen: set[tuple[str, str]],
    observed: ObservedAnchor,
) -> None:
    canonical_key = _metadata_text(observed.metadata.get("canonical_key"))
    if not canonical_key:
        canonical_key = canonical_anchor_key_for_kind(observed.kind, observed.label)
    if (
        observed.kind == MemoryAnchorKind.PROJECT
        and canonical_key in _PROJECT_HINT_STOP_WORDS
    ):
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


def _match_event_anchor(
    intent: QueryAnchorIntent,
    anchor: MemoryAnchor,
) -> QueryAnchorMatch | None:
    event_keys = _anchor_identity_keys(anchor)
    exact_event_keys = intent.keys_for_kind(MemoryAnchorKind.EVENT).intersection(event_keys)
    person_keys = intent.keys_for_kind(MemoryAnchorKind.PERSON)
    project_keys = intent.keys_for_kind(MemoryAnchorKind.PROJECT)
    temporal_keys = intent.temporal_keys()
    event_type_keys = intent.event_type_keys()

    anchor_person = _metadata_text(anchor.metadata.get("event_participant_canonical_key"))
    anchor_project = _metadata_text(
        anchor.metadata.get("event_project_canonical_key")
        or anchor.metadata.get("project_canonical_key")
    )
    anchor_person_keys = _identity_term_variants(anchor_person)
    anchor_project_keys = _identity_term_variants(anchor_project)
    anchor_temporal_keys = _temporal_identity_keys(anchor.metadata)
    anchor_event_type_keys = _event_type_identity_keys(anchor.metadata)

    if person_keys and not anchor_person_keys.intersection(person_keys):
        return None
    if project_keys and not _compatible_identity_matches(anchor_project_keys, project_keys):
        return None
    if _event_type_keys_conflict(
        query_event_type_keys=event_type_keys,
        anchor_event_type_keys=anchor_event_type_keys,
    ):
        return None
    if _temporal_keys_conflict(
        query_temporal_keys=temporal_keys,
        anchor_temporal_keys=anchor_temporal_keys,
    ):
        return None

    reasons: list[str] = []
    matched_keys: list[str] = []
    score_boost = 0.0
    if exact_event_keys:
        reasons.append("query_event_identity_match")
        matched_keys.extend(sorted(exact_event_keys)[:4])
        score_boost += 0.04
    person_matches = sorted(anchor_person_keys.intersection(person_keys))
    if person_matches:
        reasons.append("query_event_participant_match")
        matched_keys.extend(person_matches[:2])
        score_boost += 0.035
    project_matches = _compatible_identity_matches(anchor_project_keys, project_keys)
    if project_matches:
        reasons.append("query_event_project_match")
        matched_keys.extend(project_matches[:2])
        score_boost += 0.035
    shared_event_type = sorted(anchor_event_type_keys.intersection(event_type_keys))
    if shared_event_type:
        reasons.append("query_event_type_match")
        matched_keys.extend(shared_event_type[:3])
        score_boost += 0.025
    shared_temporal = sorted(anchor_temporal_keys.intersection(temporal_keys))
    if shared_temporal:
        reasons.append("query_event_temporal_match")
        matched_keys.extend(shared_temporal[:3])
        score_boost += 0.02
    if not reasons:
        return None
    return QueryAnchorMatch(
        score_boost=min(0.09, round(score_boost, 4)),
        reasons=tuple(_bounded_unique(reasons)),
        matched_keys=tuple(_bounded_unique(matched_keys, limit=8)),
    )


def _match_observed_event_anchor(
    intent: QueryAnchorIntent,
    anchor: ObservedAnchor,
) -> QueryAnchorMatch | None:
    metadata = anchor.metadata
    person_keys = intent.keys_for_kind(MemoryAnchorKind.PERSON)
    project_keys = intent.keys_for_kind(MemoryAnchorKind.PROJECT)
    temporal_keys = intent.temporal_keys()
    event_type_keys = intent.event_type_keys()

    anchor_person = _metadata_text(metadata.get("event_participant_canonical_key"))
    anchor_project = _metadata_text(
        metadata.get("event_project_canonical_key") or metadata.get("project_canonical_key")
    )
    anchor_person_keys = _identity_term_variants(anchor_person)
    anchor_project_keys = _identity_term_variants(anchor_project)
    anchor_temporal_keys = _temporal_identity_keys(metadata)
    anchor_event_type_keys = _event_type_identity_keys(metadata)

    if person_keys and anchor_person_keys and not anchor_person_keys.intersection(person_keys):
        return None
    if (
        project_keys
        and anchor_project_keys
        and not _compatible_identity_matches(anchor_project_keys, project_keys)
    ):
        return None
    if _event_type_keys_conflict(
        query_event_type_keys=event_type_keys,
        anchor_event_type_keys=anchor_event_type_keys,
    ):
        return None
    if _temporal_keys_conflict(
        query_temporal_keys=temporal_keys,
        anchor_temporal_keys=anchor_temporal_keys,
    ):
        return None

    reasons: list[str] = []
    matched_keys: list[str] = []
    score_boost = 0.0
    person_matches = sorted(anchor_person_keys.intersection(person_keys))
    if person_matches:
        reasons.append("query_event_participant_match")
        matched_keys.extend(person_matches[:2])
        score_boost += 0.02
    project_matches = _compatible_identity_matches(anchor_project_keys, project_keys)
    if project_matches:
        reasons.append("query_event_project_match")
        matched_keys.extend(project_matches[:2])
        score_boost += 0.02
    shared_event_type = sorted(anchor_event_type_keys.intersection(event_type_keys))
    if shared_event_type:
        reasons.append("query_event_type_match")
        matched_keys.extend(shared_event_type[:3])
        score_boost += 0.015
    shared_temporal = sorted(anchor_temporal_keys.intersection(temporal_keys))
    if shared_temporal:
        reasons.append("query_event_temporal_match")
        matched_keys.extend(shared_temporal[:3])
        score_boost += 0.015
    if not reasons:
        return None
    return QueryAnchorMatch(
        score_boost=min(0.045, round(score_boost, 4)),
        reasons=tuple(_bounded_unique(reasons)),
        matched_keys=tuple(_bounded_unique(matched_keys, limit=8)),
    )


def _anchor_identity_keys(anchor: MemoryAnchor) -> frozenset[str]:
    keys: set[str] = set()
    for key in (
        "canonical_key",
        "person_canonical_key",
        "project_canonical_key",
        "organization_canonical_key",
        "identity_key",
    ):
        keys.update(_metadata_identity_terms(anchor.metadata.get(key)))
    keys.add(canonical_anchor_key_for_kind(anchor.kind, anchor.label))
    for alias in anchor.aliases:
        keys.add(canonical_anchor_key_for_kind(anchor.kind, alias))
    if anchor.normalized_key:
        keys.add(canonical_anchor_key_for_kind(anchor.kind, anchor.normalized_key))
    if anchor.kind == MemoryAnchorKind.PROJECT:
        keys.update(_project_key_aliases(tuple(keys)))
    value = anchor.metadata.get("event_identity_terms")
    if isinstance(value, list | tuple):
        for item in value:
            keys.update(_metadata_identity_terms(item))
    value = anchor.metadata.get("alias_identity_terms")
    if isinstance(value, list | tuple):
        for item in value:
            keys.update(_metadata_identity_terms(item))
    return frozenset(key for key in keys if key)


def _observed_anchor_identity_keys(anchor: ObservedAnchor) -> frozenset[str]:
    keys: set[str] = set()
    keys.update(_metadata_identity_terms(anchor.metadata.get("canonical_key")))
    keys.add(canonical_anchor_key_for_kind(anchor.kind, anchor.label))
    keys.add(canonical_anchor_key_for_kind(anchor.kind, anchor.normalized_key))
    for alias in anchor.aliases:
        keys.add(canonical_anchor_key_for_kind(anchor.kind, alias))
    value = anchor.metadata.get("alias_identity_terms")
    if isinstance(value, list | tuple):
        for item in value:
            keys.update(_metadata_identity_terms(item))
    if anchor.kind == MemoryAnchorKind.PROJECT:
        keys.update(_project_key_aliases(tuple(keys)))
    return frozenset(key for key in keys if key)


def _observed_anchor_conflicts_intent(
    intent: QueryAnchorIntent,
    anchors: tuple[ObservedAnchor, ...],
    *,
    text: str,
) -> bool:
    tool_project_query = _has_only_tool_project_hints(intent)
    for kind in (
        MemoryAnchorKind.PERSON,
        MemoryAnchorKind.PROJECT,
        MemoryAnchorKind.ORGANIZATION,
    ):
        query_keys = intent.keys_for_kind(kind)
        if not query_keys:
            continue
        if kind == MemoryAnchorKind.PROJECT and tool_project_query:
            continue
        observed_keys: set[str] = set()
        for anchor in anchors:
            if anchor.kind == kind:
                observed_keys.update(_observed_anchor_identity_keys(anchor))
        if observed_keys and not _compatible_identity_matches(observed_keys, query_keys):
            return True
    event_anchors = tuple(anchor for anchor in anchors if anchor.kind == MemoryAnchorKind.EVENT)
    if event_anchors:
        observed_temporal_keys: set[str] = set()
        observed_event_type_keys: set[str] = set()
        for anchor in event_anchors:
            observed_temporal_keys.update(_temporal_identity_keys(anchor.metadata))
            observed_event_type_keys.update(_event_type_identity_keys(anchor.metadata))
        if (
            not _is_broad_activity_event_query(intent)
            and _event_type_keys_conflict(
                query_event_type_keys=intent.event_type_keys(),
                anchor_event_type_keys=frozenset(observed_event_type_keys),
            )
            and not _is_relocation_origin_evidence_text(intent, text)
        ):
            return True
        if (
            _temporal_keys_conflict(
                query_temporal_keys=intent.temporal_keys(),
                anchor_temporal_keys=frozenset(observed_temporal_keys),
            )
            and not _is_relocation_origin_evidence_text(intent, text)
        ):
            return True
    return False


def _has_only_tool_project_hints(intent: QueryAnchorIntent) -> bool:
    project_hints = tuple(
        hint for hint in intent.hints if hint.kind == MemoryAnchorKind.PROJECT
    )
    return bool(project_hints) and all(
        hint.reason == "known project/tool reference" for hint in project_hints
    )


def _is_relocation_origin_evidence_text(intent: QueryAnchorIntent, text: str) -> bool:
    """Origin snippets often answer relocation questions without repeating the date."""

    if "group:relocation" not in intent.event_type_keys():
        return False
    return bool(_RELOCATION_ORIGIN_EVIDENCE_RE.search(str(text)[:2000]))


def _is_broad_activity_event_query(intent: QueryAnchorIntent) -> bool:
    """Activity list questions often describe events with indirect verbs in evidence text."""

    return "group:activity" in intent.event_type_keys()


def _event_anchor_conflicts_intent(
    intent: QueryAnchorIntent,
    anchor: MemoryAnchor,
) -> bool:
    person_keys = intent.keys_for_kind(MemoryAnchorKind.PERSON)
    project_keys = intent.keys_for_kind(MemoryAnchorKind.PROJECT)
    temporal_keys = intent.temporal_keys()
    event_type_keys = intent.event_type_keys()
    anchor_person = _metadata_text(anchor.metadata.get("event_participant_canonical_key"))
    anchor_project = _metadata_text(
        anchor.metadata.get("event_project_canonical_key")
        or anchor.metadata.get("project_canonical_key")
    )
    anchor_temporal_keys = _temporal_identity_keys(anchor.metadata)
    anchor_event_type_keys = _event_type_identity_keys(anchor.metadata)
    if person_keys and not _identity_term_variants(anchor_person).intersection(person_keys):
        return True
    if project_keys and not _compatible_identity_matches(
        _identity_term_variants(anchor_project),
        project_keys,
    ):
        return True
    if _event_type_keys_conflict(
        query_event_type_keys=event_type_keys,
        anchor_event_type_keys=anchor_event_type_keys,
    ):
        return True
    return _temporal_keys_conflict(
        query_temporal_keys=temporal_keys,
        anchor_temporal_keys=anchor_temporal_keys,
    )


def _event_type_identity_keys(metadata: Mapping[str, object]) -> frozenset[str]:
    if _metadata_text(metadata.get("extraction_reason")) == "event query temporal hint":
        return frozenset()
    event_type = _metadata_text(metadata.get("event_type_canonical") or metadata.get("event_type"))
    if not event_type:
        return frozenset()
    keys = {event_type}
    if group := _EVENT_TYPE_TO_GROUP.get(event_type):
        keys.add(f"group:{group}")
    return frozenset(keys)


def _event_type_keys_conflict(
    *,
    query_event_type_keys: frozenset[str],
    anchor_event_type_keys: frozenset[str],
) -> bool:
    if not query_event_type_keys or not anchor_event_type_keys:
        return False
    query_groups = {key for key in query_event_type_keys if key.startswith("group:")}
    anchor_groups = {key for key in anchor_event_type_keys if key.startswith("group:")}
    if query_groups and anchor_groups:
        if _event_type_groups_are_compatible(
            query_event_type_keys=query_event_type_keys,
            anchor_groups=frozenset(anchor_groups),
        ):
            return False
        return not query_groups.intersection(anchor_groups)
    return False


def _event_type_groups_are_compatible(
    *,
    query_event_type_keys: frozenset[str],
    anchor_groups: frozenset[str],
) -> bool:
    if query_event_type_keys.intersection(_BROAD_CONVERSATION_EVENT_TYPES):
        return bool(anchor_groups.intersection(_CONVERSATIONAL_EVENT_GROUP_KEYS))
    return False


def _storage_lookup_key_variants(
    kind: MemoryAnchorKind,
    value: str,
) -> tuple[str, ...]:
    normalized = normalize_anchor_key(value)
    if not normalized:
        return ()
    variants = [normalized]
    if kind == MemoryAnchorKind.PERSON:
        variants.append(
            " ".join(normalize_cyrillic_person_case(part) for part in normalized.split() if part)
        )
    elif kind == MemoryAnchorKind.PROJECT:
        variants.append(
            " ".join(normalize_cyrillic_project_case(part) for part in normalized.split() if part)
        )
    return tuple(_bounded_unique(variants, limit=4))


def _temporal_identity_keys(metadata: Mapping[str, object]) -> frozenset[str]:
    keys: set[str] = set()
    keys.update(
        _event_time_identity_keys(
            metadata,
            hint_key="event_temporal_hint_code",
            quantity_key="event_temporal_quantity",
            unit_key="event_temporal_unit",
        )
    )
    keys.update(
        _event_time_identity_keys(
            metadata,
            hint_key="event_duration_hint_code",
            quantity_key="event_duration_quantity",
            unit_key="event_duration_unit",
        )
    )
    keys.update(
        _event_time_identity_keys(
            metadata,
            hint_key="event_recurrence_hint_code",
            quantity_key="event_recurrence_quantity",
            unit_key="event_recurrence_unit",
        )
    )
    return frozenset(keys)


def _event_time_identity_keys(
    metadata: Mapping[str, object],
    *,
    hint_key: str,
    quantity_key: str,
    unit_key: str,
) -> frozenset[str]:
    hint_code = _metadata_text(metadata.get(hint_key))
    if not hint_code:
        return frozenset()
    quantity = _metadata_text(metadata.get(quantity_key))
    unit = _metadata_text(metadata.get(unit_key))
    keys = {hint_code}
    if quantity and unit:
        keys.add(f"{hint_code}:{quantity}:{unit}")
    value = metadata.get("event_identity_terms")
    if isinstance(value, list | tuple):
        for item in value:
            text = _metadata_text(item)
            if text.startswith(f"{hint_code}:"):
                keys.add(text)
    return frozenset(keys)


def _event_temporal_keys(hints: Iterable[QueryAnchorHint]) -> frozenset[str]:
    keys: set[str] = set()
    for hint in hints:
        if hint.kind == MemoryAnchorKind.EVENT:
            keys.update(_temporal_identity_keys(hint.metadata))
    return frozenset(keys)


def _temporal_keys_conflict(
    *,
    query_temporal_keys: frozenset[str],
    anchor_temporal_keys: frozenset[str],
) -> bool:
    if not query_temporal_keys:
        return False
    if "relative_recent" in anchor_temporal_keys:
        return False
    if _exact_cadence_or_duration_mismatch(query_temporal_keys, anchor_temporal_keys):
        return True
    return not anchor_temporal_keys.intersection(query_temporal_keys)


def _exact_cadence_or_duration_mismatch(
    query_temporal_keys: frozenset[str],
    anchor_temporal_keys: frozenset[str],
) -> bool:
    query_exact = _exact_cadence_or_duration_keys(query_temporal_keys)
    anchor_exact = _exact_cadence_or_duration_keys(anchor_temporal_keys)
    if not query_exact or not anchor_exact:
        return False
    for code in {key.split(":", 1)[0] for key in query_exact}.intersection(
        key.split(":", 1)[0] for key in anchor_exact
    ):
        query_for_code = {key for key in query_exact if key.startswith(f"{code}:")}
        anchor_for_code = {key for key in anchor_exact if key.startswith(f"{code}:")}
        if query_for_code and anchor_for_code and not query_for_code.intersection(anchor_for_code):
            return True
    return False


def _exact_cadence_or_duration_keys(keys: frozenset[str]) -> frozenset[str]:
    prefixes = (
        "duration_for:",
        "duration_since_year:",
        "recurrence_every:",
        "recurrence_per:",
    )
    return frozenset(key for key in keys if key.startswith(prefixes))


def _metadata_identity_terms(value: object) -> tuple[str, ...]:
    text = _metadata_text(value)
    if not text:
        return ()
    if ":" in text:
        return tuple(
            _bounded_unique(
                (
                    text,
                    text.rsplit(":", 1)[-1],
                    *_identity_term_variants(text),
                    *_identity_term_variants(text.rsplit(":", 1)[-1]),
                )
            )
        )
    return tuple(_identity_term_variants(text))


def _identity_term_variants(value: str) -> frozenset[str]:
    text = _metadata_text(value)
    if not text:
        return frozenset()
    spaced = " ".join(part for part in text.replace("_", " ").split() if part)
    person_normalized = " ".join(
        normalize_cyrillic_person_case(part) for part in spaced.split() if part
    )
    project_normalized = " ".join(
        normalize_cyrillic_project_case(part) for part in spaced.split() if part
    )
    canonical = " ".join(canonical_token(part) for part in spaced.split() if part)
    person_canonical = " ".join(
        canonical_token(part) for part in person_normalized.split() if part
    )
    project_canonical = " ".join(
        canonical_token(part) for part in project_normalized.split() if part
    )
    return frozenset(
        term
        for term in (
            text,
            spaced,
            canonical,
            person_normalized,
            project_normalized,
            person_canonical,
            project_canonical,
        )
        if term
    )


def _compatible_identity_matches(
    anchor_keys: Iterable[str],
    query_keys: Iterable[str],
) -> tuple[str, ...]:
    anchor_set = frozenset(key for key in anchor_keys if key)
    query_set = frozenset(key for key in query_keys if key)
    exact = sorted(anchor_set.intersection(query_set))
    if exact:
        return tuple(exact[:8])
    matches: list[str] = []
    for anchor_key in sorted(anchor_set):
        for query_key in sorted(query_set):
            if _identity_key_prefix_compatible(anchor_key, query_key):
                matches.append(anchor_key)
                break
        if len(matches) >= 8:
            break
    return tuple(_bounded_unique(matches, limit=8))


def _identity_key_prefix_compatible(left: str, right: str) -> bool:
    left_parts = left.split()
    right_parts = right.split()
    if not left_parts or not right_parts:
        return False
    shorter, longer = (
        (left_parts, right_parts)
        if len(left_parts) <= len(right_parts)
        else (right_parts, left_parts)
    )
    if len(shorter) > len(longer):
        return False
    if longer[: len(shorter)] != shorter:
        return False
    return len(shorter) >= 2 or len(longer) <= 3


def _project_key_aliases(keys: tuple[str, ...]) -> frozenset[str]:
    aliases: set[str] = set()
    for key in keys:
        parts = key.split()
        if len(parts) >= 2 and parts[0] in {
            "project",
            "repo",
            "repository",
            "service",
            "проект",
        }:
            aliases.add(" ".join(parts[1:]))
    return frozenset(aliases)


def _is_eventish_query(query: str) -> bool:
    return bool(_EVENTISH_QUERY_RE.search(query) or _RELATIVE_TIME_RE.search(query))


def _metadata_text(value: object) -> str:
    if value is None:
        return ""
    return safe_metadata_text(str(value), limit=160).strip().casefold()


def _normalized(value: str) -> str:
    return value.casefold().replace("ё", "е").strip("._-:/#()[]{}")


def _bounded_unique(values: Iterable[str], *, limit: int = 12) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        safe = _metadata_text(value)
        if not safe or safe in seen:
            continue
        seen.add(safe)
        result.append(safe)
        if len(result) >= limit:
            break
    return result
