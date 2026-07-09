"""Per-case ingest/search/answer/judge execution helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_answer_context import (
    answer_context_from_evidence_bundle,
)
from infinity_context_server.memory_comparison_benchmark_shared import (
    _mapping,
    _safe_error_reason,
)
from infinity_context_server.memory_comparison_evidence import (
    evidence_bundle as build_evidence_bundle,
)
from infinity_context_server.memory_comparison_evidence import (
    retrieval_quality as build_retrieval_quality,
)
from infinity_context_server.memory_comparison_locomo_cases import (
    _case_category_label,
    _case_ground_truth,
    _case_group,
    _case_is_scored,
)
from infinity_context_server.memory_comparison_models import (
    AnswerResult,
    BackendIngestResult,
    BackendSearchResult,
    JudgeResult,
    MemoryComparisonAnswererPort,
    MemoryComparisonBackendPort,
    MemoryComparisonJudgePort,
    answer_payload,
    ingestion_payload,
    judge_payload,
    search_payload,
)
from infinity_context_server.memory_comparison_query_integrity import (
    query_integrity_diagnostics as _query_integrity_diagnostics,
)
from infinity_context_server.public_benchmark import _case_capability
from infinity_context_server.public_benchmark_models import PublicBenchmarkCase


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


