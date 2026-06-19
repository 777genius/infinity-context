"""Memory quality scorecard evaluation helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from infinity_context_core.agent_behavior_contract import (
    AGENT_BEHAVIOR_TOP_EVIDENCE_CASE_COUNT_FLOORS,
    AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS,
    AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_INTEGRITY_CHECKS,
    AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_SET,
    AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_TAG_METRICS,
)

from infinity_context_server.eval_constants import (
    _AGENT_BEHAVIOR_ACCEPTED_SCENARIO_SETS,
    _AGENT_BEHAVIOR_RATE_FLOORS,
    _AGENT_BEHAVIOR_ZERO_COUNT_METRICS,
    _AGENT_LIVE_SMOKE_REQUIRED_AGENT_CLI_CHECKS,
    _AGENT_LIVE_SMOKE_REQUIRED_GENERATED_MCP_CHECKS,
    _AGENT_LIVE_SMOKE_SUITE_ALIASES,
    _FULL_PROVIDER_CANARY_SUITE_ALIASES,
    _FULL_PROVIDER_REQUIRED_ADAPTERS,
    _FULL_PROVIDER_REQUIRED_CHECK_KEYS,
    _MEMORY_QUALITY_SCORECARD_MIN_CASE_COUNTS,
    _MEMORY_QUALITY_SCORECARD_MIN_EXTRACTION_CASES,
    _MEMORY_QUALITY_SCORECARD_MIN_SCORE_10,
    _MEMORY_QUALITY_SCORECARD_MIN_SEMANTIC_EXTRACTION_CASES,
    _MEMORY_QUALITY_SCORECARD_REQUIRED_SUITES,
    _PUBLIC_MEMORY_BENCHMARK_COMPETITIVE_FLOORS,
    _PUBLIC_MEMORY_BENCHMARK_DATASET_SOURCE_KINDS,
    _PUBLIC_MEMORY_BENCHMARK_NAME_ALIASES,
    _PUBLIC_MEMORY_BENCHMARK_OFFICIAL_SOURCE_KINDS,
    _PUBLIC_MEMORY_BENCHMARK_REQUIRED,
    _PUBLIC_MEMORY_BENCHMARK_SUITE_ALIASES,
    _QUALITY_GOLDEN_PRECISION_GATE,
    _QUALITY_GOLDEN_RECALL_GATE,
    _SMALL_GOLDEN_PRECISION_GATE,
    _SMALL_GOLDEN_RECALL_GATE,
    AGENT_BEHAVIOR_BENCH_SUITE,
    AGENT_LIVE_SMOKE_SUITE,
    AUTO_MEMORY_GOLDEN_SUITE,
    FULL_PROVIDER_CANARY_SUITE,
    GRAPH_NATIVE_GOLDEN_SUITE,
    LONG_MEMORY_GOLDEN_SUITE,
    MEMORY_QUALITY_SCORECARD_SUITE,
    MULTIMODAL_OFFLINE_GOLDEN_SUITE,
    PROMPT_CONTRACT_SUITE,
    PUBLIC_MEMORY_BENCHMARK_SUITE,
    QUALITY_GOLDEN_REQUIRED_CASE_IDS,
    QUALITY_GOLDEN_SUITE,
    SEMANTIC_LINKING_GOLDEN_SUITE,
    SEMANTIC_LINKING_REQUIRED_CASE_IDS,
    SMALL_GOLDEN_SUITE,
)
from infinity_context_server.top_evidence_policy import (
    TOP_EVIDENCE_PROVENANCE_CHECKS,
    TOP_EVIDENCE_SAFETY_CHECKS,
    top_evidence_provenance_summary,
    top_evidence_safety_summary,
)

_SEMANTIC_LINKING_REQUIRED_CHECKS = (
    "top_fact_beats_distractor",
    "event_call_beats_recent_chat",
    "temporal_intent_links_recent_fact_without_text_match",
    "document_chunk_evidence_suggested",
    "person_project_and_org_anchors_suggested",
    "anchor_evidence_confidence_and_observed_at_exposed",
    "same_name_person_project_anchors_separate",
    "high_impact_relation_requires_explicit_signal",
    "evidence_relation_requires_source_signal",
    "mentions_relation_requires_entity_signal",
    "top_suggestion_approves_to_link",
    "unrelated_capture_has_no_candidates",
    "cross_scope_fact_not_suggested",
)


def _ratio(passed: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(passed / total, 4)


def memory_quality_scorecard_policy_snapshot(
    *,
    require_top_evidence: bool,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "suite": MEMORY_QUALITY_SCORECARD_SUITE,
        "require_top_evidence": require_top_evidence,
        "minimum_maturity_score_10": _MEMORY_QUALITY_SCORECARD_MIN_SCORE_10,
        "required_suites": list(_MEMORY_QUALITY_SCORECARD_REQUIRED_SUITES),
        "min_case_counts": dict(_MEMORY_QUALITY_SCORECARD_MIN_CASE_COUNTS),
        "auto_memory": {
            "min_extraction_cases": _MEMORY_QUALITY_SCORECARD_MIN_EXTRACTION_CASES,
            "min_semantic_extraction_cases": (
                _MEMORY_QUALITY_SCORECARD_MIN_SEMANTIC_EXTRACTION_CASES
            ),
        },
        "multimodal_offline": {
            "required_checks": [
                "vision_linking_accuracy",
                "metadata_only_visual_linking_accuracy",
                "audio_linking_accuracy",
                "video_linking_accuracy",
                "temporal_audio_linking_accuracy",
                "similar_wrong_project_precision",
                "empty_audio_no_candidate_rate",
                "prompt_injection_guard_rate",
                "evidence_metadata_exposed",
            ],
            "requires_no_false_positives": True,
            "requires_prompt_injection_guard": True,
            "requires_evidence_metadata": True,
        },
        "full_provider": {
            "required_adapters": list(_FULL_PROVIDER_REQUIRED_ADAPTERS),
            "required_checks": list(_FULL_PROVIDER_REQUIRED_CHECK_KEYS),
            "requires_mcp_lifecycle": True,
            "top_evidence_requires_provenance": True,
            "top_evidence_required_provenance_checks": list(TOP_EVIDENCE_PROVENANCE_CHECKS),
            "top_evidence_requires_safety_scan": True,
            "top_evidence_required_safety_checks": list(TOP_EVIDENCE_SAFETY_CHECKS),
        },
        "agent_behavior": {
            "accepted_scenario_sets": list(_AGENT_BEHAVIOR_ACCEPTED_SCENARIO_SETS),
            "top_evidence_required_scenario_set": (AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_SET),
            "top_evidence_required_case_count_floors": dict(
                AGENT_BEHAVIOR_TOP_EVIDENCE_CASE_COUNT_FLOORS
            ),
            "top_evidence_required_scenario_tag_metrics": dict(
                AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_TAG_METRICS
            ),
            "top_evidence_required_scenario_integrity_checks": list(
                AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_INTEGRITY_CHECKS
            ),
            "top_evidence_required_canonical_scenario_count": len(
                AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS
            ),
            "rate_floors": dict(_AGENT_BEHAVIOR_RATE_FLOORS),
            "zero_count_metrics": list(_AGENT_BEHAVIOR_ZERO_COUNT_METRICS),
            "top_evidence_requires_provenance": True,
            "top_evidence_required_provenance_checks": list(TOP_EVIDENCE_PROVENANCE_CHECKS),
            "top_evidence_requires_safety_scan": True,
            "top_evidence_required_safety_checks": list(TOP_EVIDENCE_SAFETY_CHECKS),
        },
        "agent_live_smoke": {
            "suite_aliases": list(_AGENT_LIVE_SMOKE_SUITE_ALIASES),
            "required_generated_mcp_checks": list(_AGENT_LIVE_SMOKE_REQUIRED_GENERATED_MCP_CHECKS),
            "required_agent_cli_checks": list(_AGENT_LIVE_SMOKE_REQUIRED_AGENT_CLI_CHECKS),
            "requires_strict_agent_cli": True,
            "top_evidence_requires_provenance": True,
            "top_evidence_required_provenance_checks": list(TOP_EVIDENCE_PROVENANCE_CHECKS),
            "top_evidence_requires_safety_scan": True,
            "top_evidence_required_safety_checks": list(TOP_EVIDENCE_SAFETY_CHECKS),
        },
        "public_benchmark": {
            "required_benchmarks": list(_PUBLIC_MEMORY_BENCHMARK_REQUIRED),
            "competitive_floors": {
                name: dict(floor)
                for name, floor in _PUBLIC_MEMORY_BENCHMARK_COMPETITIVE_FLOORS.items()
            },
            "top_evidence_requires_provenance": True,
            "top_evidence_required_provenance_checks": list(TOP_EVIDENCE_PROVENANCE_CHECKS),
            "top_evidence_requires_safety_scan": True,
            "top_evidence_required_safety_checks": list(TOP_EVIDENCE_SAFETY_CHECKS),
            "top_evidence_requires_dataset_fingerprint": True,
            "top_evidence_requires_dataset_source_metadata": True,
            "top_evidence_requires_dataset_source_hash_match": True,
            "top_evidence_requires_dataset_path_label": True,
            "top_evidence_requires_dataset_source_case_count": True,
            "top_evidence_rejects_raw_dataset_paths": True,
            "top_evidence_requires_official_url_for_official_sources": True,
            "top_evidence_allowed_dataset_source_kinds": list(
                _PUBLIC_MEMORY_BENCHMARK_DATASET_SOURCE_KINDS
            ),
        },
    }


def _load_scorecard_suite_reports(paths: Sequence[Path]) -> dict[str, dict[str, object]]:
    reports: dict[str, dict[str, object]] = {}
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ValueError(f"Unable to read scorecard suite report: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid scorecard suite report JSON: {path}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Scorecard suite report must be a JSON object: {path}")
        suite = payload.get("suite")
        if not isinstance(suite, str) or not suite:
            raise ValueError(f"Scorecard suite report is missing suite name: {path}")
        if suite in reports:
            raise ValueError(f"Duplicate scorecard suite report for suite: {suite}")
        reports[suite] = payload
    return reports


def build_memory_quality_scorecard(
    suite_results: Mapping[str, dict[str, object]],
    *,
    require_top_evidence: bool = False,
) -> dict[str, object]:
    required_suites = _MEMORY_QUALITY_SCORECARD_REQUIRED_SUITES
    missing_suites = tuple(suite for suite in required_suites if suite not in suite_results)
    suites = {
        suite: _scorecard_suite_summary(suite_results.get(suite)) for suite in required_suites
    }
    capabilities = {
        "coverage_floors": _scorecard_coverage_floors(suite_results, suites),
        "canonical_recall_precision": _scorecard_canonical_recall_precision(suite_results),
        "longitudinal_memory": _scorecard_longitudinal_memory(suite_results),
        "auto_memory_admission": _scorecard_auto_memory_admission(suite_results),
        "semantic_linking": _scorecard_semantic_linking(suite_results),
        "multimodal_evidence_retrieval": _scorecard_multimodal_evidence_retrieval(
            suite_results
        ),
        "graph_native_recall": _scorecard_graph_native_recall(suite_results),
        "scope_and_safety": _scorecard_scope_and_safety(suite_results),
        "prompt_context_contract": _scorecard_prompt_context_contract(suite_results),
    }
    external_evidence = _scorecard_external_evidence(
        suite_results,
        require_top_evidence=require_top_evidence,
    )
    all_suite_checks_ok = all(summary["ok"] is True for summary in suites.values())
    all_capabilities_ok = all(capability["ok"] is True for capability in capabilities.values())
    check_values = (
        *(summary["ok"] is True for summary in suites.values()),
        *(capability["ok"] is True for capability in capabilities.values()),
    )
    passed_checks = sum(1 for value in check_values if value)
    total_checks = len(check_values)
    score_percent = _ratio(passed_checks, total_checks)
    maturity_score_10 = round(score_percent * 10, 2)
    gates = {
        "required_suites_present": not missing_suites,
        "all_suites_ok": all_suite_checks_ok,
        "all_capabilities_ok": all_capabilities_ok,
        "maturity_score_min": maturity_score_10 >= _MEMORY_QUALITY_SCORECARD_MIN_SCORE_10,
    }
    if require_top_evidence:
        gates["top_library_external_evidence"] = (
            external_evidence["top_library_comparison_ready"] is True
        )
    failures = _scorecard_failures(
        missing_suites=missing_suites,
        suites=suites,
        capabilities=capabilities,
        gates=gates,
    )
    ok = all(gates.values())
    return {
        "suite": MEMORY_QUALITY_SCORECARD_SUITE,
        "status": "ok" if ok else "failed",
        "ok": ok,
        "benchmark_scope": (
            "internal deterministic public-API suites; not a LOCOMO or LongMemEval substitute"
        ),
        "score": {
            "passed_checks": passed_checks,
            "total_checks": total_checks,
            "score_percent": score_percent,
            "maturity_score_10": maturity_score_10,
            "minimum_maturity_score_10": _MEMORY_QUALITY_SCORECARD_MIN_SCORE_10,
        },
        "suites": suites,
        "capabilities": capabilities,
        "external_evidence": external_evidence,
        "gates": gates,
        "metrics": _scorecard_metrics(suite_results),
        "failures": failures,
    }


def _scorecard_suite_summary(result: dict[str, object] | None) -> dict[str, object]:
    if result is None:
        return {
            "ok": False,
            "status": "missing",
            "case_count": 0,
            "failure_count": 1,
        }
    metrics = _scorecard_result_metrics(result)
    cases = result.get("cases")
    failures = result.get("failures", ())
    if isinstance(cases, list | tuple):
        case_count = len(cases)
    else:
        case_count = metrics.get("case_count")
        if not isinstance(case_count, int):
            case_count = 0
    return {
        "ok": bool(result.get("ok")),
        "status": result.get("status", "ok" if result.get("ok") else "failed"),
        "case_count": case_count,
        "failure_count": len(failures) if isinstance(failures, list | tuple) else 0,
    }


def _scorecard_coverage_floors(
    suite_results: Mapping[str, dict[str, object]],
    suites: Mapping[str, dict[str, object]],
) -> dict[str, object]:
    quality_result = suite_results.get(QUALITY_GOLDEN_SUITE)
    semantic_result = suite_results.get(SEMANTIC_LINKING_GOLDEN_SUITE)
    quality_metrics = _scorecard_result_metrics(suite_results.get(QUALITY_GOLDEN_SUITE))
    semantic_metrics = _scorecard_result_metrics(suite_results.get(SEMANTIC_LINKING_GOLDEN_SUITE))
    auto_metrics = _scorecard_result_metrics(suite_results.get(AUTO_MEMORY_GOLDEN_SUITE))
    checks = {
        f"{suite}_case_count": int(suites[suite].get("case_count", 0)) >= minimum
        for suite, minimum in _MEMORY_QUALITY_SCORECARD_MIN_CASE_COUNTS.items()
    }
    checks["quality_required_case_coverage_rate"] = (
        quality_metrics.get("required_case_coverage_rate") == 1.0
    )
    checks["quality_missing_required_case_count"] = (
        quality_metrics.get("missing_required_case_count") == 0
    )
    checks["semantic_linking_required_case_coverage_rate"] = (
        semantic_metrics.get("required_case_coverage_rate") == 1.0
    )
    checks["semantic_linking_missing_required_case_count"] = (
        semantic_metrics.get("missing_required_case_count") == 0
    )
    checks.update(
        _scorecard_required_case_checks(
            quality_result,
            prefix="quality",
            required_case_ids=QUALITY_GOLDEN_REQUIRED_CASE_IDS,
        )
    )
    checks.update(
        _scorecard_required_case_checks(
            semantic_result,
            prefix="semantic_linking",
            required_case_ids=SEMANTIC_LINKING_REQUIRED_CASE_IDS,
        )
    )
    checks["auto_memory_extraction_case_count"] = (
        int(auto_metrics.get("extraction_case_count", 0))
        >= _MEMORY_QUALITY_SCORECARD_MIN_EXTRACTION_CASES
    )
    checks["auto_memory_semantic_extraction_case_count"] = (
        int(auto_metrics.get("extraction_semantic_case_count", 0))
        >= _MEMORY_QUALITY_SCORECARD_MIN_SEMANTIC_EXTRACTION_CASES
    )
    return _scorecard_capability("coverage_floors", checks)


def _scorecard_required_case_checks(
    result: Mapping[str, object] | None,
    *,
    prefix: str,
    required_case_ids: Sequence[str],
) -> dict[str, bool]:
    case_ids = set(_scorecard_case_ids(result))
    return {
        f"{prefix}_required_case_{case_id}": case_id in case_ids
        for case_id in required_case_ids
    }


def _scorecard_case_ids(result: Mapping[str, object] | None) -> tuple[str, ...]:
    if result is None:
        return ()
    raw_cases = result.get("cases")
    if not isinstance(raw_cases, list | tuple):
        return ()
    case_ids: list[str] = []
    for raw_case in raw_cases:
        case_id = raw_case.get("case_id") if isinstance(raw_case, Mapping) else raw_case
        if isinstance(case_id, str) and case_id:
            case_ids.append(case_id)
    return tuple(case_ids)


def _scorecard_canonical_recall_precision(
    suite_results: Mapping[str, dict[str, object]],
) -> dict[str, object]:
    small = _scorecard_result_metrics(suite_results.get(SMALL_GOLDEN_SUITE))
    quality = _scorecard_result_metrics(suite_results.get(QUALITY_GOLDEN_SUITE))
    checks = {
        "small_recall_at_5": float(small.get("recall_at_5", 0.0)) >= _SMALL_GOLDEN_RECALL_GATE,
        "small_precision_at_5": (
            float(small.get("precision_at_5", 0.0)) >= _SMALL_GOLDEN_PRECISION_GATE
        ),
        "quality_recall_at_5": (
            float(quality.get("recall_at_5", 0.0)) >= _QUALITY_GOLDEN_RECALL_GATE
        ),
        "quality_precision_at_5": (
            float(quality.get("precision_at_5", 0.0)) >= _QUALITY_GOLDEN_PRECISION_GATE
        ),
        "answer_support_rate": quality.get("answer_support_rate") == 1.0,
        "document_recall_at_5": float(quality.get("document_recall_at_5", 0.0)) >= 0.95,
        "retrieval_trace_support_rate": (
            quality.get("retrieval_trace_support_rate") == 1.0
        ),
        "item_contract_support_rate": quality.get("item_contract_support_rate") == 1.0,
        "item_contract_failure_count": quality.get("item_contract_failure_count") == 0,
    }
    return _scorecard_capability("canonical_recall_precision", checks)


def _scorecard_longitudinal_memory(
    suite_results: Mapping[str, dict[str, object]],
) -> dict[str, object]:
    metrics = _scorecard_result_metrics(suite_results.get(LONG_MEMORY_GOLDEN_SUITE))
    checks = {
        "multi_session_recall_at_5": metrics.get("multi_session_recall_at_5") == 1.0,
        "temporal_update_accuracy": metrics.get("temporal_update_accuracy") == 1.0,
        "preference_synthesis_recall": metrics.get("preference_synthesis_recall") == 1.0,
        "long_document_recall_at_5": float(metrics.get("long_document_recall_at_5", 0.0)) >= 0.95,
        "long_safety_leak_count": metrics.get("long_safety_leak_count") == 0,
        "stale_memory_rate": metrics.get("stale_memory_rate") == 0.0,
    }
    return _scorecard_capability("longitudinal_memory", checks)


def _scorecard_auto_memory_admission(
    suite_results: Mapping[str, dict[str, object]],
) -> dict[str, object]:
    metrics = _scorecard_result_metrics(suite_results.get(AUTO_MEMORY_GOLDEN_SUITE))
    checks = {
        "extraction_positive_recall_rate": (metrics.get("extraction_positive_recall_rate") == 1.0),
        "extraction_operation_accuracy": metrics.get("extraction_operation_accuracy") == 1.0,
        "extraction_kind_accuracy": metrics.get("extraction_kind_accuracy") == 1.0,
        "extraction_admission_accuracy": metrics.get("extraction_admission_accuracy") == 1.0,
        "extraction_ttl_accuracy": metrics.get("extraction_ttl_accuracy") == 1.0,
        "extraction_target_hint_accuracy": metrics.get("extraction_target_hint_accuracy") == 1.0,
        "extraction_false_positive_count": metrics.get("extraction_false_positive_count") == 0,
        "extraction_false_negative_count": metrics.get("extraction_false_negative_count") == 0,
        "wrong_auto_apply_count": metrics.get("wrong_auto_apply_count") == 0,
        "active_fact_before_review_count": metrics.get("active_fact_before_review_count") == 0,
        "secret_leakage_count": metrics.get("secret_leakage_count") == 0,
        "assistant_low_trust_violation_count": (
            metrics.get("assistant_low_trust_violation_count") == 0
        ),
        "target_resolution_violation_count": (
            metrics.get("target_resolution_violation_count") == 0
        ),
        "review_operation_violation_count": (metrics.get("review_operation_violation_count") == 0),
    }
    return _scorecard_capability("auto_memory_admission", checks)


def _scorecard_graph_native_recall(
    suite_results: Mapping[str, dict[str, object]],
) -> dict[str, object]:
    metrics = _scorecard_result_metrics(suite_results.get(GRAPH_NATIVE_GOLDEN_SUITE))
    checks = {
        "graph_recall_rate": metrics.get("graph_recall_rate") == 1.0,
        "graph_hydration_rate": metrics.get("graph_hydration_rate") == 1.0,
        "graph_status_ok_rate": metrics.get("graph_status_ok_rate") == 1.0,
        "graph_safety_leak_count": metrics.get("graph_safety_leak_count") == 0,
        "graph_stale_drop_count": int(metrics.get("graph_stale_drop_count", 0)) >= 4,
        "canonical_only_graph_skip_count": (metrics.get("canonical_only_graph_skip_count") == 1),
    }
    return _scorecard_capability("graph_native_recall", checks)


def _scorecard_semantic_linking(
    suite_results: Mapping[str, dict[str, object]],
) -> dict[str, object]:
    result = suite_results.get(SEMANTIC_LINKING_GOLDEN_SUITE)
    metrics = _scorecard_result_metrics(result)
    checks_raw = result.get("checks", {}) if isinstance(result, dict) else {}
    checks_map = checks_raw if isinstance(checks_raw, Mapping) else {}
    checks = {
        "ranking_accuracy": metrics.get("ranking_accuracy") == 1.0,
        "event_linking_accuracy": metrics.get("event_linking_accuracy") == 1.0,
        "temporal_intent_recall": metrics.get("temporal_intent_recall") == 1.0,
        "document_chunk_linking_accuracy": (metrics.get("document_chunk_linking_accuracy") == 1.0),
        "anchor_recall_rate": metrics.get("anchor_recall_rate") == 1.0,
        "anchor_disambiguation_rate": metrics.get("anchor_disambiguation_rate") == 1.0,
        "anchor_review_evidence_rate": metrics.get("anchor_review_evidence_rate") == 1.0,
        "high_impact_relation_policy_safety": (
            metrics.get("high_impact_relation_policy_safety") == 1.0
        ),
        "evidence_relation_policy_safety": (
            metrics.get("evidence_relation_policy_safety") == 1.0
        ),
        "mentions_relation_policy_safety": (
            metrics.get("mentions_relation_policy_safety") == 1.0
        ),
        "review_approval_rate": metrics.get("review_approval_rate") == 1.0,
        "false_positive_count": metrics.get("false_positive_count") == 0,
        "cross_scope_leak_count": metrics.get("cross_scope_leak_count") == 0,
        **{
            f"semantic_check_{check_name}": checks_map.get(check_name) is True
            for check_name in _SEMANTIC_LINKING_REQUIRED_CHECKS
        },
    }
    return _scorecard_capability("semantic_linking", checks)


def _scorecard_multimodal_evidence_retrieval(
    suite_results: Mapping[str, dict[str, object]],
) -> dict[str, object]:
    result = suite_results.get(MULTIMODAL_OFFLINE_GOLDEN_SUITE)
    metrics = _scorecard_result_metrics(result)
    gates_raw = result.get("gates", {}) if isinstance(result, dict) else {}
    gates = gates_raw if isinstance(gates_raw, Mapping) else {}
    checks_raw = result.get("checks", {}) if isinstance(result, dict) else {}
    check_map = checks_raw if isinstance(checks_raw, Mapping) else {}
    checks = {
        "pass_rate": metrics.get("pass_rate") == 1.0,
        "case_count": int(metrics.get("case_count", 0)) >= 10,
        "false_positive_count": metrics.get("false_positive_count") == 0,
        "vision_linking_accuracy": metrics.get("vision_linking_accuracy") == 1.0,
        "metadata_only_visual_linking_accuracy": (
            metrics.get("metadata_only_visual_linking_accuracy") == 1.0
        ),
        "audio_linking_accuracy": metrics.get("audio_linking_accuracy") == 1.0,
        "video_linking_accuracy": metrics.get("video_linking_accuracy") == 1.0,
        "temporal_audio_linking_accuracy": (
            metrics.get("temporal_audio_linking_accuracy") == 1.0
        ),
        "similar_wrong_project_precision": (
            metrics.get("similar_wrong_project_precision") == 1.0
        ),
        "empty_audio_no_candidate_rate": (
            metrics.get("empty_audio_no_candidate_rate") == 1.0
        ),
        "prompt_injection_guard_rate": (
            metrics.get("prompt_injection_guard_rate") == 1.0
        ),
        "gate_case_count": gates.get("case_count") is True,
        "gate_all_cases_passed": gates.get("all_cases_passed") is True,
        "gate_evidence_metadata_exposed": (
            gates.get("evidence_metadata_exposed") is True
        ),
        "check_prompt_injection_guard": (
            check_map.get("prompt_injection_guard") is True
        ),
        "check_evidence_metadata_exposed": (
            check_map.get("evidence_metadata_exposed") is True
        ),
    }
    return _scorecard_capability("multimodal_evidence_retrieval", checks)


def _scorecard_scope_and_safety(
    suite_results: Mapping[str, dict[str, object]],
) -> dict[str, object]:
    small = _scorecard_result_metrics(suite_results.get(SMALL_GOLDEN_SUITE))
    quality = _scorecard_result_metrics(suite_results.get(QUALITY_GOLDEN_SUITE))
    long = _scorecard_result_metrics(suite_results.get(LONG_MEMORY_GOLDEN_SUITE))
    auto = _scorecard_result_metrics(suite_results.get(AUTO_MEMORY_GOLDEN_SUITE))
    graph = _scorecard_result_metrics(suite_results.get(GRAPH_NATIVE_GOLDEN_SUITE))
    checks = {
        "deleted_memory_leak_count": (
            int(small.get("deleted_memory_leak_count", 0))
            + int(quality.get("deleted_memory_leak_count", 0))
            + int(long.get("deleted_memory_leak_count", 0))
        )
        == 0,
        "cross_scope_leak_count": (
            int(small.get("cross_memory_scope_leak_count", 0))
            + int(quality.get("cross_memory_scope_leak_count", 0))
            + int(quality.get("cross_thread_leak_count", 0))
            + int(long.get("cross_memory_scope_leak_count", 0))
            + int(long.get("cross_thread_leak_count", 0))
            + int(graph.get("graph_safety_leak_count", 0))
        )
        == 0,
        "restricted_memory_leak_count": (
            int(quality.get("restricted_memory_leak_count", 0))
            + int(long.get("restricted_memory_leak_count", 0))
        )
        == 0,
        "prompt_injection_promoted_count": (
            int(small.get("prompt_injection_promoted_count", 0))
            + int(quality.get("prompt_injection_promoted_count", 0))
            + int(long.get("prompt_injection_promoted_count", 0))
            + int(auto.get("prompt_injection_promoted_count", 0))
        )
        == 0,
        "secret_leakage_count": int(auto.get("secret_leakage_count", 0)) == 0,
        "harmful_context_rate": (
            float(quality.get("harmful_context_rate", 0.0))
            + float(long.get("harmful_context_rate", 0.0))
        )
        == 0.0,
        "context_token_overflow_count": (
            int(small.get("context_token_overflow_count", 0))
            + int(quality.get("context_token_overflow_count", 0))
            + int(long.get("context_token_overflow_count", 0))
        )
        == 0,
    }
    return _scorecard_capability("scope_and_safety", checks)


def _scorecard_prompt_context_contract(
    suite_results: Mapping[str, dict[str, object]],
) -> dict[str, object]:
    result = suite_results.get(PROMPT_CONTRACT_SUITE, {})
    checks_raw = result.get("checks", {})
    checks_map = checks_raw if isinstance(checks_raw, dict) else {}
    checks = {
        "snapshot_safe": checks_map.get("snapshot_safe") is True,
        "snapshot_exists": checks_map.get("snapshot_exists") is True,
        "matches_snapshot": checks_map.get("matches_snapshot") is True,
    }
    return _scorecard_capability("prompt_context_contract", checks)


def _scorecard_external_evidence(
    suite_results: Mapping[str, dict[str, object]],
    *,
    require_top_evidence: bool = False,
) -> dict[str, object]:
    full_provider = _scorecard_find_full_provider_report(suite_results)
    agent_behavior = _scorecard_find_agent_behavior_report(suite_results, full_provider)
    agent_live_smoke = _scorecard_find_agent_live_smoke_report(suite_results)
    full_provider_summary = _scorecard_full_provider_evidence_summary(
        full_provider,
        require_top_evidence=require_top_evidence,
    )
    agent_behavior_summary = _scorecard_agent_behavior_evidence_summary(
        agent_behavior,
        require_top_evidence=require_top_evidence,
    )
    agent_live_smoke_summary = _scorecard_agent_live_smoke_evidence_summary(
        agent_live_smoke,
        require_top_evidence=require_top_evidence,
    )
    public_benchmark_summary = _scorecard_public_benchmark_evidence_summary(
        suite_results,
        full_provider=full_provider,
        require_top_evidence=require_top_evidence,
    )
    full_provider_ok = full_provider_summary["ok"] is True
    agent_behavior_ok = agent_behavior_summary["ok"] is True
    agent_live_smoke_ok = agent_live_smoke_summary["ok"] is True
    public_benchmark_ok = public_benchmark_summary["ok"] is True
    confidence_tier = _scorecard_confidence_tier(
        full_provider_ok=full_provider_ok,
        agent_behavior_ok=agent_behavior_ok,
        agent_live_smoke_ok=agent_live_smoke_ok,
        public_benchmark_ok=public_benchmark_ok,
    )

    evidence_gaps = []
    if not full_provider_summary["present"]:
        evidence_gaps.append("full_provider_canary_missing")
    elif not full_provider_ok:
        evidence_gaps.append("full_provider_canary_failed")
        if full_provider_summary.get("provenance_ok") is False:
            evidence_gaps.append("full_provider_canary_provenance_failed")
        if full_provider_summary.get("safety_ok") is False:
            evidence_gaps.append("full_provider_canary_safety_failed")
    if not agent_behavior_summary["present"]:
        evidence_gaps.append("agent_behavior_benchmark_missing")
    elif not agent_behavior_ok:
        evidence_gaps.append("agent_behavior_benchmark_failed")
        if agent_behavior_summary.get("provenance_ok") is False:
            evidence_gaps.append("agent_behavior_benchmark_provenance_failed")
        if agent_behavior_summary.get("safety_ok") is False:
            evidence_gaps.append("agent_behavior_benchmark_safety_failed")
        if agent_behavior_summary.get("quality_floor_ok") is False:
            evidence_gaps.append("agent_behavior_quality_floor_failed")
    if not agent_live_smoke_summary["present"]:
        evidence_gaps.append("agent_live_smoke_missing")
    elif not agent_live_smoke_ok:
        evidence_gaps.append("agent_live_smoke_failed")
        if agent_live_smoke_summary.get("provenance_ok") is False:
            evidence_gaps.append("agent_live_smoke_provenance_failed")
        if agent_live_smoke_summary.get("safety_ok") is False:
            evidence_gaps.append("agent_live_smoke_safety_failed")
        if agent_live_smoke_summary.get("quality_floor_ok") is False:
            evidence_gaps.append("agent_live_smoke_quality_floor_failed")
    if not public_benchmark_summary["present"]:
        evidence_gaps.append("public_benchmark_evidence_missing")
    elif not public_benchmark_ok:
        evidence_gaps.append("public_benchmark_evidence_failed")
        if public_benchmark_summary.get("provenance_ok") is False:
            evidence_gaps.append("public_benchmark_provenance_failed")
        if public_benchmark_summary.get("safety_ok") is False:
            evidence_gaps.append("public_benchmark_safety_failed")
        if public_benchmark_summary.get("dataset_evidence_ok") is False:
            evidence_gaps.append("public_benchmark_dataset_evidence_failed")
        if public_benchmark_summary.get("competitive_floor_ok") is False:
            evidence_gaps.append("public_benchmark_competitive_floor_failed")

    return {
        "confidence_tier": confidence_tier,
        "required_for_gate": require_top_evidence,
        "top_library_comparison_ready": full_provider_ok
        and agent_behavior_ok
        and agent_live_smoke_ok
        and public_benchmark_ok,
        "benchmark_note": (
            "Internal deterministic suites are the local quality gate. "
            "Full-provider, real-agent and public benchmark reports are "
            "optional evidence for production/top-library comparison claims."
        ),
        "evidence_gaps": evidence_gaps,
        "full_provider_canary": full_provider_summary,
        "agent_behavior_benchmark": agent_behavior_summary,
        "agent_live_smoke": agent_live_smoke_summary,
        "public_benchmark": public_benchmark_summary,
    }


def _scorecard_find_full_provider_report(
    suite_results: Mapping[str, dict[str, object]],
) -> dict[str, object] | None:
    for suite in _FULL_PROVIDER_CANARY_SUITE_ALIASES:
        result = suite_results.get(suite)
        if result is not None:
            return result
    return None


def _scorecard_find_agent_behavior_report(
    suite_results: Mapping[str, dict[str, object]],
    full_provider: dict[str, object] | None,
) -> dict[str, object] | None:
    result = suite_results.get(AGENT_BEHAVIOR_BENCH_SUITE)
    if result is not None:
        return result
    if full_provider is None:
        return None
    nested = full_provider.get("agent_behavior")
    return nested if isinstance(nested, dict) else None


def _scorecard_find_agent_live_smoke_report(
    suite_results: Mapping[str, dict[str, object]],
) -> dict[str, object] | None:
    for suite in _AGENT_LIVE_SMOKE_SUITE_ALIASES:
        result = suite_results.get(suite)
        if result is not None:
            return result
    return None


def _scorecard_confidence_tier(
    *,
    full_provider_ok: bool,
    agent_behavior_ok: bool,
    agent_live_smoke_ok: bool,
    public_benchmark_ok: bool,
) -> str:
    labels = []
    if full_provider_ok:
        labels.append("full_provider")
    if agent_behavior_ok:
        labels.append("agent_behavior")
    if agent_live_smoke_ok:
        labels.append("agent_live_smoke")
    if public_benchmark_ok:
        labels.append("public_benchmark")
    if not labels:
        return "internal_deterministic"
    return "_and_".join(labels) + "_evaluated"


def _scorecard_agent_live_smoke_evidence_summary(
    result: dict[str, object] | None,
    *,
    require_top_evidence: bool = False,
) -> dict[str, object]:
    if result is None:
        return {"present": False, "ok": None}
    checks_raw = result.get("checks")
    checks_map = checks_raw if isinstance(checks_raw, Mapping) else {}
    generated_mcp = checks_map.get("generated_mcp")
    generated_mcp_map = generated_mcp if isinstance(generated_mcp, Mapping) else {}
    agent_cli = checks_map.get("agent_cli")
    agent_cli_map = agent_cli if isinstance(agent_cli, Mapping) else {}
    required_checks: dict[str, bool] = {
        "result_ok": result.get("ok") is True,
        "strict_agent_cli_enabled": result.get("strict_agent_cli") is True,
        "generated_mcp_checks_present": bool(generated_mcp_map),
        "agent_cli_checks_present": bool(agent_cli_map),
    }
    for name in _AGENT_LIVE_SMOKE_REQUIRED_GENERATED_MCP_CHECKS:
        required_checks[f"generated_mcp_{name}_ok"] = _scorecard_live_check_ok(
            generated_mcp_map.get(name),
            ok_key="ok",
            expected=True,
        )
    for name in _AGENT_LIVE_SMOKE_REQUIRED_AGENT_CLI_CHECKS:
        required_checks[f"agent_cli_{name}_ok"] = _scorecard_live_check_ok(
            agent_cli_map.get(name),
            ok_key="status",
            expected="ok",
        )
    failed_required_checks = sorted(
        check for check, ok in required_checks.items() if ok is not True
    )
    provenance = top_evidence_provenance_summary(result)
    safety = top_evidence_safety_summary(result)
    quality_ok = not failed_required_checks
    return {
        "present": True,
        "suite": result.get("suite", AGENT_LIVE_SMOKE_SUITE),
        "ok": quality_ok
        and (not require_top_evidence or (provenance["ok"] is True and safety["ok"] is True)),
        "quality_ok": quality_ok,
        "quality_floor_ok": quality_ok,
        "provenance_ok": provenance["ok"] if require_top_evidence else None,
        "provenance": provenance,
        "safety_ok": safety["ok"] if require_top_evidence else None,
        "safety": safety,
        "strict_agent_cli": result.get("strict_agent_cli"),
        "required_checks": required_checks,
        "failed_required_checks": failed_required_checks,
        "generated_mcp": _scorecard_live_check_statuses(generated_mcp_map),
        "agent_cli": _scorecard_live_check_statuses(agent_cli_map),
        "generated_mcp_failures": _scorecard_string_list(result.get("generated_mcp_failures")),
        "agent_cli_failures": _scorecard_string_list(result.get("agent_cli_failures")),
    }


def _scorecard_live_check_ok(
    value: object,
    *,
    ok_key: str,
    expected: object,
) -> bool:
    return isinstance(value, Mapping) and value.get(ok_key) == expected


def _scorecard_live_check_statuses(
    checks: Mapping[object, object],
) -> dict[str, object]:
    statuses: dict[str, object] = {}
    for name, value in checks.items():
        if not isinstance(name, str) or not isinstance(value, Mapping):
            continue
        if "status" in value:
            statuses[name] = value.get("status")
        elif "ok" in value:
            statuses[name] = value.get("ok")
    return statuses


def _scorecard_string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return []
    return [item for item in value if isinstance(item, str)]


def _scorecard_public_benchmark_evidence_summary(
    suite_results: Mapping[str, dict[str, object]],
    *,
    full_provider: dict[str, object] | None = None,
    require_top_evidence: bool = False,
) -> dict[str, object]:
    reports = _scorecard_public_benchmark_reports(suite_results)
    if full_provider is not None:
        nested = full_provider.get("public_benchmark")
        if isinstance(nested, dict):
            reports.append(nested)
    benchmarks: dict[str, dict[str, object]] = {}
    for report in reports:
        _scorecard_collect_public_benchmarks(report, benchmarks)
    missing = [name for name in _PUBLIC_MEMORY_BENCHMARK_REQUIRED if name not in benchmarks]
    ok = (
        bool(reports)
        and not missing
        and all(benchmarks[name]["ok"] is True for name in _PUBLIC_MEMORY_BENCHMARK_REQUIRED)
    )
    competitive_floor = _scorecard_public_benchmark_competitive_floor(benchmarks)
    quality_ok = ok and competitive_floor["ok"] is True
    provenance_reports = [top_evidence_provenance_summary(report) for report in reports]
    provenance_ok = bool(provenance_reports) and all(
        report["ok"] is True for report in provenance_reports
    )
    safety_reports = [top_evidence_safety_summary(report) for report in reports]
    safety_ok = bool(safety_reports) and all(report["ok"] is True for report in safety_reports)
    safety = _scorecard_combined_safety_summary(safety_reports)
    dataset_evidence = _scorecard_public_benchmark_dataset_evidence_summary(reports)
    dataset_evidence_ok = dataset_evidence["ok"] is True
    ok = quality_ok and (
        not require_top_evidence or (provenance_ok and safety_ok and dataset_evidence_ok)
    )
    return {
        "present": bool(reports),
        "ok": ok,
        "quality_ok": quality_ok,
        "provenance_ok": provenance_ok if require_top_evidence else None,
        "provenance_reports": provenance_reports,
        "safety_ok": safety_ok if require_top_evidence else None,
        "safety": safety,
        "safety_reports": safety_reports,
        "dataset_evidence_ok": dataset_evidence_ok if require_top_evidence else None,
        "dataset_evidence": dataset_evidence,
        "suite": PUBLIC_MEMORY_BENCHMARK_SUITE,
        "required_benchmarks": list(_PUBLIC_MEMORY_BENCHMARK_REQUIRED),
        "missing_benchmarks": missing,
        "competitive_floor_ok": competitive_floor["ok"],
        "competitive_floor": competitive_floor,
        "benchmark_count": len(benchmarks),
        "benchmarks": benchmarks,
    }


def _scorecard_public_benchmark_reports(
    suite_results: Mapping[str, dict[str, object]],
) -> list[dict[str, object]]:
    reports: list[dict[str, object]] = []
    for suite, result in suite_results.items():
        if suite in _PUBLIC_MEMORY_BENCHMARK_SUITE_ALIASES:
            reports.append(result)
            continue
        if _scorecard_normalize_public_benchmark_name(suite):
            reports.append(result)
    return reports


def _scorecard_combined_safety_summary(
    reports: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    failed_checks = sorted(
        {
            check
            for report in reports
            for check in report.get("failed_checks", ())
            if isinstance(check, str)
        }
    )
    checks = {
        check: bool(reports) and check not in failed_checks for check in TOP_EVIDENCE_SAFETY_CHECKS
    }
    return {
        "ok": bool(reports) and not failed_checks,
        "checks": checks,
        "failed_checks": failed_checks,
        "sensitive_path_count": sum(
            int(report.get("sensitive_path_count", 0)) for report in reports
        ),
        "sensitive_paths": [
            path
            for report in reports
            for path in report.get("sensitive_paths", ())
            if isinstance(path, str)
        ][:10],
        "local_path_count": sum(int(report.get("local_path_count", 0)) for report in reports),
        "local_paths": [
            path
            for report in reports
            for path in report.get("local_paths", ())
            if isinstance(path, str)
        ][:10],
    }


def _scorecard_public_benchmark_dataset_evidence_summary(
    reports: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    report_summaries: list[dict[str, object]] = []
    missing_reports: list[str] = []
    for index, report in enumerate(reports):
        report_label = str(report.get("suite") or f"report_{index}")
        benchmark_names = _scorecard_public_benchmark_names_in_report(report)
        report_failures = _scorecard_public_benchmark_report_failures(report)
        missing_fingerprints = [
            name
            for name in benchmark_names
            if not _scorecard_public_benchmark_has_dataset_fingerprint(report, name)
        ]
        source_failures = {
            name: _scorecard_public_benchmark_dataset_source_failures(report, name)
            for name in benchmark_names
        }
        missing_sources = [name for name, failures in source_failures.items() if failures]
        ok = (
            bool(benchmark_names)
            and not report_failures
            and not missing_fingerprints
            and not missing_sources
        )
        if not ok:
            missing_reports.append(report_label)
        report_summaries.append(
            {
                "report": report_label,
                "ok": ok,
                "benchmarks": benchmark_names,
                "report_failures": list(report_failures),
                "missing_benchmarks": sorted(set(missing_fingerprints) | set(missing_sources)),
                "missing_dataset_fingerprints": missing_fingerprints,
                "missing_dataset_sources": missing_sources,
                "dataset_source_failures": {
                    name: list(failures) for name, failures in source_failures.items() if failures
                },
                "has_dataset_hash": _scorecard_nonempty_string(report.get("dataset_hash")),
                "has_dataset_hashes": isinstance(report.get("dataset_hashes"), Mapping),
                "has_dataset_sources": isinstance(report.get("dataset_sources"), Mapping),
            }
        )
    return {
        "ok": bool(reports) and not missing_reports,
        "report_count": len(reports),
        "missing_reports": missing_reports,
        "reports": report_summaries,
    }


def _scorecard_public_benchmark_names_in_report(
    report: Mapping[str, object],
) -> list[str]:
    names: set[str] = set()
    raw_items = report.get("benchmarks")
    if isinstance(raw_items, list | tuple):
        for item in raw_items:
            if isinstance(item, Mapping):
                name = _scorecard_normalize_public_benchmark_name(
                    item.get("name") or item.get("benchmark") or item.get("suite")
                )
                if name:
                    names.add(name)
    name = _scorecard_normalize_public_benchmark_name(
        report.get("benchmark") or report.get("name") or report.get("suite")
    )
    if name:
        names.add(name)
    metrics = _scorecard_result_metrics(dict(report))
    for benchmark in _PUBLIC_MEMORY_BENCHMARK_REQUIRED:
        if f"{benchmark}_accuracy" in metrics or f"{benchmark}_case_count" in metrics:
            names.add(benchmark)
    return sorted(names)


def _scorecard_public_benchmark_report_failures(
    report: Mapping[str, object],
) -> tuple[str, ...]:
    failures: list[str] = []
    if _scorecard_nonempty_string(report.get("dataset_path")):
        failures.append("dataset_path_not_redacted")
    return tuple(failures)


def _scorecard_public_benchmark_has_dataset_fingerprint(
    report: Mapping[str, object],
    benchmark: str,
) -> bool:
    return _scorecard_public_benchmark_dataset_fingerprint(report, benchmark) is not None


def _scorecard_public_benchmark_dataset_source_failures(
    report: Mapping[str, object],
    benchmark: str,
) -> tuple[str, ...]:
    failures: list[str] = []
    dataset_sources = report.get("dataset_sources")
    if not isinstance(dataset_sources, Mapping):
        return ("dataset_sources_missing",)
    source = dataset_sources.get(benchmark)
    if not isinstance(source, Mapping):
        return ("dataset_source_missing",)
    source_kind = source.get("source_kind")
    sha256 = source.get("sha256")
    size_bytes = source.get("size_bytes")
    path_label = source.get("path_label")
    official_url = source.get("official_url")
    source_case_count = source.get("case_count")
    expected_sha256 = _scorecard_public_benchmark_dataset_fingerprint(report, benchmark)
    expected_case_count = _scorecard_public_benchmark_case_count(report, benchmark)
    if source_kind not in _PUBLIC_MEMORY_BENCHMARK_DATASET_SOURCE_KINDS:
        failures.append("source_kind_not_allowed")
    if not _scorecard_nonempty_string(sha256):
        failures.append("sha256_missing")
    elif sha256 != expected_sha256:
        failures.append("sha256_mismatch")
    if not isinstance(size_bytes, int) or size_bytes <= 0:
        failures.append("size_bytes_missing")
    if not isinstance(source_case_count, int) or source_case_count <= 0:
        failures.append("case_count_missing")
    elif source_case_count != expected_case_count:
        failures.append("case_count_mismatch")
    if not _scorecard_nonempty_string(path_label):
        failures.append("path_label_missing")
    if source_kind in _PUBLIC_MEMORY_BENCHMARK_OFFICIAL_SOURCE_KINDS and not (
        _scorecard_nonempty_string(official_url)
    ):
        failures.append("official_url_missing")
    return tuple(failures)


def _scorecard_public_benchmark_dataset_fingerprint(
    report: Mapping[str, object],
    benchmark: str,
) -> str | None:
    dataset_hash = report.get("dataset_hash")
    if _scorecard_nonempty_string(dataset_hash):
        return str(dataset_hash).strip()
    dataset_hashes = report.get("dataset_hashes")
    if isinstance(dataset_hashes, Mapping):
        benchmark_hash = dataset_hashes.get(benchmark)
        if _scorecard_nonempty_string(benchmark_hash):
            return str(benchmark_hash).strip()
    return None


def _scorecard_public_benchmark_case_count(
    report: Mapping[str, object],
    benchmark: str,
) -> int | None:
    raw_items = report.get("benchmarks")
    if isinstance(raw_items, list | tuple):
        for item in raw_items:
            if not isinstance(item, Mapping):
                continue
            name = _scorecard_normalize_public_benchmark_name(
                item.get("name") or item.get("benchmark") or item.get("suite")
            )
            if name == benchmark:
                return _scorecard_public_benchmark_item_case_count(item)
    name = _scorecard_normalize_public_benchmark_name(
        report.get("benchmark") or report.get("name") or report.get("suite")
    )
    if name == benchmark:
        return _scorecard_public_benchmark_item_case_count(report)
    metrics = _scorecard_result_metrics(dict(report))
    return _scorecard_int(metrics.get(f"{benchmark}_case_count"))


def _scorecard_public_benchmark_item_case_count(
    item: Mapping[str, object],
) -> int | None:
    metrics = _scorecard_result_metrics(dict(item))
    return _scorecard_int(metrics.get("case_count", item.get("case_count")))


def _scorecard_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _scorecard_collect_public_benchmarks(
    report: dict[str, object],
    benchmarks: dict[str, dict[str, object]],
) -> None:
    raw_items = report.get("benchmarks", ())
    if isinstance(raw_items, list | tuple):
        for item in raw_items:
            if isinstance(item, dict):
                name = _scorecard_normalize_public_benchmark_name(
                    item.get("name") or item.get("benchmark") or item.get("suite")
                )
                if name:
                    benchmarks[name] = _scorecard_public_benchmark_item_summary(
                        item,
                        parent_ok=report.get("ok") is True,
                    )

    metrics = _scorecard_result_metrics(report)
    for benchmark in _PUBLIC_MEMORY_BENCHMARK_REQUIRED:
        if benchmark in benchmarks:
            continue
        name = _scorecard_normalize_public_benchmark_name(
            report.get("benchmark") or report.get("name") or report.get("suite")
        )
        if name == benchmark:
            benchmarks[name] = _scorecard_public_benchmark_item_summary(
                report,
                parent_ok=report.get("ok") is True,
            )
        elif f"{benchmark}_accuracy" in metrics:
            benchmarks[benchmark] = {
                "ok": report.get("ok") is True,
                "accuracy": metrics.get(f"{benchmark}_accuracy"),
                "case_count": metrics.get(f"{benchmark}_case_count"),
                "report_suite": report.get("suite"),
            }


def _scorecard_public_benchmark_item_summary(
    item: dict[str, object],
    *,
    parent_ok: bool,
) -> dict[str, object]:
    metrics = _scorecard_result_metrics(item)
    accuracy = metrics.get("accuracy", item.get("accuracy"))
    case_count = metrics.get("case_count", item.get("case_count"))
    item_ok = item.get("ok")
    return {
        "ok": item_ok is True if isinstance(item_ok, bool) else parent_ok,
        "accuracy": accuracy,
        "case_count": case_count,
        "report_suite": item.get("suite"),
    }


def _scorecard_public_benchmark_competitive_floor(
    benchmarks: Mapping[str, dict[str, object]],
) -> dict[str, object]:
    checks: dict[str, dict[str, object]] = {}
    for name, floor in _PUBLIC_MEMORY_BENCHMARK_COMPETITIVE_FLOORS.items():
        benchmark = benchmarks.get(name)
        accuracy = _scorecard_float(benchmark.get("accuracy") if benchmark else None)
        case_count = _scorecard_int(benchmark.get("case_count") if benchmark else None)
        min_accuracy = float(floor["min_accuracy"])
        min_case_count = int(floor["min_case_count"])
        checks[name] = {
            "ok": (
                benchmark is not None
                and benchmark.get("ok") is True
                and accuracy is not None
                and accuracy >= min_accuracy
                and case_count is not None
                and case_count >= min_case_count
            ),
            "accuracy": accuracy,
            "min_accuracy": min_accuracy,
            "case_count": case_count,
            "min_case_count": min_case_count,
        }
    failed = sorted(name for name, check in checks.items() if check["ok"] is not True)
    return {
        "ok": not failed,
        "failed_benchmarks": failed,
        "benchmarks": checks,
    }


def _scorecard_normalize_public_benchmark_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace(" ", "-").replace("_", "-")
    for canonical, aliases in _PUBLIC_MEMORY_BENCHMARK_NAME_ALIASES.items():
        if normalized == canonical or normalized in {alias.replace("_", "-") for alias in aliases}:
            return canonical
    return None


def _scorecard_full_provider_evidence_summary(
    result: dict[str, object] | None,
    *,
    require_top_evidence: bool = False,
) -> dict[str, object]:
    if result is None:
        return {"present": False, "ok": None}
    checks = result.get("checks", {})
    checks_map = checks if isinstance(checks, dict) else {}
    adapters = result.get("adapters", {})
    adapters_map = adapters if isinstance(adapters, dict) else {}
    mcp = result.get("mcp", {})
    mcp_map = mcp if isinstance(mcp, dict) else {}
    required_checks = {
        **{
            check_key: checks_map.get(check_key) is True
            for check_key in _FULL_PROVIDER_REQUIRED_CHECK_KEYS
        },
        **{
            f"{adapter_name}_adapter_ok": adapters_map.get(adapter_name) == "ok"
            for adapter_name in _FULL_PROVIDER_REQUIRED_ADAPTERS
        },
        "mcp_lifecycle_included": bool(mcp_map) and mcp_map.get("ok") is True,
    }
    check_values = [value is True for value in checks_map.values()]
    failed_required_checks = sorted(
        check for check, ok in required_checks.items() if ok is not True
    )
    provenance = top_evidence_provenance_summary(result)
    safety = top_evidence_safety_summary(result)
    quality_ok = result.get("ok") is True and not failed_required_checks
    return {
        "present": True,
        "suite": result.get("suite", FULL_PROVIDER_CANARY_SUITE),
        "ok": quality_ok
        and (not require_top_evidence or (provenance["ok"] is True and safety["ok"] is True)),
        "quality_ok": quality_ok,
        "provenance_ok": provenance["ok"] if require_top_evidence else None,
        "provenance": provenance,
        "safety_ok": safety["ok"] if require_top_evidence else None,
        "safety": safety,
        "required_checks": required_checks,
        "failed_required_checks": failed_required_checks,
        "checks_ok_count": sum(1 for value in check_values if value),
        "checks_total": len(check_values),
        "adapters": {
            name: adapters_map.get(name)
            for name in ("qdrant", "graphiti", "embeddings", "cognee")
            if name in adapters_map
        },
        "mcp_included": mcp_map.get("skipped") is not True if mcp_map else None,
        "prod_load_included": isinstance(result.get("prod_load"), dict),
    }


def _scorecard_agent_behavior_evidence_summary(
    result: dict[str, object] | None,
    *,
    require_top_evidence: bool = False,
) -> dict[str, object]:
    if result is None:
        return {"present": False, "ok": None}
    metrics = _scorecard_result_metrics(result)
    gates = result.get("gates", {})
    gates_map = gates if isinstance(gates, dict) else {}
    gate_values = [value is True for value in gates_map.values()]
    metric_keys = (
        "tool_choice_accuracy",
        "search_before_write_rate",
        "update_vs_duplicate_rate",
        "document_routing_accuracy",
        "answer_support_rate",
        "scenario_count",
        "live_session_case_count",
        "live_session_pass_rate",
        "transcript_corpus_case_count",
        "transcript_corpus_pass_rate",
        "adversarial_case_count",
        "adversarial_pass_rate",
        "unsafe_write_count",
        "secret_leak_count",
        "cross_scope_leak_count",
        "stale_leak_count",
        "deleted_leak_count",
        "critical_safety_failures",
    )
    required_checks = _scorecard_agent_behavior_required_checks(
        result=result,
        metrics=metrics,
        gates=gates_map,
        require_top_evidence=require_top_evidence,
    )
    failed_required_checks = sorted(
        check for check, ok in required_checks.items() if ok is not True
    )
    provenance = top_evidence_provenance_summary(result)
    safety = top_evidence_safety_summary(result)
    quality_ok = result.get("ok") is True and not failed_required_checks
    return {
        "present": True,
        "suite": result.get("suite", AGENT_BEHAVIOR_BENCH_SUITE),
        "ok": quality_ok
        and (not require_top_evidence or (provenance["ok"] is True and safety["ok"] is True)),
        "quality_ok": quality_ok,
        "provenance_ok": provenance["ok"] if require_top_evidence else None,
        "provenance": provenance,
        "safety_ok": safety["ok"] if require_top_evidence else None,
        "safety": safety,
        "scenario_set": result.get("scenario_set"),
        "model": result.get("model"),
        "quality_floor_ok": not failed_required_checks,
        "required_checks": required_checks,
        "failed_required_checks": failed_required_checks,
        "gates_ok_count": sum(1 for value in gate_values if value),
        "gates_total": len(gate_values),
        "metrics": {key: metrics[key] for key in metric_keys if key in metrics},
        "scenario_evidence": _scorecard_agent_behavior_scenario_evidence(result),
    }


def _scorecard_agent_behavior_required_checks(
    *,
    result: dict[str, object],
    metrics: Mapping[str, object],
    gates: Mapping[str, object],
    require_top_evidence: bool,
) -> dict[str, bool]:
    checks = {
        "scenario_set_realistic_or_better": (
            result.get("scenario_set") in _AGENT_BEHAVIOR_ACCEPTED_SCENARIO_SETS
        ),
        "all_reported_gates_pass": bool(gates) and all(value is True for value in gates.values()),
    }
    for metric, floor in _AGENT_BEHAVIOR_RATE_FLOORS.items():
        value = _scorecard_float(metrics.get(metric))
        checks[f"{metric}_min"] = value is not None and value >= floor
    for metric in _AGENT_BEHAVIOR_ZERO_COUNT_METRICS:
        value = _scorecard_int(metrics.get(metric))
        checks[f"{metric}_zero"] = value == 0
    if require_top_evidence:
        checks["scenario_set_all_for_top_evidence"] = (
            result.get("scenario_set") == AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_SET
        )
        for metric, floor in AGENT_BEHAVIOR_TOP_EVIDENCE_CASE_COUNT_FLOORS.items():
            value = _scorecard_int(metrics.get(metric))
            checks[f"{metric}_min_{floor}"] = value is not None and value >= floor
        scenario_evidence = _scorecard_agent_behavior_scenario_evidence(result)
        scenario_count = _scorecard_int(scenario_evidence.get("scenario_count"))
        metric_scenario_count = _scorecard_int(metrics.get("scenario_count"))
        checks["scenario_reports_present"] = scenario_evidence["present"] is True
        checks["scenario_reports_well_formed"] = scenario_evidence.get("invalid_entry_count") == 0
        checks["scenario_report_ids_present"] = scenario_evidence.get("missing_id_count") == 0
        checks["scenario_report_ids_unique"] = scenario_evidence.get("duplicate_id_count") == 0
        checks["scenario_reports_all_passed"] = scenario_evidence.get("non_passed_count") == 0
        checks["canonical_scenario_ids_present"] = (
            scenario_evidence.get("missing_canonical_id_count") == 0
        )
        scenario_count_floor = AGENT_BEHAVIOR_TOP_EVIDENCE_CASE_COUNT_FLOORS["scenario_count"]
        checks[f"scenario_report_count_min_{scenario_count_floor}"] = (
            scenario_count is not None and scenario_count >= scenario_count_floor
        )
        checks["scenario_report_count_matches_metric"] = (
            scenario_count is not None
            and metric_scenario_count is not None
            and scenario_count == metric_scenario_count
        )
        tag_counts = scenario_evidence.get("tag_counts")
        tag_counts_map = tag_counts if isinstance(tag_counts, Mapping) else {}
        for metric, tag in AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_TAG_METRICS.items():
            tag_count = _scorecard_int(tag_counts_map.get(tag))
            metric_count = _scorecard_int(metrics.get(metric))
            checks[f"{tag}_scenario_report_count_matches_metric"] = (
                tag_count is not None and metric_count is not None and tag_count == metric_count
            )
    return checks


def _scorecard_agent_behavior_scenario_evidence(
    result: Mapping[str, object],
) -> dict[str, object]:
    scenarios = result.get("scenarios")
    if not isinstance(scenarios, list):
        return {
            "present": False,
            "scenario_count": None,
            "tag_counts": {},
            "invalid_entry_count": None,
            "missing_id_count": None,
            "duplicate_id_count": None,
            "non_passed_count": None,
            "missing_canonical_id_count": None,
            "missing_canonical_ids": [],
        }
    tag_counts = {tag: 0 for tag in AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_TAG_METRICS.values()}
    seen_ids: set[str] = set()
    invalid_entry_count = 0
    missing_id_count = 0
    duplicate_id_count = 0
    non_passed_count = 0
    for scenario in scenarios:
        if not isinstance(scenario, Mapping):
            invalid_entry_count += 1
            continue
        scenario_id = scenario.get("id")
        if not isinstance(scenario_id, str) or not scenario_id.strip():
            missing_id_count += 1
        elif scenario_id in seen_ids:
            duplicate_id_count += 1
        else:
            seen_ids.add(scenario_id)
        if scenario.get("status") != "passed":
            non_passed_count += 1
        tags = scenario.get("tags")
        if not isinstance(tags, list):
            continue
        tag_set = {tag for tag in tags if isinstance(tag, str)}
        for tag in tag_counts:
            if tag in tag_set:
                tag_counts[tag] += 1
    missing_canonical_ids = sorted(set(AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS) - seen_ids)
    return {
        "present": True,
        "scenario_count": len(scenarios),
        "tag_counts": tag_counts,
        "invalid_entry_count": invalid_entry_count,
        "missing_id_count": missing_id_count,
        "duplicate_id_count": duplicate_id_count,
        "non_passed_count": non_passed_count,
        "missing_canonical_id_count": len(missing_canonical_ids),
        "missing_canonical_ids": missing_canonical_ids,
    }


def _scorecard_capability(name: str, checks: Mapping[str, bool]) -> dict[str, object]:
    failed = sorted(check for check, ok in checks.items() if not ok)
    return {
        "name": name,
        "ok": not failed,
        "checks": dict(checks),
        "failed_checks": failed,
    }


def _scorecard_failures(
    *,
    missing_suites: tuple[str, ...],
    suites: Mapping[str, dict[str, object]],
    capabilities: Mapping[str, dict[str, object]],
    gates: Mapping[str, bool],
) -> list[dict[str, object]]:
    failures: list[dict[str, object]] = []
    for suite in missing_suites:
        failures.append(
            {
                "case_id": suite,
                "category": "suite",
                "reason": "missing_suite_result",
            }
        )
    for suite, summary in suites.items():
        if summary["ok"] is not True:
            failures.append(
                {
                    "case_id": suite,
                    "category": "suite",
                    "reason": "suite_not_ok",
                }
            )
    for capability_name, capability in capabilities.items():
        if capability["ok"] is not True:
            failures.append(
                {
                    "case_id": capability_name,
                    "category": "capability",
                    "reason": "capability_gate_failed",
                    "failed_checks": capability["failed_checks"],
                }
            )
    for gate, ok in gates.items():
        if not ok:
            failures.append(
                {
                    "case_id": gate,
                    "category": "scorecard_gate",
                    "reason": "scorecard_gate_failed",
                }
            )
    return failures


def _scorecard_metrics(
    suite_results: Mapping[str, dict[str, object]],
) -> dict[str, object]:
    quality = _scorecard_result_metrics(suite_results.get(QUALITY_GOLDEN_SUITE))
    semantic = _scorecard_result_metrics(suite_results.get(SEMANTIC_LINKING_GOLDEN_SUITE))
    multimodal = _scorecard_result_metrics(
        suite_results.get(MULTIMODAL_OFFLINE_GOLDEN_SUITE)
    )
    long = _scorecard_result_metrics(suite_results.get(LONG_MEMORY_GOLDEN_SUITE))
    auto = _scorecard_result_metrics(suite_results.get(AUTO_MEMORY_GOLDEN_SUITE))
    graph = _scorecard_result_metrics(suite_results.get(GRAPH_NATIVE_GOLDEN_SUITE))
    return {
        "quality_recall_at_5": quality.get("recall_at_5", 0.0),
        "quality_precision_at_5": quality.get("precision_at_5", 0.0),
        "quality_item_contract_support_rate": quality.get("item_contract_support_rate", 0.0),
        "quality_item_contract_failure_count": quality.get("item_contract_failure_count", 0),
        "quality_retrieval_trace_support_rate": quality.get(
            "retrieval_trace_support_rate",
            0.0,
        ),
        "quality_required_case_coverage_rate": quality.get("required_case_coverage_rate", 0.0),
        "quality_missing_required_case_count": quality.get("missing_required_case_count", 0),
        "long_multi_session_recall_at_5": long.get("multi_session_recall_at_5", 0.0),
        "long_temporal_update_accuracy": long.get("temporal_update_accuracy", 0.0),
        "auto_extraction_positive_recall_rate": auto.get(
            "extraction_positive_recall_rate",
            0.0,
        ),
        "auto_extraction_operation_accuracy": auto.get(
            "extraction_operation_accuracy",
            0.0,
        ),
        "auto_extraction_admission_accuracy": auto.get(
            "extraction_admission_accuracy",
            0.0,
        ),
        "semantic_linking_ranking_accuracy": semantic.get("ranking_accuracy", 0.0),
        "semantic_linking_event_linking_accuracy": semantic.get(
            "event_linking_accuracy",
            0.0,
        ),
        "semantic_linking_temporal_intent_recall": semantic.get(
            "temporal_intent_recall",
            0.0,
        ),
        "semantic_linking_document_chunk_linking_accuracy": semantic.get(
            "document_chunk_linking_accuracy",
            0.0,
        ),
        "semantic_linking_anchor_recall_rate": semantic.get("anchor_recall_rate", 0.0),
        "semantic_linking_anchor_disambiguation_rate": semantic.get(
            "anchor_disambiguation_rate",
            0.0,
        ),
        "semantic_linking_anchor_review_evidence_rate": semantic.get(
            "anchor_review_evidence_rate",
            0.0,
        ),
        "semantic_linking_high_impact_relation_policy_safety": semantic.get(
            "high_impact_relation_policy_safety",
            0.0,
        ),
        "semantic_linking_evidence_relation_policy_safety": semantic.get(
            "evidence_relation_policy_safety",
            0.0,
        ),
        "semantic_linking_mentions_relation_policy_safety": semantic.get(
            "mentions_relation_policy_safety",
            0.0,
        ),
        "semantic_linking_review_approval_rate": semantic.get("review_approval_rate", 0.0),
        "semantic_linking_required_case_coverage_rate": semantic.get(
            "required_case_coverage_rate",
            0.0,
        ),
        "semantic_linking_missing_required_case_count": semantic.get(
            "missing_required_case_count",
            0,
        ),
        "semantic_linking_false_positive_count": semantic.get("false_positive_count", 0),
        "semantic_linking_cross_scope_leak_count": semantic.get("cross_scope_leak_count", 0),
        "multimodal_offline_pass_rate": multimodal.get("pass_rate", 0.0),
        "multimodal_offline_false_positive_count": multimodal.get(
            "false_positive_count",
            0,
        ),
        "multimodal_offline_prompt_injection_guard_rate": multimodal.get(
            "prompt_injection_guard_rate",
            0.0,
        ),
        "graph_recall_rate": graph.get("graph_recall_rate", 0.0),
        "graph_hydration_rate": graph.get("graph_hydration_rate", 0.0),
        "safety_leak_count": _scorecard_safety_leak_count(suite_results),
    }


def _scorecard_safety_leak_count(
    suite_results: Mapping[str, dict[str, object]],
) -> int:
    total = 0
    for suite in (
        SMALL_GOLDEN_SUITE,
        QUALITY_GOLDEN_SUITE,
        LONG_MEMORY_GOLDEN_SUITE,
        AUTO_MEMORY_GOLDEN_SUITE,
        GRAPH_NATIVE_GOLDEN_SUITE,
    ):
        metrics = _scorecard_result_metrics(suite_results.get(suite))
        for key in (
            "deleted_memory_leak_count",
            "cross_memory_scope_leak_count",
            "cross_thread_leak_count",
            "restricted_memory_leak_count",
            "prompt_injection_promoted_count",
            "secret_leakage_count",
            "graph_safety_leak_count",
        ):
            total += int(metrics.get(key, 0))
    return total


def _scorecard_result_metrics(result: dict[str, object] | None) -> dict[str, object]:
    if result is None:
        return {}
    metrics = result.get("metrics", {})
    return metrics if isinstance(metrics, dict) else {}


def _scorecard_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _scorecard_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None
