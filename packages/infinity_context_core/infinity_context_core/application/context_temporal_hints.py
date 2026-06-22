"""Shared bounded relative temporal hint parsing for memory retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TemporalHint:
    code: str
    min_hours: float
    max_hours: float
    canonical_code: str = ""


_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
}
_NUMERIC_TEMPORAL_HINT_PATTERNS: tuple[tuple[str, re.Pattern[str], float, int], ...] = (
    (
        "hours",
        re.compile(
            r"\b(?:(?:about|around)\s+)?"
            r"(?P<count>\d{1,3}|one|two|three|four|five|six)\s+hours?\s+ago\b",
            re.IGNORECASE,
        ),
        1.0,
        24 * 14,
    ),
    (
        "hours",
        re.compile(
            r"\b(?:около\s+)?(?P<count>\d{1,3})\s+час(?:а|ов)?\s+назад\b",
            re.IGNORECASE,
        ),
        1.0,
        24 * 14,
    ),
    (
        "days",
        re.compile(
            r"\b(?:(?:about|around)\s+)?(?P<count>\d{1,3})\s+days?\s+ago\b",
            re.IGNORECASE,
        ),
        24.0,
        365,
    ),
    (
        "days",
        re.compile(
            r"\b(?:около\s+)?(?P<count>\d{1,3})\s+д(?:ень|ня|ней)\s+назад\b",
            re.IGNORECASE,
        ),
        24.0,
        365,
    ),
    (
        "weeks",
        re.compile(
            r"\b(?:(?:about|around)\s+)?(?P<count>\d{1,2})\s+weeks?\s+ago\b",
            re.IGNORECASE,
        ),
        24.0 * 7,
        52,
    ),
    (
        "weeks",
        re.compile(
            r"\b(?:около\s+)?(?P<count>\d{1,2})\s+недел[юи]\s+назад\b",
            re.IGNORECASE,
        ),
        24.0 * 7,
        52,
    ),
)
_TEMPORAL_HINT_PATTERNS: tuple[tuple[str, re.Pattern[str], float, float], ...] = (
    (
        "earlier_today",
        re.compile(r"\b(?:earlier\s+today|ранее\s+сегодня)\b", re.IGNORECASE),
        0.0,
        30.0,
    ),
    (
        "today_morning",
        re.compile(
            r"\b(?:this\s+morning|сегодня\s+утром|утром\s+сегодня)\b",
            re.IGNORECASE,
        ),
        0.0,
        18.0,
    ),
    (
        "today_afternoon",
        re.compile(
            r"\b(?:this\s+afternoon|сегодня\s+д[нн]ём|д[нн]ём\s+сегодня|"
            r"сегодня\s+днем|днем\s+сегодня)\b",
            re.IGNORECASE,
        ),
        0.0,
        12.0,
    ),
    (
        "today_evening",
        re.compile(
            r"\b(?:this\s+evening|сегодня\s+вечером|вечером\s+сегодня)\b",
            re.IGNORECASE,
        ),
        0.0,
        8.0,
    ),
    (
        "hour_ago",
        re.compile(
            r"\b(?:an?\s+hour\s+ago|1\s+hour\s+ago|last\s+hour|"
            r"(?<!\d\s)(?:около\s+)?час(?:а|ов)?\s+назад)\b",
            re.IGNORECASE,
        ),
        0.0,
        2.5,
    ),
    (
        "today",
        re.compile(r"\b(?:today|сегодня)\b", re.IGNORECASE),
        0.0,
        30.0,
    ),
    (
        "yesterday",
        re.compile(r"\b(?:yesterday|вчера)\b", re.IGNORECASE),
        18.0,
        54.0,
    ),
    (
        "last_week",
        re.compile(
            r"\b(?:(?:last|previous)\s+week|(?:a\s+)?week\s+ago|1\s+week\s+ago|"
            r"на\s+прошлой\s+неделе|прошл(?:ой|ую)\s+недел[юе]|"
            r"недел[юи]\s+назад)\b",
            re.IGNORECASE,
        ),
        24.0,
        24.0 * 10,
    ),
)


def temporal_hint_windows(text: str) -> tuple[TemporalHint, ...]:
    hints: list[TemporalHint] = []
    seen: set[str] = set()
    for hint in _numeric_temporal_hints(text):
        seen.add(hint.code)
        hints.append(hint)
    for code, pattern, min_hours, max_hours in _TEMPORAL_HINT_PATTERNS:
        if code in seen or not pattern.search(text):
            continue
        seen.add(code)
        hints.append(
            TemporalHint(
                code=code,
                min_hours=min_hours,
                max_hours=max_hours,
                canonical_code=code,
            )
        )
    return tuple(hints)


def temporal_hint_codes(text: str) -> tuple[str, ...]:
    codes: list[str] = []
    seen: set[str] = set()
    for hint in temporal_hint_windows(text):
        code = hint.canonical_code or hint.code
        if code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return tuple(codes)


def _numeric_temporal_hints(text: str) -> tuple[TemporalHint, ...]:
    hints: list[TemporalHint] = []
    seen: set[str] = set()
    for unit, pattern, unit_hours, max_count in _NUMERIC_TEMPORAL_HINT_PATTERNS:
        for match in pattern.finditer(text):
            count = _parse_count(match.group("count"))
            if count <= 0 or count > max_count:
                continue
            code = f"{count}_{unit}_ago"
            if code in seen:
                continue
            seen.add(code)
            min_hours, max_hours = _numeric_temporal_window(count * unit_hours)
            hints.append(
                TemporalHint(
                    code=code,
                    min_hours=min_hours,
                    max_hours=max_hours,
                    canonical_code=_canonical_numeric_code(unit=unit, count=count),
                )
            )
    return tuple(hints)


def _numeric_temporal_window(target_hours: float) -> tuple[float, float]:
    if target_hours <= 24:
        tolerance = max(1.0, target_hours * 0.3)
    elif target_hours <= 24 * 7:
        tolerance = max(6.0, target_hours * 0.2)
    else:
        tolerance = max(24.0, target_hours * 0.15)
    return max(0.0, target_hours - tolerance), target_hours + tolerance


def _canonical_numeric_code(*, unit: str, count: int) -> str:
    if unit == "hours":
        return "hours_ago"
    if unit == "days":
        return "days_ago"
    if unit == "weeks":
        return "last_week" if count == 1 else "weeks_ago"
    return f"{unit}_ago"


def _parse_count(value: str) -> int:
    normalized = value.casefold()
    if normalized.isdigit():
        return int(normalized)
    return _NUMBER_WORDS.get(normalized, 0)
