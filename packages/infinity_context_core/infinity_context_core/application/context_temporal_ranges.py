"""Temporal range evidence signals for deterministic context rerank."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from infinity_context_core.application.context_diagnostics import (
    normalize_context_diagnostics,
    safe_diagnostic_mapping,
)
from infinity_context_core.application.context_temporal_metadata import (
    temporal_hint_code_from_metadata,
)
from infinity_context_core.application.dto import ContextItem

_MONTH_ALIASES = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_MONTH_PATTERN = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?"
)
_SEASON_MONTHS = {
    "spring": frozenset({3, 4, 5}),
    "summer": frozenset({6, 7, 8}),
    "fall": frozenset({9, 10, 11}),
    "autumn": frozenset({9, 10, 11}),
    "winter": frozenset({12, 1, 2}),
}
_ISO_DATE_RE = re.compile(
    r"(?<!\d)(?P<year>(?:19|20)\d{2})[-/.](?P<month>\d{1,2})[-/.](?P<day>\d{1,2})(?!\d)"
)
_LOCAL_DATE_RE = re.compile(
    r"(?<!\d)(?P<first>\d{1,2})[-/.](?P<second>\d{1,2})[-/.](?P<year>(?:19|20)\d{2})(?!\d)"
)
_MONTH_DAY_RE = re.compile(
    rf"\b(?P<month>{_MONTH_PATTERN})\.?\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(?P<year>(?:19|20)\d{2}))?\b",
    re.IGNORECASE,
)
_DAY_MONTH_RE = re.compile(
    r"\b(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+"
    rf"(?P<month>{_MONTH_PATTERN})\.?(?:,?\s+(?P<year>(?:19|20)\d{{2}}))?\b",
    re.IGNORECASE,
)
_MONTH_YEAR_RE = re.compile(
    rf"\b(?P<month>{_MONTH_PATTERN})\.?\s*,?\s+(?P<year>(?:19|20)\d{{2}})\b",
    re.IGNORECASE,
)
_PREPOSITIONAL_MONTH_RE = re.compile(
    rf"\b(?:in|during|over|throughout|by|before|after)\s+"
    rf"(?P<month>{_MONTH_PATTERN})\.?\b",
    re.IGNORECASE,
)
_SEASON_RE = re.compile(
    r"\b(?P<season>spring|summer|fall|autumn|winter)"
    r"(?:\s+(?P<year>(?:19|20)\d{2}))?\b",
    re.IGNORECASE,
)
_WEEKEND_RE = re.compile(
    r"\b(?:over|during|on|for|that|the|a|long|first|last|this|next)\s+"
    r"(?:long\s+)?weekend\b|\bweekend\s+(?:before|after|of)\b",
    re.IGNORECASE,
)
_BEFORE_RE = re.compile(r"\b(?:before|prior\s+to|until|up\s+to)\b", re.IGNORECASE)
_AFTER_RE = re.compile(r"\b(?:after|following|since)\b", re.IGNORECASE)
_DATE_VALUE_RE = re.compile(r"(?P<year>(?:19|20)\d{2})-(?P<month>\d{2})-(?P<day>\d{2})")


@dataclass(frozen=True)
class TemporalRangeSignal:
    boost: float = 0.0
    reason: str = ""
    code: str = ""

    @property
    def empty(self) -> bool:
        return self.boost == 0.0


@dataclass(frozen=True)
class _DateSurface:
    value: date
    start: int
    end: int

    @property
    def code(self) -> str:
        return f"date_{self.value.year:04d}_{self.value.month:02d}_{self.value.day:02d}"


def temporal_range_codes(text: str) -> tuple[str, ...]:
    """Return normalized broad range codes explicitly requested in text."""

    seen: dict[str, None] = {}
    for match in _MONTH_YEAR_RE.finditer(text):
        month = _month_number(match.group("month"))
        if month:
            seen.setdefault(f"month_{int(match.group('year')):04d}_{month:02d}", None)
    for match in _PREPOSITIONAL_MONTH_RE.finditer(text):
        month = _month_number(match.group("month"))
        if month:
            seen.setdefault(f"month_{month:02d}", None)
    for match in _SEASON_RE.finditer(text):
        season = _canonical_season(match.group("season"))
        if not season:
            continue
        year = match.group("year")
        seen.setdefault(f"season_{year}_{season}" if year else f"season_{season}", None)
    if _WEEKEND_RE.search(text):
        seen.setdefault("weekend", None)
    return tuple(seen)


def temporal_boundary_dates(text: str) -> tuple[str, str]:
    """Return ``(after_date, before_date)`` ISO dates for date-boundary queries."""

    after_date = ""
    before_date = ""
    for surface in _date_surfaces(text):
        before_window = text[max(0, surface.start - 40) : surface.start]
        after_window = text[surface.end : surface.end + 40]
        if not after_date and (_AFTER_RE.search(before_window) or _BEFORE_RE.search(after_window)):
            after_date = surface.value.isoformat()
        if not before_date and (
            _BEFORE_RE.search(before_window) or _AFTER_RE.search(after_window)
        ):
            before_date = surface.value.isoformat()
    return after_date, before_date


def temporal_range_boost_signal(
    item: ContextItem,
    *,
    range_codes: tuple[str, ...],
    after_date: str = "",
    before_date: str = "",
) -> TemporalRangeSignal:
    if not range_codes and not after_date and not before_date:
        return TemporalRangeSignal()

    diagnostics = normalize_context_diagnostics(item.diagnostics)
    provenance = safe_diagnostic_mapping(diagnostics.get("provenance"))
    temporal_hint_code = temporal_hint_code_from_metadata(diagnostics, provenance)

    if signal := _boundary_date_signal(item.text, after_date=after_date, before_date=before_date):
        return signal

    metadata_dates = _metadata_dates(diagnostics, provenance, temporal_hint_code)
    if signal := _metadata_range_signal(
        dates=metadata_dates,
        range_codes=range_codes,
        after_date=after_date,
        before_date=before_date,
    ):
        return signal

    if temporal_hint_code and temporal_hint_code in range_codes:
        return TemporalRangeSignal(
            boost=0.03,
            reason="query temporal range matches item event window",
            code="temporal_range_hint_match",
        )

    text_dates = tuple(surface.value for surface in _date_surfaces(item.text))
    if signal := _text_date_range_signal(dates=text_dates, range_codes=range_codes):
        return signal

    if _text_has_range_surface(item.text, range_codes):
        return TemporalRangeSignal(
            boost=0.028,
            reason="query temporal range matches item text",
            code="temporal_range_text_match",
        )

    return TemporalRangeSignal()


def _metadata_range_signal(
    *,
    dates: tuple[date, ...],
    range_codes: tuple[str, ...],
    after_date: str,
    before_date: str,
) -> TemporalRangeSignal | None:
    if not dates:
        return None
    if after_boundary := _parse_iso_date(after_date):
        if any(candidate > after_boundary for candidate in dates):
            return TemporalRangeSignal(
                boost=0.03,
                reason="query asks after date and item date is after boundary",
                code="after_date_metadata_match",
            )
        return TemporalRangeSignal(
            boost=-0.018,
            reason="query asks after date and item date is not after boundary",
            code="after_date_metadata_conflict",
        )
    if before_boundary := _parse_iso_date(before_date):
        if any(candidate < before_boundary for candidate in dates):
            return TemporalRangeSignal(
                boost=0.03,
                reason="query asks before date and item date is before boundary",
                code="before_date_metadata_match",
            )
        return TemporalRangeSignal(
            boost=-0.018,
            reason="query asks before date and item date is not before boundary",
            code="before_date_metadata_conflict",
        )
    if not range_codes:
        return None
    if any(_date_matches_any_range(candidate, range_codes) for candidate in dates):
        return TemporalRangeSignal(
            boost=0.036,
            reason="query temporal range contains item metadata date",
            code="temporal_range_metadata_match",
        )
    if any(_date_range_is_specific(code) for code in range_codes):
        return TemporalRangeSignal(
            boost=-0.018,
            reason="query temporal range conflicts with item metadata date",
            code="temporal_range_metadata_conflict",
        )
    return None


def _text_date_range_signal(
    *,
    dates: tuple[date, ...],
    range_codes: tuple[str, ...],
) -> TemporalRangeSignal | None:
    if not dates or not range_codes:
        return None
    if any(_date_matches_any_range(candidate, range_codes) for candidate in dates):
        return TemporalRangeSignal(
            boost=0.03,
            reason="query temporal range contains item text date",
            code="temporal_range_text_date_match",
        )
    return None


def _boundary_date_signal(
    text: str,
    *,
    after_date: str,
    before_date: str,
) -> TemporalRangeSignal | None:
    expected = after_date or before_date
    if not expected:
        return None
    expected_date = _parse_iso_date(expected)
    if expected_date is None:
        return None
    for surface in _date_surfaces(text):
        if surface.value != expected_date:
            continue
        before_window = text[max(0, surface.start - 40) : surface.start]
        if after_date and _AFTER_RE.search(before_window):
            return TemporalRangeSignal(
                boost=0.032,
                reason="query asks after date and item text matches boundary",
                code="after_date_text_boundary_match",
            )
        if before_date and _BEFORE_RE.search(before_window):
            return TemporalRangeSignal(
                boost=0.032,
                reason="query asks before date and item text matches boundary",
                code="before_date_text_boundary_match",
            )
    return None


def _metadata_dates(*sources: Mapping[str, object] | str) -> tuple[date, ...]:
    seen: dict[date, None] = {}
    for source in sources:
        if isinstance(source, str):
            parsed_hint = _parse_date_hint_code(source)
            if parsed_hint is not None:
                seen.setdefault(parsed_hint, None)
            continue
        for key in (
            "event_valid_from",
            "event_valid_to",
            "valid_from",
            "valid_to",
            "event_date",
            "date",
            "created_at",
            "updated_at",
        ):
            value = source.get(key)
            if not isinstance(value, str):
                continue
            parsed = _parse_iso_date(value[:10])
            if parsed is not None:
                seen.setdefault(parsed, None)
    return tuple(seen)


def _parse_date_hint_code(code: str) -> date | None:
    match = re.fullmatch(r"date_(?P<year>\d{4})_(?P<month>\d{2})_(?P<day>\d{2})", code)
    if not match:
        return None
    try:
        return date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
    except ValueError:
        return None


def _text_has_range_surface(text: str, range_codes: tuple[str, ...]) -> bool:
    text_ranges = set(temporal_range_codes(text))
    for code in range_codes:
        if code in text_ranges:
            return True
        if code == "weekend" and "weekend" in text_ranges:
            return True
    return False


def _date_matches_any_range(candidate: date, range_codes: tuple[str, ...]) -> bool:
    return any(_date_matches_range(candidate, code) for code in range_codes)


def _date_matches_range(candidate: date, code: str) -> bool:
    if code == "weekend":
        return candidate.weekday() in {5, 6}
    if code.startswith("month_"):
        parts = code.split("_")
        if len(parts) == 2:
            return candidate.month == int(parts[1])
        if len(parts) == 3:
            return candidate.year == int(parts[1]) and candidate.month == int(parts[2])
    if code.startswith("season_"):
        parts = code.split("_")
        if len(parts) == 2:
            return candidate.month in _SEASON_MONTHS.get(parts[1], frozenset())
        if len(parts) == 3:
            return (
                candidate.year == int(parts[1])
                and candidate.month in _SEASON_MONTHS.get(parts[2], frozenset())
            )
    return False


def _date_range_is_specific(code: str) -> bool:
    return code == "weekend" or code.startswith("month_") or code.startswith("season_")


def _date_surfaces(text: str) -> tuple[_DateSurface, ...]:
    surfaces: list[_DateSurface] = []
    for match in _ISO_DATE_RE.finditer(text):
        _append_surface(
            surfaces,
            start=match.start(),
            end=match.end(),
            year=int(match.group("year")),
            month=int(match.group("month")),
            day=int(match.group("day")),
        )
    for match in _LOCAL_DATE_RE.finditer(text):
        first = int(match.group("first"))
        second = int(match.group("second"))
        year = int(match.group("year"))
        if first > 12 >= second:
            _append_surface(
                surfaces,
                start=match.start(),
                end=match.end(),
                year=year,
                month=second,
                day=first,
            )
        elif second > 12 >= first:
            _append_surface(
                surfaces,
                start=match.start(),
                end=match.end(),
                year=year,
                month=first,
                day=second,
            )
    for pattern in (_MONTH_DAY_RE, _DAY_MONTH_RE):
        for match in pattern.finditer(text):
            year = match.group("year")
            if not year:
                continue
            month = _month_number(match.group("month"))
            if month:
                _append_surface(
                    surfaces,
                    start=match.start(),
                    end=match.end(),
                    year=int(year),
                    month=month,
                    day=int(match.group("day")),
                )
    return tuple(dict.fromkeys(surfaces))


def _append_surface(
    surfaces: list[_DateSurface],
    *,
    start: int,
    end: int,
    year: int,
    month: int,
    day: int,
) -> None:
    try:
        surfaces.append(_DateSurface(date(year, month, day), start, end))
    except ValueError:
        return


def _month_number(value: str) -> int:
    return _MONTH_ALIASES.get(value.casefold().rstrip("."), 0)


def _canonical_season(value: str) -> str:
    normalized = value.casefold()
    return "fall" if normalized == "autumn" else normalized


def _parse_iso_date(value: str) -> date | None:
    if not isinstance(value, str):
        return None
    match = _DATE_VALUE_RE.fullmatch(value.strip())
    if not match:
        return None
    try:
        return date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
    except ValueError:
        return None
