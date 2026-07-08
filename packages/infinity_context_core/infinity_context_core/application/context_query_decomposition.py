"""Deterministic decomposition of compound memory queries."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from infinity_context_core.application.context_answer_unit_shapes import (
    requested_answer_unit_shapes,
)
from infinity_context_core.application.context_conversation_counterparty import (
    requests_conversation_recency,
    requests_conversation_topic,
)
from infinity_context_core.application.context_english_temporal_dates import (
    english_textual_month_year_terms,
)
from infinity_context_core.application.context_lexical import query_terms
from infinity_context_core.application.context_query_duration import (
    activity_duration_tail,
    requests_activity_duration_context,
)
from infinity_context_core.application.context_query_frequency import (
    frequency_recurrence_tail,
    requests_frequency_recurrence_context,
)
from infinity_context_core.application.context_query_intent import (
    QueryAnchorIntent,
    build_query_anchor_intent,
)
from infinity_context_core.application.context_query_state_transition import (
    state_transition_query_variants,
)
from infinity_context_core.application.context_query_support_role import (
    requests_support_role_fit,
    support_role_query_variants,
)
from infinity_context_core.application.context_query_workflow_intent import (
    gotcha_failure_query_variants,
    workflow_commitment_query_variants,
)
from infinity_context_core.application.context_temporal_query import (
    TemporalQueryIntent,
    build_temporal_query_intent,
)
from infinity_context_core.domain.entities import MemoryAnchorKind

_MAX_DECOMPOSITIONS = 6
_MAX_QUERY_CHARS = 220
_MAX_IDENTITY_TERMS = 4
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_CLAUSE_SPLIT_RE = re.compile(
    r"(?:[;?!]+|,\s+|"
    r"\s+\b(?:and|also|then|plus)\b\s+"
    r"(?=(?:what|when|where|who|why|how|which|did|does|do|is|are|was|were|"
    r"can|could|should|would|will)\b)|"
    r"\s+\b(?:и|также|потом|затем)\b\s+"
    r"(?=(?:что|когда|где|кто|почему|как|какая|какие|какой|куда|откуда)\b))",
    re.IGNORECASE,
)
_QUESTION_STOPWORDS = frozenset(
    {
        "are",
        "can",
        "could",
        "did",
        "does",
        "how",
        "is",
        "may",
        "might",
        "should",
        "the",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "would",
        "где",
        "зачем",
        "как",
        "какая",
        "какие",
        "какой",
        "когда",
        "кто",
        "почему",
        "что",
        "куда",
        "откуда",
    }
)
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
_ARTIFACT_TERMS = frozenset(
    {
        "artifact",
        "attachment",
        "audio",
        "document",
        "file",
        "image",
        "photo",
        "picture",
        "recording",
        "screenshot",
        "video",
        "артефакт",
        "аудио",
        "видео",
        "вложение",
        "запись",
        "документ",
        "изображение",
        "картинка",
        "скриншот",
        "файл",
        "фото",
    }
)
_SOURCE_TERMS = frozenset(
    {
        "citation",
        "citations",
        "evidence",
        "file",
        "proof",
        "provenance",
        "quote",
        "quoted",
        "quotes",
        "reference",
        "references",
        "source",
        "sources",
        "доказательство",
        "источник",
        "источники",
        "ссылка",
        "ссылки",
        "файл",
        "цитата",
        "цитаты",
    }
)
_EMOTION_CAUSE_PROMPT_TERMS = frozenset(
    {
        "gave",
        "made",
        "why",
        "what",
        "как",
        "почему",
        "что",
    }
)
_EMOTION_CAUSE_STATE_TERMS = frozenset(
    {
        "accept",
        "accepted",
        "acceptance",
        "belong",
        "belonged",
        "belonging",
        "comfort",
        "comforted",
        "empower",
        "empowered",
        "empowering",
        "feel",
        "feeling",
        "felt",
        "home",
        "powerful",
        "pride",
        "proud",
        "sad",
        "sense",
        "upset",
        "welcome",
        "welcomed",
        "принят",
        "принята",
        "принятой",
        "почувствовал",
        "почувствовала",
        "почувствовали",
        "рядом",
        "своей",
        "свой",
    }
)
_NON_EMOTIONAL_ACCEPTANCE_CONTEXT_TERMS = frozenset(
    {
        "experience",
        "internship",
        "job",
        "position",
        "professional",
        "program",
        "role",
        "workshop",
    }
)
_INFERENCE_TERMS = frozenset(
    {
        "considered",
        "could",
        "infer",
        "inference",
        "likely",
        "might",
        "probably",
        "would",
        "вероятно",
        "вывод",
        "может",
        "мог",
        "могла",
        "похоже",
        "считается",
        "скорее",
    }
)
_COUNTERFACTUAL_TERMS = frozenset(
    {
        "would",
        "wouldn",
        "wouldnt",
        "бы",
    }
)
_COUNTERFACTUAL_EXPLICIT_TERMS = frozenset(
    {
        "hadn",
        "hadnt",
        "if",
        "without",
        "без",
        "если",
    }
)
_COUNTERFACTUAL_SUPPORT_TERMS = frozenset(
    {
        "accept",
        "accepted",
        "acceptance",
        "encourage",
        "encouraging",
        "help",
        "helping",
        "join",
        "joining",
        "support",
        "supportive",
        "welcome",
    }
)
_COMPARISON_TERMS = frozenset(
    {
        "between",
        "compare",
        "compared",
        "comparison",
        "interested",
        "less",
        "more",
        "prefer",
        "preference",
        "rather",
        "versus",
        "vs",
        "больше",
        "выбор",
        "интереснее",
        "лучше",
        "между",
        "меньше",
        "предпочел",
        "предпочла",
        "предпочитает",
        "сравни",
    }
)
_ATTRIBUTE_AGGREGATION_TERMS = frozenset(
    {
        "attend",
        "attended",
        "bought",
        "buy",
        "events",
        "instrument",
        "instruments",
        "items",
        "participate",
        "participated",
        "play",
        "plays",
        "share",
        "shared",
        "traits",
    }
)
_INVENTORY_LIST_SLOT_TERMS = frozenset(
    {
        "areas",
        "artists",
        "bands",
        "books",
        "causes",
        "cities",
        "countries",
        "country",
        "cake",
        "cakes",
        "dessert",
        "desserts",
        "dish",
        "dishes",
        "food",
        "foods",
        "frosting",
        "hobbies",
        "instruments",
        "items",
        "kinds",
        "meal",
        "meals",
        "people",
        "places",
        "projects",
        "recipe",
        "recipes",
        "shelter",
        "shelters",
        "sport",
        "sports",
        "states",
        "tasks",
        "things",
        "types",
        "volunteering",
        "виды",
        "вещи",
        "города",
        "места",
        "страна",
        "страны",
        "типы",
    }
)
_INVENTORY_LIST_ACTION_TERMS = frozenset(
    {
        "attend",
        "attended",
        "been",
        "bought",
        "buy",
        "done",
        "feel",
        "favorite",
        "favorites",
        "favourite",
        "favourites",
        "go",
        "gone",
        "had",
        "has",
        "have",
        "helped",
        "having",
        "enjoy",
        "enjoyed",
        "enjoys",
        "joined",
        "like",
        "liked",
        "likes",
        "love",
        "loved",
        "loves",
        "make",
        "made",
        "mention",
        "mentioned",
        "met",
        "participated",
        "planning",
        "played",
        "read",
        "seen",
        "support",
        "supporting",
        "taken",
        "use",
        "used",
        "visited",
        "volunteer",
        "volunteered",
        "went",
        "ездил",
        "ездила",
        "ездили",
        "посещал",
        "посещала",
        "посещали",
        "посетил",
        "посетила",
        "посетили",
        "сделал",
        "сделала",
        "сделали",
    }
)
_INVENTORY_LIST_PROMPT_TERMS = frozenset(
    {
        "what",
        "where",
        "which",
        "где",
        "какие",
        "какой",
        "какую",
        "какое",
        "что",
    }
)
_PEOPLE_INVENTORY_PROMPT_TERMS = frozenset(
    {
        "who",
        "whom",
        "кого",
        "кому",
        "кто",
    }
)
_PEOPLE_INVENTORY_ACTION_TERMS = frozenset(
    {
        "help",
        "helped",
        "helping",
        "meet",
        "met",
        "support",
        "supported",
        "supporting",
        "volunteer",
        "volunteered",
        "volunteering",
        "work",
        "worked",
        "working",
        "помог",
        "помогал",
        "помогала",
        "помогали",
        "поддержал",
        "поддержала",
        "поддержали",
        "работал",
        "работала",
        "работали",
    }
)
_SOCIAL_SUPPORT_ACTION_TERMS = frozenset(
    {
        "support",
        "supported",
        "supporting",
        "supports",
        "there",
        "rocks",
        "поддерживает",
        "поддерживал",
        "поддерживала",
        "поддержал",
        "поддержала",
        "поддержали",
        "рядом",
    }
)
_SOCIAL_SUPPORT_RELATION_TERMS = frozenset(
    {
        "coach",
        "family",
        "father",
        "friend",
        "friends",
        "mentor",
        "mentors",
        "mother",
        "parent",
        "parents",
        "rock",
        "rocks",
        "system",
        "друзья",
        "наставники",
        "родители",
        "семья",
    }
)
_TECHNICAL_SUPPORT_CONTEXT_TERMS = frozenset(
    {
        "api",
        "backend",
        "browser",
        "client",
        "cloud",
        "customer",
        "database",
        "frontend",
        "infra",
        "infrastructure",
        "integration",
        "library",
        "model",
        "platform",
        "provider",
        "runtime",
        "sdk",
        "service",
        "software",
        "technical",
        "tool",
        "tools",
        "web",
    }
)
_PLACE_INVENTORY_ACTION_TERMS = frozenset(
    {
        "been",
        "friend",
        "friends",
        "go",
        "gone",
        "made",
        "meet",
        "met",
        "vacation",
        "vacationed",
        "visited",
        "went",
    }
)
_COMMONALITY_TERMS = frozenset(
    {
        "both",
        "common",
        "mutual",
        "same",
        "shared",
        "similar",
        "оба",
        "обе",
        "общ",
        "общего",
        "общие",
        "похож",
    }
)
_QUANTITY_COUNT_TERMS = frozenset(
    {
        "count",
        "counts",
        "many",
        "much",
        "number",
        "quantity",
        "total",
        "сколько",
    }
)
_TEMPORAL_ANSWER_TERMS = frozenset(
    {
        "date",
        "day",
        "time",
        "when",
        "weekday",
        "дата",
        "день",
        "когда",
        "число",
    }
)
_KNOWLEDGE_UPDATE_ENTITY_TERMS = frozenset(
    {
        "choice",
        "database",
        "decision",
        "engine",
        "model",
        "option",
        "plan",
        "policy",
        "provider",
        "service",
        "source",
        "tool",
        "вариант",
        "движок",
        "инструмент",
        "модель",
        "план",
        "политика",
        "провайдер",
        "решение",
        "сервис",
    }
)
_KNOWLEDGE_UPDATE_DECISION_TERMS = frozenset(
    {
        "choose",
        "chosen",
        "chose",
        "decide",
        "decided",
        "pick",
        "picked",
        "prefer",
        "preferred",
        "recommend",
        "recommended",
        "select",
        "selected",
        "use",
        "выбрал",
        "выбрала",
        "выбрать",
        "использовать",
        "решил",
        "решила",
        "рекомендовал",
        "рекомендовала",
    }
)
_KNOWLEDGE_UPDATE_STRONG_DECISION_TERMS = (
    _KNOWLEDGE_UPDATE_DECISION_TERMS - frozenset({"use", "использовать"})
)
_KNOWLEDGE_UPDATE_CURRENT_STATE_TERMS = frozenset(
    {
        "active",
        "canonical",
        "current",
        "currently",
        "final",
        "latest",
        "newest",
        "recommended",
        "settled",
        "source",
        "still",
        "truth",
        "valid",
        "актуальная",
        "актуальное",
        "актуальные",
        "актуальный",
        "последнее",
        "последние",
        "последний",
        "последняя",
        "окончательн",
        "сейчас",
        "текущая",
        "текущее",
        "текущие",
        "текущий",
        "финальн",
        "финальное",
        "выбранный",
    }
)
_KNOWLEDGE_UPDATE_PROMPT_TERMS = frozenset(
    {
        "what",
        "which",
        "какая",
        "какие",
        "какой",
        "какую",
        "какое",
        "что",
    }
)
_KNOWLEDGE_UPDATE_PROMPT_ACTION_TERMS = frozenset(
    {
        "choose",
        "chosen",
        "chose",
        "pick",
        "picked",
        "select",
        "selected",
        "use",
        "выбрал",
        "выбрала",
        "выбрать",
        "использовать",
    }
)
_ACTIVITY_PARTICIPATION_TERMS = frozenset(
    {
        "activities",
        "activity",
        "hobbies",
        "hobby",
        "partake",
        "participate",
        "participates",
        "participated",
        "sport",
        "sports",
    }
)
_IDENTITY_ATTRIBUTE_TERMS = frozenset(
    {
        "gender",
        "identity",
        "pronouns",
        "trans",
        "transgender",
    }
)
_COMMUNITY_MEMBERSHIP_IDENTITY_TERMS = frozenset(
    {
        "lgbtq",
        "queer",
        "trans",
        "transgender",
    }
)
_COMMUNITY_MEMBERSHIP_QUERY_TERMS = frozenset(
    {
        "belong",
        "belonged",
        "belonging",
        "belongs",
        "identified",
        "identifies",
        "identify",
        "member",
        "members",
        "membership",
    }
)
_ALLY_SUPPORT_QUERY_TERMS = frozenset(
    {
        "allies",
        "ally",
        "support",
        "supporter",
        "supportive",
    }
)
_RELATIONSHIP_STATUS_TERMS = frozenset(
    {
        "breakup",
        "dating",
        "divorced",
        "friend",
        "friends",
        "married",
        "partner",
        "relationship",
        "single",
        "spouse",
        "status",
        "друг",
        "друга",
        "друзья",
        "отношения",
        "пара",
        "партнер",
        "партнеры",
        "партнёр",
        "партнёры",
        "связан",
        "связана",
        "связаны",
        "супруг",
        "супруга",
    }
)
_ACTION_ROLE_TERMS = frozenset(
    {
        "approve",
        "approved",
        "ask",
        "asked",
        "assign",
        "assigned",
        "call",
        "called",
        "decide",
        "decided",
        "decision",
        "give",
        "gave",
        "hear",
        "heard",
        "help",
        "helped",
        "assist",
        "assisted",
        "support",
        "supported",
        "introduce",
        "introduced",
        "introducing",
        "learn",
        "learned",
        "message",
        "messaged",
        "promise",
        "promised",
        "recommendation",
        "recommend",
        "recommended",
        "send",
        "sent",
        "suggestion",
        "tell",
        "text",
        "texted",
        "told",
        "назначил",
        "назначила",
        "одобрил",
        "одобрила",
        "познакомил",
        "познакомила",
        "познакомили",
        "пообещал",
        "пообещала",
        "представил",
        "представила",
        "представили",
        "рекомендовал",
        "рекомендовала",
        "решил",
        "решила",
        "сказал",
        "сказала",
        "спросил",
        "спросила",
        "помог",
        "помогла",
        "помогли",
        "поддержал",
        "поддержала",
        "поддержали",
        "узнал",
        "узнала",
        "узнали",
        "услышал",
        "услышала",
        "услышали",
    }
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
_COLLECTIBLE_OBJECT_TERMS = frozenset(
    {
        "collectible",
        "collectibles",
        "collection",
        "memorabilia",
        "keepsake",
        "keepsakes",
        "memento",
        "mementos",
        "souvenir",
        "souvenirs",
        "possession",
        "possessions",
        "object",
        "objects",
        "item",
        "items",
    }
)
_GOTCHA_FAILURE_TERMS = frozenset(
    {
        "blocked",
        "blocker",
        "broke",
        "broken",
        "caveat",
        "caveats",
        "error",
        "errors",
        "fail",
        "failed",
        "failure",
        "failures",
        "gotcha",
        "gotchas",
        "pitfall",
        "pitfalls",
        "problem",
        "problems",
        "risk",
        "risks",
        "trap",
        "traps",
        "warning",
        "warnings",
        "workaround",
        "workarounds",
        "воркэраунд",
        "избегать",
        "камни",
        "ошибка",
        "ошибки",
        "подводные",
        "проблема",
        "проблемы",
        "риск",
        "риски",
        "сломалось",
        "сбой",
    }
)
_CURRENT_GOAL_TERMS = frozenset(
    {
        "adopt",
        "adoption",
        "back",
        "career",
        "country",
        "future",
        "goal",
        "goals",
        "move",
        "moved",
        "moving",
        "open",
        "plan",
        "pursue",
        "soon",
        "want",
        "wants",
    }
)
_COUNTRY_DESTINATION_ACTION_TERMS = frozenset(
    {
        "go",
        "going",
        "meet",
        "meeting",
        "met",
        "see",
        "show",
        "stay",
        "staying",
        "tour",
        "travel",
        "traveled",
        "travelled",
        "traveling",
        "travelling",
        "trip",
        "visit",
        "visited",
        "visiting",
    }
)
_KIND_TYPE_DESCRIPTOR_TERMS = frozenset(
    {
        "kind",
        "kinds",
        "sort",
        "type",
        "types",
    }
)
_IMPACT_EFFECT_TERMS = frozenset(
    {
        "affect",
        "affected",
        "effect",
        "impact",
        "impacted",
        "influence",
        "influenced",
        "inspire",
        "inspired",
        "motivate",
        "motivated",
    }
)
_CONTENT_TOPIC_TERMS = frozenset(
    {
        "article",
        "articles",
        "blog",
        "blogging",
        "content",
        "focus",
        "post",
        "posts",
        "research",
        "share",
        "shared",
        "topic",
        "writing",
    }
)
_SPORT_TEAM_ATTRIBUTE_TERMS = frozenset(
    {
        "basketball",
        "coach",
        "contract",
        "franchise",
        "jersey",
        "jerseys",
        "player",
        "position",
        "roster",
        "school",
        "schools",
        "sport",
        "sports",
        "team",
        "teammates",
    }
)
_SALIENT_DROP_VARIANTS = frozenset(
    {
        *_QUESTION_STOPWORDS,
        *_INFERENCE_TERMS,
        "career",
        "consider",
        "considered",
        "does",
        "focus",
        "kind",
        "kinds",
        "option",
        "still",
        "topic",
        "type",
        "types",
    }
)
_MAX_SALIENT_TERMS = 5
_EVIDENCE_REASON_RE = re.compile(
    r"\b("
    r"why|reason|because|what evidence|which evidence|what shows|what showed|"
    r"what indicates|how do we know|how can we tell|how would we know|"
    r"почему|причин|потому что|какие доказательства|какое доказательство|"
    r"что показывает|что показало|как мы знаем|откуда известно"
    r")\b",
    re.IGNORECASE,
)
_ABSENCE_CONTRAST_RE = re.compile(
    r"\b(?:instead\s+of|rather\s+than|without)\b|"
    r"\b(?:did\s+not|didn'?t|never|not)\s+"
    r"(?:mention|mentioned|say|said|discuss|discussed)\b|"
    r"\b(?:не\s+упоминал\w*|не\s+говорил\w*|вместо|без)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QueryDecomposition:
    query: str
    reason: str


@dataclass(frozen=True)
class QueryDecompositionPlan:
    original_query: str
    decompositions: tuple[QueryDecomposition, ...]

    @property
    def empty(self) -> bool:
        return not self.decompositions

    def diagnostics(self) -> dict[str, object]:
        return {
            "query_decomposition_status": "empty" if self.empty else "available",
            "query_decomposition_count": len(self.decompositions),
            "query_decomposition_reasons": [item.reason for item in self.decompositions],
        }


def build_query_decomposition_plan(
    query: str,
    *,
    anchor_intent: QueryAnchorIntent | None = None,
    temporal_intent: TemporalQueryIntent | None = None,
) -> QueryDecompositionPlan:
    normalized_query = _normalize_query(query)
    if not normalized_query:
        return QueryDecompositionPlan(original_query=query, decompositions=())
    anchor_intent = anchor_intent or build_query_anchor_intent(query)
    temporal_intent = temporal_intent or build_temporal_query_intent(query)
    variants = _query_variant_set(query)
    variants = frozenset(
        (
            *variants,
            *gotcha_failure_query_variants(query),
            *state_transition_query_variants(query),
            *support_role_query_variants(query),
            *workflow_commitment_query_variants(query),
        )
    )
    raw_tokens = frozenset(_raw_query_tokens(query))
    identities = _identity_terms(query, anchor_intent)
    salient_terms = _salient_terms(query, identities=identities)
    requested_answer_units = frozenset(requested_answer_unit_shapes(query))
    requests_relocation_context = _requests_relocation_context(
        query=normalized_query,
        variants=variants,
    )
    requests_relocation_destination_context = _requests_relocation_destination_context(
        variants=variants,
    )
    requests_country_destination_context = _requests_country_destination_context(
        raw_tokens=raw_tokens,
        variants=variants,
    )
    candidates: list[QueryDecomposition] = []
    _append_clause_decompositions(candidates, query=query, identities=identities)
    if requests_country_destination_context:
        _append_candidate(
            candidates,
            query=_compose_query(
                (
                    *identities,
                    *salient_terms,
                    *english_textual_month_year_terms(query),
                ),
                (
                    "country city destination place trip travel visit meet meeting "
                    "show around town flight upcoming plan going headed see"
                ),
            ),
            reason="decomposition_country_destination",
        )
    if _has_event_focus(anchor_intent, variants) and not (
        requests_relocation_context or requests_relocation_destination_context
    ):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "event conversation meeting call chat message dm transcript "
                    "notes discussed mentioned decision action item follow up"
                ),
            ),
            reason="decomposition_event_context",
        )
    if _requests_lgbtq_event_slot_aggregation(variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "lgbtq pride parade pride march went attended participated "
                    "rainbow flags community belonged accepted happy equality"
                ),
            ),
            reason="decomposition_lgbtq_pride_event",
        )
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "lgbtq support group attended went transgender stories powerful "
                    "inspiring accepted courage embrace community"
                ),
            ),
            reason="decomposition_lgbtq_support_group_event",
        )
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "school event speech talk spoke gave transgender journey students "
                    "involved lgbtq community awareness inclusion"
                ),
            ),
            reason="decomposition_lgbtq_school_speech_event",
        )
    if requests_relocation_destination_context:
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "relocation moved move relocated to destination new current "
                    "home country city settled lives now timeline"
                ),
            ),
            reason="decomposition_relocation_destination",
        )
    if requests_relocation_context:
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "relocation moved move relocated from origin previous home "
                    "country city lived before timeline"
                ),
            ),
            reason="decomposition_relocation_context",
        )
    if temporal_intent.requests_change:
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "changed updated current previous before after superseded "
                    "replaced difference decision"
                ),
            ),
            reason="decomposition_temporal_change",
        )
    if _requests_state_transition_context(variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "state transition changed switched replaced migrated from to "
                    "previous old current new active final selected superseded "
                    "no longer valid replacement replaced by before after"
                ),
            ),
            reason="decomposition_state_transition",
        )
    if temporal_intent.after_event or temporal_intent.before_event:
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                _event_sequence_tail(temporal_intent),
            ),
            reason="decomposition_event_sequence",
        )
    if temporal_intent.relative_time_hints:
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "event temporal time window occurred capture transcript "
                    "notes meeting call chat message "
                    f"{' '.join(temporal_intent.relative_time_hints)}"
                ),
            ),
            reason="decomposition_relative_time",
        )
    if _requests_knowledge_update_current(
        variants=variants,
        temporal_intent=temporal_intent,
    ):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "current latest active final decided chose selected switched "
                    "recommended preferred should use provider tool model option "
                    "engine database service retrieval valid not stale superseded old"
                ),
            ),
            reason="decomposition_knowledge_update_current",
        )
    if _requests_knowledge_update_previous(
        query=normalized_query,
        variants=variants,
        temporal_intent=temporal_intent,
    ):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "previous old stale outdated superseded no longer valid "
                    "not current replaced deprecated expired before review"
                ),
            ),
            reason="decomposition_knowledge_update_previous",
        )
    if variants.intersection(_TEMPORAL_ANSWER_TERMS):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "when date day time session date weekday monday tuesday "
                    "wednesday thursday friday saturday sunday calendar occurred"
                ),
            ),
            reason="decomposition_temporal_answer",
        )
    if "quantity_dollar" in requested_answer_units:
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "amount cost price value dollars usd paid spent charged "
                    "fee deposit budget salary rent payment total exact number"
                ),
            ),
            reason="decomposition_value_answer",
        )
    if variants.intersection(_ARTIFACT_TERMS):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "artifact file screenshot image video audio document ocr "
                    "transcript detected text keyframe source"
                ),
            ),
            reason="decomposition_artifact_evidence",
        )
    if variants.intersection(_SOURCE_TERMS):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                "source citation evidence quote excerpt file artifact reference provenance",
            ),
            reason="decomposition_source_evidence",
        )
    if _requests_emotion_cause(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "feeling emotion felt feel accepted acceptance belonged belonging "
                    "sense of belonging at home community welcomed pride parade "
                    "support group powerful proud empowering school speech talk "
                    "journey upset sad comfort reason because event experience"
                ),
            ),
            reason="decomposition_emotion_cause",
        )
    if _requests_evidence_reason(query):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "reason evidence because observed mentioned showed indicates "
                    "supporting fact source citation quote explanation why"
                ),
            ),
            reason="decomposition_evidence_reason",
        )
    if _requests_gotcha_failure_context(variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "gotcha pitfall caveat known issue known problem failure "
                    "failed error broke blocked blocker risk warning workaround "
                    "root cause troubleshooting avoid do not repeat next time "
                    "prerequisite limitation trap"
                ),
            ),
            reason="decomposition_gotcha_failure",
        )
    if _requests_absence_contrast(query):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "mentioned did not mention absent instead rather than without "
                    "contrast alternative named pet cat dog hamster evidence"
                ),
            ),
            reason="decomposition_absence_contrast",
        )
    if _requests_community_membership_inference(variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "self identification identify identified identifies refers herself "
                    "himself themself as member part belong belongs belonging lgbtq "
                    "queer community pride accepted"
                ),
            ),
            reason="decomposition_community_membership_evidence",
        )
    requests_ally_support = _requests_ally_support_inference(variants=variants)
    if requests_ally_support:
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "ally allies supportive support acceptance encouraging kind words "
                    "rights inclusion respected transition transgender trans lgbtq "
                    "community care help advocated stood up"
                ),
            ),
            reason="decomposition_ally_support_evidence",
        )
    if raw_tokens.intersection(_IDENTITY_ATTRIBUTE_TERMS) and not requests_ally_support:
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "identity gender pronouns transgender trans woman transition "
                    "true self accepted belongs community support group pride"
                ),
            ),
            reason="decomposition_identity_attribute",
        )
    if _requests_relationship_status(
        raw_tokens=raw_tokens,
        variants=variants,
        identities=identities,
    ):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "relationship status single parent not dating breakup divorced "
                    "separated partner spouse husband wife married dating romantic "
                    "отношения статус друзья дружба партнер супруг семья вместе"
                ),
            ),
            reason="decomposition_relationship_status",
        )
        if raw_tokens.intersection({"friend", "friends", "друг", "друзья", "дружба"}):
            _append_candidate(
                candidates,
                query=_compose_query(
                    (*identities, *salient_terms),
                    "relationship status friends friendship dating partner family",
                ),
                reason="decomposition_clause",
            )
    if variants.intersection(_ACTION_ROLE_TERMS):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "decision decided promised promise recommendation recommended "
                    "asked assigned approved sent gave told actor recipient speaker "
                    "dialogue quote transcript outcome commitment next step"
                ),
            ),
            reason="decomposition_action_role",
        )
    if _requests_conversation_counterparty(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "conversation counterparty participant with to from talked spoke "
                    "met called messaged texted chatted discussed dm meeting call "
                    "speaker recipient person name about project topic"
                ),
            ),
            reason="decomposition_conversation_counterparty",
        )
    if requests_conversation_recency(query) or _requests_relative_time_conversation_recency(
        raw_tokens=raw_tokens,
        variants=variants,
        temporal_intent=temporal_intent,
    ):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                _conversation_recency_tail(raw_tokens=raw_tokens, variants=variants),
            ),
            reason="decomposition_conversation_recency",
        )
    if requests_conversation_topic(query):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "conversation topic subject about discussed talked spoke chatted "
                    "agenda context project decision plan issue question outcome "
                    "speaker turn transcript"
                ),
            ),
            reason="decomposition_conversation_topic",
        )
    if _requests_recommendation_source_context(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "recommendation suggestion advice recommended suggested advised "
                    "recommend it definitely would source actor recipient to from "
                    "because of who whom whose should get should start for one "
                    "also another pointers tips ideas how about make sure "
                    "invest in look for great one good one followed read watched "
                    "tried used provenance try buy visit play make"
                ),
            ),
            reason="decomposition_recommendation_source",
        )
    if variants.intersection(_DEADLINE_TERMS):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "deadline due date target date schedule milestone timeline "
                    "deliverable overdue upcoming commitment action item follow up "
                    "meeting call decision promised agreed"
                ),
            ),
            reason="decomposition_deadline_commitment",
        )
    if _requests_followup_task_context(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "action item task todo follow up next step reminder assigned "
                    "owner responsible assignee commitment promised due date deadline "
                    "meeting call decision status"
                ),
            ),
            reason="decomposition_followup_task",
        )
    if _requests_counterfactual_evidence(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "counterfactual hypothetical would likely past behavior "
                    "preference trait supporting evidence observed mentioned "
                    "enjoyed disliked avoided interested supportive acceptance "
                    "similar situation"
                ),
            ),
            reason="decomposition_counterfactual_evidence",
        )
    if requests_support_role_fit(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "support role fit mentor mentoring guidance advice coach "
                    "volunteer counseling counselor listened comfort empathy "
                    "patient helped accepted safe trust similar issues reliable "
                    "responsible care confide confided open opened opening private "
                    "sensitive personal anxiety struggles"
                ),
            ),
            reason="decomposition_support_role_fit",
        )
    if variants.intersection(_INFERENCE_TERMS):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "inference supporting evidence likely would considered "
                    "observed mentioned indicates preference trait decision reason "
                    "support supportive encouraging acceptance care help"
                ),
            ),
            reason="decomposition_inference_support",
        )
        if _requests_inference_current_preference_or_goal(
            raw_tokens=raw_tokens,
            variants=variants,
        ):
            _append_candidate(
                candidates,
                query=_compose_query(
                    (*identities, *salient_terms),
                    (
                        "current goal future plan next steps figure out wants decided "
                        "committed lease contract signed stay local job role school "
                        "program semester deadline career option counseling counselor "
                        "mental health jobs preference interested recently now "
                        "adoption family children kids home roof agency interview "
                        "build career activity service country office military move back soon"
                    ),
                ),
                reason="decomposition_current_preference_or_goal",
            )
    if _requests_non_inference_career_goal(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "current career path goal decided pursue education options "
                    "counseling counselor mental health jobs work career option "
                    "next steps figure out looking into"
                ),
            ),
            reason="decomposition_current_preference_or_goal",
        )
    if _requests_comparison_preference(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                identities,
                (
                    "comparison preference choice option alternative likes dislikes "
                    "interested more less rather prefer similar difference evidence"
                ),
            ),
            reason="decomposition_comparison_preference",
        )
    if _requests_activity_participation(raw_tokens=raw_tokens, variants=variants):
        activity_terms = (
            "activities hobbies activity partake participate observed "
            "painting swimming swim pottery class camping running creative "
            "outdoors exercise family kids fam weekend unplug hang therapy therapeutic"
        )
        sport_terms = (
            "sports sport game team court scored surfing surfboard waves "
            "position jersey jerseys season opener"
        )
        if variants.intersection(
            {
                "basketball",
                "game",
                "games",
                "sport",
                "sports",
                "surf",
                "surfing",
            }
        ):
            activity_tail = (
                f"activities hobbies activity partake participate observed {sport_terms} "
                f"{activity_terms} photo picture image visual query take look"
            )
        else:
            activity_tail = (
                f"{activity_terms} {sport_terms} "
                "photo picture image visual query take look"
            )
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                activity_tail,
            ),
            reason="decomposition_activity_participation",
        )
    if _requests_sport_team_attribute(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "sports team basketball position jersey school high school "
                    "signed sign contract roster club franchise teammate teammates "
                    "coach coaching point guard forward center years season trip "
                    "travel tournament game played"
                ),
            ),
            reason="decomposition_sport_team_attribute",
        )
    if _requests_inventory_list_context(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                _inventory_list_tail(variants),
            ),
            reason="decomposition_inventory_list",
        )
    if _requests_kind_type_descriptor_context(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "kind type category genre style form format descriptor described "
                    "called named specific exact what kind what type answer evidence"
                ),
            ),
            reason="decomposition_kind_type_descriptor",
        )
    if _requests_impact_effect_context(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "impact effect affected influenced inspired motivated helped "
                    "changed perspective changed life positive impact made a difference "
                    "response outcome result people readers community homes"
                ),
            ),
            reason="decomposition_impact_effect",
        )
    if _requests_content_topic_context(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "content topic focus blog post article writing research shared "
                    "posted wrote about online projects story stories youtube video "
                    "channel readers letter response inspired"
                ),
            ),
            reason="decomposition_content_topic",
        )
    if _requests_commonality_context(identities=identities, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "common shared both mutual same similar overlap interests hobbies "
                    "activities enjoy like love prefer painting camping hiking music "
                    "books games food art evidence"
                ),
            ),
            reason="decomposition_commonality",
        )
    if _requests_collectible_object_context(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "collectible memorabilia keepsake memento possession object "
                    "own owned signed autographed autograph reminder bond friendship "
                    "appreciation gift received teammates friends favorite player "
                    "ball jersey trophy card photo"
                ),
            ),
            reason="decomposition_collectible_object",
        )
    if requests_activity_duration_context(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                activity_duration_tail(variants),
            ),
            reason="decomposition_activity_duration",
        )
    if variants.intersection(_QUANTITY_COUNT_TERMS):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                (
                    "count number total quantity amount many much times "
                    "one two three four five six seven eight nine ten "
                    "once twice couple several multiple"
                ),
            ),
            reason="decomposition_quantity_count",
        )
    if requests_frequency_recurrence_context(raw_tokens=raw_tokens, variants=variants):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                frequency_recurrence_tail(variants),
            ),
            reason="decomposition_frequency_recurrence",
        )
    if variants.intersection(_ATTRIBUTE_AGGREGATION_TERMS) and not variants.intersection(
        _QUANTITY_COUNT_TERMS
    ):
        _append_candidate(
            candidates,
            query=_compose_query(
                (*identities, *salient_terms),
                _attribute_aggregation_tail(variants),
            ),
            reason="decomposition_attribute_aggregation",
        )
    return QueryDecompositionPlan(
        original_query=query,
        decompositions=tuple(candidates[:_MAX_DECOMPOSITIONS]),
    )


def _append_clause_decompositions(
    candidates: list[QueryDecomposition],
    *,
    query: str,
    identities: tuple[str, ...],
) -> None:
    normalized_query_key = _query_dedupe_key(query)
    for raw_clause in _CLAUSE_SPLIT_RE.split(query):
        clause = _clean_clause_query(raw_clause)
        if not _is_useful_clause(clause):
            continue
        clause_query = _with_missing_identities(clause, identities)
        if _query_dedupe_key(clause_query) == normalized_query_key:
            continue
        _append_candidate(
            candidates,
            query=clause_query,
            reason="decomposition_clause",
        )


def _append_candidate(
    candidates: list[QueryDecomposition],
    *,
    query: str,
    reason: str,
) -> None:
    normalized_query = _normalize_query(query)
    if not normalized_query:
        return
    key = _query_dedupe_key(normalized_query)
    if any(
        _query_dedupe_key(item.query) == key
        or (item.reason == reason and reason != "decomposition_clause")
        for item in candidates
    ):
        return
    candidates.append(
        QueryDecomposition(
            query=_truncate_query(normalized_query),
            reason=reason,
        )
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


def _requests_community_membership_inference(*, variants: frozenset[str]) -> bool:
    return bool(
        variants.intersection(_COMMUNITY_MEMBERSHIP_IDENTITY_TERMS)
        and variants.intersection(_COMMUNITY_MEMBERSHIP_QUERY_TERMS)
    )


def _requests_ally_support_inference(*, variants: frozenset[str]) -> bool:
    return bool(
        variants.intersection(_ALLY_SUPPORT_QUERY_TERMS)
        and variants.intersection(_COMMUNITY_MEMBERSHIP_IDENTITY_TERMS)
    )


def _compose_query(
    identities: Sequence[str],
    tail: str,
) -> str:
    return _normalize_query(" ".join((*identities, tail)))


def _salient_terms(query: str, *, identities: tuple[str, ...]) -> tuple[str, ...]:
    identity_keys = {identity.casefold() for identity in identities}
    terms: list[str] = []
    seen: set[str] = set()
    for term in query_terms(query, min_chars=3, max_terms=18):
        variants = frozenset(term.variants)
        raw = _normalize_identity_term(term.raw)
        if not raw:
            continue
        key = raw.casefold()
        if key in seen or key in identity_keys:
            continue
        if variants.intersection(_SALIENT_DROP_VARIANTS):
            continue
        terms.append(raw)
        seen.add(key)
        if len(terms) >= _MAX_SALIENT_TERMS:
            break
    return tuple(terms)


def _attribute_aggregation_tail(variants: frozenset[str]) -> str:
    tails: list[str] = [
        "aggregate list multiple mentions evidence observed mentioned",
    ]
    if variants.intersection({"items", "bought", "buy"}):
        tails.append("item bought purchased got new gift object possession")
    if variants.intersection({"instrument", "instruments", "play", "plays"}):
        tails.append("instrument music play plays played violin clarinet piano guitar")
    if variants.intersection({"events", "attend", "attended", "participate", "participated"}):
        tails.append(
            "event attended participated went conference parade speech support group "
            "reading meeting mentorship mentoring youth children school talk gender "
            "identity inclusion community ally allies"
        )
    if variants.intersection({"share", "shared"}):
        tails.append(
            "shared both similar interests hobbies enjoy watching movies making "
            "desserts recipes baking"
        )
    if variants.intersection(_COMMONALITY_TERMS):
        tails.append(
            "common shared both mutual same similar overlap interests hobbies "
            "activities enjoy like love prefer painting camping hiking music books games"
        )
    if variants.intersection({"traits"}):
        tails.append(
            "trait personality thoughtful authentic driven caring supportive concerned helpful"
        )
    return _normalize_query(" ".join(tails))


def _inventory_list_tail(variants: frozenset[str]) -> str:
    tails: list[str] = []
    if variants.intersection({"where", "где"}) and variants.intersection(
        _PLACE_INVENTORY_ACTION_TERMS
    ):
        tails.append(
            "place friends shelter church gym community welcoming people fellow "
            "volunteers joined made met"
        )
    elif variants.intersection(
        {
            "areas",
            "cities",
            "places",
            "states",
            "города",
            "места",
        }
    ):
        tails.append(
            "place area country state city coast destination visited went travel "
            "trip vacation planning go abroad"
        )
    elif variants.intersection({"countries", "country", "страна", "страны"}):
        tails.append(
            "country countries europe european england spain france italy germany "
            "portugal ireland sweden abroad solo trip travel visited went"
        )
    if variants.intersection({"shelter", "shelters", "volunteering", "volunteer"}):
        tails.append(
            "volunteer volunteered volunteering shelter homeless dog church gym helped "
            "met people residents names donated local pup old car"
        )
    if variants.intersection({"causes", "support", "supporting"}):
        tails.append(
            "cause causes passionate support supporting veterans schools infrastructure "
            "education reform infrastructure development rights charity community "
            "campaign project appreciation"
        )
    if variants.intersection({"events", "события"}):
        tails.append(
            "event events attended participated joined went planning fundraiser tournament "
            "fair networking conference parade speech support group"
        )
    if variants.intersection({"dessert", "desserts", "recipe", "recipes"}):
        tails.append(
            "dessert desserts recipes recipe homemade made baked coconut milk "
            "dairy-free ice cream icecream sweet treat treats pudding parfait "
            "visual query image caption cobbler sundae cake tart pie cookies "
            "brownies pastry chocolate raspberry strawberry blueberry gluten-free"
        )
    if variants.intersection(
        {
            "cake",
            "cakes",
            "dish",
            "dishes",
            "food",
            "foods",
            "frosting",
            "meal",
            "meals",
        }
    ):
        tails.append(
            "dinner spread plate meal food dish ingredients homemade made cooked "
            "prepared cake filling frosting cooked prepared cream cheese pizza pasta salad roasted "
            "vegetables family photo shared"
        )
    if variants.intersection({"types", "kinds", "projects", "виды", "типы"}):
        tails.append(
            "type kind made finished created project item object piece visual image "
            "caption query cup bowl pot plate painting"
        )
    if variants.intersection({"people"}) or (
        variants.intersection(_PEOPLE_INVENTORY_PROMPT_TERMS)
        and variants.intersection(_PEOPLE_INVENTORY_ACTION_TERMS)
    ):
        tails.append("people person names met helped worked with friend customer resident")
    if variants.intersection({"artists", "bands"}):
        tails.append("artist artists band bands music concert live saw seen performance")
    if variants.intersection({"items", "things"}):
        tails.append("item thing bought got had having owned mentioned object gift possession")
    tails.append("inventory list evidence observed mentioned answer options")
    return _normalize_query(" ".join(tails))


def _requests_emotion_cause(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if not raw_tokens.intersection(_EMOTION_CAUSE_STATE_TERMS):
        return False
    if (
        raw_tokens.intersection({"accept", "accepted"})
        and "for" in raw_tokens
        and raw_tokens.intersection(_NON_EMOTIONAL_ACCEPTANCE_CONTEXT_TERMS)
    ):
        return False
    if raw_tokens.intersection(_EMOTION_CAUSE_PROMPT_TERMS):
        return True
    return bool(
        variants.intersection({"feel", "felt", "feeling", "почувствовал", "почувствовала"})
        and variants.intersection({"because", "reason", "причин", "почему"})
    )


def _requests_non_inference_career_goal(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    return "career" in variants and bool(
        raw_tokens.intersection({"decided", "persue"}) or "path" in variants
    )


def _requests_inference_current_preference_or_goal(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if raw_tokens.intersection(_CURRENT_GOAL_TERMS):
        return True
    return bool("career" in variants and raw_tokens.intersection({"option", "path", "pursue"}))


def _requests_comparison_preference(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if raw_tokens.intersection(_COMPARISON_TERMS):
        return True
    return bool({"or", "option"}.issubset(raw_tokens) and variants.intersection({"prefer"}))


def _requests_counterfactual_evidence(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if raw_tokens.intersection(_COUNTERFACTUAL_EXPLICIT_TERMS):
        return True
    if variants.intersection({"would", "wouldnt"}) or raw_tokens.intersection(
        {"would", "wouldn", "wouldnt"}
    ):
        return bool(variants.intersection(_COUNTERFACTUAL_SUPPORT_TERMS))
    return bool("бы" in raw_tokens and variants.intersection({"мог", "могла", "может"}))


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


def _requests_evidence_reason(query: str) -> bool:
    return bool(_EVIDENCE_REASON_RE.search(query))


def _requests_knowledge_update_current(
    *,
    variants: frozenset[str],
    temporal_intent: TemporalQueryIntent,
) -> bool:
    if (
        temporal_intent.after_event
        or temporal_intent.before_event
        or temporal_intent.relative_time_hints
        or temporal_intent.requests_previous
    ):
        return False
    if variants.intersection(_KNOWLEDGE_UPDATE_ENTITY_TERMS) and variants.intersection(
        _KNOWLEDGE_UPDATE_CURRENT_STATE_TERMS
    ):
        return True
    if not variants.intersection(_KNOWLEDGE_UPDATE_DECISION_TERMS):
        return False
    if variants.intersection(_KNOWLEDGE_UPDATE_ENTITY_TERMS):
        return True
    return bool(
        variants.intersection(_KNOWLEDGE_UPDATE_PROMPT_TERMS)
        and variants.intersection(_KNOWLEDGE_UPDATE_PROMPT_ACTION_TERMS)
        and variants.intersection({"use", "использовать"})
        and variants.intersection(_KNOWLEDGE_UPDATE_STRONG_DECISION_TERMS)
    )


def _requests_knowledge_update_previous(
    *,
    query: str,
    variants: frozenset[str],
    temporal_intent: TemporalQueryIntent,
) -> bool:
    if not temporal_intent.requests_previous:
        return False
    if "no longer" in query or "not current" in query:
        return True
    return bool(
        variants.intersection(
            {
                "anymore",
                "больше",
                "longer",
                "stopped",
                "перестал",
                "перестала",
                "перестали",
            }
        )
    )


def _requests_absence_contrast(query: str) -> bool:
    return bool(_ABSENCE_CONTRAST_RE.search(query))


def _requests_country_destination_context(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    return bool(
        variants.intersection({"country", "страна"})
        and (
            raw_tokens.intersection(_INVENTORY_LIST_PROMPT_TERMS)
            or variants.intersection(_INVENTORY_LIST_PROMPT_TERMS)
        )
        and (
            raw_tokens.intersection(_COUNTRY_DESTINATION_ACTION_TERMS)
            or variants.intersection(_COUNTRY_DESTINATION_ACTION_TERMS)
        )
    )


def _requests_relationship_status(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
    identities: tuple[str, ...],
) -> bool:
    if {"relationship", "status"}.issubset(variants):
        return True
    if raw_tokens.intersection({"отношения", "статус"}):
        return True
    if raw_tokens.intersection({"помимо", "кроме", "besides", "other", "apart"}):
        return False
    if len(identities) >= 2 and raw_tokens.intersection(_RELATIONSHIP_STATUS_TERMS):
        return True
    return bool(
        variants.intersection({"single", "married", "dating", "partner", "spouse"})
        and variants.intersection(_RELATIONSHIP_STATUS_TERMS)
    )


def _requests_activity_participation(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if not variants.intersection({"activity", "hobby", "sport", "sports"}):
        return False
    return bool(raw_tokens.intersection(_ACTIVITY_PARTICIPATION_TERMS))


def _requests_sport_team_attribute(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if variants.intersection({"collectible", "collectibles"}):
        return False
    if not variants.intersection(_SPORT_TEAM_ATTRIBUTE_TERMS):
        return False
    direct_sport_terms = variants.intersection(
        {
            "basketball",
            "coach",
            "contract",
            "franchise",
            "jersey",
            "jerseys",
            "player",
            "roster",
            "sport",
            "sports",
            "teammates",
        }
    )
    team_signing_terms = (
        "team" in raw_tokens
        and bool(raw_tokens.intersection({"sign", "signed"}))
        and "up" not in raw_tokens
    )
    team_trip_terms = "team" in raw_tokens and bool(
        raw_tokens.intersection({"travel", "traveling", "trip"})
    )
    team_position_terms = "position" in raw_tokens and "team" in variants
    school_sport_terms = bool(raw_tokens.intersection({"school", "schools"})) and (
        "basketball" in variants or bool(raw_tokens.intersection({"play", "played"}))
    )
    if not (
        direct_sport_terms
        or team_signing_terms
        or team_trip_terms
        or team_position_terms
        or school_sport_terms
    ):
        return False
    return bool(
        raw_tokens.intersection(
            {
                "how",
                "position",
                "school",
                "schools",
                "sign",
                "signed",
                "team",
                "which",
                "what",
                "when",
            }
        )
    )


def _requests_inventory_list_context(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if _is_book_recommendation_object_query(raw_tokens=raw_tokens):
        return False
    if _requests_recommendation_source_context(raw_tokens=raw_tokens, variants=variants):
        return False
    if _requests_place_inventory_context(raw_tokens=raw_tokens, variants=variants):
        return True
    if _requests_people_inventory_context(raw_tokens=raw_tokens, variants=variants):
        return True
    if not variants.intersection(_INVENTORY_LIST_SLOT_TERMS):
        return False
    if not (
        raw_tokens.intersection(_INVENTORY_LIST_PROMPT_TERMS)
        or variants.intersection(_INVENTORY_LIST_PROMPT_TERMS)
    ):
        return False
    return bool(
        raw_tokens.intersection(_INVENTORY_LIST_ACTION_TERMS)
        or variants.intersection(_INVENTORY_LIST_ACTION_TERMS)
        or variants.intersection({"areas", "countries", "places", "states", "types", "kinds"})
    )


def _requests_kind_type_descriptor_context(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if not variants.intersection(_KIND_TYPE_DESCRIPTOR_TERMS):
        return False
    return bool(raw_tokens.intersection({"what", "which", "какой", "какая", "какие"}))


def _requests_impact_effect_context(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if not variants.intersection(_IMPACT_EFFECT_TERMS):
        return False
    return bool(raw_tokens.intersection({"how", "what", "which"}))


def _requests_content_topic_context(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if not variants.intersection(_CONTENT_TOPIC_TERMS):
        return False
    return bool(raw_tokens.intersection({"what", "which", "how"}))


def _requests_people_inventory_context(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if _requests_social_support_network_context(raw_tokens=raw_tokens, variants=variants):
        return False
    if not (
        raw_tokens.intersection(_PEOPLE_INVENTORY_PROMPT_TERMS)
        or variants.intersection(_PEOPLE_INVENTORY_PROMPT_TERMS)
    ):
        return False
    return bool(
        raw_tokens.intersection(_PEOPLE_INVENTORY_ACTION_TERMS)
        or variants.intersection(_PEOPLE_INVENTORY_ACTION_TERMS)
    )


def _requests_social_support_network_context(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if not (
        raw_tokens.intersection(_PEOPLE_INVENTORY_PROMPT_TERMS)
        or variants.intersection(_PEOPLE_INVENTORY_PROMPT_TERMS)
    ):
        return False
    if raw_tokens.intersection(_TECHNICAL_SUPPORT_CONTEXT_TERMS):
        return False
    if variants.intersection(_TECHNICAL_SUPPORT_CONTEXT_TERMS):
        return False
    has_support_action = bool(
        raw_tokens.intersection(_SOCIAL_SUPPORT_ACTION_TERMS)
        or variants.intersection(_SOCIAL_SUPPORT_ACTION_TERMS)
    )
    has_relation_marker = bool(
        raw_tokens.intersection(_SOCIAL_SUPPORT_RELATION_TERMS)
        or variants.intersection(_SOCIAL_SUPPORT_RELATION_TERMS)
    )
    return has_support_action or has_relation_marker


def _requests_place_inventory_context(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if not (raw_tokens.intersection({"where", "где"}) or variants.intersection({"where", "где"})):
        return False
    if variants.intersection(_RELOCATION_ACTION_TERMS):
        return False
    return bool(
        raw_tokens.intersection(_PLACE_INVENTORY_ACTION_TERMS)
        or variants.intersection(_PLACE_INVENTORY_ACTION_TERMS)
    )


def _requests_commonality_context(
    *,
    identities: tuple[str, ...],
    variants: frozenset[str],
) -> bool:
    return len(identities) >= 2 and bool(variants.intersection(_COMMONALITY_TERMS))


def _requests_collectible_object_context(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    if variants.intersection({"collectible", "collectibles", "memorabilia"}):
        return True
    if not variants.intersection(_COLLECTIBLE_OBJECT_TERMS):
        return False
    return bool(
        raw_tokens.intersection({"own", "owns", "owned", "have", "has", "similar", "same"})
        or variants.intersection({"own", "owns", "owned", "similar", "same", "shared"})
    )


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


def _is_book_recommendation_object_query(*, raw_tokens: frozenset[str]) -> bool:
    return (
        bool(raw_tokens.intersection({"book", "books"}))
        and bool(raw_tokens.intersection({"what"}))
        and bool(raw_tokens.intersection(_RECOMMENDATION_SOURCE_TERMS))
        and not raw_tokens.intersection({"who", "whose", "whom", "source"})
    )


def _requests_gotcha_failure_context(*, variants: frozenset[str]) -> bool:
    if "gotcha_failure_request" in variants:
        return True
    if {"known", "issue"}.issubset(variants) or {"known", "problem"}.issubset(variants):
        return True
    return bool(variants.intersection(_GOTCHA_FAILURE_TERMS))


def _requests_state_transition_context(*, variants: frozenset[str]) -> bool:
    return "state_transition_request" in variants


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


def _with_missing_identities(clause: str, identities: tuple[str, ...]) -> str:
    if not identities:
        return clause
    clause_key = clause.casefold()
    if _clause_contains_identity(clause_key, identities):
        return clause
    missing = tuple(
        identity for identity in identities[:2] if identity.casefold() not in clause_key
    )
    if not missing:
        return clause
    return _normalize_query(" ".join((*missing, clause)))


def _clause_contains_identity(clause_key: str, identities: tuple[str, ...]) -> bool:
    return any(
        re.search(rf"(?<!\w){re.escape(identity.casefold())}(?!\w)", clause_key)
        for identity in identities
        if identity
    )


def _identity_terms(
    query: str,
    anchor_intent: QueryAnchorIntent,
) -> tuple[str, ...]:
    labels = [
        hint.label
        for hint in anchor_intent.hints
        if hint.kind
        in {
            MemoryAnchorKind.PERSON,
            MemoryAnchorKind.PROJECT,
            MemoryAnchorKind.ORGANIZATION,
        }
    ]
    labels.extend(_capitalized_identity_terms(query))
    deduped: list[str] = []
    seen: set[str] = set()
    for label in labels:
        term = _normalize_identity_term(label)
        if not term:
            continue
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(term)
        if len(deduped) >= _MAX_IDENTITY_TERMS:
            break
    return tuple(deduped)


def _capitalized_identity_terms(query: str) -> Iterable[str]:
    for match in _TOKEN_RE.finditer(query):
        token = match.group(0).strip("_")
        if len(token) < 2 or token.casefold() in _QUESTION_STOPWORDS:
            continue
        if token[:1].isupper():
            yield token


def _normalize_identity_term(value: str) -> str:
    tokens = _normalize_query(value).strip("@").split()
    while tokens and tokens[0].casefold() in _QUESTION_STOPWORDS:
        tokens = tokens[1:]
    while tokens and tokens[-1].casefold() in _QUESTION_STOPWORDS:
        tokens = tokens[:-1]
    token = _normalize_query(" ".join(tokens)).strip("@")
    if len(token) < 2 or token.casefold() in _QUESTION_STOPWORDS:
        return ""
    return token


def _is_useful_clause(clause: str) -> bool:
    if len(clause) < 8:
        return False
    terms = query_terms(clause, min_chars=2, max_terms=12)
    distinctive = [
        term for term in terms if not set(term.variants).intersection(_QUESTION_STOPWORDS)
    ]
    return len(distinctive) >= 2


def _query_variant_set(query: str) -> frozenset[str]:
    variants: set[str] = set()
    for term in query_terms(query, min_chars=2, max_terms=32):
        variants.update(term.variants)
    variants.update(_raw_query_tokens(query))
    return frozenset(variants)


def _raw_query_tokens(query: str) -> Iterable[str]:
    for match in _TOKEN_RE.finditer(query):
        token = match.group(0).casefold().strip("_")
        if len(token) >= 2:
            yield token


def _normalize_query(query: str) -> str:
    return " ".join(query.split())


def _clean_clause_query(query: str) -> str:
    normalized = _normalize_query(query)
    return re.sub(
        r"^(?:and|also|then|plus|и|также|потом|затем)\s+",
        "",
        normalized,
        flags=re.IGNORECASE,
    )


def _query_dedupe_key(query: str) -> str:
    return _normalize_query(query).strip(" \t\r\n.,;:!?").casefold()


def _truncate_query(query: str) -> str:
    if len(query) <= _MAX_QUERY_CHARS:
        return query.strip()
    candidate = query[:_MAX_QUERY_CHARS].rstrip()
    if not candidate:
        return ""
    boundary = candidate.rfind(" ")
    if boundary >= max(0, _MAX_QUERY_CHARS - 32):
        candidate = candidate[:boundary]
    return candidate.strip(" \t\r\n.,;:!?")
