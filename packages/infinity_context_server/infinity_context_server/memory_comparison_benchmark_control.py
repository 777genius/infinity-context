"""Benchmark setup, selection, timeout, and report IO helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import isfinite
from pathlib import Path

from infinity_context_server.memory_comparison_benchmark_config import (
    _LOCOMO_FAST_CASE_SET_GROUPS,
    _LOCOMO_FAST_CASES_PER_GROUP,
    MEMORY_COMPARISON_CASE_SET_ALL,
    MEMORY_COMPARISON_CASE_SETS,
    MEMORY_COMPARISON_MODE,
    MEMORY_COMPARISON_REPORT_FULL,
    MEMORY_COMPARISON_REPORT_MODES,
    MEMORY_COMPARISON_SCHEMA_VERSION,
    MEMORY_COMPARISON_SUITE,
)
from infinity_context_server.memory_comparison_benchmark_shared import _elapsed_ms
from infinity_context_server.memory_comparison_locomo_cases import (
    _case_capability,
    _case_group,
    _case_is_scored,
)
from infinity_context_server.public_benchmark import (
    LOCOMO_BENCHMARK_SUITE,
    PUBLIC_MEMORY_BENCHMARK_SUITE,
)
from infinity_context_server.public_benchmark_artifacts import write_json_atomic
from infinity_context_server.public_benchmark_models import (
    BenchmarkValidationError,
    PublicBenchmarkCase,
)
from infinity_context_server.public_benchmark_selection import (
    case_selection_missing_capabilities,
    case_selection_missing_case_ids,
    missing_capability_failures,
    missing_case_id_failures,
)


def _normalize_case_set(value: str | None) -> str:
    normalized = (value or MEMORY_COMPARISON_CASE_SET_ALL).strip()
    if normalized not in MEMORY_COMPARISON_CASE_SETS:
        raise BenchmarkValidationError(
            "Unsupported memory comparison case set: "
            f"{normalized}. Supported: {', '.join(MEMORY_COMPARISON_CASE_SETS)}"
        )
    return normalized


def _normalize_report_mode(value: str | None) -> str:
    normalized = (value or MEMORY_COMPARISON_REPORT_FULL).strip()
    if normalized not in MEMORY_COMPARISON_REPORT_MODES:
        raise BenchmarkValidationError(
            "Unsupported memory comparison report mode: "
            f"{normalized}. Supported: {', '.join(MEMORY_COMPARISON_REPORT_MODES)}"
        )
    return normalized


def _normalize_runtime_timeout_seconds(value: float | None) -> float | None:
    if value is None:
        return None
    timeout_seconds = float(value)
    if not isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise BenchmarkValidationError("runtime_timeout_seconds must be positive")
    return timeout_seconds


def _runtime_timeout_blocker(
    *,
    started: float,
    timeout_seconds: float | None,
    backend_name: str,
    stage: str,
    case: PublicBenchmarkCase | None = None,
) -> dict[str, object] | None:
    if timeout_seconds is None:
        return None
    elapsed_ms = _elapsed_ms(started)
    if elapsed_ms < timeout_seconds * 1000:
        return None
    blocker: dict[str, object] = {
        "case_id": case.case_id if case is not None else "suite_runtime",
        "backend": backend_name,
        "group": _case_group(case) if case is not None else "runtime",
        "stage": stage,
        "reason": "runtime_timeout_seconds_exceeded",
        "elapsed_ms": elapsed_ms,
        "timeout_seconds": timeout_seconds,
        "preserves_benchmark_honesty": True,
    }
    if case is not None:
        blocker["capability"] = _case_capability(case)
    return blocker


def _apply_case_set(
    cases: Sequence[PublicBenchmarkCase],
    *,
    case_set: str,
) -> tuple[tuple[PublicBenchmarkCase, ...], dict[str, object]]:
    selected_input = tuple(cases)
    if case_set == MEMORY_COMPARISON_CASE_SET_ALL:
        return selected_input, {
            "name": MEMORY_COMPARISON_CASE_SET_ALL,
            "input_count": len(selected_input),
            "selected_count": len(selected_input),
        }

    groups = _LOCOMO_FAST_CASE_SET_GROUPS[case_set]
    selected: list[PublicBenchmarkCase] = []
    selected_by_group: dict[str, int] = {}
    for group in groups:
        group_cases = [
            case
            for case in selected_input
            if case.benchmark == LOCOMO_BENCHMARK_SUITE
            and _case_is_scored(case)
            and _case_group(case) == group
        ]
        selected_slice = group_cases[:_LOCOMO_FAST_CASES_PER_GROUP]
        selected.extend(selected_slice)
        selected_by_group[group] = len(selected_slice)

    return tuple(selected), {
        "name": case_set,
        "input_count": len(selected_input),
        "selected_count": len(selected),
        "requested_groups": list(groups),
        "requested_per_group": _LOCOMO_FAST_CASES_PER_GROUP,
        "selected_by_group": selected_by_group,
        "goal": "fast_locomo_diagnostic_not_full_benchmark",
    }



def _empty_failure_report(
    *,
    dataset_path: Path,
    dataset_hash: str,
    run_id: str,
    backend_names: Sequence[str],
    case_selection: Mapping[str, object],
    requested_case_ids: Sequence[str],
    requested_capabilities: Sequence[str],
    top_k: int,
    cutoffs: Sequence[int],
    failures: Sequence[Mapping[str, object]],
    elapsed_ms: float,
) -> dict[str, object]:
    return {
        "schema_version": MEMORY_COMPARISON_SCHEMA_VERSION,
        "suite": MEMORY_COMPARISON_SUITE,
        "source_suite": PUBLIC_MEMORY_BENCHMARK_SUITE,
        "status": "failed",
        "ok": False,
        "benchmark_scope": "memory_system_side_by_side",
        "evaluation_mode": MEMORY_COMPARISON_MODE,
        "run_id": run_id,
        "dataset_path_label": dataset_path.name,
        "dataset_hash": dataset_hash,
        "requested_case_ids": list(requested_case_ids),
        "requested_capabilities": list(requested_capabilities),
        "case_selection": dict(case_selection or {}),
        "metadata": {
            "top_k": top_k,
            "top_k_cutoffs": list(cutoffs),
            "backend_names": list(backend_names),
        },
        "metrics": {
            "backend_count": len(backend_names),
            "case_count": 0,
            "evaluation_count": 0,
            "accuracy": 0.0,
            "elapsed_ms": elapsed_ms,
        },
        "backend_metrics": {},
        "backend_comparison": {},
        "evaluations": [],
        "failure_analysis": list(failures),
        "failures": list(failures),
        "elapsed_ms": elapsed_ms,
    }


def _setup_failures(
    cases: Sequence[PublicBenchmarkCase],
    case_selection: Mapping[str, object],
) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    if not cases:
        failures.append(
            {
                "case_id": "dataset",
                "backend": "setup",
                "group": "setup",
                "reason": "no_supported_cases",
            }
        )
    failures.extend(missing_case_id_failures(case_selection_missing_case_ids(case_selection)))
    failures.extend(
        missing_capability_failures(case_selection_missing_capabilities(case_selection))
    )
    return failures



def _write_report(result: dict[str, object], report_out: Path | None) -> None:
    if report_out is None:
        return
    report_out.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(report_out, result)
