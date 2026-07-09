"""Answer-shape and evidence policy for query decomposition."""

from __future__ import annotations

import re

from infinity_context_core.application.context_temporal_query import TemporalQueryIntent

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

def _requests_gotcha_failure_context(*, variants: frozenset[str]) -> bool:
    if "gotcha_failure_request" in variants:
        return True
    if {"known", "issue"}.issubset(variants) or {"known", "problem"}.issubset(variants):
        return True
    return bool(variants.intersection(_GOTCHA_FAILURE_TERMS))

def _requests_state_transition_context(*, variants: frozenset[str]) -> bool:
    return "state_transition_request" in variants
