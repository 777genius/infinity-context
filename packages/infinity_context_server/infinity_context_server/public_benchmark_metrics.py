"""JSON-safe metric summaries for public memory benchmark runs."""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from infinity_context_server.public_benchmark_checkpoint import CaseRunResult


def run_metric_summary(run_results: Sequence[CaseRunResult]) -> dict[str, object]:
    """Return bounded aggregate metrics that are safe for checkpoints/results."""

    return {
        "case_count": len(run_results),
        "failure_count": sum(1 for item in run_results if not item.ok),
        "accuracy": accuracy(run_results),
        "latency_ms_p95": p95([item.latency_ms for item in run_results]),
        "capability_count": len({item.capability for item in run_results if item.capability}),
        "capability_accuracy": flat_capability_accuracy(run_results),
        "capability_case_count": flat_capability_case_count(run_results),
        "capability_failure_count": flat_capability_failure_count(run_results),
        "benchmark_metrics": benchmark_metric_map(run_results),
    }


def benchmark_summaries(
    run_results: Sequence[CaseRunResult],
    *,
    min_accuracy: float,
) -> list[dict[str, object]]:
    grouped: dict[str, list[CaseRunResult]] = defaultdict(list)
    for item in run_results:
        grouped[item.benchmark].append(item)
    summaries: list[dict[str, object]] = []
    for benchmark in sorted(grouped):
        cases = grouped[benchmark]
        benchmark_accuracy = accuracy(cases)
        summaries.append(
            {
                "name": benchmark,
                "suite": benchmark,
                "ok": benchmark_accuracy >= min_accuracy,
                "metrics": {
                    "accuracy": benchmark_accuracy,
                    "case_count": len(cases),
                    "capability_count": len({item.capability for item in cases if item.capability}),
                    "expected_recall": _ratio(
                        sum(1 for item in cases if item.expected_ok),
                        len(cases),
                    ),
                    "forbidden_leak_rate": _ratio(
                        sum(1 for item in cases if not item.forbidden_ok),
                        len(cases),
                    ),
                    "latency_ms_p95": p95([item.latency_ms for item in cases]),
                },
                "capability_breakdown": capability_breakdown(cases),
            }
        )
    return summaries


def case_payload(item: CaseRunResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "benchmark": item.benchmark,
        "case_id": item.case_id,
        "capability": item.capability,
        "status": "ok" if item.ok else "failed",
        "expected_ok": item.expected_ok,
        "forbidden_ok": item.forbidden_ok,
        "missing_terms": list(item.missing_terms),
        "leaked_terms": list(item.leaked_terms),
        "item_ids": list(item.item_ids),
        "latency_ms": item.latency_ms,
    }
    if item.question_preview:
        payload["question_preview"] = item.question_preview[:240]
    return payload


def case_failures(run_results: Sequence[CaseRunResult]) -> list[dict[str, object]]:
    return [_case_failure_payload(item) for item in run_results if not item.ok]


def _case_failure_payload(item: CaseRunResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "case_id": item.case_id,
        "category": item.benchmark,
        "capability": item.capability,
        "reason": "missing_expected_terms" if item.missing_terms else "forbidden_terms_leaked",
        "missing_terms": list(item.missing_terms),
        "leaked_terms": list(item.leaked_terms),
    }
    if item.question_preview:
        payload["question_preview"] = item.question_preview[:240]
    return payload


def bounded_progress_fields(fields: Mapping[str, object]) -> dict[str, object]:
    bounded: dict[str, object] = {}
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, str):
            bounded[key] = value[:240]
        elif isinstance(value, bool | int | float):
            bounded[key] = value
        elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
            bounded[key] = [
                item[:120] if isinstance(item, str) else item
                for item in value[:20]
                if isinstance(item, str | bool | int | float)
            ]
        elif isinstance(value, Mapping):
            bounded[key] = {
                str(map_key)[:80]: map_value[:120] if isinstance(map_value, str) else map_value
                for map_key, map_value in list(value.items())[:20]
                if isinstance(map_value, str | bool | int | float)
            }
    return bounded


def progress_timing_fields(
    *,
    processed_case_count: int,
    total_case_count: int,
    started: float,
) -> dict[str, object]:
    if processed_case_count <= 0 or total_case_count <= 0:
        return {
            "average_case_ms": 0.0,
            "cases_per_second": 0.0,
            "estimated_remaining_ms": 0.0,
            "estimated_total_ms": 0.0,
            "eta_confidence": "unavailable",
        }
    elapsed_seconds = max(0.001, time.perf_counter() - started)
    cases_per_second = processed_case_count / elapsed_seconds
    average_case_ms = elapsed_seconds / processed_case_count * 1000
    remaining_case_count = max(0, total_case_count - processed_case_count)
    estimated_remaining_ms = (
        remaining_case_count / cases_per_second * 1000 if cases_per_second > 0 else 0.0
    )
    estimated_total_ms = elapsed_seconds * 1000 + estimated_remaining_ms
    return {
        "average_case_ms": round(average_case_ms, 2),
        "cases_per_second": round(cases_per_second, 4),
        "estimated_remaining_ms": round(estimated_remaining_ms, 2),
        "estimated_total_ms": round(estimated_total_ms, 2),
        "eta_confidence": "stable" if processed_case_count >= 3 else "warming_up",
    }


def progress_case_outcome_fields(
    *,
    processed_case_count: int,
    run_results: Sequence[CaseRunResult],
    failures: Sequence[Mapping[str, object]],
    total_case_count: int,
) -> dict[str, object]:
    bounded_processed_case_count = max(0, min(processed_case_count, total_case_count))
    succeeded_case_count = sum(1 for item in run_results if item.ok)
    failed_case_count = sum(1 for item in run_results if not item.ok)
    remaining_case_count = max(0, total_case_count - bounded_processed_case_count)
    result: dict[str, object] = {
        "remaining_case_count": remaining_case_count,
        "succeeded_case_count": succeeded_case_count,
        "failed_case_count": failed_case_count,
        "resume_pending_case_count": remaining_case_count + failed_case_count,
        "failure_count": len(failures),
        "failure_report_count": len(failures),
        "failure_case_ratio": _ratio(failed_case_count, bounded_processed_case_count),
        "recent_failed_case_ids": [
            item.case_id for item in run_results if not item.ok
        ][-10:],
    }
    if run_results:
        last = run_results[-1]
        result.update(
            {
                "last_case_benchmark": last.benchmark,
                "last_case_id": last.case_id,
                "last_case_status": "ok" if last.ok else "failed",
                "last_case_capability": last.capability,
                "last_case_latency_ms": round(last.latency_ms, 2),
            }
        )
        if last.question_preview:
            result["last_question_preview"] = last.question_preview[:240]
    return result


def dataset_source_metadata(
    *,
    dataset_path: Path,
    dataset_hash: str,
    source_kind: str,
    case_count: int | None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "source_kind": source_kind,
        "path_label": dataset_path.name,
        "sha256": dataset_hash,
        "size_bytes": dataset_path.stat().st_size,
    }
    if isinstance(case_count, int):
        result["case_count"] = case_count
    return result


def benchmark_summary_case_count(summary: Mapping[str, object]) -> int | None:
    metrics = summary.get("metrics")
    if not isinstance(metrics, Mapping):
        return None
    case_count = metrics.get("case_count")
    return case_count if isinstance(case_count, int) else None


def benchmark_metric_map(
    run_results: Sequence[CaseRunResult],
) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[CaseRunResult]] = defaultdict(list)
    for item in run_results:
        benchmark = _metric_key_part(item.benchmark) or "unknown_benchmark"
        grouped[benchmark].append(item)
    return {
        benchmark: {
            "case_count": len(items),
            "failure_count": sum(1 for item in items if not item.ok),
            "accuracy": accuracy(items),
            "latency_ms_p95": p95([item.latency_ms for item in items]),
            "capability_count": len({item.capability for item in items if item.capability}),
            "capability_breakdown": capability_breakdown(items),
        }
        for benchmark, items in sorted(grouped.items())
    }


def capability_breakdown(cases: Sequence[CaseRunResult]) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[CaseRunResult]] = defaultdict(list)
    for item in cases:
        capability = _metric_key_part(item.capability)
        if capability:
            grouped[capability].append(item)
    return {
        capability: {
            "case_count": len(items),
            "failure_count": sum(1 for item in items if not item.ok),
            "accuracy": accuracy(items),
            "expected_recall": _ratio(
                sum(1 for item in items if item.expected_ok),
                len(items),
            ),
            "forbidden_leak_rate": _ratio(
                sum(1 for item in items if not item.forbidden_ok),
                len(items),
            ),
        }
        for capability, items in sorted(grouped.items())
    }


def flat_capability_accuracy(run_results: Sequence[CaseRunResult]) -> dict[str, float]:
    return {
        capability: accuracy(items)
        for capability, items in _group_by_benchmark_capability(run_results).items()
    }


def flat_capability_case_count(run_results: Sequence[CaseRunResult]) -> dict[str, int]:
    return {
        capability: len(items)
        for capability, items in _group_by_benchmark_capability(run_results).items()
    }


def flat_capability_failure_count(run_results: Sequence[CaseRunResult]) -> dict[str, int]:
    return {
        capability: sum(1 for item in items if not item.ok)
        for capability, items in _group_by_benchmark_capability(run_results).items()
    }


def accuracy(run_results: Sequence[CaseRunResult]) -> float:
    return _ratio(sum(1 for item in run_results if item.ok), len(run_results))


def p95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95))))
    return round(ordered[index], 2)


def _group_by_benchmark_capability(
    run_results: Sequence[CaseRunResult],
) -> dict[str, list[CaseRunResult]]:
    grouped: dict[str, list[CaseRunResult]] = defaultdict(list)
    for item in run_results:
        benchmark = _metric_key_part(item.benchmark) or "unknown_benchmark"
        capability = _metric_key_part(item.capability) or "unknown_capability"
        grouped[f"{benchmark}:{capability}"].append(item)
    return dict(sorted(grouped.items()))


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _metric_key_part(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    normalized = value.strip().casefold().replace("-", "_").replace(" ", "_")
    return "".join(char for char in normalized if char.isalnum() or char == "_").strip("_")
