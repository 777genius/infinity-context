from datetime import UTC, datetime

from memo_stack_core.application.temporal_validity import is_temporal_window_current


def test_temporal_window_current_handles_open_and_bounded_ranges() -> None:
    now = datetime(2026, 6, 18, tzinfo=UTC)

    assert is_temporal_window_current(valid_from=None, valid_to=None, now=now) is True
    assert (
        is_temporal_window_current(
            valid_from=datetime(2026, 6, 1, tzinfo=UTC),
            valid_to=datetime(2026, 7, 1, tzinfo=UTC),
            now=now,
        )
        is True
    )
    assert (
        is_temporal_window_current(
            valid_from=datetime(2099, 1, 1, tzinfo=UTC),
            valid_to=None,
            now=now,
        )
        is False
    )
    assert (
        is_temporal_window_current(
            valid_from=None,
            valid_to=datetime(2026, 1, 1, tzinfo=UTC),
            now=now,
        )
        is False
    )


def test_temporal_window_current_normalizes_mixed_timezone_awareness() -> None:
    aware_now = datetime(2026, 6, 18, tzinfo=UTC)
    naive_now = datetime(2026, 6, 18)

    assert (
        is_temporal_window_current(
            valid_from=datetime(2026, 6, 1),
            valid_to=datetime(2026, 7, 1),
            now=aware_now,
        )
        is True
    )
    assert (
        is_temporal_window_current(
            valid_from=datetime(2026, 6, 1, tzinfo=UTC),
            valid_to=datetime(2026, 7, 1, tzinfo=UTC),
            now=naive_now,
        )
        is True
    )
