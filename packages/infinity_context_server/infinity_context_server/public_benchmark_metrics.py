"""JSON-safe metric summaries for public memory benchmark runs."""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from infinity_context_server.memory_comparison_source_identity import (
    safe_item_id_for_output as _safe_item_id_for_output,
)
from infinity_context_server.memory_comparison_source_identity import (
    safe_source_refs_for_output as _safe_source_refs_for_output,
)
from infinity_context_server.public_benchmark_case_diagnostics import (
    artifact_text_value as _artifact_text_value,
)
from infinity_context_server.public_benchmark_case_diagnostics import (
    preview_value as _preview_value,
)
from infinity_context_server.public_benchmark_checkpoint import CaseRunResult

_PREVIEW_CHARS = 240
_TERM_CHARS = 120
_EVIDENCE_PREVIEW_CHARS = 360
_MAX_TERM_VALUES = 20


def run_metric_summary(run_results: Sequence[CaseRunResult]) -> dict[str, object]:
    """Return bounded aggregate metrics that are safe for checkpoints/results."""

    return {
        "case_count": len(run_results),
        "failure_count": sum(1 for item in run_results if not item.ok),
        "accuracy": accuracy(run_results),
        "latency_ms_p95": p95([item.latency_ms for item in run_results]),
        "capability_count": len({item.capability for item in run_results if item.capability}),
        **coverage_summary(run_results),
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
                    **coverage_summary(cases),
                },
                "capability_breakdown": capability_breakdown(cases),
            }
        )
    return summaries


def case_payload(item: CaseRunResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "benchmark": _safe_scalar_text(item.benchmark, max_chars=_TERM_CHARS),
        "case_id": _safe_scalar_text(item.case_id, max_chars=_TERM_CHARS),
        "capability": _safe_scalar_text(item.capability, max_chars=_TERM_CHARS),
        "status": "ok" if item.ok else "failed",
        "expected_ok": item.expected_ok,
        "forbidden_ok": item.forbidden_ok,
        "missing_terms": _safe_preview_list(item.missing_terms),
        "leaked_terms": _safe_preview_list(item.leaked_terms),
        "item_ids": _safe_item_id_list(item.item_ids),
        "latency_ms": item.latency_ms,
        "coverage": _case_coverage_payload(item),
        "covered_terms": _safe_preview_list(item.covered_terms),
        "covered_evidence_refs": _safe_source_ref_list(item.covered_evidence_refs),
        "missing_evidence_refs": _safe_source_ref_list(item.missing_evidence_refs),
    }
    if item.question_preview:
        payload["question_preview"] = _safe_preview_text(
            item.question_preview,
            max_chars=_PREVIEW_CHARS,
        )
    if not item.ok and item.answer_preview:
        payload["answer_preview"] = _safe_preview_text(
            item.answer_preview,
            max_chars=_PREVIEW_CHARS,
        )
    if not item.ok and item.expected_terms_preview:
        payload["expected_terms_preview"] = _safe_preview_list(
            item.expected_terms_preview
        )
    if not item.ok and item.evidence_refs:
        payload["evidence_refs"] = _safe_source_ref_list(item.evidence_refs)
    if not item.ok and item.evidence_ref_previews:
        payload["evidence_ref_previews"] = _safe_preview_list(
            item.evidence_ref_previews,
            max_chars=_EVIDENCE_PREVIEW_CHARS,
        )
    if not item.ok and item.missing_evidence_ref_previews:
        payload["missing_evidence_ref_previews"] = _safe_preview_list(
            item.missing_evidence_ref_previews,
            max_chars=_EVIDENCE_PREVIEW_CHARS,
        )
    return payload


def case_failures(run_results: Sequence[CaseRunResult]) -> list[dict[str, object]]:
    return [_case_failure_payload(item) for item in run_results if not item.ok]


def _case_failure_payload(item: CaseRunResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "case_id": _safe_scalar_text(item.case_id, max_chars=_TERM_CHARS),
        "category": _safe_scalar_text(item.benchmark, max_chars=_TERM_CHARS),
        "capability": _safe_scalar_text(item.capability, max_chars=_TERM_CHARS),
        "reason": "missing_expected_terms" if item.missing_terms else "forbidden_terms_leaked",
        "missing_terms": _safe_preview_list(item.missing_terms),
        "leaked_terms": _safe_preview_list(item.leaked_terms),
    }
    if item.question_preview:
        payload["question_preview"] = _safe_preview_text(
            item.question_preview,
            max_chars=_PREVIEW_CHARS,
        )
    if item.answer_preview:
        payload["answer_preview"] = _safe_preview_text(
            item.answer_preview,
            max_chars=_PREVIEW_CHARS,
        )
    if item.expected_terms_preview:
        payload["expected_terms_preview"] = _safe_preview_list(
            item.expected_terms_preview
        )
    if item.evidence_refs:
        payload["evidence_refs"] = _safe_source_ref_list(item.evidence_refs)
    if item.evidence_ref_previews:
        payload["evidence_ref_previews"] = _safe_preview_list(
            item.evidence_ref_previews,
            max_chars=_EVIDENCE_PREVIEW_CHARS,
        )
    if item.covered_terms:
        payload["covered_terms"] = _safe_preview_list(item.covered_terms)
    if item.covered_evidence_refs:
        payload["covered_evidence_refs"] = _safe_source_ref_list(
            item.covered_evidence_refs
        )
    if item.missing_evidence_refs:
        payload["missing_evidence_refs"] = _safe_source_ref_list(
            item.missing_evidence_refs
        )
    if item.missing_evidence_ref_previews:
        payload["missing_evidence_ref_previews"] = _safe_preview_list(
            item.missing_evidence_ref_previews,
            max_chars=_EVIDENCE_PREVIEW_CHARS,
        )
    return payload


def _case_coverage_payload(item: CaseRunResult) -> dict[str, object]:
    expected_term_count = len(item.covered_terms) + len(item.missing_terms)
    evidence_ref_count = len(item.covered_evidence_refs) + len(item.missing_evidence_refs)
    return {
        "expected_term_count": expected_term_count,
        "covered_expected_term_count": len(item.covered_terms),
        "expected_term_coverage": _ratio(len(item.covered_terms), expected_term_count),
        "evidence_ref_count": evidence_ref_count,
        "covered_evidence_ref_count": len(item.covered_evidence_refs),
        "evidence_ref_coverage": _ratio(len(item.covered_evidence_refs), evidence_ref_count),
    }


def bounded_progress_fields(fields: Mapping[str, object]) -> dict[str, object]:
    return bounded_public_artifact_fields(fields)


def bounded_public_artifact_fields(fields: Mapping[str, object]) -> dict[str, object]:
    bounded: dict[str, object] = {}
    for raw_key, value in fields.items():
        if value is None:
            continue
        key = _safe_field_key(raw_key)
        if not key:
            continue
        if isinstance(value, str):
            safe_value = _safe_artifact_text(key, value, max_chars=240)
            if safe_value:
                bounded[key] = safe_value
        elif isinstance(value, bool | int | float):
            bounded[key] = value
        elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
            bounded[key] = _safe_artifact_sequence(key, value, max_chars=120)
        elif isinstance(value, Mapping):
            nested = _safe_artifact_mapping(key, value)
            if nested:
                bounded[key] = nested
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
            _safe_progress_identifier(item.case_id) for item in run_results if not item.ok
        ][-10:],
    }
    if run_results:
        last = run_results[-1]
        result.update(
            {
                "last_case_benchmark": _safe_progress_identifier(last.benchmark),
                "last_case_id": _safe_progress_identifier(last.case_id),
                "last_case_status": "ok" if last.ok else "failed",
                "last_case_capability": _safe_progress_identifier(last.capability),
                "last_case_latency_ms": round(last.latency_ms, 2),
            }
        )
        if last.question_preview:
            result["last_question_preview"] = _safe_preview_text(
                last.question_preview,
                max_chars=_PREVIEW_CHARS,
            )
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
            **coverage_summary(items),
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
            **coverage_summary(items),
        }
        for capability, items in sorted(grouped.items())
    }


def coverage_summary(run_results: Sequence[CaseRunResult]) -> dict[str, object]:
    expected_term_count = sum(
        len(item.covered_terms) + len(item.missing_terms) for item in run_results
    )
    covered_expected_term_count = sum(len(item.covered_terms) for item in run_results)
    evidence_ref_count = sum(
        len(item.covered_evidence_refs) + len(item.missing_evidence_refs)
        for item in run_results
    )
    covered_evidence_ref_count = sum(
        len(item.covered_evidence_refs) for item in run_results
    )
    return {
        "expected_term_count": expected_term_count,
        "covered_expected_term_count": covered_expected_term_count,
        "expected_term_coverage": _ratio(
            covered_expected_term_count,
            expected_term_count,
        ),
        "evidence_ref_count": evidence_ref_count,
        "covered_evidence_ref_count": covered_evidence_ref_count,
        "evidence_ref_coverage": _ratio(
            covered_evidence_ref_count,
            evidence_ref_count,
        ),
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


def _safe_preview_text(value: object, *, max_chars: int) -> str:
    return _preview_value(value, max_chars=max_chars)


def _safe_progress_identifier(value: object) -> str:
    return _safe_preview_text(value, max_chars=_PREVIEW_CHARS)


def _safe_preview_list(
    values: Sequence[str],
    *,
    max_chars: int = _TERM_CHARS,
    limit: int = _MAX_TERM_VALUES,
) -> list[str]:
    previews: list[str] = []
    for value in values[:limit]:
        preview = _safe_preview_text(value, max_chars=max_chars)
        if preview:
            previews.append(preview)
    return previews


def _safe_item_id_list(values: Sequence[str], *, limit: int = _MAX_TERM_VALUES) -> list[str]:
    item_ids: list[str] = []
    for value in values[:limit]:
        item_id = _safe_item_id_for_output(value)
        if not item_id:
            refs = _safe_source_refs_for_output((value,))
            item_id = refs[0] if refs else ""
        if item_id and item_id not in item_ids:
            item_ids.append(item_id)
    return item_ids


def _safe_source_ref_list(
    values: Sequence[str],
    *,
    limit: int = _MAX_TERM_VALUES,
) -> list[str]:
    refs: list[str] = []
    for value in values[:limit]:
        for ref in _safe_source_refs_for_output((value,)):
            if ref and ref not in refs:
                refs.append(ref[:_TERM_CHARS])
    return refs


def _safe_field_key(value: object) -> str:
    return _artifact_text_value(value, max_chars=80)


def _safe_artifact_mapping(
    parent_key: str,
    values: Mapping[object, object],
) -> dict[str, object]:
    bounded: dict[str, object] = {}
    for raw_key, raw_value in list(values.items())[:20]:
        if raw_value is None:
            continue
        key = _safe_field_key(raw_key)
        if not key:
            continue
        field_key = f"{parent_key}.{key}"
        if isinstance(raw_value, str):
            safe_value = _safe_artifact_text(field_key, raw_value, max_chars=120)
            if safe_value:
                bounded[key] = safe_value
        elif isinstance(raw_value, bool | int | float):
            bounded[key] = raw_value
        elif isinstance(raw_value, Sequence) and not isinstance(raw_value, str | bytes):
            bounded[key] = _safe_artifact_sequence(
                field_key,
                raw_value,
                max_chars=120,
            )
        elif isinstance(raw_value, Mapping):
            nested = _safe_artifact_mapping(field_key, raw_value)
            if nested:
                bounded[key] = nested
    return bounded


def _safe_artifact_sequence(
    key: str,
    values: Sequence[object],
    *,
    max_chars: int,
) -> list[object]:
    if _is_preview_field(key):
        return [
            preview
            for item in values[:20]
            if (preview := _safe_preview_text(item, max_chars=max_chars))
        ]
    if _is_source_ref_field(key):
        refs: list[str] = []
        for item in values[:20]:
            if not isinstance(item, str | bool | int | float):
                continue
            for ref in _safe_source_refs_for_output((item,)):
                safe_ref = ref[:max_chars]
                if safe_ref and safe_ref not in refs:
                    refs.append(safe_ref)
                if len(refs) >= 20:
                    return refs
        return refs
    if _is_item_id_field(key):
        item_ids: list[str] = []
        for item in values[:20]:
            if not isinstance(item, str | bool | int | float):
                continue
            item_id = _safe_item_id_for_output(item)
            if not item_id:
                refs = _safe_source_refs_for_output((item,))
                item_id = refs[0] if refs else ""
            item_id = item_id[:max_chars]
            if item_id and item_id not in item_ids:
                item_ids.append(item_id)
        return item_ids
    result: list[object] = []
    for item in values[:20]:
        if isinstance(item, str):
            text = _safe_scalar_text(item, max_chars=max_chars)
            if text:
                result.append(text)
        elif isinstance(item, bool | int | float):
            result.append(item)
        elif isinstance(item, Mapping):
            nested = _safe_artifact_mapping(key, item)
            if nested:
                result.append(nested)
    return result


def _safe_artifact_text(key: str, value: object, *, max_chars: int) -> str:
    if _is_preview_field(key):
        return _safe_preview_text(value, max_chars=max_chars)
    if _is_source_ref_field(key):
        refs = _safe_source_refs_for_output((value,))
        return refs[0][:max_chars] if refs else ""
    if _is_item_id_field(key):
        item_id = _safe_item_id_for_output(value)
        if not item_id:
            refs = _safe_source_refs_for_output((value,))
            item_id = refs[0] if refs else ""
        return item_id[:max_chars]
    return _safe_scalar_text(value, max_chars=max_chars)


def _safe_scalar_text(value: object, *, max_chars: int) -> str:
    return _artifact_text_value(value, max_chars=max_chars)


def _is_preview_field(key: str) -> bool:
    return "preview" in key.casefold()


def _is_source_ref_field(key: str) -> bool:
    normalized = key.casefold()
    return "evidence_ref" in normalized or "source_ref" in normalized


def _is_item_id_field(key: str) -> bool:
    normalized = key.casefold()
    return normalized.endswith("item_id") or normalized.endswith("item_ids")


def _metric_key_part(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    normalized = value.strip().casefold().replace("-", "_").replace(" ", "_")
    return "".join(char for char in normalized if char.isalnum() or char == "_").strip("_")
