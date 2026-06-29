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
from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path

from infinity_context_core.application.sensitive_text import redact_sensitive_text
from infinity_context_core.reporting import with_report_provenance

from infinity_context_server.memory_comparison_llm import (
    EvidenceOnlyAnswerer,
    ExpectedTermsJudge,
    approximate_token_count,
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
from infinity_context_server.public_benchmark import (
    LOCOMO_BENCHMARK_SUITE,
    PUBLIC_MEMORY_BENCHMARK_SUITE,
    _case_capability,
    _dataset_hash,
    _duplicate_case_keys,
    _load_cases,
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

_LOCOMO_CATEGORY_NAMES = {
    1: "multi-hop",
    2: "temporal",
    3: "open-domain",
    4: "single-hop",
    5: "adversarial",
}
_LOCOMO_SCORED_CATEGORIES = frozenset({1, 2, 3, 4})


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
) -> dict[str, object]:
    """Run a mem0-style benchmark against multiple memory backends."""

    if not backends:
        raise BenchmarkValidationError("at least one comparison backend is required")
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
    cases = tuple(cases_override) if cases_override is not None else _load_cases(dataset_path)
    canonical_benchmark = _normalize_benchmark_name(benchmark) if benchmark else None
    if canonical_benchmark:
        cases = tuple(case for case in cases if case.benchmark == canonical_benchmark)
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
        _write_report(result, report_out)
        return result

    evaluations: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    ingested_corpus_by_backend: dict[str, set[str]] = {name: set() for name in backend_names}

    reset_failure_by_backend: dict[str, str] = {}
    for backend, backend_name in zip(backends, backend_names, strict=True):
        try:
            backend.reset(run_id=run_id)
        except Exception as exc:
            reset_failure_by_backend[backend_name] = _safe_error_reason(exc)

    for case in cases:
        corpus_key = _case_corpus_key(case)
        for backend, backend_name in zip(backends, backend_names, strict=True):
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
                if ingest_result.items_failed == 0:
                    ingested_corpus_by_backend[backend_name].add(corpus_key)
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

    backend_metrics = {
        backend_name: _backend_metrics(
            evaluations,
            backend_name=backend_name,
            min_accuracy=min_accuracy,
            primary_cutoff=primary_cutoff,
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
            "backend_names": list(backend_names),
            "scoring_note": "LoCoMo category 5 is reported but excluded from scored accuracy.",
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
    retrieval_quality = _retrieval_quality(case, search_result.memories)
    cutoff_results: dict[str, object] = {}
    primary_answer = None
    primary_judgment = None
    for cutoff in cutoffs:
        sliced = search_result.memories[:cutoff]
        try:
            answer = answerer.answer(case, sliced, backend_name=backend_name, cutoff=cutoff)
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
                sliced,
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
        "retrieval": search_payload(search_result),
        "retrieval_quality": retrieval_quality,
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
    retrieval_quality = retrieval_quality or _retrieval_quality(case, search_result.memories)
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
        "retrieval": search_payload(search_result),
        "retrieval_quality": retrieval_quality,
        "generation": answer_payload(answer),
        "judgment": judge_payload(judgment),
        "cutoff_results": cutoff_results,
    }


def _backend_metrics(
    evaluations: Sequence[Mapping[str, object]],
    *,
    backend_name: str,
    min_accuracy: float,
    primary_cutoff: int,
    answerer_token_cost_rate: TokenCostRate,
    judge_token_cost_rate: TokenCostRate,
) -> dict[str, object]:
    backend_items = [item for item in evaluations if item.get("backend") == backend_name]
    scored = [item for item in backend_items if item.get("scored") is True]
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
        "token_usage": _token_usage_summary(backend_items),
        "token_cost": _token_cost_summary(
            backend_items,
            answerer_token_cost_rate=answerer_token_cost_rate,
            judge_token_cost_rate=judge_token_cost_rate,
        ),
        "by_category": by_category,
        "by_group": by_group,
        "by_cutoff": _cutoff_metrics(backend_items, primary_cutoff=primary_cutoff),
    }


def _bucket_metrics(items: Sequence[Mapping[str, object]]) -> dict[str, object]:
    scored = [item for item in items if item.get("scored") is True]
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
    }


def _cutoff_metrics(
    items: Sequence[Mapping[str, object]],
    *,
    primary_cutoff: int,
) -> dict[str, object]:
    cutoffs = sorted(
        {
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
        }
    return metrics


def _retrieval_quality(
    case: PublicBenchmarkCase,
    memories: Sequence[RetrievedMemory],
) -> dict[str, object]:
    evidence = _normalize_text(" ".join(memory.text for memory in memories))
    covered_terms = tuple(
        term for term in case.expected_terms if _normalize_text(term) in evidence
    )
    missing_terms = tuple(term for term in case.expected_terms if term not in covered_terms)
    return {
        "expected_term_count": len(case.expected_terms),
        "covered_expected_term_count": len(covered_terms),
        "expected_term_recall": _ratio(len(covered_terms), len(case.expected_terms)),
        "covered_terms": list(covered_terms),
        "missing_terms": list(missing_terms),
    }


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
    return {
        "backend": evaluation.get("backend"),
        "case_id": evaluation.get("case_id"),
        "group": evaluation.get("group"),
        "capability": evaluation.get("capability"),
        "score": score,
        "retrieval_expected_term_recall": retrieval_recall,
        "missing_terms": missing_terms if isinstance(missing_terms, list) else [],
        "reason": judgment.get("reason") or "retrieval_or_judgment_failed",
        "answer_preview": str(_mapping(evaluation.get("generation")).get("answer", ""))[:240],
    }


def _backend_comparison(
    backend_metrics: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    ranked = sorted(
        backend_metrics.items(),
        key=lambda item: float(item[1].get("accuracy", 0.0)),
        reverse=True,
    )
    comparison: dict[str, object] = {
        "ranked_by_accuracy": [name for name, _ in ranked],
    }
    if ranked:
        comparison["winner_by_accuracy"] = ranked[0][0]
    if "memo-stack" in backend_metrics and "mem0" in backend_metrics:
        comparison["memo_stack_vs_mem0_accuracy_delta"] = round(
            float(backend_metrics["memo-stack"].get("accuracy", 0.0))
            - float(backend_metrics["mem0"].get("accuracy", 0.0)),
            4,
        )
    return comparison


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


def _case_corpus_key(case: PublicBenchmarkCase) -> str:
    memory_scope = case.memory_scope_external_ref or case.case_id
    thread = case.thread_external_ref or case.case_id
    return f"{case.benchmark}:{memory_scope}:{thread}:{_case_corpus_fingerprint(case)}"


def _case_corpus_fingerprint(case: PublicBenchmarkCase) -> str:
    source_parts: list[dict[str, object]] = []
    for index, memory in enumerate(case.memories):
        source_parts.append(
            {
                "kind": "memory",
                "index": index,
                "memory_kind": memory.kind,
                "source_external_id": memory.source_external_id,
                "text": memory.text,
            }
        )
    for index, document in enumerate(case.documents):
        source_parts.append(
            {
                "kind": "document",
                "index": index,
                "title": document.title,
                "source_type": document.source_type,
                "classification": document.classification,
                "source_external_id": document.source_external_id,
                "text": document.text,
            }
        )
    encoded = json.dumps(
        source_parts,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _case_group(case: PublicBenchmarkCase) -> str:
    category = _case_category(case)
    if case.benchmark == LOCOMO_BENCHMARK_SUITE and category in _LOCOMO_CATEGORY_NAMES:
        return _LOCOMO_CATEGORY_NAMES[int(category)]
    return _case_capability(case)


def _case_category_label(case: PublicBenchmarkCase) -> str:
    category = _case_category(case)
    if category is None:
        return "uncategorized"
    if case.benchmark == LOCOMO_BENCHMARK_SUITE:
        name = _LOCOMO_CATEGORY_NAMES.get(category)
        if name:
            return f"{category}:{name}"
    return str(category)


def _case_is_scored(case: PublicBenchmarkCase) -> bool:
    category = _case_category(case)
    if case.benchmark == LOCOMO_BENCHMARK_SUITE and category is not None:
        return int(category) in _LOCOMO_SCORED_CATEGORIES
    return True


def _case_category(case: PublicBenchmarkCase) -> int | None:
    value = case.metadata.get("category")
    if isinstance(value, bool):
        return None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _case_ground_truth(case: PublicBenchmarkCase) -> str:
    answer = case.metadata.get("answer_preview")
    if isinstance(answer, str) and answer.strip():
        return answer
    return " | ".join(case.expected_terms)


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
