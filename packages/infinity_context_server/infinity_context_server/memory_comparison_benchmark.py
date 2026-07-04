"""Side-by-side memory benchmark runner.

This layer intentionally does not replace ``public_benchmark.py``. The existing
runner verifies retrieval/evidence coverage. This runner mirrors the mem0-style
pipeline: ingest -> search -> answer -> judge.
"""

from __future__ import annotations

import json
import time
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from math import isfinite
from pathlib import Path

from infinity_context_core.application.sensitive_text import redact_sensitive_text
from infinity_context_core.reporting import with_report_provenance

from infinity_context_server.memory_comparison_answer_context import (
    answer_context_from_evidence_bundle,
)
from infinity_context_server.memory_comparison_answer_context import (
    answer_context_metrics as _answer_context_metrics,
)
from infinity_context_server.memory_comparison_evidence import (
    evidence_bundle as build_evidence_bundle,
)
from infinity_context_server.memory_comparison_evidence import (
    retrieval_quality as build_retrieval_quality,
)
from infinity_context_server.memory_comparison_failure_diagnostics import (
    failure_diagnostic_reason_codes as _failure_diagnostic_reason_codes,
)
from infinity_context_server.memory_comparison_failure_diagnostics import (
    failure_diagnostics as _failure_diagnostics,
)
from infinity_context_server.memory_comparison_llm import (
    EvidenceOnlyAnswerer,
    ExpectedTermsJudge,
    approximate_token_count,
)
from infinity_context_server.memory_comparison_locomo_cases import (
    _LOCOMO_CATEGORY_NAMES,
    LOCOMO_INGEST_RICH_DOCUMENTS,
    _case_category_label,
    _case_corpus_key,
    _case_ground_truth,
    _case_group,
    _case_is_scored,
    _load_memory_comparison_cases,
)
from infinity_context_server.memory_comparison_locomo_cases import (
    LOCOMO_INGEST_OFFICIAL_TURNS as LOCOMO_INGEST_OFFICIAL_TURNS,
)
from infinity_context_server.memory_comparison_models import (
    AnswerResult,
    BackendIngestResult,
    BackendSearchResult,
    JudgeResult,
    MemoryComparisonAnswererPort,
    MemoryComparisonBackendPort,
    MemoryComparisonJudgePort,
    RetrievedMemory,
    TokenCostRate,
    TokenUsage,
    answer_payload,
    ingestion_payload,
    judge_payload,
    search_payload,
    token_cost_payload,
    token_cost_rate_payload,
)
from infinity_context_server.memory_comparison_quality_diagnostics import (
    evidence_ref_rank_gate_metrics as _evidence_ref_rank_gate_metrics,
)
from infinity_context_server.memory_comparison_quality_diagnostics import (
    fast_gate_metrics as _fast_gate_metrics,
)
from infinity_context_server.memory_comparison_quality_diagnostics import (
    quality_diagnostics as _quality_diagnostics,
)
from infinity_context_server.memory_comparison_query_integrity import (
    query_integrity_diagnostics as _query_integrity_diagnostics,
)
from infinity_context_server.public_benchmark import (
    LOCOMO_BENCHMARK_SUITE,
    PUBLIC_MEMORY_BENCHMARK_SUITE,
    _case_capability,
    _dataset_hash,
    _duplicate_case_keys,
    _normalize_benchmark_name,
)
from infinity_context_server.public_benchmark_artifacts import (
    validate_artifact_paths_do_not_overwrite_dataset,
    write_json_atomic,
)
from infinity_context_server.public_benchmark_models import (
    BenchmarkValidationError,
    PublicBenchmarkCase,
)
from infinity_context_server.public_benchmark_selection import (
    CASE_SELECTION_FIRST,
    case_selection_missing_capabilities,
    case_selection_missing_case_ids,
    missing_capability_failures,
    missing_case_id_failures,
    normalize_requested_capabilities,
    normalize_requested_case_ids,
    select_cases,
)

MEMORY_COMPARISON_SUITE = "memory-comparison-benchmark"
MEMORY_COMPARISON_SCHEMA_VERSION = "memory-comparison-benchmark-v1"
MEMORY_COMPARISON_MODE = "ingest_search_answer_judge"
MEMORY_COMPARISON_REPLAY_MODE = "evaluate_only_replay"
MEMORY_COMPARISON_CASE_SET_ALL = "all"
MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST = "locomo-fast"
MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_MULTI_HOP = "locomo-fast-multi-hop"
MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_TEMPORAL = "locomo-fast-temporal"
MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_OPEN_DOMAIN = "locomo-fast-open-domain"
MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_SINGLE_HOP = "locomo-fast-single-hop"
MEMORY_COMPARISON_CASE_SETS = (
    MEMORY_COMPARISON_CASE_SET_ALL,
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST,
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_MULTI_HOP,
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_TEMPORAL,
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_OPEN_DOMAIN,
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_SINGLE_HOP,
)
MEMORY_COMPARISON_REPORT_FULL = "full"
MEMORY_COMPARISON_REPORT_COMPACT = "compact"
MEMORY_COMPARISON_REPORT_MODES = (
    MEMORY_COMPARISON_REPORT_FULL,
    MEMORY_COMPARISON_REPORT_COMPACT,
)

_LOCOMO_FAST_CASES_PER_GROUP = 10
_LOCOMO_FAST_CASE_SET_GROUPS = {
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST: (
        "multi-hop",
        "temporal",
        "open-domain",
        "single-hop",
    ),
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_MULTI_HOP: ("multi-hop",),
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_TEMPORAL: ("temporal",),
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_OPEN_DOMAIN: ("open-domain",),
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_SINGLE_HOP: ("single-hop",),
}


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
        runtime_blocker = _runtime_timeout_blocker(
            started=started,
            timeout_seconds=runtime_timeout_seconds,
            backend_name=backend_name,
            stage="reset",
        )
        if runtime_blocker is not None:
            break
        try:
            backend.reset(run_id=run_id)
        except Exception as exc:
            reset_failure_by_backend[backend_name] = _safe_error_reason(exc)
    if runtime_blocker is not None:
        failures.append(runtime_blocker)

    for case in cases if runtime_blocker is None else ():
        corpus_key = _case_corpus_key(case)
        for backend, backend_name in zip(backends, backend_names, strict=True):
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


def _run_backend_case(
    case: PublicBenchmarkCase,
    *,
    backend: MemoryComparisonBackendPort,
    backend_name: str,
    run_id: str,
    ingest_result: BackendIngestResult,
    answerer: MemoryComparisonAnswererPort,
    judge: MemoryComparisonJudgePort,
    top_k: int,
    cutoffs: Sequence[int],
    primary_cutoff: int,
) -> dict[str, object]:
    try:
        search_result = backend.search(case, run_id=run_id, top_k=top_k)
    except Exception as exc:
        return _stage_failure_evaluation(
            case,
            backend_name=backend_name,
            stage="search",
            reason=_safe_error_reason(exc),
            ingest_result=ingest_result,
            answerer_model=answerer.model,
            judge_model=judge.model,
        )
    retrieval_quality = build_retrieval_quality(case, search_result.memories)
    evidence_bundle = build_evidence_bundle(case, search_result.memories)
    cutoff_results: dict[str, object] = {}
    primary_answer = None
    primary_judgment = None
    for cutoff in cutoffs:
        sliced = search_result.memories[:cutoff]
        answer_context = answer_context_from_evidence_bundle(
            search_result.memories,
            evidence_bundle,
            cutoff=cutoff,
        )
        try:
            answer = answerer.answer(
                case,
                answer_context.memories,
                backend_name=backend_name,
                cutoff=cutoff,
            )
        except Exception as exc:
            return _stage_failure_evaluation(
                case,
                backend_name=backend_name,
                stage="answer",
                reason=_safe_error_reason(exc),
                ingest_result=ingest_result,
                search_result=search_result,
                retrieval_quality=retrieval_quality,
                answerer_model=answerer.model,
                judge_model=judge.model,
                cutoff=cutoff,
            )
        try:
            judgment = judge.judge(
                case,
                answer,
                answer_context.memories,
                backend_name=backend_name,
                cutoff=cutoff,
            )
        except Exception as exc:
            return _stage_failure_evaluation(
                case,
                backend_name=backend_name,
                stage="judge",
                reason=_safe_error_reason(exc),
                ingest_result=ingest_result,
                search_result=search_result,
                retrieval_quality=retrieval_quality,
                answer=answer,
                answerer_model=answerer.model,
                judge_model=judge.model,
                cutoff=cutoff,
            )
        cutoff_payload = {
            "generation": answer_payload(answer),
            "judgment": judge_payload(judgment),
            "memories_evaluated": len(sliced),
            "answer_context": answer_context.to_diagnostics(),
        }
        cutoff_results[str(cutoff)] = cutoff_payload
        if cutoff == primary_cutoff:
            primary_answer = answer
            primary_judgment = judgment
    assert primary_answer is not None
    assert primary_judgment is not None
    return {
        "id": f"{backend_name}:{case.benchmark}:{case.case_id}",
        "backend": backend_name,
        "benchmark": case.benchmark,
        "case_id": case.case_id,
        "category": _case_category_label(case),
        "group": _case_group(case),
        "capability": _case_capability(case),
        "scored": _case_is_scored(case),
        "question": case.question,
        "ground_truth": _case_ground_truth(case),
        "expected_terms": list(case.expected_terms),
        "forbidden_terms": list(case.forbidden_terms),
        "ingestion": ingestion_payload(ingest_result),
        "retrieval": _search_payload_with_query_integrity(case, search_result),
        "retrieval_quality": retrieval_quality,
        "evidence_bundle": evidence_bundle,
        "generation": answer_payload(primary_answer),
        "judgment": judge_payload(primary_judgment),
        "cutoff_results": cutoff_results,
    }


def _stage_failure_evaluation(
    case: PublicBenchmarkCase,
    *,
    backend_name: str,
    stage: str,
    reason: str,
    ingest_result: BackendIngestResult,
    answerer_model: str,
    judge_model: str,
    search_result: BackendSearchResult | None = None,
    retrieval_quality: Mapping[str, object] | None = None,
    answer: AnswerResult | None = None,
    cutoff: int | None = None,
) -> dict[str, object]:
    search_result = search_result or BackendSearchResult(
        query=case.question,
        memories=(),
        total_results=0,
        context_token_count=0,
        metadata={"stage": stage, "error": reason},
    )
    retrieval_quality = retrieval_quality or build_retrieval_quality(case, search_result.memories)
    evidence_bundle = build_evidence_bundle(case, search_result.memories)
    error_metadata: dict[str, object] = {"stage": stage, "error": reason}
    if cutoff is not None:
        error_metadata["cutoff"] = cutoff
    answer = answer or AnswerResult(
        answer="",
        model=answerer_model,
        metadata=error_metadata,
    )
    judgment = JudgeResult(
        verdict="error",
        score=0.0,
        reason=f"{stage}_failed",
        model=judge_model,
        metadata=error_metadata,
    )
    cutoff_results = {}
    if cutoff is not None:
        cutoff_results[str(cutoff)] = {
            "generation": answer_payload(answer),
            "judgment": judge_payload(judgment),
            "memories_evaluated": len(search_result.memories[:cutoff]),
        }
    return {
        "id": f"{backend_name}:{case.benchmark}:{case.case_id}",
        "backend": backend_name,
        "benchmark": case.benchmark,
        "case_id": case.case_id,
        "category": _case_category_label(case),
        "group": _case_group(case),
        "capability": _case_capability(case),
        "scored": _case_is_scored(case),
        "question": case.question,
        "ground_truth": _case_ground_truth(case),
        "expected_terms": list(case.expected_terms),
        "forbidden_terms": list(case.forbidden_terms),
        "ingestion": ingestion_payload(ingest_result),
        "retrieval": _search_payload_with_query_integrity(case, search_result),
        "retrieval_quality": retrieval_quality,
        "evidence_bundle": evidence_bundle,
        "generation": answer_payload(answer),
        "judgment": judge_payload(judgment),
        "cutoff_results": cutoff_results,
    }


def _search_payload_with_query_integrity(
    case: PublicBenchmarkCase,
    search_result: BackendSearchResult,
) -> dict[str, object]:
    payload = search_payload(search_result)
    metadata = dict(_mapping(payload.get("metadata")))
    metadata["query_integrity"] = _query_integrity_diagnostics(case, search_result)
    payload["metadata"] = metadata
    return payload


def _load_replay_source_report(report_path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BenchmarkValidationError(
            f"Unable to read replay source report: {report_path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise BenchmarkValidationError(
            f"Replay source report is not valid JSON: {report_path}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise BenchmarkValidationError("Replay source report must be a JSON object")
    return payload


def _replay_source_evaluations(
    source_report: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    raw_evaluations = source_report.get("evaluations")
    if not isinstance(raw_evaluations, Sequence) or isinstance(
        raw_evaluations,
        str | bytes,
    ):
        raise BenchmarkValidationError(
            "Replay requires a full memory comparison report with evaluations"
        )
    evaluations = tuple(
        item for item in raw_evaluations if isinstance(item, Mapping)
    )
    if not evaluations:
        raise BenchmarkValidationError(
            "Replay source report has no evaluations; compact reports cannot be replayed"
        )
    return evaluations


def _replay_cutoffs(
    *,
    source_metadata: Mapping[str, object],
    source_evaluations: Sequence[Mapping[str, object]],
    top_k_cutoffs: Sequence[int] | None,
    primary_cutoff: int | None,
) -> tuple[tuple[int, ...], int]:
    source_cutoffs = _positive_ints(source_metadata.get("top_k_cutoffs"))
    if not source_cutoffs:
        source_cutoffs = tuple(
            sorted(
                {
                    int(cutoff)
                    for evaluation in source_evaluations
                    for cutoff in _mapping(evaluation.get("cutoff_results"))
                    if str(cutoff).isdigit() and int(cutoff) > 0
                }
            )
        )
    if top_k_cutoffs is not None:
        source_cutoffs = tuple(int(cutoff) for cutoff in top_k_cutoffs)
    primary = (
        primary_cutoff
        or _positive_int(source_metadata.get("primary_cutoff"))
        or _positive_int(source_metadata.get("top_k"))
        or (max(source_cutoffs) if source_cutoffs else 200)
    )
    return _normalize_top_k_cutoffs(top_k=primary, values=source_cutoffs), primary


def _replay_backend_names(
    source_evaluations: Sequence[Mapping[str, object]],
    source_metadata: Mapping[str, object],
) -> tuple[str, ...]:
    from_metadata = _str_tuple(source_metadata.get("backend_names"))
    if from_metadata:
        return from_metadata
    return tuple(
        sorted(
            {
                str(evaluation.get("backend"))
                for evaluation in source_evaluations
                if str(evaluation.get("backend", "")).strip()
            }
        )
    )


def _replay_case_count(
    source_report: Mapping[str, object],
    source_evaluations: Sequence[Mapping[str, object]],
) -> int:
    metrics = _mapping(source_report.get("metrics"))
    case_count = _positive_int(metrics.get("case_count"))
    if case_count is not None:
        return case_count
    return len(
        {
            str(evaluation.get("case_id"))
            for evaluation in source_evaluations
            if str(evaluation.get("case_id", "")).strip()
        }
    )


def _replay_evaluation(
    source: Mapping[str, object],
    *,
    answerer: MemoryComparisonAnswererPort,
    judge: MemoryComparisonJudgePort,
    cutoffs: Sequence[int],
    primary_cutoff: int,
) -> dict[str, object]:
    case = _replay_case_from_evaluation(source)
    backend_name = str(source.get("backend") or "unknown")
    memories = _replay_memories_from_evaluation(source)
    retrieval_quality = dict(_mapping(source.get("retrieval_quality"))) or (
        build_retrieval_quality(case, memories)
    )
    evidence_bundle = dict(_mapping(source.get("evidence_bundle"))) or build_evidence_bundle(
        case,
        memories,
    )
    cutoff_results: dict[str, object] = {}
    primary_answer = None
    primary_judgment = None
    for cutoff in cutoffs:
        sliced = memories[:cutoff]
        answer_context = answer_context_from_evidence_bundle(
            memories,
            evidence_bundle,
            cutoff=cutoff,
        )
        try:
            answer = answerer.answer(
                case,
                answer_context.memories,
                backend_name=backend_name,
                cutoff=cutoff,
            )
        except Exception as exc:
            return _replay_stage_failure_evaluation(
                source,
                case,
                backend_name=backend_name,
                stage="answer",
                reason=_safe_error_reason(exc),
                answerer_model=answerer.model,
                judge_model=judge.model,
                retrieval_quality=retrieval_quality,
                evidence_bundle=evidence_bundle,
                cutoff=cutoff,
            )
        try:
            judgment = judge.judge(
                case,
                answer,
                answer_context.memories,
                backend_name=backend_name,
                cutoff=cutoff,
            )
        except Exception as exc:
            return _replay_stage_failure_evaluation(
                source,
                case,
                backend_name=backend_name,
                stage="judge",
                reason=_safe_error_reason(exc),
                answer=answer,
                answerer_model=answerer.model,
                judge_model=judge.model,
                retrieval_quality=retrieval_quality,
                evidence_bundle=evidence_bundle,
                cutoff=cutoff,
            )
        cutoff_results[str(cutoff)] = {
            "generation": answer_payload(answer),
            "judgment": judge_payload(judgment),
            "memories_evaluated": len(sliced),
            "answer_context": answer_context.to_diagnostics(),
        }
        if cutoff == primary_cutoff:
            primary_answer = answer
            primary_judgment = judgment
    assert primary_answer is not None
    assert primary_judgment is not None
    return _replay_evaluation_payload(
        source,
        case,
        backend_name=backend_name,
        retrieval_quality=retrieval_quality,
        evidence_bundle=evidence_bundle,
        generation=answer_payload(primary_answer),
        judgment=judge_payload(primary_judgment),
        cutoff_results=cutoff_results,
    )


def _replay_stage_failure_evaluation(
    source: Mapping[str, object],
    case: PublicBenchmarkCase,
    *,
    backend_name: str,
    stage: str,
    reason: str,
    answerer_model: str,
    judge_model: str,
    retrieval_quality: Mapping[str, object],
    evidence_bundle: Mapping[str, object],
    answer: AnswerResult | None = None,
    cutoff: int,
) -> dict[str, object]:
    error_metadata = {"stage": stage, "error": reason, "cutoff": cutoff}
    answer = answer or AnswerResult(
        answer="",
        model=answerer_model,
        metadata=error_metadata,
    )
    judgment = JudgeResult(
        verdict="error",
        score=0.0,
        reason=f"{stage}_failed",
        model=judge_model,
        metadata=error_metadata,
    )
    cutoff_results = {
        str(cutoff): {
            "generation": answer_payload(answer),
            "judgment": judge_payload(judgment),
            "memories_evaluated": len(_replay_memories_from_evaluation(source)[:cutoff]),
        }
    }
    return _replay_evaluation_payload(
        source,
        case,
        backend_name=backend_name,
        retrieval_quality=retrieval_quality,
        evidence_bundle=evidence_bundle,
        generation=answer_payload(answer),
        judgment=judge_payload(judgment),
        cutoff_results=cutoff_results,
    )


def _replay_evaluation_payload(
    source: Mapping[str, object],
    case: PublicBenchmarkCase,
    *,
    backend_name: str,
    retrieval_quality: Mapping[str, object],
    evidence_bundle: Mapping[str, object],
    generation: Mapping[str, object],
    judgment: Mapping[str, object],
    cutoff_results: Mapping[str, object],
) -> dict[str, object]:
    return {
        "id": source.get("id") or f"{backend_name}:{case.benchmark}:{case.case_id}",
        "backend": backend_name,
        "benchmark": case.benchmark,
        "case_id": case.case_id,
        "category": source.get("category") or _case_category_label(case),
        "group": source.get("group") or _case_group(case),
        "capability": source.get("capability") or _case_capability(case),
        "scored": source.get("scored")
        if isinstance(source.get("scored"), bool)
        else _case_is_scored(case),
        "question": case.question,
        "ground_truth": source.get("ground_truth") or _case_ground_truth(case),
        "expected_terms": list(case.expected_terms),
        "forbidden_terms": list(case.forbidden_terms),
        "ingestion": dict(_mapping(source.get("ingestion"))),
        "retrieval": dict(_mapping(source.get("retrieval"))),
        "retrieval_quality": dict(retrieval_quality),
        "evidence_bundle": dict(evidence_bundle),
        "generation": dict(generation),
        "judgment": dict(judgment),
        "cutoff_results": dict(cutoff_results),
        "replay": {
            "source_evaluation_id": source.get("id"),
            "memory_calls": 0,
        },
    }


def _replay_case_from_evaluation(source: Mapping[str, object]) -> PublicBenchmarkCase:
    benchmark = str(source.get("benchmark") or LOCOMO_BENCHMARK_SUITE)
    case_id = str(source.get("case_id") or source.get("id") or "unknown")
    question = str(source.get("question") or "")
    expected_terms = _str_tuple(source.get("expected_terms"))
    forbidden_terms = _str_tuple(source.get("forbidden_terms"))
    category = _locomo_category_from_replay_value(
        source.get("category"),
        group=source.get("group"),
    )
    metadata: dict[str, object] = {
        "answer_preview": str(source.get("ground_truth") or " | ".join(expected_terms)),
    }
    if category is not None:
        metadata["category"] = category
    return PublicBenchmarkCase(
        benchmark=benchmark,
        case_id=case_id,
        question=question,
        expected_terms=expected_terms,
        forbidden_terms=forbidden_terms,
        metadata=metadata,
    )


def _replay_memories_from_evaluation(
    source: Mapping[str, object],
) -> tuple[RetrievedMemory, ...]:
    retrieval = _mapping(source.get("retrieval"))
    results = retrieval.get("results")
    if not isinstance(results, Sequence) or isinstance(results, str | bytes):
        return ()
    memories: list[RetrievedMemory] = []
    for index, item in enumerate(results, start=1):
        if not isinstance(item, Mapping):
            continue
        memories.append(
            RetrievedMemory(
                text=str(item.get("memory") or item.get("text") or ""),
                rank=_positive_int(item.get("rank")) or index,
                score=_float_value(item.get("score")),
                item_id=str(item["id"]) if item.get("id") is not None else None,
                created_at=(
                    str(item["created_at"])
                    if item.get("created_at") is not None
                    else None
                ),
                source_refs=_str_tuple(item.get("source_refs")),
                metadata=dict(_mapping(item.get("metadata"))),
            )
        )
    return tuple(memories)


def _locomo_category_from_replay_value(
    value: object,
    *,
    group: object,
) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raw = str(value or "").strip()
    prefix = raw.split(":", 1)[0]
    if prefix.isdigit():
        return int(prefix)
    reverse = {name: category for category, name in _LOCOMO_CATEGORY_NAMES.items()}
    mapped = reverse.get(str(group or raw).strip())
    return int(mapped) if mapped is not None else None


def _backend_metrics(
    evaluations: Sequence[Mapping[str, object]],
    *,
    backend_name: str,
    min_accuracy: float,
    primary_cutoff: int,
    cutoffs: Sequence[int],
    answerer_token_cost_rate: TokenCostRate,
    judge_token_cost_rate: TokenCostRate,
) -> dict[str, object]:
    backend_items = [item for item in evaluations if item.get("backend") == backend_name]
    scored = [item for item in backend_items if item.get("scored") is True]
    evidence_scored = [item for item in scored if _has_evidence_recall(item)]
    passed = sum(1 for item in scored if _evaluation_score(item) >= 1.0)
    accuracy = _ratio(passed, len(scored))
    by_group = {
        group: _bucket_metrics(items)
        for group, items in sorted(_group_by(scored, key="group").items())
    }
    by_category = {
        category: _bucket_metrics(items)
        for category, items in sorted(_group_by(backend_items, key="category").items())
    }
    return {
        "ok": accuracy >= min_accuracy and bool(scored),
        "total": len(scored),
        "unscored": len(backend_items) - len(scored),
        "passed": passed,
        "failed": len(scored) - passed,
        "accuracy": accuracy,
        "avg_score": _avg(_evaluation_score(item) for item in scored),
        "avg_retrieved_count": _avg(_retrieved_count(item) for item in backend_items),
        "avg_search_latency_ms": _avg(_search_latency(item) for item in backend_items),
        "avg_ingest_latency_ms": _avg(_ingest_latency(item) for item in backend_items),
        "avg_generation_latency_ms": _avg(
            _stage_latency(item, "generation") for item in backend_items
        ),
        "avg_judge_latency_ms": _avg(
            _stage_latency(item, "judgment") for item in backend_items
        ),
        "avg_context_tokens": _avg(_context_tokens(item) for item in backend_items),
        "expected_term_recall": _avg(_retrieval_recall(item) for item in scored),
        "evidence_term_recall": _avg(_evidence_recall(item) for item in evidence_scored),
        "evidence_term_recall_evaluation_count": len(evidence_scored),
        "token_usage": _token_usage_summary(backend_items),
        "token_cost": _token_cost_summary(
            backend_items,
            answerer_token_cost_rate=answerer_token_cost_rate,
            judge_token_cost_rate=judge_token_cost_rate,
        ),
        "by_category": by_category,
        "by_group": by_group,
        "by_cutoff": _cutoff_metrics(
            backend_items,
            configured_cutoffs=cutoffs,
            primary_cutoff=primary_cutoff,
        ),
        "top_k_gate": _top_k_gate_metrics(
            backend_items,
            configured_cutoffs=cutoffs,
            primary_cutoff=primary_cutoff,
        ),
        "answer_context_metrics": _answer_context_metrics(
            backend_items,
            configured_cutoffs=cutoffs,
            primary_cutoff=primary_cutoff,
        ),
        "source_mix_gate": _source_mix_gate_metrics(backend_items),
        "temporal_metadata_gate": _temporal_metadata_gate_metrics(backend_items),
        "benchmark_rerank_gate": _benchmark_rerank_gate_metrics(backend_items),
        "query_integrity_gate": _query_integrity_gate_metrics(backend_items),
        "multi_hop_bundle_gate": _multi_hop_bundle_gate_metrics(backend_items),
        "evidence_ref_rank_gate": _evidence_ref_rank_gate_metrics(backend_items),
        "quality_diagnostics": _quality_diagnostics(backend_items),
        "fast_gate": _fast_gate_metrics(backend_items),
    }


def _bucket_metrics(items: Sequence[Mapping[str, object]]) -> dict[str, object]:
    scored = [item for item in items if item.get("scored") is True]
    evidence_scored = [item for item in scored if _has_evidence_recall(item)]
    passed = sum(1 for item in scored if _evaluation_score(item) >= 1.0)
    return {
        "total": len(items),
        "scored": len(scored),
        "unscored": len(items) - len(scored),
        "passed": passed,
        "failed": len(scored) - passed,
        "accuracy": _ratio(passed, len(scored)),
        "avg_score": _avg(_evaluation_score(item) for item in scored),
        "expected_term_recall": _avg(_retrieval_recall(item) for item in scored),
        "evidence_term_recall": _avg(_evidence_recall(item) for item in evidence_scored),
        "evidence_term_recall_evaluation_count": len(evidence_scored),
    }


def _cutoff_metrics(
    items: Sequence[Mapping[str, object]],
    *,
    configured_cutoffs: Sequence[int],
    primary_cutoff: int,
) -> dict[str, object]:
    cutoffs = sorted(
        set(configured_cutoffs)
        | {
            int(cutoff)
            for item in items
            for cutoff in _mapping(item.get("cutoff_results"))
            if str(cutoff).isdigit()
        }
    )
    metrics: dict[str, object] = {}
    for cutoff in cutoffs:
        cutoff_items = [
            _mapping(_mapping(item.get("cutoff_results")).get(str(cutoff)))
            for item in items
            if item.get("scored") is True
        ]
        scores = [
            float(_mapping(item.get("judgment")).get("score", 0.0))
            for item in cutoff_items
        ]
        passed = sum(1 for score in scores if score >= 1.0)
        metrics[str(cutoff)] = {
            "primary": cutoff == primary_cutoff,
            "total": len(scores),
            "passed": passed,
            "failed": len(scores) - passed,
            "accuracy": _ratio(passed, len(scores)),
            "avg_score": _avg(scores),
            "avg_memories_evaluated": _avg(
                _memories_evaluated_for_cutoff(item, cutoff) for item in cutoff_items
            ),
            "max_memories_evaluated": max(
                (_memories_evaluated_for_cutoff(item, cutoff) for item in cutoff_items),
                default=0,
            ),
        }
    return metrics


def _top_k_gate_metrics(
    items: Sequence[Mapping[str, object]],
    *,
    configured_cutoffs: Sequence[int],
    primary_cutoff: int,
) -> dict[str, object]:
    lower_cutoffs = tuple(
        sorted(cutoff for cutoff in configured_cutoffs if cutoff < primary_cutoff)
    )
    largest_lower_cutoff = lower_cutoffs[-1] if lower_cutoffs else None
    primary_counts = [
        _evaluation_memories_evaluated_for_cutoff(item, primary_cutoff)
        for item in items
        if item.get("scored") is True
    ]
    lower_counts = (
        [
            _evaluation_memories_evaluated_for_cutoff(item, largest_lower_cutoff)
            for item in items
            if item.get("scored") is True
        ]
        if largest_lower_cutoff is not None
        else []
    )
    primary_avg = _avg(primary_counts)
    lower_avg = _avg(lower_counts)
    primary_exceeds_lower = (
        largest_lower_cutoff is not None
        and bool(primary_counts)
        and primary_avg > lower_avg
    )
    return {
        "primary_cutoff": primary_cutoff,
        "largest_lower_cutoff": largest_lower_cutoff,
        "primary_avg_memories_evaluated": primary_avg,
        "largest_lower_avg_memories_evaluated": lower_avg,
        "primary_max_memories_evaluated": max(primary_counts, default=0),
        "largest_lower_max_memories_evaluated": max(lower_counts, default=0),
        "primary_reached_cutoff_count": sum(
            1 for count in primary_counts if count >= primary_cutoff
        ),
        "primary_exceeds_largest_lower": primary_exceeds_lower,
        "fake_top_k_suspected": (
            largest_lower_cutoff is not None
            and bool(primary_counts)
            and primary_avg <= lower_avg
        ),
    }


def _source_mix_gate_metrics(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    counts = _retrieval_source_counts(items)
    non_postgres_count = sum(
        count
        for source, count in counts.items()
        if source not in {"postgres_facts", "unknown"}
    )
    hybrid_item_count = sum(
        1
        for item in items
        for result in _retrieval_results(item)
        if len(_result_retrieval_sources(result)) > 1
    )
    unique_sources = tuple(source for source in counts if source != "unknown")
    return {
        "retrieval_source_counts": counts,
        "unique_source_count": len(unique_sources),
        "non_postgres_source_count": non_postgres_count,
        "hybrid_item_count": hybrid_item_count,
        "only_postgres_facts": bool(counts) and set(counts) <= {"postgres_facts"},
        "source_mix_ok": non_postgres_count > 0 or hybrid_item_count > 0,
    }


def _temporal_metadata_gate_metrics(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    timestamped_operations = 0
    session_date_operations = 0
    for item in items:
        ingestion = _mapping(item.get("ingestion"))
        operations = ingestion.get("operations", ())
        if not isinstance(operations, Sequence) or isinstance(operations, str | bytes):
            continue
        for operation in operations:
            if not isinstance(operation, Mapping):
                continue
            metadata = _mapping(operation.get("metadata"))
            if _positive_int(metadata.get("source_timestamp")) is not None:
                timestamped_operations += 1
            if str(metadata.get("session_date") or "").strip():
                session_date_operations += 1
    return {
        "timestamped_ingestion_operations": timestamped_operations,
        "session_dated_ingestion_operations": session_date_operations,
        "temporal_metadata_ok": timestamped_operations > 0,
    }


def _benchmark_rerank_gate_metrics(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    retrieval_metadata = [
        _mapping(_mapping(item.get("retrieval")).get("metadata")) for item in items
    ]
    reranks = [
        metadata.get("benchmark_rerank") for metadata in retrieval_metadata
    ]
    query_expansions = [
        metadata.get("query_expansion") for metadata in retrieval_metadata
    ]
    multi_query_merges = [
        metadata.get("multi_query_merge") for metadata in retrieval_metadata
    ]
    rerank_payloads = [_mapping(item) for item in reranks if isinstance(item, Mapping)]
    query_expansion_payloads = [
        _mapping(item) for item in query_expansions if isinstance(item, Mapping)
    ]
    multi_query_merge_payloads = [
        _mapping(item) for item in multi_query_merges if isinstance(item, Mapping)
    ]
    boosted_counts = [
        _positive_int(payload.get("boosted_memory_count")) or 0
        for payload in rerank_payloads
    ]
    max_boosts = [_metric_value(payload, "max_boost") for payload in rerank_payloads]
    uses_ground_truth_count = sum(
        1 for payload in rerank_payloads if bool(payload.get("uses_ground_truth"))
    ) + sum(
        1
        for payload in query_expansion_payloads
        if bool(payload.get("uses_ground_truth"))
    )
    return {
        "evaluation_count": len(rerank_payloads),
        "query_expansion_evaluation_count": len(query_expansion_payloads),
        "query_expansion_applied_count": sum(
            1 for payload in query_expansion_payloads if payload.get("applied")
        ),
        "multi_query_evaluation_count": len(multi_query_merge_payloads),
        "multi_query_raw_result_count": sum(
            _positive_int(payload.get("raw_result_count")) or 0
            for payload in multi_query_merge_payloads
        ),
        "multi_query_unique_result_count": sum(
            _positive_int(payload.get("unique_result_count")) or 0
            for payload in multi_query_merge_payloads
        ),
        "multi_query_hit_count": sum(
            _positive_int(payload.get("multi_query_hit_count")) or 0
            for payload in multi_query_merge_payloads
        ),
        "applied_count": sum(1 for payload in rerank_payloads if payload.get("applied")),
        "boosted_memory_count": sum(boosted_counts),
        "max_boost": max(max_boosts, default=0.0),
        "uses_ground_truth_count": uses_ground_truth_count,
        "uses_ground_truth": uses_ground_truth_count > 0,
        "benchmark_rerank_ok": bool(rerank_payloads) and uses_ground_truth_count == 0,
    }


def _query_integrity_gate_metrics(items: Sequence[Mapping[str, object]]) -> dict[str, object]:
    item_payloads = [
        (
            item,
            _mapping(
                _mapping(_mapping(item.get("retrieval")).get("metadata")).get(
                    "query_integrity"
                )
            ),
        )
        for item in items
    ]
    item_payloads = [
        (item, payload) for item, payload in item_payloads if payload
    ]
    overlap_items = [
        (item, payload)
        for item, payload in item_payloads
        if _positive_int(payload.get("expected_answer_query_overlap_count"))
    ]
    profile_overlap_items = [
        (item, payload)
        for item, payload in item_payloads
        if _positive_int(payload.get("expected_answer_query_profile_overlap_count"))
    ]
    intent_overlap_items = [
        (item, payload)
        for item, payload in item_payloads
        if _positive_int(
            payload.get("expected_answer_retrieval_intent_overlap_count")
        )
    ]
    overlap_counts = [
        _positive_int(payload.get("expected_answer_query_overlap_count")) or 0
        for _item, payload in item_payloads
    ]
    profile_overlap_counts = [
        _positive_int(payload.get("expected_answer_query_profile_overlap_count")) or 0
        for _item, payload in item_payloads
    ]
    intent_overlap_counts = [
        _positive_int(
            payload.get("expected_answer_retrieval_intent_overlap_count")
        )
        or 0
        for _item, payload in item_payloads
    ]
    ranked_overlap_items = _ranked_query_integrity_overlap_items(
        overlap_items,
        count_key="expected_answer_query_overlap_count",
    )
    ranked_profile_overlap_items = _ranked_query_integrity_overlap_items(
        profile_overlap_items,
        count_key="expected_answer_query_profile_overlap_count",
    )
    ranked_intent_overlap_items = _ranked_query_integrity_overlap_items(
        intent_overlap_items,
        count_key="expected_answer_retrieval_intent_overlap_count",
    )
    overlap_samples = _query_integrity_overlap_samples(
        ranked_overlap_items,
        count_key="expected_answer_query_overlap_count",
        terms_key="expected_answer_query_overlap_terms",
    )
    profile_overlap_samples = _query_integrity_overlap_samples(
        ranked_profile_overlap_items,
        count_key="expected_answer_query_profile_overlap_count",
        terms_key="expected_answer_query_profile_overlap_terms",
    )
    intent_overlap_samples = _query_integrity_overlap_samples(
        ranked_intent_overlap_items,
        count_key="expected_answer_retrieval_intent_overlap_count",
        terms_key="expected_answer_retrieval_intent_overlap_terms",
    )
    return {
        "diagnostic_only": True,
        "affects_retrieval": False,
        "evaluation_count": len(item_payloads),
        "overlap_case_count": len(overlap_items),
        "overlap_token_total": sum(overlap_counts),
        "overlap_case_rate": _ratio(len(overlap_items), len(item_payloads)),
        "avg_overlap_count": _avg(overlap_counts),
        "max_overlap_count": max(overlap_counts, default=0),
        "profile_overlap_case_count": len(profile_overlap_items),
        "profile_overlap_token_total": sum(profile_overlap_counts),
        "profile_overlap_case_rate": _ratio(
            len(profile_overlap_items),
            len(item_payloads),
        ),
        "avg_profile_overlap_count": _avg(profile_overlap_counts),
        "max_profile_overlap_count": max(profile_overlap_counts, default=0),
        "retrieval_intent_overlap_case_count": len(intent_overlap_items),
        "retrieval_intent_overlap_token_total": sum(intent_overlap_counts),
        "retrieval_intent_overlap_case_rate": _ratio(
            len(intent_overlap_items),
            len(item_payloads),
        ),
        "avg_retrieval_intent_overlap_count": _avg(intent_overlap_counts),
        "max_retrieval_intent_overlap_count": max(intent_overlap_counts, default=0),
        "query_integrity_clean": (
            len(overlap_items) == 0
            and len(profile_overlap_items) == 0
            and len(intent_overlap_items) == 0
        ),
        "profile_query_integrity_clean": len(profile_overlap_items) == 0,
        "retrieval_intent_query_integrity_clean": len(intent_overlap_items) == 0,
        "sample_overlap_case_ids": [
            str(item.get("case_id"))
            for item, _payload in ranked_overlap_items[:10]
            if item.get("case_id")
        ],
        "sample_overlap_cases": overlap_samples,
        "sample_profile_overlap_case_ids": [
            str(item.get("case_id"))
            for item, _payload in ranked_profile_overlap_items[:10]
            if item.get("case_id")
        ],
        "sample_profile_overlap_cases": profile_overlap_samples,
        "sample_retrieval_intent_overlap_case_ids": [
            str(item.get("case_id"))
            for item, _payload in ranked_intent_overlap_items[:10]
            if item.get("case_id")
        ],
        "sample_retrieval_intent_overlap_cases": intent_overlap_samples,
    }


def _ranked_query_integrity_overlap_items(
    overlap_items: Sequence[tuple[Mapping[str, object], Mapping[str, object]]],
    *,
    count_key: str,
) -> tuple[tuple[Mapping[str, object], Mapping[str, object]], ...]:
    return tuple(
        sorted(
            overlap_items,
            key=lambda item: (
                -(_positive_int(item[1].get(count_key)) or 0),
                str(item[0].get("case_id") or ""),
            ),
        )
    )


def _query_integrity_overlap_samples(
    overlap_items: Sequence[tuple[Mapping[str, object], Mapping[str, object]]],
    *,
    count_key: str,
    terms_key: str,
) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for item, payload in overlap_items[:10]:
        case_id = item.get("case_id")
        if not case_id:
            continue
        overlap_terms = _str_tuple(payload.get(terms_key))[:20]
        samples.append(
            {
                "case_id": str(case_id),
                "overlap_count": _positive_int(payload.get(count_key))
                or len(overlap_terms),
                "overlap_terms": list(overlap_terms),
            }
        )
    return samples


def _multi_hop_bundle_gate_metrics(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    multi_hop_items = [
        item
        for item in items
        if item.get("group") == "multi-hop" and item.get("scored") is True
    ]
    bundles = [_mapping(item.get("evidence_bundle")) for item in multi_hop_items]
    complete_count = sum(1 for bundle in bundles if bool(bundle.get("bundle_complete")))
    return {
        "multi_hop_evaluation_count": len(multi_hop_items),
        "bundle_complete_count": complete_count,
        "bundle_completion_rate": _ratio(complete_count, len(multi_hop_items)),
        "avg_bundle_item_count": _avg(
            _metric_value(bundle, "item_count") for bundle in bundles
        ),
        "avg_supporting_evidence_count": _avg(
            _metric_value(bundle, "supporting_evidence_count") for bundle in bundles
        ),
        "avg_bundle_evidence_term_recall": _avg(
            _metric_value(bundle, "evidence_term_recall") for bundle in bundles
        ),
        "avg_bundle_query_support_term_recall": _avg(
            _metric_value(bundle, "query_support_term_recall") for bundle in bundles
        ),
        "avg_bundle_query_support_term_count": _avg(
            _metric_value(bundle, "query_support_term_count") for bundle in bundles
        ),
        "multi_hop_bundle_ok": bool(multi_hop_items) and complete_count > 0,
    }


def _memories_evaluated_for_cutoff(
    cutoff_payload: Mapping[str, object],
    cutoff: int,
) -> int:
    value = cutoff_payload.get("memories_evaluated")
    if value is None:
        value = _mapping(cutoff_payload.get(str(cutoff))).get("memories_evaluated")
    return _positive_int(value) or 0


def _evaluation_memories_evaluated_for_cutoff(
    item: Mapping[str, object],
    cutoff: int,
) -> int:
    cutoff_payload = _mapping(_mapping(item.get("cutoff_results")).get(str(cutoff)))
    return _memories_evaluated_for_cutoff(cutoff_payload, cutoff)


def _failure_analysis_entry(
    evaluation: Mapping[str, object],
) -> dict[str, object] | None:
    if evaluation.get("scored") is not True:
        return None
    retrieval_quality = _mapping(evaluation.get("retrieval_quality"))
    judgment = _mapping(evaluation.get("judgment"))
    missing_terms = retrieval_quality.get("missing_terms")
    score = float(judgment.get("score", 0.0))
    retrieval_recall = float(retrieval_quality.get("expected_term_recall", 0.0))
    if score >= 1.0 and retrieval_recall >= 1.0:
        return None
    diagnostics = _failure_diagnostics(evaluation)
    return {
        "backend": evaluation.get("backend"),
        "case_id": evaluation.get("case_id"),
        "group": evaluation.get("group"),
        "capability": evaluation.get("capability"),
        "score": score,
        "retrieval_expected_term_recall": retrieval_recall,
        "missing_terms": missing_terms if isinstance(missing_terms, list) else [],
        "reason": judgment.get("reason") or "retrieval_or_judgment_failed",
        "diagnostic_reason_codes": _failure_diagnostic_reason_codes(
            evaluation,
            score=score,
            retrieval_recall=retrieval_recall,
            diagnostics=diagnostics,
        ),
        "diagnostics": diagnostics,
        "answer_preview": str(_mapping(evaluation.get("generation")).get("answer", ""))[:240],
    }


def _backend_comparison(
    backend_metrics: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    ranked = sorted(
        backend_metrics.items(),
        key=lambda item: _metric_value(item[1], "accuracy"),
        reverse=True,
    )
    comparison: dict[str, object] = {
        "ranked_by_accuracy": [name for name, _ in ranked],
    }
    if ranked:
        comparison["winner_by_accuracy"] = ranked[0][0]
    if "memo-stack" in backend_metrics and "mem0" in backend_metrics:
        memo_metrics = backend_metrics["memo-stack"]
        mem0_metrics = backend_metrics["mem0"]
        comparison["memo_stack_vs_mem0_accuracy_delta"] = _metric_delta(
            memo_metrics,
            mem0_metrics,
            "accuracy",
        )
        comparison["memo_stack_vs_mem0_expected_term_recall_delta"] = _metric_delta(
            memo_metrics,
            mem0_metrics,
            "expected_term_recall",
        )
        comparison["memo_stack_vs_mem0_evidence_term_recall_delta"] = _metric_delta(
            memo_metrics,
            mem0_metrics,
            "evidence_term_recall",
        )
        comparison["memo_stack_vs_mem0_avg_retrieved_count_delta"] = _metric_delta(
            memo_metrics,
            mem0_metrics,
            "avg_retrieved_count",
        )
        comparison["memo_stack_vs_mem0_avg_context_tokens_delta"] = _metric_delta(
            memo_metrics,
            mem0_metrics,
            "avg_context_tokens",
        )
        comparison["memo_stack_vs_mem0_latency_delta_ms"] = {
            "ingest": _metric_delta(memo_metrics, mem0_metrics, "avg_ingest_latency_ms"),
            "search": _metric_delta(memo_metrics, mem0_metrics, "avg_search_latency_ms"),
            "generation": _metric_delta(
                memo_metrics,
                mem0_metrics,
                "avg_generation_latency_ms",
            ),
            "judge": _metric_delta(memo_metrics, mem0_metrics, "avg_judge_latency_ms"),
        }
        comparison["memo_stack_vs_mem0_token_cost_total_usd_delta"] = round(
            _nested_float(memo_metrics, "token_cost", "total_usd")
            - _nested_float(mem0_metrics, "token_cost", "total_usd"),
            8,
        )
    return comparison


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
    metadata = {
        **dict(_mapping(result.get("metadata"))),
        "report_mode": MEMORY_COMPARISON_REPORT_COMPACT,
        "full_evaluation_count": len(evaluations),
        "compact_failure_limit": failure_limit,
    }
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
        "requested_case_ids": result.get("requested_case_ids", []),
        "requested_capabilities": result.get("requested_capabilities", []),
        "case_selection": result.get("case_selection", {}),
        "metadata": metadata,
        "metrics": result.get("metrics", {}),
        "backend_metrics": result.get("backend_metrics", {}),
        "backend_comparison": result.get("backend_comparison", {}),
        "diagnostics": _compact_diagnostics(evaluations),
        "failure_analysis": failure_analysis[:failure_limit],
        "failures": failures[:failure_limit],
        "evaluations": [],
        "elapsed_ms": result.get("elapsed_ms", 0.0),
    }
    provenance = result.get("provenance")
    if isinstance(provenance, Mapping):
        compact["provenance"] = dict(provenance)
    return compact


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


def _compact_fast_gate_summary(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    gate = _fast_gate_metrics(items)
    selected_weakness = _mapping(gate.get("selected_evidence_weakness"))
    query_role_gaps = _mapping(gate.get("query_role_gap_breakdown"))
    query_plan_gaps = _mapping(gate.get("query_plan_gap_breakdown"))
    bundle_gaps = _mapping(gate.get("bundle_gap_breakdown"))
    rerank_signal_gaps = _mapping(gate.get("rerank_signal_gap_breakdown"))
    actionable = _mapping(gate.get("actionable_gap_summary"))
    return {
        "schema_version": "compact_fast_gate_summary.v1",
        "ready_for_full_locomo": bool(gate.get("ready_for_full_locomo")),
        "failed_gates": list(_str_tuple(gate.get("failed_gates"))),
        "evaluation_count": _positive_int(gate.get("evaluation_count")) or 0,
        "expected_case_count": _positive_int(gate.get("expected_case_count")) or 0,
        "top_gap": actionable.get("top_gap"),
        "blocking_gap_count": _positive_int(actionable.get("blocking_gap_count")) or 0,
        "diagnostic_gap_count": _positive_int(actionable.get("diagnostic_gap_count")) or 0,
        "selected_evidence_weakness_counts": {
            "weak_case_count": _positive_int(selected_weakness.get("weak_case_count"))
            or 0,
            "low_answerability_item_count": _positive_int(
                selected_weakness.get("low_answerability_item_count")
            )
            or 0,
            "weak_source_locality_item_count": _positive_int(
                selected_weakness.get("weak_source_locality_item_count")
            )
            or 0,
            "broad_summary_item_count": _positive_int(
                selected_weakness.get("broad_summary_item_count")
            )
            or 0,
            "conflict_or_stale_item_count": _positive_int(
                selected_weakness.get("conflict_or_stale_item_count")
            )
            or 0,
            "reason_counts": _compact_count_mapping(
                selected_weakness.get("reason_counts")
            ),
            "risk_reason_counts": _compact_count_mapping(
                selected_weakness.get("risk_reason_counts")
            ),
        },
        "selected_evidence_weakness_samples": {
            "samples": _compact_selected_evidence_weakness_samples(
                selected_weakness.get("samples")
            ),
            "low_answerability_samples": _compact_selected_evidence_weakness_samples(
                selected_weakness.get("low_answerability_samples")
            ),
            "weak_source_locality_samples": _compact_selected_evidence_weakness_samples(
                selected_weakness.get("weak_source_locality_samples")
            ),
            "broad_summary_samples": _compact_selected_evidence_weakness_samples(
                selected_weakness.get("broad_summary_samples")
            ),
            "conflict_or_stale_samples": _compact_selected_evidence_weakness_samples(
                selected_weakness.get("conflict_or_stale_samples")
            ),
        },
        "query_role_gap_counts": {
            "role_gap_count": _positive_int(query_role_gaps.get("role_gap_count")) or 0,
            "role_family_gap_count": _positive_int(
                query_role_gaps.get("role_family_gap_count")
            )
            or 0,
            "required_role_coverage_gap_count": _positive_int(
                query_role_gaps.get("required_role_coverage_gap_count")
            )
            or 0,
            "bridge_hit_roles_without_selected_items": list(
                _str_tuple(query_role_gaps.get("bridge_hit_roles_without_selected_items"))
            ),
            "bridge_hit_role_families_without_selected_items": list(
                _str_tuple(
                    query_role_gaps.get(
                        "bridge_hit_role_families_without_selected_items"
                    )
                )
            ),
        },
        "query_plan_gap_counts": {
            "plan_gap_case_count": _positive_int(
                query_plan_gaps.get("plan_gap_case_count")
            )
            or 0,
            "missing_evidence_role_query_family_total": _positive_int(
                query_plan_gaps.get("missing_evidence_role_query_family_total")
            )
            or 0,
            "missing_evidence_role_query_family_counts": _compact_count_mapping(
                query_plan_gaps.get("missing_evidence_role_query_family_counts")
            ),
            "gap_reason_counts": _compact_count_mapping(
                query_plan_gaps.get("gap_reason_counts")
            ),
        },
        "bundle_gap_counts": {
            "incomplete_case_count": _positive_int(
                bundle_gaps.get("incomplete_case_count")
            )
            or 0,
            "reason_counts": _compact_count_mapping(bundle_gaps.get("reason_counts")),
            "bridge_gap_reason_counts": _compact_count_mapping(
                bundle_gaps.get("bridge_gap_reason_counts")
            ),
        },
        "rerank_signal_gap_counts": {
            "candidate_count": _positive_int(rerank_signal_gaps.get("candidate_count"))
            or 0,
            "selected_item_count": _positive_int(
                rerank_signal_gaps.get("selected_item_count")
            )
            or 0,
            "positive_rerank_candidate_count": _positive_int(
                rerank_signal_gaps.get("positive_rerank_candidate_count")
            )
            or 0,
            "positive_unselected_candidate_count": _positive_int(
                rerank_signal_gaps.get("positive_unselected_candidate_count")
            )
            or 0,
            "positive_unselected_case_count": _positive_int(
                rerank_signal_gaps.get("positive_unselected_case_count")
            )
            or 0,
            "selected_with_positive_rerank_count": _positive_int(
                rerank_signal_gaps.get("selected_with_positive_rerank_count")
            )
            or 0,
            "selected_without_positive_rerank_count": _positive_int(
                rerank_signal_gaps.get("selected_without_positive_rerank_count")
            )
            or 0,
            "selected_without_positive_rerank_case_count": _positive_int(
                rerank_signal_gaps.get(
                    "selected_without_positive_rerank_case_count"
                )
            )
            or 0,
            "positive_signal_counts": _compact_count_mapping(
                rerank_signal_gaps.get("positive_signal_counts")
            ),
            "positive_unselected_signal_counts": _compact_count_mapping(
                rerank_signal_gaps.get("positive_unselected_signal_counts")
            ),
            "selected_without_positive_reason_counts": _compact_count_mapping(
                rerank_signal_gaps.get("selected_without_positive_reason_counts")
            ),
        },
    }


def _compact_selected_evidence_weakness_samples(
    value: object,
    *,
    limit: int = 3,
) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return []
    samples: list[dict[str, object]] = []
    allowed_scalar_keys = {
        "case_id",
        "group",
        "item_id",
        "role",
        "query_role_count",
        "retrieval_order",
        "answerability_score",
        "source_locality_score",
        "broad_summary",
        "conflict_or_stale",
        "source_ref_count",
        "risk_reason_count",
        "planner_reason_count",
        "answerability_reason_count",
        "source_locality_reason_count",
        "retrieval_source_count",
        "source_type_count",
        "relation_category_count",
        "relation_category_hit_count",
        "source_type",
        "stale_reason",
        "conflict_reason",
    }
    allowed_sequence_keys = {
        "query_roles",
        "reasons",
        "source_refs",
        "risk_reason_codes",
        "planner_reason_codes",
        "answerability_reason_codes",
        "source_locality_reason_codes",
        "retrieval_sources",
        "source_types",
        "relation_categories",
        "relation_category_hits",
    }
    for raw_sample in value:
        sample = _mapping(raw_sample)
        if not sample:
            continue
        compact: dict[str, object] = {}
        for key in sorted(allowed_scalar_keys):
            if key in sample:
                compact[key] = sample[key]
        for key in sorted(allowed_sequence_keys):
            if key in sample:
                compact[key] = list(_str_tuple(sample.get(key))[:6])
        samples.append(compact)
        if len(samples) >= limit:
            break
    return samples


def _compact_evidence_bundle_coverage(
    items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    bundles = [
        _mapping(item.get("evidence_bundle"))
        for item in items
        if _mapping(item.get("evidence_bundle"))
    ]
    complete_count = sum(1 for bundle in bundles if bundle.get("bundle_complete") is True)
    missing_required_role_counts: dict[str, int] = defaultdict(int)
    for bundle in bundles:
        for role in _str_tuple(bundle.get("missing_required_roles")):
            missing_required_role_counts[role] += 1
    evidence_term_count = sum(
        _positive_int(bundle.get("evidence_term_count")) or 0 for bundle in bundles
    )
    covered_evidence_term_count = sum(
        len(_str_tuple(bundle.get("covered_evidence_terms"))) for bundle in bundles
    )
    incomplete_samples: list[dict[str, object]] = []
    for item in items:
        bundle = _mapping(item.get("evidence_bundle"))
        if not bundle or bundle.get("bundle_complete") is True:
            continue
        if len(incomplete_samples) >= 5:
            break
        quality = _mapping(item.get("retrieval_quality"))
        incomplete_samples.append(
            {
                "case_id": str(item.get("case_id") or ""),
                "group": str(item.get("group") or ""),
                "item_count": _positive_int(bundle.get("item_count")) or 0,
                "evidence_term_recall": round(
                    _metric_value(bundle, "evidence_term_recall"),
                    4,
                ),
                "missing_evidence_terms": list(
                    _str_tuple(quality.get("missing_evidence_terms"))[:8]
                ),
                "missing_expected_terms": list(
                    _str_tuple(quality.get("missing_terms"))[:8]
                ),
            }
        )
    return {
        "schema_version": "compact_evidence_bundle_coverage.v1",
        "bundle_count": len(bundles),
        "bundle_complete_count": complete_count,
        "bundle_incomplete_count": len(bundles) - complete_count,
        "bundle_completion_rate": _ratio(complete_count, len(bundles)),
        "avg_bundle_item_count": _avg(
            _metric_value(bundle, "item_count") for bundle in bundles
        ),
        "avg_evidence_term_recall": _avg(
            _metric_value(bundle, "evidence_term_recall") for bundle in bundles
        ),
        "avg_supporting_evidence_count": _avg(
            _metric_value(bundle, "supporting_evidence_count") for bundle in bundles
        ),
        "avg_query_support_term_recall": _avg(
            _metric_value(bundle, "query_support_term_recall") for bundle in bundles
        ),
        "evidence_term_count": evidence_term_count,
        "covered_evidence_term_count": covered_evidence_term_count,
        "missing_required_role_counts": dict(
            sorted(missing_required_role_counts.items())
        ),
        "incomplete_samples": incomplete_samples,
    }


def _numeric_summary(values: Iterable[float]) -> dict[str, object]:
    sequence = [float(value) for value in values]
    if not sequence:
        return {"count": 0, "avg": 0.0, "min": 0.0, "max": 0.0}
    return {
        "count": len(sequence),
        "avg": round(sum(sequence) / len(sequence), 4),
        "min": round(min(sequence), 4),
        "max": round(max(sequence), 4),
    }


def _retrieval_source_counts(
    items: Sequence[Mapping[str, object]],
) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        for result in _retrieval_results(item):
            for source in _result_retrieval_sources(result):
                counts[source] += 1
    return dict(sorted(counts.items()))


def _compact_count_mapping(value: object, *, limit: int = 12) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not isinstance(value, Mapping):
        return counts
    for key, raw_count in value.items():
        count = _positive_int(raw_count)
        if count is None:
            continue
        counts[str(key)] = count
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return dict(ranked[:limit])


def _retrieval_results(item: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    retrieval = _mapping(item.get("retrieval"))
    results = retrieval.get("results", ())
    if not isinstance(results, Sequence) or isinstance(results, str | bytes):
        return ()
    return tuple(result for result in results if isinstance(result, Mapping))


def _result_retrieval_sources(result: Mapping[str, object]) -> tuple[str, ...]:
    metadata = _mapping(result.get("metadata"))
    diagnostics = _mapping(metadata.get("diagnostics"))
    sources = diagnostics.get("retrieval_sources")
    if isinstance(sources, Sequence) and not isinstance(sources, str | bytes):
        return tuple(str(source or "unknown") for source in sources)
    return (str(diagnostics.get("retrieval_source") or "unknown"),)


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


def _normalize_top_k_cutoffs(*, top_k: int, values: Sequence[int]) -> tuple[int, ...]:
    if isinstance(top_k, bool) or top_k < 1:
        raise BenchmarkValidationError("top_k must be greater than zero")
    normalized = {top_k}
    for raw in values:
        value = int(raw)
        if value < 1:
            raise BenchmarkValidationError("top_k_cutoffs must be greater than zero")
        if value > top_k:
            raise BenchmarkValidationError("top_k_cutoffs cannot exceed top_k")
        normalized.add(value)
    return tuple(sorted(normalized))


def _unique_backend_names(backends: Sequence[MemoryComparisonBackendPort]) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    duplicates: set[str] = set()
    for index, backend in enumerate(backends, start=1):
        name = str(backend.name).strip()
        if not name:
            raise BenchmarkValidationError(
                f"comparison backend at position {index} must have a non-empty name"
            )
        if name in seen:
            duplicates.add(name)
        seen.add(name)
        names.append(name)
    if duplicates:
        duplicate_names = ", ".join(sorted(duplicates))
        raise BenchmarkValidationError(
            f"comparison backend names must be unique: {duplicate_names}"
        )
    return tuple(names)


def _evaluation_score(item: Mapping[str, object]) -> float:
    return float(_mapping(item.get("judgment")).get("score", 0.0))


def _retrieved_count(item: Mapping[str, object]) -> float:
    retrieval = _mapping(item.get("retrieval"))
    return float(retrieval.get("total_results", 0.0))


def _search_latency(item: Mapping[str, object]) -> float:
    return float(_mapping(item.get("retrieval")).get("latency_ms", 0.0))


def _ingest_latency(item: Mapping[str, object]) -> float:
    return float(_mapping(item.get("ingestion")).get("latency_ms", 0.0))


def _stage_latency(item: Mapping[str, object], stage: str) -> float:
    return float(_mapping(item.get(stage)).get("latency_ms", 0.0))


def _context_tokens(item: Mapping[str, object]) -> float:
    retrieval = _mapping(item.get("retrieval"))
    value = retrieval.get("context_token_count")
    if isinstance(value, int | float):
        return float(value)
    memories = retrieval.get("results")
    if not isinstance(memories, list):
        return 0.0
    return float(
        sum(
            approximate_token_count(str(_mapping(memory).get("memory", "")))
            for memory in memories
        )
    )


def _retrieval_recall(item: Mapping[str, object]) -> float:
    return float(_mapping(item.get("retrieval_quality")).get("expected_term_recall", 0.0))


def _has_evidence_recall(item: Mapping[str, object]) -> bool:
    return "evidence_term_recall" in _mapping(item.get("retrieval_quality"))


def _evidence_recall(item: Mapping[str, object]) -> float:
    return float(_mapping(item.get("retrieval_quality")).get("evidence_term_recall", 0.0))


def _metric_delta(
    left: Mapping[str, object],
    right: Mapping[str, object],
    key: str,
) -> float:
    return round(_metric_value(left, key) - _metric_value(right, key), 4)


def _metric_value(item: Mapping[str, object], key: str) -> float:
    value = item.get(key)
    if isinstance(value, bool):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _nested_float(item: Mapping[str, object], *keys: str) -> float:
    current: object = item
    for key in keys:
        current = _mapping(current).get(key)
    if isinstance(current, bool):
        return 0.0
    try:
        return float(current)
    except (TypeError, ValueError):
        return 0.0


def _token_usage_summary(items: Sequence[Mapping[str, object]]) -> dict[str, object]:
    answerer = _stage_token_usage_summary(items, "generation")
    judge = _stage_token_usage_summary(items, "judgment")
    prompt_tokens = answerer.prompt_tokens + judge.prompt_tokens
    completion_tokens = answerer.completion_tokens + judge.completion_tokens
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "by_stage": {
            "answerer": {
                "prompt_tokens": answerer.prompt_tokens,
                "completion_tokens": answerer.completion_tokens,
                "total_tokens": answerer.total_tokens,
            },
            "judge": {
                "prompt_tokens": judge.prompt_tokens,
                "completion_tokens": judge.completion_tokens,
                "total_tokens": judge.total_tokens,
            },
        },
    }


def _token_cost_summary(
    items: Sequence[Mapping[str, object]],
    *,
    answerer_token_cost_rate: TokenCostRate,
    judge_token_cost_rate: TokenCostRate,
) -> dict[str, object]:
    answerer_usage = _stage_token_usage_summary(items, "generation")
    judge_usage = _stage_token_usage_summary(items, "judgment")
    answerer_cost = token_cost_payload(answerer_usage, answerer_token_cost_rate)
    judge_cost = token_cost_payload(judge_usage, judge_token_cost_rate)
    return {
        "configured": (
            answerer_token_cost_rate.is_configured
            or judge_token_cost_rate.is_configured
        ),
        "scope": "answerer_judge_only",
        "unmeasured_backend_provider_costs": True,
        "currency": "USD",
        "answerer": answerer_cost,
        "judge": judge_cost,
        "total_usd": round(
            float(answerer_cost["total_usd"]) + float(judge_cost["total_usd"]),
            8,
        ),
    }


def _stage_token_usage_summary(
    items: Sequence[Mapping[str, object]],
    stage: str,
) -> TokenUsage:
    prompt_tokens = 0
    completion_tokens = 0
    for item in items:
        usage = _mapping(_mapping(item.get(stage)).get("token_usage"))
        prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens += int(usage.get("completion_tokens", 0) or 0)
    return TokenUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def _group_by(
    items: Sequence[Mapping[str, object]],
    *,
    key: str,
) -> dict[str, list[Mapping[str, object]]]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for item in items:
        grouped[str(item.get(key) or "unknown")].append(item)
    return grouped


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _avg(values: Sequence[float] | object) -> float:
    sequence = tuple(float(value) for value in values)  # type: ignore[arg-type]
    return round(sum(sequence) / len(sequence), 4) if sequence else 0.0


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _str_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else ()
    if not isinstance(value, Sequence) or isinstance(value, bytes):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _positive_ints(value: object) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    return tuple(parsed for item in value if (parsed := _positive_int(item)) is not None)


def _float_value(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _safe_error_reason(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return redact_sensitive_text(f"{exc.__class__.__name__}: {message}")[:500]


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def _write_report(result: dict[str, object], report_out: Path | None) -> None:
    if report_out is None:
        return
    report_out.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(report_out, result)
