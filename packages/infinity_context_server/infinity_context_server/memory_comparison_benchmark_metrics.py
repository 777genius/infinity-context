"""Aggregate metric and comparison helpers for memory comparison reports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_answer_context import (
    answer_context_metrics as _answer_context_metrics,
)
from infinity_context_server.memory_comparison_benchmark_compact_samples import (
    _result_retrieval_sources,
    _retrieval_results,
    _retrieval_source_counts,
)
from infinity_context_server.memory_comparison_benchmark_shared import (
    _avg,
    _context_tokens,
    _evaluation_score,
    _evidence_recall,
    _group_by,
    _has_evidence_recall,
    _ingest_latency,
    _mapping,
    _metric_delta,
    _metric_value,
    _nested_float,
    _positive_int,
    _ratio,
    _retrieval_recall,
    _retrieved_count,
    _search_latency,
    _stage_latency,
    _str_tuple,
    _token_cost_summary,
    _token_usage_summary,
)
from infinity_context_server.memory_comparison_failure_diagnostics import (
    failure_diagnostic_reason_codes as _failure_diagnostic_reason_codes,
)
from infinity_context_server.memory_comparison_failure_diagnostics import (
    failure_diagnostics as _failure_diagnostics,
)
from infinity_context_server.memory_comparison_models import TokenCostRate
from infinity_context_server.memory_comparison_quality_diagnostics import (
    evidence_ref_rank_gate_metrics as _evidence_ref_rank_gate_metrics,
)
from infinity_context_server.memory_comparison_quality_diagnostics import (
    fast_gate_metrics as _fast_gate_metrics,
)
from infinity_context_server.memory_comparison_quality_diagnostics import (
    quality_diagnostics as _quality_diagnostics,
)


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
    missing_evidence_terms = retrieval_quality.get("missing_evidence_terms")
    score = float(judgment.get("score", 0.0))
    retrieval_recall = float(retrieval_quality.get("expected_term_recall", 0.0))
    evidence_recall = (
        _metric_value(retrieval_quality, "evidence_term_recall")
        if "evidence_term_recall" in retrieval_quality
        else None
    )
    evidence_recall_failed = evidence_recall is not None and evidence_recall < 1.0
    if score >= 1.0 and retrieval_recall >= 1.0 and not evidence_recall_failed:
        return None
    diagnostics = _failure_diagnostics(evaluation)
    return {
        "backend": evaluation.get("backend"),
        "case_id": evaluation.get("case_id"),
        "group": evaluation.get("group"),
        "category": evaluation.get("category"),
        "capability": evaluation.get("capability"),
        "score": score,
        "retrieval_expected_term_recall": retrieval_recall,
        "retrieval_evidence_term_recall": evidence_recall,
        "missing_terms": missing_terms if isinstance(missing_terms, list) else [],
        "missing_evidence_terms": (
            missing_evidence_terms if isinstance(missing_evidence_terms, list) else []
        ),
        "reason": (
            judgment.get("reason")
            or (
                "evidence_ref_support_incomplete"
                if evidence_recall_failed
                else "retrieval_or_judgment_failed"
            )
        ),
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


