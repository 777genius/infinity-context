"""Shared temporal validity helpers for application policies."""

from __future__ import annotations

from datetime import datetime


def is_temporal_window_current(
    *,
    valid_from: datetime | None,
    valid_to: datetime | None,
    now: datetime | None,
) -> bool:
    if now is None:
        return True
    comparable_now = _comparable_datetime(now, valid_from or valid_to) or now
    comparable_from = _comparable_datetime(valid_from, comparable_now)
    comparable_to = _comparable_datetime(valid_to, comparable_now)
    if comparable_from is not None and comparable_now < comparable_from:
        return False
    return not (comparable_to is not None and comparable_now >= comparable_to)


def _comparable_datetime(value: datetime | None, reference: datetime | None) -> datetime | None:
    if value is None or reference is None:
        return value
    if value.tzinfo is None and reference.tzinfo is not None:
        return value.replace(tzinfo=reference.tzinfo)
    if value.tzinfo is not None and reference.tzinfo is None:
        return value.replace(tzinfo=None)
    return value
