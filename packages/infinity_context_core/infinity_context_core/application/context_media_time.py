"""Media timestamp intent helpers for multimodal context retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass
from math import isfinite

from infinity_context_core.domain.entities import SourceRef

_MAX_QUERY_WINDOWS = 8
_POINT_TOLERANCE_MS = 5_000
_MINUTE_TOLERANCE_MS = 30_000
_MAX_MEDIA_TIME_MS = 24 * 60 * 60 * 1000

_COLON_TIME_RE = re.compile(
    r"(?<![\w])(?P<a>\d{1,2}):(?P<b>\d{2})(?::(?P<c>\d{2}))?(?![\w])",
    re.UNICODE,
)
_NUMBER_UNIT_RE = re.compile(
    r"(?<![\w])(?P<number>\d+(?:[.,]\d+)?)\s*"
    r"(?P<unit>milliseconds?|msecs?|ms|seconds?|secs?|sec|s|minutes?|mins?|min|m|"
    r"hours?|hrs?|hr|h|миллисекунд[а-я]*|мс|секунд[а-я]*|сек|с|"
    r"минут[а-я]*|мин|м|час[а-я]*|ч)(?![\w])",
    re.IGNORECASE | re.UNICODE,
)
_UNIT_NUMBER_RE = re.compile(
    r"(?<![\w])(?P<unit>minute|minutes|min|минута|минуте|минуты|минут|мин|"
    r"second|seconds|sec|секунда|секунде|секунды|секунд|сек)"
    r"\s+(?P<number>\d+(?:[.,]\d+)?)(?![\w])",
    re.IGNORECASE | re.UNICODE,
)
_MEDIA_CUE_RE = re.compile(
    r"\b(timestamp|timecode|video|audio|recording|transcript|clip|"
    r"таймкод|видео|аудио|запис[ьи]|транскрипт|клип)\b",
    re.IGNORECASE | re.UNICODE,
)


@dataclass(frozen=True)
class MediaTimeWindow:
    start_ms: int
    end_ms: int
    label: str
    precision: str


@dataclass(frozen=True)
class MediaTimeMatch:
    boost: float
    matched_window_count: int
    best_overlap_ms: int
    best_distance_ms: int | None


def media_time_windows_from_query(query: str) -> tuple[MediaTimeWindow, ...]:
    """Parse explicit media timestamp hints without treating normal clock time as media."""

    if not query.strip():
        return ()
    windows: list[MediaTimeWindow] = []
    occupied: list[tuple[int, int]] = []
    has_media_cue = bool(_MEDIA_CUE_RE.search(query))
    for match in _COLON_TIME_RE.finditer(query):
        parsed = _colon_match_to_ms(match, has_media_cue=has_media_cue, query=query)
        if parsed is None:
            continue
        point_ms, precision = parsed
        window = _point_window(point_ms, label=match.group(0), precision=precision)
        if window is not None:
            windows.append(window)
            occupied.append((match.start(), match.end()))
    for match in _NUMBER_UNIT_RE.finditer(query):
        if _overlaps_occupied(match.start(), match.end(), occupied):
            continue
        window = _unit_match_to_window(match.group("number"), match.group("unit"))
        if window is not None:
            windows.append(window)
            occupied.append((match.start(), match.end()))
    for match in _UNIT_NUMBER_RE.finditer(query):
        if _overlaps_occupied(match.start(), match.end(), occupied):
            continue
        window = _unit_match_to_window(match.group("number"), match.group("unit"))
        if window is not None:
            windows.append(window)
            occupied.append((match.start(), match.end()))
    return _dedupe_windows(tuple(windows))[:_MAX_QUERY_WINDOWS]


def media_time_match_for_source_ref(
    ref: SourceRef,
    windows: tuple[MediaTimeWindow, ...],
) -> MediaTimeMatch | None:
    if not windows:
        return None
    ref_start, ref_end = _source_ref_time_range(ref)
    if ref_start is None or ref_end is None:
        return None
    matched = 0
    best_overlap = 0
    best_distance: int | None = None
    for window in windows:
        overlap = _overlap_ms(ref_start, ref_end, window.start_ms, window.end_ms)
        distance = _distance_ms(ref_start, ref_end, window.start_ms, window.end_ms)
        if overlap > 0:
            matched += 1
            best_overlap = max(best_overlap, overlap)
        if best_distance is None or distance < best_distance:
            best_distance = distance
    if matched <= 0:
        return None
    boost = min(0.08, 0.055 + 0.01 * min(2, matched - 1) + min(0.015, best_overlap / 60_000))
    return MediaTimeMatch(
        boost=round(boost, 4),
        matched_window_count=matched,
        best_overlap_ms=best_overlap,
        best_distance_ms=best_distance,
    )


def media_time_query_diagnostics(windows: tuple[MediaTimeWindow, ...]) -> dict[str, object]:
    if not windows:
        return {}
    return {
        "media_time_query_count": len(windows),
        "media_time_query_windows": [
            {
                "start_ms": window.start_ms,
                "end_ms": window.end_ms,
                "precision": window.precision,
            }
            for window in windows
        ],
    }


def media_time_match_score_signals(match: MediaTimeMatch | None) -> dict[str, object]:
    if match is None:
        return {}
    return {
        "media_time_match_boost": match.boost,
        "media_time_matched_window_count": match.matched_window_count,
        "media_time_best_overlap_ms": match.best_overlap_ms,
        "media_time_best_distance_ms": match.best_distance_ms,
    }


def _colon_match_to_ms(
    match: re.Match[str],
    *,
    has_media_cue: bool,
    query: str,
) -> tuple[int, str] | None:
    first = int(match.group("a"))
    second = int(match.group("b"))
    third = match.group("c")
    if third is not None:
        if second > 59 or int(third) > 59:
            return None
        return _valid_time_ms(((first * 60 + second) * 60 + int(third)) * 1000), "second"
    if second > 59:
        return None
    if first >= 3 and not has_media_cue and not _near_media_cue(query, match.start(), match.end()):
        return None
    return _valid_time_ms((first * 60 + second) * 1000, "second")


def _unit_match_to_window(number: str, unit: str) -> MediaTimeWindow | None:
    parsed = _parse_number(number)
    if parsed is None:
        return None
    unit_kind = _unit_kind(unit)
    if unit_kind == "millisecond":
        point_ms = int(round(parsed))
        precision = "millisecond"
    elif unit_kind == "second":
        point_ms = int(round(parsed * 1000))
        precision = "second"
    elif unit_kind == "minute":
        point_ms = int(round(parsed * 60_000))
        precision = "minute"
    elif unit_kind == "hour":
        point_ms = int(round(parsed * 3_600_000))
        precision = "hour"
    else:
        return None
    return _point_window(point_ms, label=f"{number} {unit}", precision=precision)


def _point_window(point_ms: int, *, label: str, precision: str) -> MediaTimeWindow | None:
    if point_ms < 0 or point_ms > _MAX_MEDIA_TIME_MS:
        return None
    tolerance = _MINUTE_TOLERANCE_MS if precision in {"minute", "hour"} else _POINT_TOLERANCE_MS
    return MediaTimeWindow(
        start_ms=max(0, point_ms - tolerance),
        end_ms=min(_MAX_MEDIA_TIME_MS, point_ms + tolerance),
        label=label,
        precision=precision,
    )


def _valid_time_ms(value: int, precision: str) -> tuple[int, str] | None:
    if value < 0 or value > _MAX_MEDIA_TIME_MS:
        return None
    return value, precision


def _source_ref_time_range(ref: SourceRef) -> tuple[int | None, int | None]:
    if ref.time_start_ms is None and ref.time_end_ms is None:
        return None, None
    start = ref.time_start_ms if ref.time_start_ms is not None else ref.time_end_ms
    end = ref.time_end_ms if ref.time_end_ms is not None else ref.time_start_ms
    if start is None or end is None or end < start:
        return None, None
    return start, end


def _overlap_ms(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def _distance_ms(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    if _overlap_ms(a_start, a_end, b_start, b_end) > 0:
        return 0
    if a_end < b_start:
        return b_start - a_end
    return a_start - b_end


def _parse_number(value: str) -> float | None:
    try:
        parsed = float(value.replace(",", "."))
    except ValueError:
        return None
    if not isfinite(parsed) or parsed < 0:
        return None
    return parsed


def _unit_kind(unit: str) -> str:
    text = unit.casefold()
    if (
        text in {"ms", "msec", "msecs"}
        or text.startswith("millisecond")
        or text.startswith("миллисекунд")
    ):
        return "millisecond"
    if (
        text in {"s", "sec", "secs"}
        or text.startswith("second")
        or text in {"сек", "с"}
        or text.startswith("секунд")
    ):
        return "second"
    if (
        text in {"m", "min", "mins", "мин", "м"}
        or text.startswith("minute")
        or text.startswith("минут")
    ):
        return "minute"
    if text in {"h", "hr", "hrs", "ч"} or text.startswith("hour") or text.startswith("час"):
        return "hour"
    return ""


def _near_media_cue(query: str, start: int, end: int) -> bool:
    left = max(0, start - 32)
    right = min(len(query), end + 32)
    return bool(_MEDIA_CUE_RE.search(query[left:right]))


def _overlaps_occupied(start: int, end: int, occupied: list[tuple[int, int]]) -> bool:
    return any(
        start < occupied_end and end > occupied_start
        for occupied_start, occupied_end in occupied
    )


def _dedupe_windows(windows: tuple[MediaTimeWindow, ...]) -> tuple[MediaTimeWindow, ...]:
    deduped: list[MediaTimeWindow] = []
    seen: set[tuple[int, int, str]] = set()
    for window in windows:
        key = (window.start_ms, window.end_ms, window.precision)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(window)
    return tuple(deduped)
