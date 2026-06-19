"""Resolve relative event anchor time hints against observation time."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from infinity_context_core.application.anchor_extraction import ObservedAnchor
from infinity_context_core.domain.entities import MemoryAnchorKind


def temporal_window_for_observed_anchor(
    observed: ObservedAnchor,
    *,
    observed_at: datetime,
) -> tuple[datetime | None, datetime | None]:
    if observed.kind != MemoryAnchorKind.EVENT:
        return None, None
    hint = _metadata_text(observed.metadata.get("event_temporal_hint_code"))
    if not hint:
        return None, None
    quantity = _metadata_int(observed.metadata.get("event_temporal_quantity"), default=1)
    unit = _metadata_text(observed.metadata.get("event_temporal_unit"))
    now = _aware_utc(observed_at)
    if hint == "today":
        return _day_window(now)
    if hint == "tomorrow":
        return _day_window(now + timedelta(days=quantity))
    if hint == "yesterday":
        return _day_window(now - timedelta(days=quantity))
    if hint == "hours_ago" and unit == "hour":
        start = now - timedelta(hours=max(1, quantity))
        return start, min(now, start + timedelta(hours=1))
    if hint == "days_ago" and unit == "day":
        return _day_window(now - timedelta(days=max(1, quantity)))
    if hint in {"last_week", "weeks_ago"} and unit == "week":
        target = now - timedelta(weeks=max(1, quantity))
        start = _week_start(target)
        return start, start + timedelta(days=7)
    return None, None


def temporal_window_metadata(
    valid_from: datetime | None,
    valid_to: datetime | None,
) -> dict[str, object]:
    if valid_from is None or valid_to is None:
        return {}
    return {
        "event_temporal_window_source": "relative_hint_v1",
        "event_valid_from": valid_from.isoformat(),
        "event_valid_to": valid_to.isoformat(),
    }


def _day_window(value: datetime) -> tuple[datetime, datetime]:
    start = datetime.combine(value.date(), time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


def _week_start(value: datetime) -> datetime:
    start_day = value.date() - timedelta(days=value.weekday())
    return datetime.combine(start_day, time.min, tzinfo=UTC)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _metadata_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _metadata_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int) and value >= 0:
        return value
    return default
