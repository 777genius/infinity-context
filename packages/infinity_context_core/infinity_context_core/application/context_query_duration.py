"""Activity and state duration query helpers."""

from __future__ import annotations

_DURATION_PROMPT_TERMS = frozenset(
    {
        "duration",
        "long",
        "since",
        "started",
        "долго",
        "давно",
        "начала",
        "начал",
        "начали",
        "сколько",
    }
)
_DURATION_UNIT_TERMS = frozenset(
    {
        "day",
        "days",
        "month",
        "months",
        "week",
        "weeks",
        "year",
        "years",
        "день",
        "дней",
        "дня",
        "год",
        "года",
        "лет",
        "месяц",
        "месяца",
        "месяцев",
        "недель",
        "недели",
        "неделю",
    }
)
_ACTIVITY_STATE_TERMS = frozenset(
    {
        "attend",
        "attended",
        "belong",
        "belonged",
        "do",
        "doing",
        "go",
        "goes",
        "has",
        "have",
        "learn",
        "learning",
        "live",
        "lived",
        "lives",
        "own",
        "owned",
        "owns",
        "participate",
        "participated",
        "play",
        "played",
        "practice",
        "practiced",
        "run",
        "running",
        "study",
        "studied",
        "studying",
        "take",
        "takes",
        "taking",
        "train",
        "trained",
        "use",
        "used",
        "using",
        "volunteer",
        "volunteered",
        "volunteering",
        "work",
        "worked",
        "working",
        "волонтерит",
        "волонтерство",
        "живет",
        "живёт",
        "жил",
        "жила",
        "занимается",
        "играет",
        "использует",
        "работает",
        "участвует",
    }
)
_RELATIONSHIP_DURATION_TERMS = frozenset(
    {
        "dating",
        "friend",
        "friends",
        "husband",
        "known",
        "married",
        "partner",
        "relationship",
        "spouse",
        "wife",
        "друг",
        "друзья",
        "жена",
        "знаком",
        "муж",
        "отношения",
        "партнер",
        "партнёр",
        "супруг",
        "супруга",
    }
)


def requests_activity_duration_context(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    """Return true for non-relationship duration questions."""

    tokens = raw_tokens | variants
    if tokens & _RELATIONSHIP_DURATION_TERMS:
        return False
    has_prompt = (
        {"how", "long"}.issubset(tokens)
        or {"как", "долго"}.issubset(tokens)
        or "duration" in tokens
        or ("since" in tokens and bool(tokens & _ACTIVITY_STATE_TERMS))
        or (
            {"how", "many"}.issubset(tokens)
            and bool(tokens & _DURATION_UNIT_TERMS)
            and bool(tokens & _ACTIVITY_STATE_TERMS)
        )
        or (
            "сколько" in tokens
            and bool(tokens & _DURATION_UNIT_TERMS)
            and bool(tokens & _ACTIVITY_STATE_TERMS)
        )
    )
    if not has_prompt:
        return False
    return bool(tokens & _ACTIVITY_STATE_TERMS)


def activity_duration_tail(variants: frozenset[str]) -> str:
    activity_terms = " ".join(sorted(variants & _ACTIVITY_STATE_TERMS))[:120]
    return " ".join(
        part
        for part in (
            activity_terms,
            (
                "duration since for years months weeks days started began "
                "started in began in from already still ongoing continuous "
                "long time how long age since I was had have owned"
            ),
        )
        if part
    )
