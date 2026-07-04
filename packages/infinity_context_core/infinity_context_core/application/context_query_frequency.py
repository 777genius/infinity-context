"""Frequency and recurrence query helpers for deterministic retrieval."""

from __future__ import annotations

_FREQUENCY_PROMPT_TERMS = frozenset(
    {
        "cadence",
        "every",
        "frequent",
        "frequently",
        "frequency",
        "often",
        "periodically",
        "recur",
        "recurs",
        "recurring",
        "repeat",
        "repeated",
        "repeats",
        "regular",
        "regularly",
        "routine",
        "usually",
        "кажд",
        "регулярно",
        "часто",
        "частота",
        "обычно",
    }
)
_FREQUENCY_UNIT_TERMS = frozenset(
    {
        "annually",
        "biweekly",
        "daily",
        "day",
        "days",
        "fortnightly",
        "monthly",
        "month",
        "months",
        "night",
        "nights",
        "per",
        "times",
        "week",
        "weekday",
        "weekdays",
        "weekend",
        "weekends",
        "weekly",
        "year",
        "yearly",
        "день",
        "дня",
        "дней",
        "ежедневно",
        "ежемесячно",
        "еженедельно",
        "год",
        "года",
        "лет",
        "месяц",
        "месяца",
        "недел",
        "недели",
        "неделю",
        "раз",
    }
)
_FREQUENCY_EVENT_TERMS = frozenset(
    {
        "attend",
        "attended",
        "beach",
        "call",
        "called",
        "checkup",
        "checkups",
        "church",
        "class",
        "classes",
        "coffee",
        "chat",
        "chatted",
        "dance",
        "dancing",
        "exercise",
        "exercises",
        "go",
        "goes",
        "library",
        "lesson",
        "lessons",
        "meet",
        "meeting",
        "met",
        "message",
        "messaged",
        "park",
        "participate",
        "participated",
        "practice",
        "practices",
        "run",
        "runs",
        "sunset",
        "sunsets",
        "talk",
        "talked",
        "take",
        "takes",
        "train",
        "trains",
        "visit",
        "visited",
        "walk",
        "walked",
        "walks",
        "volunteer",
        "volunteered",
        "volunteers",
        "work",
        "workout",
        "workouts",
        "works",
        "бегает",
        "встречается",
        "волонтерит",
        "волонтерство",
        "говорит",
        "ходит",
        "работает",
        "созванивается",
        "тренируется",
        "участвует",
    }
)


def requests_frequency_recurrence_context(
    *,
    raw_tokens: frozenset[str],
    variants: frozenset[str],
) -> bool:
    """Return true for queries asking how often an event/activity recurs."""

    tokens = raw_tokens | variants
    if {"how", "many", "times"}.issubset(tokens) and not (
        tokens
        & {
            "cadence",
            "every",
            "frequent",
            "frequently",
            "frequency",
            "often",
            "per",
            "recurring",
            "regular",
            "regularly",
            "routine",
            "usually",
        }
    ):
        return False
    has_frequency_prompt = bool(tokens & _FREQUENCY_PROMPT_TERMS) or (
        {"how", "often"}.issubset(tokens) or {"как", "часто"}.issubset(tokens)
    )
    has_rate_unit = bool(tokens & _FREQUENCY_UNIT_TERMS) and bool(
        {"per", "times", "раз"} & tokens
    )
    if not (has_frequency_prompt or has_rate_unit):
        return False
    return bool(tokens & _FREQUENCY_EVENT_TERMS) or has_frequency_prompt


def frequency_recurrence_tail(variants: frozenset[str]) -> str:
    """Build a compact retrieval tail for recurrence evidence."""

    activity_terms = " ".join(sorted(variants & _FREQUENCY_EVENT_TERMS))[:80]
    return " ".join(
        part
        for part in (
            activity_terms,
            (
                "frequency recurrence cadence regular regularly often routine every "
                "each daily weekly monthly yearly weekend weekdays every other "
                "every few every two biweekly fortnightly once twice three "
                "times per week per month couple times"
            ),
        )
        if part
    )
