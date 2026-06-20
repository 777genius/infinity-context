from infinity_context_core.application.context_media_time import (
    media_time_match_for_source_ref,
    media_time_windows_from_query,
)
from infinity_context_core.domain.entities import SourceRef


def test_media_time_query_parses_explicit_timestamps_and_units() -> None:
    windows = media_time_windows_from_query("what happened at 00:42 in the video")
    assert len(windows) == 1
    assert windows[0].start_ms <= 42_000 <= windows[0].end_ms
    assert windows[0].precision == "second"

    ru_windows = media_time_windows_from_query("что было на 42 секунде записи")
    assert len(ru_windows) == 1
    assert ru_windows[0].start_ms <= 42_000 <= ru_windows[0].end_ms

    minute_windows = media_time_windows_from_query("open transcript around minute 7")
    assert len(minute_windows) == 1
    assert minute_windows[0].start_ms <= 420_000 <= minute_windows[0].end_ms
    assert minute_windows[0].precision == "minute"


def test_media_time_query_avoids_plain_clock_time_without_media_cue() -> None:
    assert media_time_windows_from_query("meeting with Alex at 10:30 tomorrow") == ()

    windows = media_time_windows_from_query("video timecode 10:30")
    assert len(windows) == 1
    assert windows[0].start_ms <= 630_000 <= windows[0].end_ms


def test_media_time_match_uses_source_ref_time_range_overlap() -> None:
    windows = media_time_windows_from_query("00:42")
    matching = media_time_match_for_source_ref(
        SourceRef(
            source_type="extraction_artifact",
            source_id="artifact_audio",
            chunk_id="segment_42",
            time_start_ms=40_000,
            time_end_ms=45_000,
        ),
        windows,
    )
    decoy = media_time_match_for_source_ref(
        SourceRef(
            source_type="extraction_artifact",
            source_id="artifact_audio",
            chunk_id="segment_5",
            time_start_ms=5_000,
            time_end_ms=9_000,
        ),
        windows,
    )

    assert matching is not None
    assert matching.boost > 0
    assert matching.best_overlap_ms > 0
    assert decoy is None
