"""Replay helpers for saved memory comparison reports."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from infinity_context_server.memory_comparison_answer_context import (
    answer_context_from_evidence_bundle,
)
from infinity_context_server.memory_comparison_benchmark_shared import (
    _float_value,
    _mapping,
    _normalize_top_k_cutoffs,
    _positive_int,
    _positive_ints,
    _safe_error_reason,
    _str_tuple,
)
from infinity_context_server.memory_comparison_evidence import (
    evidence_bundle as build_evidence_bundle,
)
from infinity_context_server.memory_comparison_evidence import (
    retrieval_quality as build_retrieval_quality,
)
from infinity_context_server.memory_comparison_locomo_cases import (
    _LOCOMO_CATEGORY_NAMES,
    _case_category_label,
    _case_ground_truth,
    _case_group,
    _case_is_scored,
)
from infinity_context_server.memory_comparison_models import (
    AnswerResult,
    JudgeResult,
    MemoryComparisonAnswererPort,
    MemoryComparisonJudgePort,
    RetrievedMemory,
    answer_payload,
    judge_payload,
)
from infinity_context_server.public_benchmark import LOCOMO_BENCHMARK_SUITE, _case_capability
from infinity_context_server.public_benchmark_models import (
    BenchmarkValidationError,
    PublicBenchmarkCase,
)


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


