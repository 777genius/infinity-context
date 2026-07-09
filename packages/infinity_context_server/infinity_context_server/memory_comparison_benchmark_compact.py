"""Compact report projection for memory comparison benchmark reports."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from math import isfinite

from infinity_context_server.memory_comparison_benchmark_compact_fast_gate import (
    _compact_fast_gate_summary,
)
from infinity_context_server.memory_comparison_benchmark_compact_samples import (
    _compact_count_mapping,
    _compact_diagnostic_source_refs,
    _compact_evidence_bundle_coverage,
    _compact_item_id,
    _compact_item_id_key,
    _compact_item_ids,
    _compact_item_ids_key,
    _compact_key_name,
    _compact_safe_text,
    _compact_sample_text,
    _compact_should_omit_key,
    _compact_source_id_key,
    _compact_source_id_text,
    _compact_source_ref_key,
    _compact_source_ref_text,
    _compact_source_refs_key,
    _retrieval_source_counts,
    _source_id_from_compact_ref,
)
from infinity_context_server.memory_comparison_benchmark_config import (
    _COMPACT_BACKEND_METRIC_KEYS,
    _COMPACT_OMIT,
    _MAX_COMPACT_FAILURE_MAPPING_ITEMS,
    _MAX_COMPACT_FAILURE_SEQUENCE_ITEMS,
    _MAX_COMPACT_FAILURE_TEXT_CHARS,
    _MAX_COMPACT_REQUESTED_CAPABILITIES,
    _MAX_COMPACT_REQUESTED_CASE_IDS,
    MEMORY_COMPARISON_REPORT_COMPACT,
    MEMORY_COMPARISON_REPORT_FULL,
)
from infinity_context_server.memory_comparison_benchmark_shared import (
    _group_by,
    _mapping,
    _numeric_summary,
    _positive_int,
    _retrieved_count,
    _str_tuple,
)
from infinity_context_server.memory_comparison_compact_gap_report import (
    compact_text_list as _compact_text_list,
)


def _report_payload(
    result: dict[str, object],
    *,
    report_mode: str,
    compact_failure_limit: int,
) -> dict[str, object]:
    if report_mode == MEMORY_COMPARISON_REPORT_FULL:
        return result
    compact_failure_limit = max(0, int(compact_failure_limit))
    return _compact_report(result, failure_limit=compact_failure_limit)


def _compact_report(
    result: Mapping[str, object],
    *,
    failure_limit: int,
) -> dict[str, object]:
    evaluations = [
        item for item in result.get("evaluations", ()) if isinstance(item, Mapping)
    ]
    failure_analysis = [
        item for item in result.get("failure_analysis", ()) if isinstance(item, Mapping)
    ]
    failures = [item for item in result.get("failures", ()) if isinstance(item, Mapping)]
    requested_case_ids = _str_tuple(result.get("requested_case_ids", ()))
    requested_capabilities = _str_tuple(result.get("requested_capabilities", ()))
    metadata = {
        **dict(_mapping(result.get("metadata"))),
        "report_mode": MEMORY_COMPARISON_REPORT_COMPACT,
        "full_evaluation_count": len(evaluations),
        "compact_failure_limit": failure_limit,
        "requested_case_id_count": len(requested_case_ids),
        "requested_case_ids_omitted": max(
            len(requested_case_ids) - _MAX_COMPACT_REQUESTED_CASE_IDS,
            0,
        ),
        "requested_capability_count": len(requested_capabilities),
        "requested_capabilities_omitted": max(
            len(requested_capabilities) - _MAX_COMPACT_REQUESTED_CAPABILITIES,
            0,
        ),
    }
    compact_metadata = _compact_failure_value(metadata)
    metadata = compact_metadata if isinstance(compact_metadata, dict) else {}
    diagnostics = _compact_diagnostics(evaluations)
    diagnostics["failure_provenance_summary"] = _compact_failure_provenance_summary(
        failure_analysis,
        failures,
    )
    compact: dict[str, object] = {
        "schema_version": result.get("schema_version"),
        "suite": result.get("suite"),
        "source_suite": result.get("source_suite"),
        "status": result.get("status"),
        "ok": result.get("ok"),
        "benchmark": result.get("benchmark"),
        "benchmark_scope": result.get("benchmark_scope"),
        "evaluation_mode": result.get("evaluation_mode"),
        "run_id": result.get("run_id"),
        "dataset_path_label": result.get("dataset_path_label"),
        "dataset_hash": result.get("dataset_hash"),
        "requested_case_ids": _compact_text_list(
            requested_case_ids,
            item_limit=_MAX_COMPACT_REQUESTED_CASE_IDS,
        ),
        "requested_capabilities": _compact_text_list(
            requested_capabilities,
            item_limit=_MAX_COMPACT_REQUESTED_CAPABILITIES,
        ),
        "case_selection": _compact_case_selection(result.get("case_selection")),
        "metadata": metadata,
        "metrics": _compact_failure_value(result.get("metrics", {})),
        "backend_metrics": _compact_backend_metrics(result.get("backend_metrics")),
        "backend_comparison": _compact_failure_value(
            result.get("backend_comparison", {})
        ),
        "diagnostics": diagnostics,
        "failure_analysis": _compact_failure_entries(
            failure_analysis,
            limit=failure_limit,
        ),
        "failures": _compact_failure_entries(failures, limit=failure_limit),
        "evaluations": [],
        "elapsed_ms": result.get("elapsed_ms", 0.0),
    }
    provenance = result.get("provenance")
    if isinstance(provenance, Mapping):
        compact["provenance"] = dict(provenance)
    return compact


def _compact_failure_entries(
    entries: Sequence[Mapping[str, object]],
    *,
    limit: int,
) -> list[dict[str, object]]:
    compact_entries: list[dict[str, object]] = []
    for entry in entries[: max(0, limit)]:
        compact = _compact_failure_value(entry)
        if isinstance(compact, dict):
            compact_entries.append(compact)
    return compact_entries


def _compact_backend_metrics(value: object) -> dict[str, object]:
    compact: dict[str, object] = {}
    for backend_name, raw_metrics in sorted(
        _mapping(value).items(),
        key=lambda item: str(item[0]),
    ):
        backend_key = _compact_sample_text(backend_name)
        metrics = _mapping(raw_metrics)
        if not backend_key or not metrics:
            continue
        compact_metrics: dict[str, object] = {}
        for key in sorted(_COMPACT_BACKEND_METRIC_KEYS):
            if key in metrics:
                compact_metrics[key] = _compact_failure_value(metrics[key])
        compact[backend_key] = compact_metrics
    return compact


def _compact_case_selection(value: object) -> dict[str, object]:
    selection = dict(_mapping(value))
    for key, limit in (
        ("requested_case_ids", _MAX_COMPACT_REQUESTED_CASE_IDS),
        ("missing_case_ids", _MAX_COMPACT_REQUESTED_CASE_IDS),
        ("requested_capabilities", _MAX_COMPACT_REQUESTED_CAPABILITIES),
        ("missing_capabilities", _MAX_COMPACT_REQUESTED_CAPABILITIES),
    ):
        values = _str_tuple(selection.get(key))
        if not values:
            continue
        selection[key] = _compact_text_list(values, item_limit=limit)
        selection[f"{key}_omitted"] = max(len(values) - limit, 0)
    for key in ("available_capability_counts", "selected_capability_counts"):
        compact_counts = _compact_count_mapping(selection.get(key), limit=20)
        if compact_counts:
            selection[key] = compact_counts
    return selection


def _compact_failure_value(value: object, *, key: str | None = None) -> object:
    key_name = _compact_key_name(key)
    if _compact_should_omit_key(key_name):
        return _COMPACT_OMIT
    if _compact_source_refs_key(key_name):
        return list(_compact_diagnostic_source_refs(value, limit=8))
    if _compact_source_ref_key(key_name):
        return _compact_source_ref_text(value) or _COMPACT_OMIT
    if _compact_source_id_key(key_name):
        return _compact_source_id_text(value) or _COMPACT_OMIT
    if _compact_item_ids_key(key_name):
        return _compact_item_ids(value, limit=8)
    if _compact_item_id_key(key_name):
        return _compact_item_id(value) or _COMPACT_OMIT
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if isfinite(value) else _compact_failure_text(value)
    if isinstance(value, str):
        return _compact_failure_text(value)
    if isinstance(value, Mapping):
        compact: dict[str, object] = {}
        for key, raw_value in sorted(value.items(), key=lambda item: str(item[0]))[
            :_MAX_COMPACT_FAILURE_MAPPING_ITEMS
        ]:
            raw_key = str(key)
            if _compact_should_omit_key(_compact_key_name(raw_key)):
                continue
            compact_value = _compact_failure_value(raw_value, key=raw_key)
            if compact_value is _COMPACT_OMIT:
                continue
            compact_key = _compact_failure_text(
                raw_key,
                limit=_MAX_COMPACT_FAILURE_TEXT_CHARS,
            )
            if compact_key:
                compact[compact_key] = compact_value
        return compact
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        values: list[object] = []
        for item in tuple(value)[:_MAX_COMPACT_FAILURE_SEQUENCE_ITEMS]:
            compact_value = _compact_failure_value(item)
            if compact_value is not _COMPACT_OMIT:
                values.append(compact_value)
        return values
    return _compact_failure_text(value)


def _compact_failure_text(
    value: object,
    *,
    limit: int = _MAX_COMPACT_FAILURE_TEXT_CHARS,
) -> str:
    return _compact_safe_text(value, limit=limit, normalize_whitespace=True)


def _compact_diagnostics(
    evaluations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    by_backend = _group_by(evaluations, key="backend")
    return {
        "evaluations_omitted": len(evaluations),
        "backend_summaries": {
            backend: _compact_backend_diagnostics(items)
            for backend, items in sorted(by_backend.items())
        },
    }


def _compact_failure_provenance_summary(
    failure_analysis: Sequence[Mapping[str, object]],
    failures: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    entries = tuple(failure_analysis) or tuple(failures)
    diagnostic_reasons: Counter[str] = Counter()
    missing_source_ids: Counter[str] = Counter()
    missing_turn_ref_count = 0
    same_source_missing_count = 0
    near_retrieved_window_count = 0
    source_absent_count = 0
    selected_source_refless_failure_count = 0
    window_samples: list[dict[str, object]] = []
    for entry in entries:
        diagnostic_reasons.update(_str_tuple(entry.get("diagnostic_reason_codes")))
        diagnostics = _mapping(entry.get("diagnostics"))
        bundle = _mapping(diagnostics.get("bundle"))
        if (
            _positive_int(bundle.get("selected_bundle_source_refless_item_count")) or 0
        ) > 0:
            selected_source_refless_failure_count += 1
        locality = _mapping(diagnostics.get("missing_evidence_source_locality"))
        missing_turn_ref_count += (
            _positive_int(locality.get("missing_turn_ref_count")) or 0
        )
        same_source_missing_count += (
            _positive_int(locality.get("same_source_missing_count")) or 0
        )
        near_retrieved_window_count += (
            _positive_int(locality.get("near_retrieved_window_count")) or 0
        )
        source_absent_count += _positive_int(locality.get("source_absent_count")) or 0
        windows = locality.get("missing_ref_windows")
        if not isinstance(windows, Sequence) or isinstance(windows, str | bytes):
            continue
        for window in windows:
            if not isinstance(window, Mapping):
                continue
            ref = _compact_source_ref_text(window.get("ref") or "")
            source_id = _compact_source_id_text(window.get("source_id") or "")
            if not source_id and ref:
                source_id = _source_id_from_compact_ref(ref)
            if source_id:
                missing_source_ids[source_id] += 1
            if len(window_samples) >= 8:
                continue
            sample: dict[str, object] = {
                "case_id": _compact_failure_text(entry.get("case_id") or ""),
                "ref": ref,
                "source_id": source_id,
                "retrieved_same_source": bool(window.get("retrieved_same_source")),
                "bundle_same_source": bool(window.get("bundle_same_source")),
            }
            for key in (
                "nearest_retrieved_turn_ref",
                "nearest_retrieved_turn_distance",
                "nearest_bundle_turn_ref",
                "nearest_bundle_turn_distance",
            ):
                if key in window:
                    compact_value = _compact_failure_value(window[key], key=key)
                    if compact_value is not _COMPACT_OMIT:
                        sample[key] = compact_value
            window_samples.append(sample)
    return {
        "schema_version": "compact_failure_provenance_summary.v1",
        "failure_count": len(entries),
        "diagnostic_reason_counts": _compact_count_mapping(
            diagnostic_reasons,
            limit=20,
        ),
        "missing_evidence_source_locality": {
            "missing_turn_ref_count": missing_turn_ref_count,
            "same_source_missing_count": same_source_missing_count,
            "near_retrieved_window_count": near_retrieved_window_count,
            "source_absent_count": source_absent_count,
            "top_missing_source_ids": {
                _compact_failure_text(source_id): count
                for source_id, count in missing_source_ids.most_common(8)
            },
            "sample_windows": window_samples,
        },
        "selected_source_refless_failure_count": selected_source_refless_failure_count,
    }


def _compact_backend_diagnostics(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    retrievals = [_mapping(item.get("retrieval")) for item in items]
    qualities = [_mapping(item.get("retrieval_quality")) for item in items]
    return {
        "retrieved_count": _numeric_summary(
            _retrieved_count(item) for item in items
        ),
        "search_latency_ms": _numeric_summary(
            float(retrieval.get("latency_ms", 0.0)) for retrieval in retrievals
        ),
        "context_tokens": _numeric_summary(
            float(retrieval.get("context_token_count", 0.0))
            for retrieval in retrievals
        ),
        "expected_term_recall": _numeric_summary(
            float(quality.get("expected_term_recall", 0.0)) for quality in qualities
        ),
        "evidence_term_recall": _numeric_summary(
            float(quality.get("evidence_term_recall", 0.0))
            for quality in qualities
            if "evidence_term_recall" in quality
        ),
        "limited_by_http_api_caps_count": sum(
            1
            for retrieval in retrievals
            if bool(_mapping(retrieval.get("metadata")).get("limited_by_http_api_caps"))
        ),
        "retrieval_source_counts": _retrieval_source_counts(items),
        "evidence_bundle_coverage": _compact_evidence_bundle_coverage(items),
        "fast_gate_summary": _compact_fast_gate_summary(items),
    }


