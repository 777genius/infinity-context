"""Compact memory-comparison gap report payloads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

_COVERAGE_GAP_LIMIT = 5
_WEAK_SIGNAL_LIMIT = 5
_SAMPLE_CASE_ID_LIMIT = 5
_LOCALITY_SAMPLE_LIMIT = 5
_LOCALITY_WINDOW_LIMIT = 3
_TEXT_LIMIT = 180


def compact_evidence_bundle_gap_report(value: object) -> dict[str, object]:
    """Return the compact-safe subset of the evidence bundle gap report."""
    report = _mapping(value)
    if not report:
        return {}
    return {
        "schema_version": _text(report.get("schema_version")),
        "status": _text(report.get("status")),
        "evaluation_count": _int(report.get("evaluation_count")),
        "incomplete_case_count": _int(report.get("incomplete_case_count")),
        "coverage_gap_reason_total": _int(report.get("coverage_gap_reason_total")),
        "coverage_gap_count": _int(report.get("coverage_gap_count")),
        "weak_provenance_signal_count": _int(
            report.get("weak_provenance_signal_count")
        ),
        "top_coverage_gaps": [
            _compact_coverage_gap(gap)
            for gap in _sequence(report.get("top_coverage_gaps"))[
                :_COVERAGE_GAP_LIMIT
            ]
            if _mapping(gap)
        ],
        "weak_provenance_signals": [
            _compact_weak_signal(signal)
            for signal in _sequence(report.get("weak_provenance_signals"))[
                :_WEAK_SIGNAL_LIMIT
            ]
            if _mapping(signal)
        ],
        "top_action": _text(report.get("top_action")),
    }


def _compact_coverage_gap(value: object) -> dict[str, object]:
    gap = _mapping(value)
    payload: dict[str, object] = {
        "reason": _text(gap.get("reason")),
        "count": _int(gap.get("count")),
        "case_rate": _number(gap.get("case_rate")),
        "action": _text(gap.get("action")),
        "sample_case_ids": _text_list(
            gap.get("sample_case_ids"),
            limit=_SAMPLE_CASE_ID_LIMIT,
        ),
    }
    locality_samples = _source_window_locality_samples(
        gap.get("source_window_locality_samples")
    )
    if locality_samples:
        payload["source_window_locality_samples"] = locality_samples
    return payload


def _compact_weak_signal(value: object) -> dict[str, object]:
    signal = _mapping(value)
    return {
        "name": _text(signal.get("name")),
        "count": _int(signal.get("count")),
        "rate": _number(signal.get("rate")),
        "action": _text(signal.get("action")),
        "sample_case_ids": _text_list(
            signal.get("sample_case_ids"),
            limit=_SAMPLE_CASE_ID_LIMIT,
        ),
    }


def _source_window_locality_samples(value: object) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for raw_sample in _sequence(value)[:_LOCALITY_SAMPLE_LIMIT]:
        sample = _mapping(raw_sample)
        if not sample:
            continue
        payload: dict[str, object] = {
            "case_id": _text(sample.get("case_id")),
            "missing_turn_ref_count": _int(sample.get("missing_turn_ref_count")),
            "same_source_missing_count": _int(
                sample.get("same_source_missing_count")
            ),
            "near_retrieved_window_count": _int(
                sample.get("near_retrieved_window_count")
            ),
            "source_absent_count": _int(sample.get("source_absent_count")),
            "missing_ref_windows": _missing_ref_windows(
                sample.get("missing_ref_windows")
            ),
        }
        samples.append(payload)
    return samples


def _missing_ref_windows(value: object) -> list[dict[str, object]]:
    windows: list[dict[str, object]] = []
    for raw_window in _sequence(value)[:_LOCALITY_WINDOW_LIMIT]:
        window = _mapping(raw_window)
        if not window:
            continue
        payload: dict[str, object] = {}
        for key in ("ref", "source_id"):
            text = _text(window.get(key))
            if text:
                payload[key] = text
        for key in ("retrieved_same_source", "bundle_same_source"):
            if key in window:
                payload[key] = bool(window.get(key))
        for key in ("nearest_retrieved_turn_ref", "nearest_bundle_turn_ref"):
            text = _text(window.get(key))
            if text:
                payload[key] = text
        for key in ("nearest_retrieved_turn_distance", "nearest_bundle_turn_distance"):
            if key in window:
                payload[key] = _int(window.get(key))
        if payload:
            windows.append(payload)
    return windows


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return value
    return ()


def _text_list(value: object, *, limit: int) -> list[str]:
    values = []
    for item in _sequence(value):
        text = _text(item)
        if text:
            values.append(text)
        if len(values) >= limit:
            break
    return values


def _text(value: object, *, limit: int = _TEXT_LIMIT) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _number(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return 0.0
