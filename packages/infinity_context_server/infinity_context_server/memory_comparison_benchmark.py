"""Side-by-side memory benchmark runner.

This layer intentionally does not replace ``public_benchmark.py``. The existing
runner verifies retrieval/evidence coverage. This runner mirrors the mem0-style
pipeline: ingest -> search -> answer -> judge.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path

from infinity_context_core.reporting import with_report_provenance

from infinity_context_server import (
    memory_comparison_benchmark_compact_fast_gate as _compact_fast_gate_module,
)
from infinity_context_server.memory_comparison_benchmark_compact import (
    _compact_backend_metrics as _compact_backend_metrics,
)
from infinity_context_server.memory_comparison_benchmark_compact import (
    _compact_report as _compact_report,
)
from infinity_context_server.memory_comparison_benchmark_compact import (
    _report_payload,
)
from infinity_context_server.memory_comparison_benchmark_compact_samples import (
    _compact_actionable_gaps as _compact_actionable_gaps,
)
from infinity_context_server.memory_comparison_benchmark_compact_samples import (
    _compact_answer_context_support_gap_samples as _compact_answer_context_support_gap_samples,
)
from infinity_context_server.memory_comparison_benchmark_compact_samples import (
    _compact_evidence_bundle_coverage as _compact_evidence_bundle_coverage,
)
from infinity_context_server.memory_comparison_benchmark_config import (
    MEMORY_COMPARISON_CASE_SET_ALL,
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST,
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_MULTI_HOP,
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_OPEN_DOMAIN,
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_SINGLE_HOP,
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_TEMPORAL,
    MEMORY_COMPARISON_CASE_SETS,
    MEMORY_COMPARISON_MODE,
    MEMORY_COMPARISON_REPLAY_MODE,
    MEMORY_COMPARISON_REPORT_COMPACT,
    MEMORY_COMPARISON_REPORT_FULL,
    MEMORY_COMPARISON_REPORT_MODES,
    MEMORY_COMPARISON_SCHEMA_VERSION,
    MEMORY_COMPARISON_SUITE,
)
from infinity_context_server.memory_comparison_benchmark_control import (
    _apply_case_set,
    _empty_failure_report,
    _normalize_case_set,
    _normalize_report_mode,
    _normalize_runtime_timeout_seconds,
    _runtime_timeout_blocker,
    _setup_failures,
    _write_report,
)
from infinity_context_server.memory_comparison_benchmark_execution import (
    _run_backend_case,
    _stage_failure_evaluation,
)
from infinity_context_server.memory_comparison_benchmark_metrics import (
    _backend_comparison as _backend_comparison,
)
from infinity_context_server.memory_comparison_benchmark_metrics import (
    _backend_metrics,
)
from infinity_context_server.memory_comparison_benchmark_metrics import (
    _failure_analysis_entry as _failure_analysis_entry,
)
from infinity_context_server.memory_comparison_benchmark_replay import (
    _load_replay_source_report,
    _replay_backend_names,
    _replay_case_count,
    _replay_cutoffs,
    _replay_evaluation,
    _replay_source_evaluations,
)
from infinity_context_server.memory_comparison_benchmark_shared import (
    _elapsed_ms,
    _mapping,
    _normalize_top_k_cutoffs,
    _safe_error_reason,
    _unique_backend_names,
)
from infinity_context_server.memory_comparison_llm import (
    EvidenceOnlyAnswerer,
    ExpectedTermsJudge,
)
from infinity_context_server.memory_comparison_locomo_cases import (
    LOCOMO_INGEST_OFFICIAL_TURNS as LOCOMO_INGEST_OFFICIAL_TURNS,
)
from infinity_context_server.memory_comparison_locomo_cases import (
    LOCOMO_INGEST_RICH_DOCUMENTS,
    _case_corpus_key,
)
from infinity_context_server.memory_comparison_locomo_cases import (
    _load_memory_comparison_cases as _load_memory_comparison_cases,
)
from infinity_context_server.memory_comparison_models import (
    BackendIngestResult,
    MemoryComparisonAnswererPort,
    MemoryComparisonBackendPort,
    MemoryComparisonJudgePort,
    TokenCostRate,
    token_cost_rate_payload,
)
from infinity_context_server.memory_comparison_quality_diagnostics import (
    fast_gate_metrics as _fast_gate_metrics,
)
from infinity_context_server.public_benchmark import (
    PUBLIC_MEMORY_BENCHMARK_SUITE,
    _case_capability,
    _dataset_hash,
    _duplicate_case_keys,
    _normalize_benchmark_name,
)
from infinity_context_server.public_benchmark_artifacts import (
    validate_artifact_paths_do_not_overwrite_dataset,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkValidationError,
    PublicBenchmarkCase,
)
from infinity_context_server.public_benchmark_selection import (
    CASE_SELECTION_FIRST,
    normalize_requested_capabilities,
    normalize_requested_case_ids,
    select_cases,
)

__all__ = [
    "LOCOMO_INGEST_OFFICIAL_TURNS",
    "MEMORY_COMPARISON_CASE_SET_ALL",
    "MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST",
    "MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_MULTI_HOP",
    "MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_OPEN_DOMAIN",
    "MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_SINGLE_HOP",
    "MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_TEMPORAL",
    "MEMORY_COMPARISON_CASE_SETS",
    "MEMORY_COMPARISON_MODE",
    "MEMORY_COMPARISON_REPLAY_MODE",
    "MEMORY_COMPARISON_REPORT_COMPACT",
    "MEMORY_COMPARISON_REPORT_FULL",
    "MEMORY_COMPARISON_REPORT_MODES",
    "MEMORY_COMPARISON_SCHEMA_VERSION",
    "MEMORY_COMPARISON_SUITE",
    "_backend_comparison",
    "_compact_actionable_gaps",
    "_compact_answer_context_support_gap_samples",
    "_compact_backend_metrics",
    "_compact_evidence_bundle_coverage",
    "_compact_fast_gate_summary",
    "_compact_report",
    "_failure_analysis_entry",
    "_fast_gate_metrics",
    "_load_memory_comparison_cases",
    "run_memory_comparison_benchmark",
    "run_memory_comparison_replay",
]


def _compact_fast_gate_summary(items: Sequence[Mapping[str, object]]) -> dict[str, object]:
    previous = _compact_fast_gate_module._fast_gate_metrics
    _compact_fast_gate_module._fast_gate_metrics = _fast_gate_metrics
    try:
        return _compact_fast_gate_module._compact_fast_gate_summary(items)
    finally:
        _compact_fast_gate_module._fast_gate_metrics = previous


def run_memory_comparison_benchmark(
    *,
    dataset_path: Path,
    backends: Sequence[MemoryComparisonBackendPort],
    cases_override: Sequence[PublicBenchmarkCase] | None = None,
    answerer: MemoryComparisonAnswererPort | None = None,
    judge: MemoryComparisonJudgePort | None = None,
    report_out: Path | None = None,
    benchmark: str | None = None,
    min_accuracy: float = 0.0,
    max_cases: int | None = None,
    case_selection_strategy: str = CASE_SELECTION_FIRST,
    case_ids: Sequence[str] | None = None,
    capabilities: Sequence[str] | None = None,
    top_k: int = 200,
    top_k_cutoffs: Sequence[int] = (10, 20, 50, 200),
    run_id: str | None = None,
    answerer_token_cost_rate: TokenCostRate | None = None,
    judge_token_cost_rate: TokenCostRate | None = None,
    locomo_ingest_mode: str = LOCOMO_INGEST_RICH_DOCUMENTS,
    case_set: str = MEMORY_COMPARISON_CASE_SET_ALL,
    report_mode: str = MEMORY_COMPARISON_REPORT_FULL,
    compact_failure_limit: int = 50,
    runtime_timeout_seconds: float | None = None,
) -> dict[str, object]:
    """Run a mem0-style benchmark against multiple memory backends."""

    if not backends:
        raise BenchmarkValidationError("at least one comparison backend is required")
    case_set = _normalize_case_set(case_set)
    report_mode = _normalize_report_mode(report_mode)
    runtime_timeout_seconds = _normalize_runtime_timeout_seconds(
        runtime_timeout_seconds
    )
    backend_names = _unique_backend_names(backends)
    validate_artifact_paths_do_not_overwrite_dataset(
        dataset_path=dataset_path,
        error_factory=BenchmarkValidationError,
        report_out=report_out,
    )

    started = time.perf_counter()
    answerer = answerer or EvidenceOnlyAnswerer()
    judge = judge or ExpectedTermsJudge()
    answerer_token_cost_rate = answerer_token_cost_rate or TokenCostRate()
    judge_token_cost_rate = judge_token_cost_rate or TokenCostRate()
    run_id = run_id or f"memory-comparison-{uuid.uuid4().hex[:12]}"
    requested_case_ids = normalize_requested_case_ids(case_ids)
    requested_capabilities = normalize_requested_capabilities(capabilities)
    cutoffs = _normalize_top_k_cutoffs(top_k=top_k, values=top_k_cutoffs)
    primary_cutoff = top_k
    dataset_hash = _dataset_hash(dataset_path)
    cases = (
        tuple(cases_override)
        if cases_override is not None
        else _load_memory_comparison_cases(
            dataset_path,
            locomo_ingest_mode=locomo_ingest_mode,
        )
    )
    canonical_benchmark = _normalize_benchmark_name(benchmark) if benchmark else None
    if canonical_benchmark:
        cases = tuple(case for case in cases if case.benchmark == canonical_benchmark)
    cases, case_set_selection = _apply_case_set(cases, case_set=case_set)
    cases, case_selection = select_cases(
        cases,
        max_cases=max_cases,
        strategy=case_selection_strategy,
        case_ids=requested_case_ids,
        capabilities=requested_capabilities,
        capability_resolver=_case_capability,
        error_factory=BenchmarkValidationError,
    )

    setup_failures = _setup_failures(cases, case_selection)
    duplicate_case_keys = _duplicate_case_keys(cases)
    if duplicate_case_keys:
        setup_failures.extend(
            {
                "case_id": key,
                "backend": "setup",
                "group": "setup",
                "reason": "duplicate_case_id",
            }
            for key in duplicate_case_keys[:20]
        )
    if setup_failures:
        result = _empty_failure_report(
            dataset_path=dataset_path,
            dataset_hash=dataset_hash,
            run_id=run_id,
            backend_names=backend_names,
            case_selection=case_selection,
            requested_case_ids=requested_case_ids,
            requested_capabilities=requested_capabilities,
            top_k=top_k,
            cutoffs=cutoffs,
            failures=setup_failures,
            elapsed_ms=_elapsed_ms(started),
        )
        result["metadata"] = {
            **dict(_mapping(result.get("metadata"))),
            "locomo_ingest_mode": locomo_ingest_mode,
            "case_set": case_set,
            "case_set_selection": case_set_selection,
            "report_mode": report_mode,
        }
        result = _report_payload(
            result,
            report_mode=report_mode,
            compact_failure_limit=compact_failure_limit,
        )
        _write_report(result, report_out)
        return result

    evaluations: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    ingested_corpus_by_backend: dict[str, set[str]] = {name: set() for name in backend_names}
    runtime_blocker: dict[str, object] | None = None

    reset_failure_by_backend: dict[str, str] = {}
    for backend, backend_name in zip(backends, backend_names, strict=True):
        try:
            backend.reset(run_id=run_id)
        except Exception as exc:
            reset_failure_by_backend[backend_name] = _safe_error_reason(exc)

    for case in cases if runtime_blocker is None else ():
        corpus_key = _case_corpus_key(case)
        for backend, backend_name in zip(backends, backend_names, strict=True):
            if evaluations:
                runtime_blocker = _runtime_timeout_blocker(
                    started=started,
                    timeout_seconds=runtime_timeout_seconds,
                    backend_name=backend_name,
                    stage="case",
                    case=case,
                )
                if runtime_blocker is not None:
                    failures.append(runtime_blocker)
                    break
            reset_failure = reset_failure_by_backend.get(backend_name)
            if reset_failure is not None:
                evaluation = _stage_failure_evaluation(
                    case,
                    backend_name=backend_name,
                    stage="reset",
                    reason=reset_failure,
                    ingest_result=BackendIngestResult(
                        items_processed=0,
                        items_failed=1,
                        metadata={"run_id": run_id, "stage": "reset"},
                    ),
                    answerer_model=answerer.model,
                    judge_model=judge.model,
                )
                evaluations.append(evaluation)
                failure = _failure_analysis_entry(evaluation)
                if failure is not None:
                    failures.append(failure)
                continue
            if corpus_key in ingested_corpus_by_backend[backend_name]:
                ingest_result = BackendIngestResult(
                    items_processed=0,
                    reused=True,
                    metadata={"corpus_key": corpus_key},
                )
            else:
                try:
                    ingest_result = backend.ingest(
                        case,
                        run_id=run_id,
                        corpus_key=corpus_key,
                    )
                except Exception as exc:
                    evaluation = _stage_failure_evaluation(
                        case,
                        backend_name=backend_name,
                        stage="ingest",
                        reason=_safe_error_reason(exc),
                        ingest_result=BackendIngestResult(
                            items_processed=0,
                            items_failed=1,
                            metadata={"corpus_key": corpus_key},
                        ),
                        answerer_model=answerer.model,
                        judge_model=judge.model,
                    )
                    evaluations.append(evaluation)
                    failure = _failure_analysis_entry(evaluation)
                    if failure is not None:
                        failures.append(failure)
                    continue
                if ingest_result.items_failed > 0:
                    evaluation = _stage_failure_evaluation(
                        case,
                        backend_name=backend_name,
                        stage="ingest",
                        reason=(
                            f"items_failed={ingest_result.items_failed}; "
                            f"items_processed={ingest_result.items_processed}"
                        ),
                        ingest_result=ingest_result,
                        answerer_model=answerer.model,
                        judge_model=judge.model,
                    )
                    evaluations.append(evaluation)
                    failure = _failure_analysis_entry(evaluation)
                    if failure is not None:
                        failures.append(failure)
                    continue
                ingested_corpus_by_backend[backend_name].add(corpus_key)
            runtime_blocker = _runtime_timeout_blocker(
                started=started,
                timeout_seconds=runtime_timeout_seconds,
                backend_name=backend_name,
                stage="search",
                case=case,
            )
            if runtime_blocker is not None:
                evaluation = _stage_failure_evaluation(
                    case,
                    backend_name=backend_name,
                    stage="runtime_timeout",
                    reason=str(runtime_blocker["reason"]),
                    ingest_result=ingest_result,
                    answerer_model=answerer.model,
                    judge_model=judge.model,
                )
                evaluations.append(evaluation)
                failure = _failure_analysis_entry(evaluation)
                if failure is not None:
                    failures.append(failure)
                failures.append(runtime_blocker)
                break
            evaluation = _run_backend_case(
                case,
                backend=backend,
                backend_name=backend_name,
                run_id=run_id,
                ingest_result=ingest_result,
                answerer=answerer,
                judge=judge,
                top_k=top_k,
                cutoffs=cutoffs,
                primary_cutoff=primary_cutoff,
            )
            evaluations.append(evaluation)
            failure = _failure_analysis_entry(evaluation)
            if failure is not None:
                failures.append(failure)
        if runtime_blocker is not None:
            break

    backend_metrics = {
        backend_name: _backend_metrics(
            evaluations,
            backend_name=backend_name,
            min_accuracy=min_accuracy,
            primary_cutoff=primary_cutoff,
            cutoffs=cutoffs,
            answerer_token_cost_rate=answerer_token_cost_rate,
            judge_token_cost_rate=judge_token_cost_rate,
        )
        for backend_name in backend_names
    }
    ok = runtime_blocker is None and bool(evaluations) and all(
        bool(metrics["ok"]) for metrics in backend_metrics.values()
    )
    result: dict[str, object] = {
        "schema_version": MEMORY_COMPARISON_SCHEMA_VERSION,
        "suite": MEMORY_COMPARISON_SUITE,
        "source_suite": PUBLIC_MEMORY_BENCHMARK_SUITE,
        "status": "ok" if ok else "failed",
        "ok": ok,
        "benchmark": canonical_benchmark or benchmark or "all",
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
            "primary_cutoff": primary_cutoff,
            "answerer_model": answerer.model,
            "judge_model": judge.model,
            "token_cost_rates": {
                "currency": "USD",
                "answerer": token_cost_rate_payload(answerer_token_cost_rate),
                "judge": token_cost_rate_payload(judge_token_cost_rate),
            },
            "token_cost_scope": "answerer_judge_only",
            "unmeasured_costs": [
                "backend_internal_ingest_provider_cost",
                "backend_internal_search_provider_cost",
            ],
            "backend_names": list(backend_names),
            "scoring_note": "LoCoMo category 5 is reported but excluded from scored accuracy.",
            "locomo_ingest_mode": locomo_ingest_mode,
            "case_set": case_set,
            "case_set_selection": case_set_selection,
            "report_mode": report_mode,
            "runtime_timeout_seconds": runtime_timeout_seconds,
            "runtime_limit_exceeded": runtime_blocker is not None,
        },
        "metrics": {
            "backend_count": len(backend_names),
            "case_count": len(cases),
            "evaluation_count": len(evaluations),
            "scored_evaluation_count": sum(1 for item in evaluations if item["scored"]),
            "min_accuracy": min_accuracy,
            "elapsed_ms": _elapsed_ms(started),
        },
        "backend_metrics": backend_metrics,
        "backend_comparison": _backend_comparison(backend_metrics),
        "evaluations": evaluations,
        "failure_analysis": failures,
        "failures": failures,
        "elapsed_ms": _elapsed_ms(started),
    }
    result = with_report_provenance(
        result,
        generated_by="infinity_context_server.memory_comparison_benchmark",
        run_id=run_id,
        cwd=Path.cwd(),
    )
    result = _report_payload(
        result,
        report_mode=report_mode,
        compact_failure_limit=compact_failure_limit,
    )
    _write_report(result, report_out)
    return result


def run_memory_comparison_replay(
    *,
    report_path: Path,
    answerer: MemoryComparisonAnswererPort | None = None,
    judge: MemoryComparisonJudgePort | None = None,
    report_out: Path | None = None,
    min_accuracy: float = 0.0,
    top_k_cutoffs: Sequence[int] | None = None,
    primary_cutoff: int | None = None,
    run_id: str | None = None,
    answerer_token_cost_rate: TokenCostRate | None = None,
    judge_token_cost_rate: TokenCostRate | None = None,
    report_mode: str = MEMORY_COMPARISON_REPORT_FULL,
    compact_failure_limit: int = 50,
) -> dict[str, object]:
    """Replay answer/judge stages from a saved full memory comparison report."""

    if report_out is not None and report_out.resolve() == report_path.resolve():
        raise BenchmarkValidationError("report_out must not overwrite the replay source")
    report_mode = _normalize_report_mode(report_mode)
    started = time.perf_counter()
    answerer = answerer or EvidenceOnlyAnswerer()
    judge = judge or ExpectedTermsJudge()
    answerer_token_cost_rate = answerer_token_cost_rate or TokenCostRate()
    judge_token_cost_rate = judge_token_cost_rate or TokenCostRate()

    source_report = _load_replay_source_report(report_path)
    source_evaluations = _replay_source_evaluations(source_report)
    source_metadata = _mapping(source_report.get("metadata"))
    cutoffs, primary_cutoff = _replay_cutoffs(
        source_metadata=source_metadata,
        source_evaluations=source_evaluations,
        top_k_cutoffs=top_k_cutoffs,
        primary_cutoff=primary_cutoff,
    )
    run_id = run_id or f"memory-comparison-replay-{uuid.uuid4().hex[:12]}"
    backend_names = _replay_backend_names(source_evaluations, source_metadata)

    evaluations: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    for source_evaluation in source_evaluations:
        evaluation = _replay_evaluation(
            source_evaluation,
            answerer=answerer,
            judge=judge,
            cutoffs=cutoffs,
            primary_cutoff=primary_cutoff,
        )
        evaluations.append(evaluation)
        failure = _failure_analysis_entry(evaluation)
        if failure is not None:
            failures.append(failure)

    backend_metrics = {
        backend_name: _backend_metrics(
            evaluations,
            backend_name=backend_name,
            min_accuracy=min_accuracy,
            primary_cutoff=primary_cutoff,
            cutoffs=cutoffs,
            answerer_token_cost_rate=answerer_token_cost_rate,
            judge_token_cost_rate=judge_token_cost_rate,
        )
        for backend_name in backend_names
    }
    ok = bool(evaluations) and all(
        bool(metrics["ok"]) for metrics in backend_metrics.values()
    )
    result: dict[str, object] = {
        "schema_version": MEMORY_COMPARISON_SCHEMA_VERSION,
        "suite": MEMORY_COMPARISON_SUITE,
        "source_suite": source_report.get("source_suite", PUBLIC_MEMORY_BENCHMARK_SUITE),
        "status": "ok" if ok else "failed",
        "ok": ok,
        "benchmark": source_report.get("benchmark", "all"),
        "benchmark_scope": source_report.get(
            "benchmark_scope",
            "memory_system_side_by_side",
        ),
        "evaluation_mode": MEMORY_COMPARISON_REPLAY_MODE,
        "run_id": run_id,
        "dataset_path_label": source_report.get("dataset_path_label"),
        "dataset_hash": source_report.get("dataset_hash"),
        "requested_case_ids": source_report.get("requested_case_ids", []),
        "requested_capabilities": source_report.get("requested_capabilities", []),
        "case_selection": source_report.get("case_selection", {}),
        "metadata": {
            "top_k": primary_cutoff,
            "top_k_cutoffs": list(cutoffs),
            "primary_cutoff": primary_cutoff,
            "answerer_model": answerer.model,
            "judge_model": judge.model,
            "token_cost_rates": {
                "currency": "USD",
                "answerer": token_cost_rate_payload(answerer_token_cost_rate),
                "judge": token_cost_rate_payload(judge_token_cost_rate),
            },
            "token_cost_scope": "answerer_judge_only",
            "replay_scope": "answerer_judge_only_no_memory_calls",
            "source_report_path_label": report_path.name,
            "source_run_id": source_report.get("run_id"),
            "source_evaluation_mode": source_report.get("evaluation_mode"),
            "source_report_mode": source_metadata.get("report_mode", "full"),
            "backend_names": list(backend_names),
            "report_mode": report_mode,
        },
        "metrics": {
            "backend_count": len(backend_names),
            "case_count": _replay_case_count(source_report, source_evaluations),
            "evaluation_count": len(evaluations),
            "scored_evaluation_count": sum(1 for item in evaluations if item["scored"]),
            "min_accuracy": min_accuracy,
            "elapsed_ms": _elapsed_ms(started),
        },
        "backend_metrics": backend_metrics,
        "backend_comparison": _backend_comparison(backend_metrics),
        "evaluations": evaluations,
        "failure_analysis": failures,
        "failures": failures,
        "elapsed_ms": _elapsed_ms(started),
    }
    result = with_report_provenance(
        result,
        generated_by="infinity_context_server.memory_comparison_replay",
        run_id=run_id,
        cwd=Path.cwd(),
    )
    result = _report_payload(
        result,
        report_mode=report_mode,
        compact_failure_limit=compact_failure_limit,
    )
    _write_report(result, report_out)
    return result
