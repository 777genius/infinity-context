from datetime import UTC, datetime

from infinity_context_core.application.anchor_extraction import extract_observed_anchors
from infinity_context_core.application.anchor_temporal_window import (
    temporal_window_for_observed_anchor,
    temporal_window_metadata,
)

NOW = datetime(2026, 6, 19, 15, 30, tzinfo=UTC)


def test_temporal_window_resolves_hours_ago_event_anchor() -> None:
    anchor = _event_anchor("Call with Alex about Project Atlas 2 hours ago.")

    valid_from, valid_to = temporal_window_for_observed_anchor(anchor, observed_at=NOW)

    assert valid_from == datetime(2026, 6, 19, 13, 30, tzinfo=UTC)
    assert valid_to == datetime(2026, 6, 19, 14, 30, tzinfo=UTC)
    assert temporal_window_metadata(valid_from, valid_to) == {
        "event_temporal_window_source": "relative_hint_v1",
        "event_valid_from": "2026-06-19T13:30:00+00:00",
        "event_valid_to": "2026-06-19T14:30:00+00:00",
    }


def test_temporal_window_resolves_day_and_week_event_anchors() -> None:
    yesterday = _event_anchor("Meeting with Dana yesterday.")
    last_week = _event_anchor("Созвон с Алексом на прошлой неделе по Project Atlas.")

    yesterday_from, yesterday_to = temporal_window_for_observed_anchor(
        yesterday,
        observed_at=NOW,
    )
    week_from, week_to = temporal_window_for_observed_anchor(last_week, observed_at=NOW)

    assert yesterday_from == datetime(2026, 6, 18, tzinfo=UTC)
    assert yesterday_to == datetime(2026, 6, 19, tzinfo=UTC)
    assert week_from == datetime(2026, 6, 8, tzinfo=UTC)
    assert week_to == datetime(2026, 6, 15, tzinfo=UTC)


def test_temporal_window_ignores_non_event_and_unknown_relative_time() -> None:
    project = next(
        anchor
        for anchor in extract_observed_anchors("Project Atlas reviewed yesterday.")
        if anchor.kind.value == "project"
    )
    unknown_event = _event_anchor("Meeting with Alex someday.")

    assert temporal_window_for_observed_anchor(project, observed_at=NOW) == (None, None)
    assert temporal_window_for_observed_anchor(unknown_event, observed_at=NOW) == (
        None,
        None,
    )


def _event_anchor(text: str):
    return next(anchor for anchor in extract_observed_anchors(text) if anchor.kind.value == "event")
