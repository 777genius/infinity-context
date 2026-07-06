from __future__ import annotations

import json

from infinity_context_server.memory_comparison_benchmark import (
    _compact_fast_gate_summary,
    _compact_report,
)
from infinity_context_server.memory_comparison_quality_diagnostics import (
    fast_gate_metrics,
)


def test_unsupported_answerability_reasons_stay_non_actionable() -> None:
    gate = fast_gate_metrics(
        (
            _evaluation_item(
                case_id="unsupported-only",
                retrieval_results=(
                    _retrieved_candidate(
                        item_id="unsupported-answer",
                        score_signals={
                            "benchmark_provenance_safety_reason_codes": [
                                "unsupported_stale_evidence_cap",
                            ],
                        },
                        candidate_features={
                            "answerability_score": 0.82,
                            "answerability_reason_codes": [
                                "unsupported_memory_answer",
                                "unsupported_answer_claim",
                                "unsupported_answer_source",
                            ],
                            "query_roles": ["primary"],
                        },
                    ),
                ),
                bundle_items=(_selected_bundle_item("unsupported-answer"),),
            ),
        ),
        expected_case_count=1,
    )

    assert gate["passed"] is True
    assert gate["answerability_gap_breakdown"]["reason_counts"] == {}
    assert gate["answerability_gap_breakdown"]["samples"] == []
    assert gate["rerank_signal_gap_breakdown"]["positive_rerank_candidate_count"] == 0
    assert gate["actionable_gap_summary"]["ranked_gaps"] == []


def test_compact_fast_gate_keeps_rerank_samples_bounded_and_diagnostic_only() -> None:
    raw_memory_text = "RAW MEMORY TEXT should not appear in compact diagnostics"
    raw_payload = "RAW PROVIDER PAYLOAD should not appear in compact diagnostics"
    summary = _compact_fast_gate_summary(
        (
            _evaluation_item(
                case_id="rerank-contract",
                retrieval_results=(
                    _retrieved_candidate(
                        item_id="unselected-actionable",
                        rank=1,
                        score=0.91,
                        memory=raw_memory_text,
                        raw_provider_payload=raw_payload,
                        source_refs=(
                            "locomo:conv-private:session_2:D2:8:turn-secret",
                        ),
                        score_signals={
                            "benchmark_answerability_boost": 0.07,
                            "benchmark_effective_boost_cap": 0.22,
                            "benchmark_rank_penalty": -0.04,
                            "benchmark_provenance_safety_reason_codes": [
                                "unsupported_stale_evidence_cap",
                            ],
                        },
                        policy_score=0.07,
                        candidate_features={
                            "answerability_score": 0.9,
                            "source_locality_score": 0.86,
                            "source_type": "raw_turn",
                            "query_roles": ["contrast_support"],
                            "relation_category_hits": ["status_profile"],
                        },
                    ),
                    _retrieved_candidate(
                        item_id="selected-without-positive",
                        rank=2,
                        score=0.73,
                        score_signals={"benchmark_rank_penalty": -0.03},
                        candidate_features={
                            "answerability_score": 0.84,
                            "source_locality_score": 0.8,
                        },
                    ),
                ),
                bundle_items=(
                    _selected_bundle_item(
                        "selected-without-positive",
                        query_roles=("contrast_support",),
                    ),
                ),
            ),
        )
    )

    assert summary["schema_version"] == "compact_fast_gate_summary.v1"
    assert summary["rerank_signal_gap_counts"][
        "positive_unselected_candidate_count"
    ] == 1
    assert summary["rerank_signal_gap_counts"][
        "selected_without_positive_rerank_count"
    ] == 1
    samples = summary["rerank_signal_gap_samples"]
    assert samples["positive_unselected_samples"] == [
        {
            "answerability_score": 0.9,
            "benchmark_rerank_boosted": True,
            "case_id": "rerank-contract",
            "group": "multi-hop",
            "item_id": "unselected-actionable",
            "positive_policy_score": 0.07,
            "rank": 1,
            "score": 0.91,
            "source_locality_score": 0.86,
            "source_type": "raw_turn",
            "source_identity_refs": [
                "source_session_turn_refs:session_2:D2:8",
                "source_turn_refs:D2:8",
            ],
            "query_roles": ["contrast_support"],
            "relation_category_hits": ["status_profile"],
            "selected_item_ids": ["selected-without-positive"],
            "cap_signals": {"benchmark_effective_boost_cap": 0.22},
            "penalty_signals": {"benchmark_rank_penalty": -0.04},
            "policy_reasons": {"FocusedTurnPolicy": ["focused_turn"]},
            "top_signals": {
                "benchmark_answerability_boost": 0.07,
                "benchmark_effective_boost_cap": 0.22,
            },
        }
    ]
    assert samples["selected_without_positive_samples"] == [
        {
            "answerability_score": 0.8,
            "case_id": "rerank-contract",
            "group": "multi-hop",
            "item_id": "selected-without-positive",
            "matched_retrieval_candidate": True,
            "positive_policy_score": 0.0,
            "reason": "no_positive_rerank_signal",
            "retrieval_order": 1,
            "role": "primary",
            "source_locality_score": 0.8,
            "source_type": "unknown",
            "source_identity_refs": ["D1:1"],
            "query_roles": ["contrast_support"],
            "penalty_signals": {"benchmark_rank_penalty": -0.03},
        }
    ]
    assert summary["top_gap"]["category"] == "rerank_signal_selection"
    serialized = json.dumps(summary)
    assert raw_memory_text not in serialized
    assert raw_payload not in serialized
    assert "locomo:conv-private" not in serialized
    assert "unsupported_stale_evidence_cap" not in serialized


def test_compact_report_output_omits_evaluations_and_limits_failure_rows() -> None:
    compact = _compact_report(
        {
            "schema_version": "memory_comparison_benchmark.v1",
            "suite": "unit",
            "source_suite": "unit",
            "status": "failed",
            "ok": False,
            "benchmark": "locomo",
            "benchmark_scope": "fast",
            "evaluation_mode": "offline",
            "run_id": "contract-smoke",
            "metadata": {"report_mode": "full"},
            "metrics": {"accuracy": 0.0},
            "backend_metrics": {},
            "backend_comparison": {},
            "evaluations": [
                _evaluation_item(
                    case_id="case-with-heavy-evaluation",
                    backend="memo-stack",
                    retrieval_results=(
                        _retrieved_candidate(
                            item_id="heavy",
                            memory="FULL RETRIEVED MEMORY should be omitted",
                        ),
                    ),
                    bundle_items=(_selected_bundle_item("heavy"),),
                )
            ],
            "failure_analysis": [
                {"case_id": "case-1", "reason": "missing_evidence_refs"},
                {"case_id": "case-2", "reason": "missing_expected_terms"},
            ],
            "failures": [
                {"case_id": "case-1", "reason": "missing_evidence_refs"},
                {"case_id": "case-2", "reason": "missing_expected_terms"},
            ],
            "elapsed_ms": 12.5,
        },
        failure_limit=1,
    )

    assert compact["metadata"]["report_mode"] == "compact"
    assert compact["metadata"]["full_evaluation_count"] == 1
    assert compact["metadata"]["compact_failure_limit"] == 1
    assert compact["evaluations"] == []
    assert compact["failure_analysis"] == [
        {"case_id": "case-1", "reason": "missing_evidence_refs"}
    ]
    assert compact["failures"] == [
        {"case_id": "case-1", "reason": "missing_evidence_refs"}
    ]
    assert compact["diagnostics"]["backend_summaries"]["memo-stack"][
        "fast_gate_summary"
    ]["schema_version"] == "compact_fast_gate_summary.v1"
    assert "FULL RETRIEVED MEMORY" not in json.dumps(compact)


def test_compact_report_bounds_requested_ids_and_failure_payloads() -> None:
    long_text = "x" * 320
    compact = _compact_report(
        {
            "schema_version": "memory_comparison_benchmark.v1",
            "suite": "unit",
            "status": "failed",
            "ok": False,
            "run_id": "compact-boundaries",
            "requested_case_ids": [f"case-{index}" for index in range(60)],
            "requested_capabilities": [f"capability-{index}" for index in range(25)],
            "metadata": {},
            "case_selection": {
                "requested_case_ids": [f"case-{index}" for index in range(60)],
                "missing_case_ids": [f"missing-{index}" for index in range(60)],
                "requested_capabilities": [
                    f"capability-{index}" for index in range(25)
                ],
                "missing_capabilities": [f"missing-cap-{index}" for index in range(25)],
                "available_capability_counts": {
                    f"capability-{index}": 25 - index for index in range(25)
                },
            },
            "metrics": {},
            "backend_metrics": {},
            "backend_comparison": {},
            "evaluations": [],
            "failure_analysis": [
                {
                    "case_id": "case-1",
                    "reason": long_text,
                    "missing_terms": [f"term-{index}" for index in range(12)],
                    "diagnostics": {
                        "missing_expected_terms": [
                            f"{long_text}-{index}" for index in range(10)
                        ],
                        "large_mapping": {
                            f"key-{index}": index for index in range(50)
                        },
                    },
                }
            ],
            "failures": [
                {
                    "case_id": "case-1",
                    "reason": long_text,
                    "missing_evidence_terms": [
                        f"D1:{index}-{long_text}" for index in range(12)
                    ],
                }
            ],
        },
        failure_limit=1,
    )

    assert len(compact["requested_case_ids"]) == 50
    assert compact["metadata"]["requested_case_id_count"] == 60
    assert compact["metadata"]["requested_case_ids_omitted"] == 10
    assert len(compact["requested_capabilities"]) == 20
    assert compact["metadata"]["requested_capabilities_omitted"] == 5
    assert len(compact["case_selection"]["requested_case_ids"]) == 50
    assert compact["case_selection"]["requested_case_ids_omitted"] == 10
    assert len(compact["case_selection"]["missing_case_ids"]) == 50
    assert compact["case_selection"]["missing_case_ids_omitted"] == 10
    assert len(compact["case_selection"]["requested_capabilities"]) == 20
    assert compact["case_selection"]["requested_capabilities_omitted"] == 5
    assert len(compact["case_selection"]["missing_capabilities"]) == 20
    assert len(compact["case_selection"]["available_capability_counts"]) == 20
    failure = compact["failure_analysis"][0]
    assert failure["reason"] == f"{long_text[:237]}..."
    assert len(failure["missing_terms"]) == 8
    assert len(failure["diagnostics"]["missing_expected_terms"]) == 8
    assert len(failure["diagnostics"]["large_mapping"]) == 40
    assert len(compact["failures"][0]["missing_evidence_terms"]) == 8
    assert long_text not in json.dumps(compact)


def test_compact_report_omits_raw_backend_diagnostic_payloads() -> None:
    raw_memory_text = "RAW BACKEND MEMORY TEXT MUST STAY OUT"
    compact = _compact_report(
        {
            "schema_version": "memory_comparison_benchmark.v1",
            "suite": "unit",
            "status": "failed",
            "ok": False,
            "run_id": "compact-backend-metrics",
            "metadata": {},
            "metrics": {"accuracy": 0.5},
            "backend_metrics": {
                "memo-stack": {
                    "ok": False,
                    "total": 1,
                    "accuracy": 0.5,
                    "quality_diagnostics": {
                        "samples": [{"text": raw_memory_text}],
                    },
                    "fast_gate": {
                        "actionable_gap_summary": {
                            "ranked_gaps": [
                                {"samples": [{"text": raw_memory_text}]}
                            ],
                        },
                    },
                }
            },
            "backend_comparison": {"winner": "memo-stack"},
            "evaluations": [],
            "failure_analysis": [],
            "failures": [],
        },
        failure_limit=1,
    )

    assert compact["backend_metrics"] == {
        "memo-stack": {"ok": False, "total": 1, "accuracy": 0.5}
    }
    serialized = json.dumps(compact)
    assert raw_memory_text not in serialized
    assert "quality_diagnostics" not in serialized
    assert "fast_gate" not in serialized


def test_compact_report_backend_metrics_allowlist_is_summary_only_and_bounded() -> None:
    long_text = "x" * 320
    allowed_metrics = {
        "ok": False,
        "total": 3,
        "unscored": 1,
        "passed": 1,
        "failed": 2,
        "accuracy": 0.333333,
        "avg_score": 0.4,
        "avg_retrieved_count": 7.0,
        "avg_search_latency_ms": 12.0,
        "avg_ingest_latency_ms": 10.0,
        "avg_generation_latency_ms": 20.0,
        "avg_judge_latency_ms": 5.0,
        "avg_context_tokens": 128.0,
        "expected_term_recall": 0.5,
        "evidence_term_recall": 0.25,
        "evidence_term_recall_evaluation_count": 2,
        "token_usage": {"prompt_tokens": 100, "completion_tokens": 20},
        "token_cost": {"usd": 0.01},
        "by_category": {
            f"category-{index}-{long_text}": index for index in range(45)
        },
        "by_group": {"multi-hop": {"accuracy": 0.5}},
        "by_cutoff": {"2024-01-01": {"accuracy": 0.5}},
    }
    compact = _compact_report(
        {
            "schema_version": "memory_comparison_benchmark.v1",
            "suite": "unit",
            "status": "failed",
            "ok": False,
            "run_id": "compact-backend-allowlist",
            "metadata": {},
            "metrics": {},
            "backend_metrics": {
                "memo-stack": {
                    **allowed_metrics,
                    "fast_gate": {"raw": long_text},
                    "quality_diagnostics": {"raw": long_text},
                    "diagnostic_samples": [{"raw": long_text}],
                    "raw_provider_payload": long_text,
                }
            },
            "backend_comparison": {},
            "evaluations": [],
            "failure_analysis": [],
            "failures": [],
        },
        failure_limit=1,
    )

    metrics = compact["backend_metrics"]["memo-stack"]

    assert set(metrics) == {
        "ok",
        "total",
        "unscored",
        "passed",
        "failed",
        "accuracy",
        "avg_score",
        "avg_retrieved_count",
        "avg_search_latency_ms",
        "avg_ingest_latency_ms",
        "avg_generation_latency_ms",
        "avg_judge_latency_ms",
        "avg_context_tokens",
        "expected_term_recall",
        "evidence_term_recall",
        "evidence_term_recall_evaluation_count",
        "token_usage",
        "token_cost",
        "by_category",
        "by_group",
        "by_cutoff",
    }
    assert len(metrics["by_category"]) == 40
    serialized = json.dumps(compact, sort_keys=True)
    assert long_text not in serialized
    assert "fast_gate" not in serialized
    assert "quality_diagnostics" not in serialized
    assert "diagnostic_samples" not in serialized
    assert "raw_provider_payload" not in serialized


def _evaluation_item(
    *,
    case_id: str,
    backend: str = "memo-stack",
    retrieval_results: tuple[dict[str, object], ...],
    bundle_items: tuple[dict[str, object], ...],
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "backend": backend,
        "group": "multi-hop",
        "scored": True,
        "judgment": {"score": 1.0},
        "retrieval_quality": {
            "expected_term_recall": 1.0,
            "evidence_term_recall": 1.0,
        },
        "retrieval": {
            "metadata": {},
            "results": list(retrieval_results),
        },
        "evidence_bundle": {
            "bundle_complete": True,
            "evidence_term_count": 1,
            "covered_evidence_terms": ["D1:1"],
            "item_count": len(bundle_items),
            "primary_evidence_count": 1,
            "supporting_evidence_count": max(0, len(bundle_items) - 1),
            "query_support_term_recall": 1.0,
            "items": list(bundle_items),
        },
    }


def _retrieved_candidate(
    *,
    item_id: str,
    rank: int = 1,
    score: float = 0.8,
    memory: str = "",
    raw_provider_payload: str = "",
    score_signals: dict[str, object] | None = None,
    policy_score: float = 0.0,
    candidate_features: dict[str, object] | None = None,
    source_refs: tuple[str, ...] = (),
) -> dict[str, object]:
    diagnostics = {
        "benchmark_rerank_boosted": bool(policy_score),
        "score_signals": score_signals or {},
        "benchmark_candidate_features": candidate_features or {},
        "benchmark_rerank_policy": {
            "contributions": [
                {
                    "policy": "FocusedTurnPolicy",
                    "score": policy_score,
                    "reason_codes": ["focused_turn"] if policy_score else [],
                }
            ]
        },
    }
    if raw_provider_payload:
        diagnostics["raw_provider_payload"] = raw_provider_payload
    return {
        "id": item_id,
        "rank": rank,
        "score": score,
        "memory": memory,
        "source_refs": list(source_refs),
        "metadata": {"diagnostics": diagnostics},
    }


def _selected_bundle_item(
    item_id: str,
    *,
    query_roles: tuple[str, ...] = ("primary",),
) -> dict[str, object]:
    return {
        "id": item_id,
        "role": "primary",
        "retrieval_order": 1,
        "covered_evidence_terms": ["D1:1"],
        "focused_evidence_score": 1.0,
        "source_refs": ["D1:1"],
        "answerability_score": 0.8,
        "source_locality_score": 0.8,
        "query_roles": list(query_roles),
    }
