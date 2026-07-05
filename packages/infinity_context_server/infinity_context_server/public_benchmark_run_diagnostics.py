"""Progress and resume diagnostics for public memory benchmark runs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol

from infinity_context_server.public_benchmark_case_diagnostics import (
    artifact_text_value as _artifact_text_value,
)
from infinity_context_server.public_benchmark_checkpoint import (
    BenchmarkSeedStats,
    CaseRunResult,
)
from infinity_context_server.public_benchmark_metrics import (
    accuracy as _accuracy,
)
from infinity_context_server.public_benchmark_metrics import (
    bounded_public_artifact_fields as _bounded_public_artifact_fields,
)
from infinity_context_server.public_benchmark_metrics import (
    flat_capability_accuracy as _flat_capability_accuracy,
)
from infinity_context_server.public_benchmark_metrics import (
    flat_capability_case_count as _flat_capability_case_count,
)
from infinity_context_server.public_benchmark_metrics import (
    flat_capability_failure_count as _flat_capability_failure_count,
)
from infinity_context_server.public_benchmark_metrics import (
    progress_case_outcome_fields as _progress_case_outcome_fields,
)
from infinity_context_server.public_benchmark_metrics import (
    progress_timing_fields as _progress_timing_fields,
)

_MAX_RESUME_CASE_ID_DETAILS = 20


class BenchmarkProgressPort(Protocol):
    total_case_count: int
    started: float

    def event(self, event_type: str, **fields: object) -> None:
        """Record a bounded public benchmark progress event."""


def emit_case_progress_snapshot(
    *,
    progress: BenchmarkProgressPort,
    run_results: Sequence[CaseRunResult],
    failures: Sequence[Mapping[str, object]],
    seeded_source_count: int,
    seed_stats: BenchmarkSeedStats,
    effective_parallelism: int,
) -> None:
    processed_case_count = len(run_results)
    progress.event(
        "case_progress",
        processed_case_count=processed_case_count,
        total_case_count=progress.total_case_count,
        processed_case_ratio=_ratio(processed_case_count, progress.total_case_count),
        **_progress_timing_fields(
            processed_case_count=processed_case_count,
            total_case_count=progress.total_case_count,
            started=progress.started,
        ),
        accuracy_so_far=_accuracy(run_results),
        capability_accuracy_so_far=_flat_capability_accuracy(run_results),
        capability_case_count_so_far=_flat_capability_case_count(run_results),
        capability_failure_count_so_far=_flat_capability_failure_count(run_results),
        **_progress_case_outcome_fields(
            processed_case_count=processed_case_count,
            run_results=run_results,
            failures=failures,
            total_case_count=progress.total_case_count,
        ),
        seeded_source_count=seeded_source_count,
        seed_source_attempt_count=seed_stats.source_attempt_count,
        seed_cache_hit_count=seed_stats.seed_cache_hit_count,
        effective_parallelism=effective_parallelism,
    )


def bounded_case_id_details(cases: Iterable[Any]) -> tuple[list[str], int]:
    case_ids = [
        _artifact_text_value(
            f"{getattr(case, 'benchmark', '')}:{getattr(case, 'case_id', '')}",
            max_chars=160,
        )
        for case in cases
    ]
    return _bounded_details(case_ids)


def bounded_checkpoint_failure_case_id_details(
    failures: Sequence[Mapping[str, object]],
) -> tuple[list[str], int]:
    case_ids = [
        _artifact_text_value(item.get("case_id"), max_chars=160)
        for item in failures
        if str(item.get("case_id") or "").strip()
    ]
    return _bounded_details(case_ids)


def public_request_artifact_fields(
    *,
    case_selection: Mapping[str, object] | None,
    requested_case_ids: Sequence[object],
    requested_capabilities: Sequence[object],
) -> dict[str, object]:
    return {
        "case_selection": _bounded_public_artifact_fields(case_selection or {}),
        "requested_case_ids": _bounded_text_list(requested_case_ids),
        "requested_capabilities": _bounded_text_list(requested_capabilities),
    }


def public_artifact_reports(reports: object) -> list[dict[str, object]]:
    if not isinstance(reports, Sequence) or isinstance(reports, str | bytes):
        return []
    return [
        _bounded_public_artifact_fields(report)
        for report in reports
        if isinstance(report, Mapping)
    ]


def _bounded_details(values: Sequence[str]) -> tuple[list[str], int]:
    return (
        list(values[:_MAX_RESUME_CASE_ID_DETAILS]),
        max(0, len(values) - _MAX_RESUME_CASE_ID_DETAILS),
    )


def _bounded_text_list(values: Sequence[object]) -> list[str]:
    return [
        text
        for value in values
        if (text := _artifact_text_value(value, max_chars=240))
    ]


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)
