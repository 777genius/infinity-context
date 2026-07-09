"""Event, temporal, and conversation decomposition policies."""

from __future__ import annotations

import re

from infinity_context_core.application.context_query_intent import QueryAnchorIntent
from infinity_context_core.application.context_temporal_query import TemporalQueryIntent
from infinity_context_core.domain.entities import MemoryAnchorKind

_RUSSIAN_MESSAGE_EVENT_TERMS = frozenset(
    {
        "написал",
        "написала",
        "написали",
        "ответил",
        "ответила",
        "ответили",
        "сказал",
        "сказала",
        "сказали",
        "сообщил",
        "сообщила",
        "сообщили",
        "скинул",
        "скинула",
        "скинули",
        "прислал",
        "прислала",
        "прислали",
        "отправил",
        "отправила",
        "отправили",
    }
)

_EVENT_TERMS = frozenset(
    {
        "call",
        "chat",
        "chatted",
        "conversation",
        "demo",
        "discussed",
        "dm",
        "attend",
        "attended",
        "hike",
        "hiked",
        "hikes",
        "hiking",
        "join",
        "joined",
        "launch",
        "meeting",
        "message",
        "move",
        "moved",
        "moving",
        "relocate",
        "relocated",
        "relocation",
        "participate",
        "participated",
        "review",
        "spoke",
        "sync",
        "talk",
        "talked",
        "meet",
        "met",
        "went",
        "workshop",
        "звонок",
        "созвон",
        "созванивалась",
        "созванивались",
        "созванивался",
        "чат",
        "встреча",
        "демо",
        "переписка",
        "переписке",
        "переписки",
        "перепиской",
        "переписку",
        "переписывалась",
        "переписывались",
        "переписывался",
        "говорил",
        "говорила",
        "говорили",
        *_RUSSIAN_MESSAGE_EVENT_TERMS,
        "переезд",
        "переехал",
        "переехала",
        "переехали",
        "переезжал",
        "переезжала",
        "переезжали",
        "разговор",
        "ревью",
        "релиз",
        "созвона",
        "стендап",
    }
)

_RELOCATION_TERMS = frozenset(
    {
        "country",
        "from",
        "home",
        "lived",
        "move",
        "moved",
        "moving",
        "origin",
        "relocate",
        "relocated",
        "relocation",
        "where",
        "город",
        "дом",
        "жила",
        "жил",
        "жили",
        "из",
        "куда",
        "откуда",
        "переезд",
        "переехал",
        "переехала",
        "переехали",
        "переезжал",
        "переезжала",
        "переезжали",
        "страна",
    }
)

_RELOCATION_ACTION_TERMS = frozenset(
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

_RELOCATION_ORIGIN_TERMS = frozenset(
    {
        "city",
        "country",
        "from",
        "home",
        "lived",
        "origin",
        "where",
        "город",
        "дом",
        "жила",
        "жил",
        "жили",
        "из",
        "куда",
        "откуда",
        "страна",
    }
)

_NON_RELOCATION_FROM_CONTEXT_RE = re.compile(
    r"\bfrom\s+(?:[A-Za-z][A-Za-z]*(?:'s)?\s+){0,3}"
    r"(?:advice|article|book|email|message|recommendation|suggestion|story)\b",
    re.IGNORECASE,
)

_CONVERSATION_COUNTERPARTY_PROMPT_TERMS = frozenset(
    {
        "who",
        "whom",
        "кем",
        "кого",
        "кому",
        "кто",
    }
)

_CONVERSATION_COUNTERPARTY_ACTION_TERMS = frozenset(
    {
        "call",
        "called",
        "chat",
        "chatted",
        "conversation",
        "discuss",
        "discussed",
        "dm",
        "meet",
        "meeting",
        "met",
        "message",
        "messaged",
        "speak",
        "speaking",
        "spoke",
        "talk",
        "talked",
        "text",
        "texted",
        "общался",
        "общалась",
        "общались",
        "говорил",
        "говорила",
        "говорили",
        "переписка",
        "переписывался",
        "переписывалась",
        "переписывались",
        "разговаривал",
        "разговаривала",
        "разговаривали",
        "созвон",
    }
)

_RELATIVE_TIME_CONVERSATION_ACTION_TERMS = frozenset(
    {
        "call",
        "called",
        "chat",
        "chatted",
        "conversation",
        "discuss",
        "discussed",
        "dm",
        "message",
        "messaged",
        "said",
        "say",
        "speak",
        "speaking",
        "spoke",
        "talk",
        "talked",
        "tell",
        "text",
        "texted",
        "told",
    }
)

_RECOMMENDATION_SOURCE_TERMS = frozenset(
    {
        "advice",
        "advise",
        "advised",
        "recommend",
        "recommendation",
        "recommended",
        "suggest",
        "suggested",
        "suggestion",
        "совет",
        "совета",
        "советом",
        "совету",
        "посоветовал",
        "посоветовала",
        "посоветовали",
        "посоветовать",
        "порекомендовал",
        "порекомендовала",
        "порекомендовали",
        "порекомендовать",
        "рекомендация",
        "рекомендации",
    }
)

_RECOMMENDATION_PROVENANCE_TERMS = frozenset(
    {
        "because",
        "follow",
        "followed",
        "from",
        "read",
        "recipient",
        "source",
        "to",
        "tried",
        "use",
        "used",
        "watched",
        "who",
        "whom",
        "whose",
        "из-за",
        "кому",
        "кто",
        "по",
        "прочитал",
        "прочитала",
        "прочитали",
        "чей",
        "чьему",
    }
)

_DEADLINE_TERMS = frozenset(
    {
        "deadline",
        "deadlines",
        "deliverable",
        "deliverables",
        "due",
        "milestone",
        "milestones",
        "overdue",
        "schedule",
        "scheduled",
        "target",
        "timeline",
        "upcoming",
        "дедлайн",
        "дедлайны",
        "просрочен",
        "просрочена",
        "просрочено",
        "просроченные",
        "срок",
        "сроки",
    }
)

_FOLLOWUP_TASK_TERMS = frozenset(
    {
        "action",
        "assigned",
        "assignee",
        "assignees",
        "agreed",
        "commitment",
        "commitments",
        "committed",
        "followup",
        "own",
        "owner",
        "owns",
        "promise",
        "promised",
        "promises",
        "remind",
        "reminder",
        "reminders",
        "responsibility",
        "responsible",
        "task",
        "tasks",
        "todo",
        "todos",
        "ответственный",
        "ответственная",
        "ответственные",
        "задача",
        "задачи",
        "обещал",
        "обещала",
        "назначено",
        "назначил",
        "назначила",
        "напомни",
        "напоминание",
        "напоминания",
        "поручение",
        "поручения",
    }
)

def _has_event_focus(
    anchor_intent: QueryAnchorIntent,
    variants: frozenset[str],
) -> bool:
    return bool(
        variants.intersection(_EVENT_TERMS)
        or anchor_intent.keys_for_kind(MemoryAnchorKind.EVENT)
        or anchor_intent.event_type_keys()
    )

def _requests_lgbtq_event_slot_aggregation(variants: frozenset[str]) -> bool:
    return bool(
        variants.intersection({"lgbtq", "queer"})
        and variants.intersection(
            {"event", "events", "attend", "attended", "participate", "participated"}
        )
    )

def _event_sequence_tail(intent: TemporalQueryIntent) -> str:
    event_prefix = " ".join(intent.event_sequence_terms)
    if intent.after_event and not intent.before_event:
        tail = (
            "after following later next timeline outcome follow up decision "
            "result happened then response meeting call chat message conversation event"
        )
    elif intent.before_event and not intent.after_event:
        tail = (
            "before earlier prior previous timeline context lead up reason "
            "setup happened meeting call chat message conversation event"
        )
    else:
        tail = (
            "before after timeline sequence earlier later prior next meeting call message "
            "conversation event outcome context"
        )
    return f"{event_prefix} {tail}".strip()

def _requests_followup_task_context(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if "workflow_commitment_request" in variants:
        return True
    if {"action", "item"}.issubset(variants) or {"follow", "up"}.issubset(raw_tokens):
        return True
    return bool(variants.intersection(_FOLLOWUP_TASK_TERMS))

def _requests_conversation_counterparty(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if not (
        raw_tokens.intersection(_CONVERSATION_COUNTERPARTY_PROMPT_TERMS)
        or variants.intersection(_CONVERSATION_COUNTERPARTY_PROMPT_TERMS)
    ):
        return False
    return bool(variants.intersection(_CONVERSATION_COUNTERPARTY_ACTION_TERMS))

def _requests_relative_time_conversation_recency(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
    temporal_intent: TemporalQueryIntent,
) -> bool:
    return bool(
        temporal_intent.relative_time_hints
        and (
            raw_tokens.intersection(_RELATIVE_TIME_CONVERSATION_ACTION_TERMS)
            or variants.intersection(_RELATIVE_TIME_CONVERSATION_ACTION_TERMS)
            or raw_tokens.intersection(_RUSSIAN_MESSAGE_EVENT_TERMS)
            or variants.intersection(_RUSSIAN_MESSAGE_EVENT_TERMS)
        )
    )

def _conversation_recency_tail(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> str:
    if raw_tokens.intersection(_RUSSIAN_MESSAGE_EVENT_TERMS) or variants.intersection(
        _RUSSIAN_MESSAGE_EVENT_TERMS
    ):
        return (
            "latest recent newest current today yesterday hours ago temporal event "
            "conversation call meeting chat dm message написал ответил сказал сообщил "
            "скинул прислал отправил talked spoke discussed transcript turn topic "
            "subject agenda outcome"
        )
    return (
        "latest recent newest current conversation call meeting chat dm "
        "message talked spoke discussed transcript turn topic subject "
        "agenda outcome today yesterday hours ago temporal event"
    )

def _requests_recommendation_source_context(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if not variants.intersection(_RECOMMENDATION_SOURCE_TERMS):
        return False
    return bool(
        raw_tokens.intersection(_RECOMMENDATION_PROVENANCE_TERMS)
        or variants.intersection(_RECOMMENDATION_PROVENANCE_TERMS)
    )

def _requests_relocation_context(*, query: str, variants: frozenset[str]) -> bool:
    if not variants.intersection(_RELOCATION_TERMS):
        return False
    if _NON_RELOCATION_FROM_CONTEXT_RE.search(query):
        return False
    if _requests_relocation_destination_only(variants=variants):
        return False
    if variants.intersection(_RELOCATION_ACTION_TERMS):
        return True
    if "откуда" in variants:
        return True
    origin_terms = variants.intersection(_RELOCATION_ORIGIN_TERMS)
    if {"where", "from"}.issubset(origin_terms):
        return True
    if "from" in variants and origin_terms.intersection({"home", "country", "city"}):
        return True
    if origin_terms.intersection({"home", "lived", "origin"}):
        return True
    if origin_terms.intersection({"дом", "жила", "жил", "жили"}):
        return True
    return bool(
        variants.intersection({"из", "откуда"})
        and origin_terms.intersection({"город", "страна"})
    )

def _requests_relocation_destination_only(*, variants: frozenset[str]) -> bool:
    if not variants.intersection(_RELOCATION_ACTION_TERMS):
        return False
    if variants.intersection({"from", "откуда", "из"}):
        return False
    return _requests_relocation_destination_context(variants=variants)

def _requests_relocation_destination_context(*, variants: frozenset[str]) -> bool:
    if not variants.intersection(_RELOCATION_ACTION_TERMS):
        return False
    if "куда" in variants:
        return True
    return bool({"where", "to"}.issubset(variants))
