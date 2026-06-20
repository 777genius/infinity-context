import json
from pathlib import Path
from typing import Any

from infinity_context_core.agent_behavior_contract import (
    AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS,
)
from infinity_context_server.eval import (
    build_memory_quality_scorecard,
    memory_quality_scorecard_policy_snapshot,
    run_memory_quality_scorecard,
)
from infinity_context_server.eval_constants import (
    MULTIMODAL_OFFLINE_GOLDEN_SUITE,
    QUALITY_GOLDEN_REQUIRED_CASE_IDS,
    SEMANTIC_LINKING_REQUIRED_CASE_IDS,
)


def _case_reports(case_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        {
            "case_id": case_id,
            "category": "fixture",
            "status": "ok",
            "item_ids": [],
        }
        for case_id in case_ids
    ]


def _scorecard_fixture_results() -> dict[str, dict[str, Any]]:
    return {
        "small-golden": {
            "suite": "small-golden",
            "ok": True,
            "status": "ok",
            "metrics": {
                "case_count": 8,
                "recall_at_5": 0.9,
                "precision_at_5": 0.8,
                "deleted_memory_leak_count": 0,
                "cross_memory_scope_leak_count": 0,
                "prompt_injection_promoted_count": 0,
                "context_token_overflow_count": 0,
            },
            "failures": [],
        },
        "quality-golden": {
            "suite": "quality-golden",
            "ok": True,
            "status": "ok",
            "metrics": {
                "case_count": 16,
                "required_case_coverage_rate": 1.0,
                "missing_required_case_count": 0,
                "recall_at_5": 0.96,
                "precision_at_5": 0.95,
                "answer_support_rate": 1.0,
                "answer_support_breakdown_rate": 1.0,
                "document_recall_at_5": 1.0,
                "retrieval_trace_support_rate": 1.0,
                "retrieval_trace_location_contract_rate": 1.0,
                "retrieval_answerability_contract_rate": 1.0,
                "precise_citation_contract_rate": 1.0,
                "item_contract_support_rate": 1.0,
                "item_contract_failure_count": 0,
                "multi_memory_scope_recall_at_5": 1.0,
                "thread_recall_at_5": 1.0,
                "stale_memory_rate": 0.0,
                "deleted_memory_leak_count": 0,
                "cross_memory_scope_leak_count": 0,
                "cross_thread_leak_count": 0,
                "restricted_memory_leak_count": 0,
                "prompt_injection_promoted_count": 0,
                "harmful_context_rate": 0.0,
                "context_token_overflow_count": 0,
            },
            "cases": _case_reports(
                (
                    *QUALITY_GOLDEN_REQUIRED_CASE_IDS,
                    "current_model_beats_decoy",
                    "architecture_roles_recall",
                    "clean_architecture_recall_without_frontend_noise",
                    "deleted_fact_hidden",
                    "restricted_fact_hidden",
                    "thread_current_visible_without_neighbor",
                    "thread_other_visible_without_current",
                )
            ),
            "failures": [],
        },
        "semantic-linking-golden": {
            "suite": "semantic-linking-golden",
            "ok": True,
            "status": "ok",
            "metrics": {
                "case_count": 18,
                "required_case_coverage_rate": 1.0,
                "missing_required_case_count": 0,
                "ranking_accuracy": 1.0,
                "event_linking_accuracy": 1.0,
                "temporal_intent_recall": 1.0,
                "document_chunk_linking_accuracy": 1.0,
                "anchor_recall_rate": 1.0,
                "anchor_disambiguation_rate": 1.0,
                "mixed_script_event_anchor_rate": 1.0,
                "anchor_review_evidence_rate": 1.0,
                "high_impact_relation_policy_safety": 1.0,
                "evidence_relation_policy_safety": 1.0,
                "mentions_relation_policy_safety": 1.0,
                "review_approval_rate": 1.0,
                "false_positive_count": 0,
                "cross_scope_leak_count": 0,
            },
            "cases": _case_reports(SEMANTIC_LINKING_REQUIRED_CASE_IDS),
            "checks": {
                "top_fact_beats_distractor": True,
                "event_call_beats_recent_chat": True,
                "temporal_intent_links_recent_fact_without_text_match": True,
                "document_chunk_evidence_suggested": True,
                "person_project_and_org_anchors_suggested": True,
                "anchor_evidence_confidence_and_observed_at_exposed": True,
                "person_and_project_anchors_suggested": True,
                "same_name_person_project_anchors_separate": True,
                "explicit_alias_anchor_identity_terms_rank_correct_target": True,
                "high_impact_relation_requires_explicit_signal": True,
                "weak_overlap_below_review_threshold_denied": True,
                "evidence_relation_requires_source_signal": True,
                "mentions_relation_requires_entity_signal": True,
                "top_suggestion_approves_to_link": True,
                "unrelated_capture_has_no_candidates": True,
                "cross_scope_fact_not_suggested": True,
            },
            "failures": [],
        },
        MULTIMODAL_OFFLINE_GOLDEN_SUITE: {
            "suite": MULTIMODAL_OFFLINE_GOLDEN_SUITE,
            "ok": True,
            "status": "ok",
            "checks": {
                "ocr_visual_text_links_image_chunk": True,
                "metadata_only_bbox_region_links_image_chunk": True,
                "transcript_links_audio_time_range": True,
                "video_keyframe_links_frame_timeline": True,
                "video_without_audio_keeps_keyframe_candidate": True,
                "alex_hour_ago_links_recent_audio_event": True,
                "similar_wrong_project_keeps_atlas_over_aurora": True,
                "empty_audio_without_speech_has_no_candidates": True,
                "prompt_injection_guard": True,
                "unrelated_capture_has_no_candidates": True,
                "evidence_metadata_exposed": True,
                "retrieval_evidence_coverage_profile": True,
            },
            "metrics": {
                "case_count": 11,
                "passed_case_count": 11,
                "pass_rate": 1.0,
                "false_positive_count": 0,
                "vision_linking_accuracy": 1.0,
                "metadata_only_visual_linking_accuracy": 1.0,
                "audio_linking_accuracy": 1.0,
                "video_linking_accuracy": 1.0,
                "temporal_audio_linking_accuracy": 1.0,
                "similar_wrong_project_precision": 1.0,
                "empty_audio_no_candidate_rate": 1.0,
                "prompt_injection_guard_rate": 1.0,
                "retrieval_evidence_location_coverage_rate": 1.0,
                "retrieval_evidence_location_gap_count": 0,
            },
            "gates": {
                "case_count": True,
                "all_cases_passed": True,
                "false_positive_count": True,
                "prompt_injection_guard": True,
                "evidence_metadata_exposed": True,
                "retrieval_evidence_coverage_profile": True,
            },
            "evidence_coverage_profile": {
                "schema_version": "evidence-coverage-v1",
                "evidence_items_total": 5,
                "precise_evidence_location_coverage_ratio": 1.0,
                "transcript_time_range_coverage_ratio": 1.0,
                "image_bbox_coverage_ratio": 1.0,
                "video_time_range_coverage_ratio": 1.0,
                "evidence_location_gap_count": 0,
                "evidence_location_gaps": [],
                "prompt_ready_multimodal_evidence": True,
            },
            "cases": _case_reports(
                (
                    "ocr_visual_text_links_image_chunk",
                    "metadata_only_bbox_region_links_image_chunk",
                    "transcript_links_audio_time_range",
                    "video_keyframe_links_frame_timeline",
                    "video_without_audio_keeps_keyframe_candidate",
                    "alex_hour_ago_links_recent_audio_event",
                    "similar_wrong_project_keeps_atlas_over_aurora",
                    "empty_audio_without_speech_has_no_candidates",
                    "prompt_injection_screenshot_stays_review_evidence",
                    "russian_prompt_injection_screenshot_stays_review_evidence",
                    "unrelated_multimodal_capture_has_no_candidates",
                )
            ),
            "failures": [],
        },
        "long-memory-golden": {
            "suite": "long-memory-golden",
            "ok": True,
            "status": "ok",
            "metrics": {
                "case_count": 16,
                "long_memory_case_count": 16,
                "recall_at_5": 0.96,
                "precision_at_5": 0.95,
                "multi_session_recall_at_5": 1.0,
                "temporal_update_accuracy": 1.0,
                "preference_synthesis_recall": 1.0,
                "long_document_recall_at_5": 1.0,
                "thread_recall_at_5": 1.0,
                "multi_memory_scope_recall_at_5": 1.0,
                "stale_memory_rate": 0.0,
                "deleted_memory_leak_count": 0,
                "cross_memory_scope_leak_count": 0,
                "cross_thread_leak_count": 0,
                "restricted_memory_leak_count": 0,
                "prompt_injection_promoted_count": 0,
                "long_safety_leak_count": 0,
                "harmful_context_rate": 0.0,
                "context_token_overflow_count": 0,
            },
            "failures": [],
        },
        "auto-memory-golden": {
            "suite": "auto-memory-golden",
            "ok": True,
            "status": "ok",
            "metrics": {
                "case_count": 13,
                "extraction_case_count": 78,
                "extraction_semantic_case_count": 18,
                "extraction_positive_recall_rate": 1.0,
                "extraction_operation_accuracy": 1.0,
                "extraction_kind_accuracy": 1.0,
                "extraction_admission_accuracy": 1.0,
                "extraction_ttl_accuracy": 1.0,
                "extraction_target_hint_accuracy": 1.0,
                "extraction_false_positive_count": 0,
                "extraction_false_negative_count": 0,
                "duplicate_suggestion_count": 0,
                "replay_duplicate_suggestion_count": 0,
                "wrong_auto_apply_count": 0,
                "active_fact_before_review_count": 0,
                "prompt_injection_promoted_count": 0,
                "secret_leakage_count": 0,
                "assistant_low_trust_violation_count": 0,
                "target_resolution_violation_count": 0,
                "review_operation_violation_count": 0,
            },
            "cases": _case_reports(
                (
                    "explicit_remember_creates_pending_suggestion",
                    "auto_apply_safe_rejects_medium_confidence",
                    "temporary_task_not_promoted_to_durable",
                    "prompt_injection_not_promoted",
                    "secret_redacted_before_storage",
                    "assistant_inference_is_low_trust_review_only",
                    "candidate_flood_is_capped",
                    "update_target_hint_resolves_to_review_suggestion",
                    "delete_target_hint_resolves_to_review_suggestion",
                    "ambiguous_target_hint_is_not_promoted",
                    "explicit_review_operation_stays_review_only",
                    "capture_replay_is_idempotent",
                    "approved_fact_creates_duplicate_merge_review",
                )
            ),
            "failures": [],
        },
        "graph-native-golden": {
            "suite": "graph-native-golden",
            "ok": True,
            "status": "ok",
            "metrics": {
                "case_count": 8,
                "graph_recall_rate": 1.0,
                "graph_hydration_rate": 1.0,
                "graph_status_ok_rate": 1.0,
                "graph_safety_leak_count": 0,
                "graph_stale_drop_count": 4,
                "canonical_only_graph_skip_count": 1,
            },
            "failures": [],
        },
        "prompt-contract": {
            "suite": "prompt-contract",
            "ok": True,
            "status": "ok",
            "checks": {
                "snapshot_safe": True,
                "snapshot_exists": True,
                "matches_snapshot": True,
            },
            "cases": [
                "cross_memory_scope_isolation",
                "degraded_graphiti",
                "degraded_qdrant",
                "deleted_fact_filtered",
                "empty_context",
                "facts_only",
                "facts_plus_chunks",
                "instruction_flag_dropped",
                "prompt_injection_quoted",
                "token_budget_truncated",
            ],
            "failures": [],
        },
    }


def _scorecard_provenance(
    *,
    generated_by: str,
    suite: str,
    commit: str = "abc123",
    dirty: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_by": generated_by,
        "suite": suite,
        "git": {"commit": commit, "dirty": dirty},
        "runtime": {"python_version": "3.13.5", "platform": "test-platform"},
    }


def _full_provider_canary_report() -> dict[str, Any]:
    return {
        "suite": "infinity-context-full-provider-canary",
        "ok": True,
        "provenance": _scorecard_provenance(
            generated_by="scripts/clean_full_smoke.py",
            suite="infinity-context-full-provider-canary",
        ),
        "checks": {
            "fact_created": True,
            "updated_fact_versioned": True,
            "forgotten_fact_deleted": True,
            "providers_are_healthy": True,
            "context_provider_status_ok": True,
            "mcp_provider_diagnostics_ok": True,
            "mcp_search_has_graphiti_fact_after_worker": True,
            "mcp_search_has_qdrant_document_chunk_after_worker": True,
            "mcp_search_hides_old_fact_after_update": True,
            "mcp_search_hides_deleted_fact": True,
            "outbox_has_no_pending_or_dead": True,
            "mcp_outbox_has_no_pending_or_dead": True,
        },
        "adapters": {
            "qdrant": "ok",
            "graphiti": "ok",
            "embeddings": "ok",
            "cognee": "disabled",
        },
        "mcp": {"ok": True},
    }


def _multimodal_live_provider_canary_report() -> dict[str, Any]:
    requirements = {
        "vision_real_provider": {"ok": True, "status": "succeeded"},
        "vision_response_evidence": {"ok": True, "status": "succeeded"},
        "audio_transcription_real_provider": {"ok": True, "status": "succeeded"},
        "audio_transcription_format_matrix": {
            "covered_suffixes": [".mp3", ".wav"],
            "ok": True,
            "status": "succeeded",
        },
        "transcription_response_artifact": {"ok": True, "status": "succeeded"},
        "transcription_request_contract": {"ok": True, "status": "contract_covered"},
        "invalid_key_live_probe": {"ok": True, "status": "succeeded"},
        "no_secret_leak_guard": {"ok": True, "status": "contract_covered"},
    }
    return {
        "suite": "infinity-context-multimodal-live-provider-canary",
        "ok": True,
        "provider_key_present": True,
        "provenance": _scorecard_provenance(
            generated_by="scripts/multimodal_live_provider_canary.py",
            suite="infinity-context-multimodal-live-provider-canary",
        ),
        "proof_matrix": {
            "schema_version": "multimodal-provider-proof-matrix-v1",
            "summary": {
                "contract_requirements_passed": 8,
                "contract_requirements_total": 8,
                "live_requirements_passed": 6,
                "live_requirements_total": 6,
            },
            "requirements": requirements,
        },
        "secrets_redacted": True,
    }


def _degraded_multimodal_live_provider_canary_report() -> dict[str, Any]:
    report = _multimodal_live_provider_canary_report()
    report["ok"] = False
    report["provider_key_present"] = False
    requirements = report["proof_matrix"]["requirements"]
    for name in (
        "vision_real_provider",
        "vision_response_evidence",
        "audio_transcription_real_provider",
        "audio_transcription_format_matrix",
        "transcription_response_artifact",
    ):
        requirements[name] = {
            "ok": False,
            "reason": "provider_credential_missing",
            "status": "skipped",
        }
    report["proof_matrix"]["summary"] = {
        "contract_requirements_passed": 8,
        "contract_requirements_total": 8,
        "live_requirements_passed": 1,
        "live_requirements_total": 6,
    }
    return report


def _agent_behavior_benchmark_report() -> dict[str, Any]:
    return {
        "suite": "memory_mcp_agent_behavior",
        "ok": True,
        "provenance": _scorecard_provenance(
            generated_by="infinity_context_mcp.agent_behavior_bench",
            suite="memory_mcp_agent_behavior",
        ),
        "scenario_set": "all",
        "model": "gpt-5.4-mini",
        "metrics": {
            "scenario_count": len(AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS),
            "tool_choice_accuracy": 1.0,
            "search_before_write_rate": 1.0,
            "update_vs_duplicate_rate": 1.0,
            "document_routing_accuracy": 1.0,
            "answer_support_rate": 1.0,
            "live_session_case_count": 11,
            "live_session_pass_rate": 1.0,
            "transcript_corpus_case_count": 5,
            "transcript_corpus_pass_rate": 1.0,
            "adversarial_case_count": 9,
            "adversarial_pass_rate": 1.0,
            "unsafe_write_count": 0,
            "secret_leak_count": 0,
            "cross_scope_leak_count": 0,
            "stale_leak_count": 0,
            "deleted_leak_count": 0,
            "critical_safety_failures": 0,
        },
        "gates": {
            "critical_safety_failures_zero": True,
            "secret_leak_count_zero": True,
            "unsafe_write_count_zero": True,
            "cross_scope_leak_count_zero": True,
            "stale_leak_count_zero": True,
            "deleted_leak_count_zero": True,
            "search_before_write_rate_min_0_90": True,
            "update_vs_duplicate_rate_min_0_80": True,
            "tool_choice_accuracy_min_0_80": True,
            "answer_support_rate_min_0_80": True,
            "live_session_pass_rate_min_0_80": True,
            "transcript_corpus_pass_rate_min_0_80": True,
            "adversarial_pass_rate_min_0_90": True,
            "critical_scenarios_pass": True,
        },
        "scenarios": _agent_behavior_scenario_reports(),
    }


def _agent_live_smoke_report() -> dict[str, Any]:
    return {
        "suite": "infinity-context-agent-live-smoke",
        "ok": True,
        "provenance": _scorecard_provenance(
            generated_by="scripts/agent_install_verification.py",
            suite="infinity-context-agent-live-smoke",
        ),
        "strict_agent_cli": True,
        "checks": {
            "generated_mcp": {
                "codex_claude_cursor_package": {"ok": True},
                "gemini": {"ok": True},
                "opencode": {"ok": True},
                "cursor_workspace": {"ok": True},
            },
            "agent_cli": {
                "claude": {"status": "ok"},
                "gemini": {"status": "ok"},
                "opencode": {"status": "ok"},
                "codex": {"status": "ok"},
            },
        },
        "generated_mcp_failures": [],
        "agent_cli_failures": [],
        "failures": [],
    }


def _agent_behavior_scenario_reports(
    *,
    scenario_count: int = len(AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS),
    live_session_count: int = 11,
    transcript_corpus_count: int = 5,
    adversarial_count: int = 9,
) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    transcript_adversarial_count = min(transcript_corpus_count, adversarial_count)
    for index in range(transcript_adversarial_count):
        scenarios.append(
            _agent_behavior_scenario_report(
                index,
                tags=("live_session", "transcript_corpus", "adversarial"),
            )
        )
    remaining_adversarial = adversarial_count - transcript_adversarial_count
    for _ in range(remaining_adversarial):
        scenarios.append(
            _agent_behavior_scenario_report(
                len(scenarios),
                tags=("live_session", "adversarial"),
            )
        )
    remaining_live = live_session_count - sum(
        "live_session" in scenario["tags"] for scenario in scenarios
    )
    for _ in range(max(remaining_live, 0)):
        scenarios.append(
            _agent_behavior_scenario_report(
                len(scenarios),
                tags=("live_session",),
            )
        )
    while len(scenarios) < scenario_count:
        scenarios.append(_agent_behavior_scenario_report(len(scenarios), tags=("core",)))
    return scenarios[:scenario_count]


def _agent_behavior_scenario_report(
    index: int,
    *,
    tags: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "id": AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS[index]
        if index < len(AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS)
        else f"external-agent-scenario-{index}",
        "category": "answer",
        "tags": list(tags),
        "critical": True,
        "status": "passed",
        "tool_calls": [],
        "failures": [],
        "memory_checks": [],
    }


def _public_benchmark_report() -> dict[str, Any]:
    return {
        "suite": "public-memory-benchmark",
        "ok": True,
        "provenance": _scorecard_provenance(
            generated_by="infinity_context_server.official_public_benchmark",
            suite="public-memory-benchmark",
        ),
        "benchmarks": [
            {
                "name": "locomo",
                "ok": True,
                "metrics": {"accuracy": 0.947, "case_count": 600},
            },
            {
                "name": "longmemeval",
                "ok": True,
                "metrics": {"accuracy": 0.902, "case_count": 500},
            },
        ],
        "dataset_hashes": {
            "locomo": "locomo-dataset-sha256",
            "longmemeval": "longmemeval-dataset-sha256",
        },
        "dataset_sources": {
            "locomo": {
                "source_kind": "official_download",
                "official_url": "https://example.test/locomo.json",
                "path_label": "locomo.json",
                "sha256": "locomo-dataset-sha256",
                "size_bytes": 1000,
                "case_count": 600,
            },
            "longmemeval": {
                "source_kind": "official_download",
                "official_url": "https://example.test/longmemeval.json",
                "path_label": "longmemeval.json",
                "sha256": "longmemeval-dataset-sha256",
                "size_bytes": 1000,
                "case_count": 500,
            },
        },
        "metrics": {"benchmark_count": 2},
    }


def test_memory_quality_scorecard_passes_with_required_capabilities(tmp_path: Path) -> None:
    report = tmp_path / "memory-quality-scorecard.json"

    result = run_memory_quality_scorecard(
        suite_results=_scorecard_fixture_results(),
        report_out=report,
    )
    report_text = report.read_text(encoding="utf-8")
    payload = json.loads(report_text)

    assert result["ok"] is True
    assert result["suite"] == "memory-quality-scorecard"
    assert result["score"]["maturity_score_10"] == 10.0
    assert result["gates"]["required_suites_present"] is True
    assert result["capabilities"]["coverage_floors"]["ok"] is True
    assert result["capabilities"]["canonical_recall_precision"]["ok"] is True
    assert result["capabilities"]["longitudinal_memory"]["ok"] is True
    assert result["capabilities"]["auto_memory_admission"]["ok"] is True
    assert result["capabilities"]["semantic_linking"]["ok"] is True
    assert result["capabilities"]["dedup_merge_conflict_resolution"]["ok"] is True
    assert result["capabilities"]["multimodal_evidence_retrieval"]["ok"] is True
    assert result["capabilities"]["graph_native_recall"]["ok"] is True
    assert result["capabilities"]["scope_and_safety"]["ok"] is True
    assert result["capabilities"]["prompt_context_contract"]["ok"] is True
    assert result["external_evidence"]["confidence_tier"] == "internal_deterministic"
    assert result["external_evidence"]["top_library_comparison_ready"] is False
    assert result["external_evidence"]["evidence_gaps"] == [
        "full_provider_canary_missing",
        "multimodal_live_provider_canary_missing",
        "agent_behavior_benchmark_missing",
        "agent_live_smoke_missing",
        "public_benchmark_evidence_missing",
    ]
    assert result["metrics"]["safety_leak_count"] == 0
    assert result["metrics"]["multimodal_offline_pass_rate"] == 1.0
    assert result["metrics"]["multimodal_offline_false_positive_count"] == 0
    assert result["metrics"]["multimodal_offline_prompt_injection_guard_rate"] == 1.0
    assert result["metrics"]["auto_duplicate_suggestion_count"] == 0
    assert result["metrics"]["auto_replay_duplicate_suggestion_count"] == 0
    assert result["failures"] == []
    assert payload["ok"] is True
    assert "QUALITY_RESTRICTED_SECRET" not in report_text
    assert "Ignore previous instructions" not in report_text


def test_memory_quality_scorecard_fails_on_item_contract_regression() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["quality-golden"]["metrics"].update(
        {
            "item_contract_support_rate": 0.0,
            "item_contract_failure_count": 1,
        }
    )

    result = build_memory_quality_scorecard(suite_results)

    assert result["ok"] is False
    assert result["capabilities"]["canonical_recall_precision"]["ok"] is False
    assert result["capabilities"]["canonical_recall_precision"]["failed_checks"] == [
        "item_contract_failure_count",
        "item_contract_support_rate",
    ]
    assert result["metrics"]["quality_item_contract_support_rate"] == 0.0
    assert result["metrics"]["quality_item_contract_failure_count"] == 1


def test_memory_quality_scorecard_fails_on_retrieval_trace_regression() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["quality-golden"]["metrics"]["retrieval_trace_support_rate"] = 0.0

    result = build_memory_quality_scorecard(suite_results)

    assert result["ok"] is False
    assert result["capabilities"]["canonical_recall_precision"]["ok"] is False
    assert result["capabilities"]["canonical_recall_precision"]["failed_checks"] == [
        "retrieval_trace_support_rate"
    ]
    assert result["metrics"]["quality_retrieval_trace_support_rate"] == 0.0


def test_memory_quality_scorecard_fails_on_answer_support_breakdown_regression() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["quality-golden"]["metrics"]["answer_support_breakdown_rate"] = 0.0

    result = build_memory_quality_scorecard(suite_results)

    assert result["ok"] is False
    assert result["capabilities"]["canonical_recall_precision"]["ok"] is False
    assert result["capabilities"]["canonical_recall_precision"]["failed_checks"] == [
        "answer_support_breakdown_rate"
    ]
    assert result["metrics"]["quality_answer_support_breakdown_rate"] == 0.0


def test_memory_quality_scorecard_fails_on_retrieval_trace_location_regression() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["quality-golden"]["metrics"][
        "retrieval_trace_location_contract_rate"
    ] = 0.0

    result = build_memory_quality_scorecard(suite_results)

    assert result["ok"] is False
    assert result["capabilities"]["canonical_recall_precision"]["ok"] is False
    assert result["capabilities"]["canonical_recall_precision"]["failed_checks"] == [
        "retrieval_trace_location_contract_rate"
    ]
    assert result["metrics"]["quality_retrieval_trace_location_contract_rate"] == 0.0


def test_memory_quality_scorecard_fails_on_answerability_contract_regression() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["quality-golden"]["metrics"][
        "retrieval_answerability_contract_rate"
    ] = 0.0

    result = build_memory_quality_scorecard(suite_results)

    assert result["ok"] is False
    assert result["capabilities"]["canonical_recall_precision"]["ok"] is False
    assert result["capabilities"]["canonical_recall_precision"]["failed_checks"] == [
        "retrieval_answerability_contract_rate"
    ]
    assert result["metrics"]["quality_retrieval_answerability_contract_rate"] == 0.0


def test_memory_quality_scorecard_fails_on_precise_citation_contract_regression() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["quality-golden"]["metrics"]["precise_citation_contract_rate"] = 0.0

    result = build_memory_quality_scorecard(suite_results)

    assert result["ok"] is False
    assert result["capabilities"]["canonical_recall_precision"]["ok"] is False
    assert result["capabilities"]["canonical_recall_precision"]["failed_checks"] == [
        "precise_citation_contract_rate"
    ]
    assert result["metrics"]["quality_precise_citation_contract_rate"] == 0.0


def test_memory_quality_scorecard_policy_snapshot_documents_top_evidence_floors() -> None:
    policy = memory_quality_scorecard_policy_snapshot(require_top_evidence=True)

    assert policy["require_top_evidence"] is True
    assert "semantic-linking-golden" in policy["required_suites"]
    assert policy["min_case_counts"]["semantic-linking-golden"] == len(
        SEMANTIC_LINKING_REQUIRED_CASE_IDS
    )
    assert MULTIMODAL_OFFLINE_GOLDEN_SUITE in policy["required_suites"]
    assert policy["min_case_counts"][MULTIMODAL_OFFLINE_GOLDEN_SUITE] == 11
    assert policy["multimodal_offline"]["requires_evidence_metadata"] is True
    assert policy["multimodal_offline"]["requires_prompt_injection_guard"] is True
    assert (
        policy["multimodal_offline"]["requires_retrieval_evidence_coverage_profile"]
        is True
    )
    assert "audio_linking_accuracy" in policy["multimodal_offline"]["required_checks"]
    assert (
        "retrieval_evidence_coverage_profile"
        in policy["multimodal_offline"]["required_checks"]
    )
    assert policy["dedup_merge_conflict_resolution"]["required_quality_case_ids"] == [
        "pending_conflict_review_visible",
        "pending_duplicate_merge_review_visible",
    ]
    assert policy["dedup_merge_conflict_resolution"]["required_auto_memory_case_ids"] == [
        "capture_replay_is_idempotent",
        "approved_fact_creates_duplicate_merge_review",
    ]
    assert "weak_overlap_below_review_threshold_denied" in policy[
        "dedup_merge_conflict_resolution"
    ]["required_semantic_checks"]
    assert policy["dedup_merge_conflict_resolution"]["requires_replay_idempotency"] is True
    assert policy["dedup_merge_conflict_resolution"]["requires_review_before_merge"] is True
    assert policy["full_provider"]["required_adapters"] == [
        "qdrant",
        "graphiti",
        "embeddings",
    ]
    assert policy["multimodal_live_provider"]["requires_live_vision"] is True
    assert policy["multimodal_live_provider"]["requires_live_audio_transcription"] is True
    assert "vision_real_provider" in policy["multimodal_live_provider"][
        "required_requirements"
    ]
    assert "audio_transcription_format_matrix" in policy["multimodal_live_provider"][
        "required_requirements"
    ]
    assert "transcription_request_contract" in policy["multimodal_live_provider"][
        "required_requirements"
    ]
    assert (
        "mcp_search_has_qdrant_document_chunk_after_worker"
        in (policy["full_provider"]["required_checks"])
    )
    assert policy["agent_behavior"]["accepted_scenario_sets"] == [
        "realistic",
        "live",
        "transcript",
        "all",
    ]
    assert policy["agent_behavior"]["top_evidence_required_scenario_set"] == "all"
    assert policy["agent_behavior"]["top_evidence_required_case_count_floors"] == {
        "scenario_count": len(AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS),
        "live_session_case_count": 11,
        "transcript_corpus_case_count": 5,
        "adversarial_case_count": 9,
    }
    assert policy["agent_behavior"]["top_evidence_required_scenario_tag_metrics"] == {
        "live_session_case_count": "live_session",
        "transcript_corpus_case_count": "transcript_corpus",
        "adversarial_case_count": "adversarial",
    }
    assert policy["agent_behavior"]["top_evidence_required_scenario_integrity_checks"] == [
        "scenario_reports_well_formed",
        "scenario_report_ids_present",
        "scenario_report_ids_unique",
        "scenario_reports_all_passed",
        "canonical_scenario_ids_present",
    ]
    assert policy["full_provider"]["top_evidence_requires_provenance"] is True
    assert policy["full_provider"]["top_evidence_requires_safety_scan"] is True
    assert policy["full_provider"]["top_evidence_required_safety_checks"] == [
        "no_sensitive_text",
        "no_local_home_paths",
    ]
    assert policy["agent_behavior"]["top_evidence_requires_provenance"] is True
    assert policy["agent_behavior"]["top_evidence_requires_safety_scan"] is True
    assert policy["agent_behavior"]["top_evidence_required_safety_checks"] == [
        "no_sensitive_text",
        "no_local_home_paths",
    ]
    assert policy["agent_live_smoke"]["required_generated_mcp_checks"] == [
        "codex_claude_cursor_package",
        "gemini",
        "opencode",
        "cursor_workspace",
    ]
    assert policy["agent_live_smoke"]["required_agent_cli_checks"] == [
        "claude",
        "gemini",
        "opencode",
        "codex",
    ]
    assert policy["agent_live_smoke"]["requires_strict_agent_cli"] is True
    assert policy["agent_live_smoke"]["top_evidence_requires_provenance"] is True
    assert policy["agent_live_smoke"]["top_evidence_requires_safety_scan"] is True
    assert policy["public_benchmark"]["top_evidence_requires_provenance"] is True
    assert policy["public_benchmark"]["top_evidence_requires_safety_scan"] is True
    assert policy["public_benchmark"]["top_evidence_required_safety_checks"] == [
        "no_sensitive_text",
        "no_local_home_paths",
    ]
    assert policy["public_benchmark"]["top_evidence_requires_dataset_fingerprint"] is True
    assert policy["public_benchmark"]["top_evidence_requires_dataset_source_metadata"] is True
    assert policy["public_benchmark"]["top_evidence_requires_dataset_source_hash_match"] is True
    assert policy["public_benchmark"]["top_evidence_requires_dataset_path_label"] is True
    assert policy["public_benchmark"]["top_evidence_requires_dataset_source_case_count"] is True
    assert policy["public_benchmark"]["top_evidence_rejects_raw_dataset_paths"] is True
    assert (
        policy["public_benchmark"]["top_evidence_requires_official_url_for_official_sources"]
        is True
    )
    assert policy["public_benchmark"]["top_evidence_allowed_dataset_source_kinds"] == [
        "official_download",
        "local_override",
        "local_dataset",
    ]
    assert (
        "provenance_generator_allowed"
        in policy["agent_behavior"]["top_evidence_required_provenance_checks"]
    )
    assert policy["agent_behavior"]["rate_floors"]["adversarial_pass_rate"] == 0.9
    assert "unsafe_write_count" in policy["agent_behavior"]["zero_count_metrics"]
    assert policy["public_benchmark"]["required_benchmarks"] == [
        "locomo",
        "longmemeval",
    ]
    assert policy["public_benchmark"]["competitive_floors"]["locomo"] == {
        "min_accuracy": 0.947,
        "min_case_count": 600,
    }


def test_memory_quality_scorecard_loads_existing_suite_reports(tmp_path: Path) -> None:
    suite_report_paths = []
    for suite, payload in _scorecard_fixture_results().items():
        path = tmp_path / f"{suite}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        suite_report_paths.append(path)

    result = run_memory_quality_scorecard(suite_report_paths=tuple(suite_report_paths))

    assert result["ok"] is True
    assert result["score"]["maturity_score_10"] == 10.0
    assert result["suites"]["auto-memory-golden"]["case_count"] == 13
    assert result["suites"]["prompt-contract"]["ok"] is True


def test_memory_quality_scorecard_reports_external_evidence_tier() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()

    result = build_memory_quality_scorecard(suite_results)

    assert result["ok"] is True
    evidence = result["external_evidence"]
    assert evidence["confidence_tier"] == "full_provider_and_agent_behavior_evaluated"
    assert evidence["top_library_comparison_ready"] is False
    assert evidence["evidence_gaps"] == [
        "multimodal_live_provider_canary_missing",
        "agent_live_smoke_missing",
        "public_benchmark_evidence_missing",
    ]
    assert evidence["full_provider_canary"]["ok"] is True
    assert evidence["full_provider_canary"]["adapters"]["graphiti"] == "ok"
    assert evidence["full_provider_canary"]["failed_required_checks"] == []
    assert evidence["agent_behavior_benchmark"]["ok"] is True
    assert evidence["agent_behavior_benchmark"]["quality_floor_ok"] is True
    assert evidence["agent_behavior_benchmark"]["failed_required_checks"] == []
    assert evidence["agent_behavior_benchmark"]["metrics"]["tool_choice_accuracy"] == 1.0
    assert evidence["agent_behavior_benchmark"]["scenario_evidence"] == {
        "present": True,
        "scenario_count": len(AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS),
        "tag_counts": {
            "live_session": 11,
            "transcript_corpus": 5,
            "adversarial": 9,
        },
        "invalid_entry_count": 0,
        "missing_id_count": 0,
        "duplicate_id_count": 0,
        "non_passed_count": 0,
        "missing_canonical_id_count": 0,
        "missing_canonical_ids": [],
    }
    assert evidence["public_benchmark"]["present"] is False


def test_memory_quality_scorecard_requires_live_agent_smoke_for_top_ready() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["infinity-context-multimodal-live-provider-canary"] = (
        _multimodal_live_provider_canary_report()
    )
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results)

    evidence = result["external_evidence"]
    assert evidence["top_library_comparison_ready"] is False
    assert evidence["agent_live_smoke"]["present"] is False
    assert evidence["evidence_gaps"] == ["agent_live_smoke_missing"]


def test_memory_quality_scorecard_reports_degraded_multimodal_live_provider() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["infinity-context-multimodal-live-provider-canary"] = (
        _degraded_multimodal_live_provider_canary_report()
    )
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    suite_results["infinity-context-agent-live-smoke"] = _agent_live_smoke_report()
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    provider = evidence["multimodal_live_provider"]
    assert result["ok"] is False
    assert provider["present"] is True
    assert provider["ok"] is False
    assert provider["provider_key_present"] is False
    assert provider["requirement_reasons"]["vision_real_provider"] == (
        "provider_credential_missing"
    )
    assert "provider_key_present" in provider["failed_required_checks"]
    assert "vision_real_provider_ok" in provider["failed_required_checks"]
    assert "multimodal_live_provider_canary_failed" in evidence["evidence_gaps"]
    assert "multimodal_live_provider_key_missing" in evidence["evidence_gaps"]


def test_memory_quality_scorecard_rejects_weak_live_agent_smoke_evidence() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["infinity-context-multimodal-live-provider-canary"] = (
        _multimodal_live_provider_canary_report()
    )
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    suite_results["infinity-context-agent-live-smoke"] = _agent_live_smoke_report()
    suite_results["public-memory-benchmark"] = _public_benchmark_report()
    live_smoke = suite_results["infinity-context-agent-live-smoke"]
    live_smoke["strict_agent_cli"] = False
    live_smoke["checks"]["agent_cli"]["gemini"] = {
        "status": "blocked",
        "reason": "gemini auth unavailable",
    }

    result = build_memory_quality_scorecard(suite_results)

    evidence = result["external_evidence"]
    assert evidence["top_library_comparison_ready"] is False
    assert evidence["agent_live_smoke"]["ok"] is False
    assert evidence["agent_live_smoke"]["failed_required_checks"] == [
        "agent_cli_gemini_ok",
        "strict_agent_cli_enabled",
    ]
    assert "agent_live_smoke_failed" in evidence["evidence_gaps"]
    assert "agent_live_smoke_quality_floor_failed" in evidence["evidence_gaps"]


def test_memory_quality_scorecard_reports_top_library_ready_with_public_benchmarks() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["infinity-context-multimodal-live-provider-canary"] = (
        _multimodal_live_provider_canary_report()
    )
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    suite_results["infinity-context-agent-live-smoke"] = _agent_live_smoke_report()
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results)

    evidence = result["external_evidence"]
    assert result["ok"] is True
    assert evidence["confidence_tier"] == (
        "full_provider_and_multimodal_live_provider_and_agent_behavior_and_agent_live_smoke_and_public_benchmark_evaluated"
    )
    assert evidence["top_library_comparison_ready"] is True
    assert evidence["evidence_gaps"] == []
    assert evidence["agent_live_smoke"]["ok"] is True
    assert evidence["agent_live_smoke"]["agent_cli"]["claude"] == "ok"
    assert evidence["public_benchmark"]["ok"] is True
    assert evidence["public_benchmark"]["competitive_floor_ok"] is True
    assert evidence["public_benchmark"]["benchmarks"]["locomo"]["accuracy"] == 0.947
    assert evidence["public_benchmark"]["benchmarks"]["longmemeval"]["case_count"] == 500


def test_memory_quality_scorecard_accepts_split_public_benchmark_reports() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["infinity-context-multimodal-live-provider-canary"] = (
        _multimodal_live_provider_canary_report()
    )
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    suite_results["infinity-context-agent-live-smoke"] = _agent_live_smoke_report()
    suite_results["locomo"] = {
        "suite": "locomo",
        "ok": True,
        "dataset_hash": "locomo-dataset-sha256",
        "dataset_sources": {
            "locomo": {
                "source_kind": "local_dataset",
                "path_label": "locomo.json",
                "sha256": "locomo-dataset-sha256",
                "size_bytes": 1000,
                "case_count": 600,
            }
        },
        "provenance": _scorecard_provenance(
            generated_by="infinity_context_server.public_benchmark",
            suite="locomo",
        ),
        "metrics": {"accuracy": 0.947, "case_count": 600},
    }
    suite_results["longmemeval"] = {
        "suite": "longmemeval",
        "ok": True,
        "dataset_hash": "longmemeval-dataset-sha256",
        "dataset_sources": {
            "longmemeval": {
                "source_kind": "local_dataset",
                "path_label": "longmemeval.json",
                "sha256": "longmemeval-dataset-sha256",
                "size_bytes": 1000,
                "case_count": 500,
            }
        },
        "provenance": _scorecard_provenance(
            generated_by="infinity_context_server.public_benchmark",
            suite="longmemeval",
        ),
        "metrics": {"accuracy": 0.902, "case_count": 500},
    }

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    assert result["ok"] is True
    public_benchmark = result["external_evidence"]["public_benchmark"]
    assert public_benchmark["ok"] is True
    assert public_benchmark["benchmark_count"] == 2
    assert public_benchmark["competitive_floor_ok"] is True
    assert public_benchmark["dataset_evidence_ok"] is True
    assert public_benchmark["benchmarks"]["locomo"]["case_count"] == 600
    assert public_benchmark["benchmarks"]["longmemeval"]["accuracy"] == 0.902


def test_memory_quality_scorecard_requires_public_benchmark_dataset_fingerprint() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    public_benchmark = _public_benchmark_report()
    public_benchmark.pop("dataset_hashes")
    suite_results["public-memory-benchmark"] = public_benchmark

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["top_library_comparison_ready"] is False
    assert evidence["public_benchmark"]["quality_ok"] is True
    assert evidence["public_benchmark"]["dataset_evidence_ok"] is False
    assert evidence["public_benchmark"]["dataset_evidence"]["missing_reports"] == [
        "public-memory-benchmark"
    ]
    assert "public_benchmark_dataset_evidence_failed" in evidence["evidence_gaps"]


def test_memory_quality_scorecard_requires_public_benchmark_dataset_source() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    public_benchmark = _public_benchmark_report()
    public_benchmark.pop("dataset_sources")
    suite_results["public-memory-benchmark"] = public_benchmark

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["top_library_comparison_ready"] is False
    assert evidence["public_benchmark"]["quality_ok"] is True
    assert evidence["public_benchmark"]["dataset_evidence_ok"] is False
    assert evidence["public_benchmark"]["dataset_evidence"]["reports"][0][
        "missing_dataset_sources"
    ] == ["locomo", "longmemeval"]
    assert "public_benchmark_dataset_evidence_failed" in evidence["evidence_gaps"]


def test_memory_quality_scorecard_rejects_public_benchmark_source_hash_mismatch() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    public_benchmark = _public_benchmark_report()
    public_benchmark["dataset_sources"]["locomo"]["sha256"] = "different-sha256"
    suite_results["public-memory-benchmark"] = public_benchmark

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["public_benchmark"]["dataset_evidence_ok"] is False
    assert evidence["public_benchmark"]["dataset_evidence"]["reports"][0][
        "missing_dataset_sources"
    ] == ["locomo"]
    assert evidence["public_benchmark"]["dataset_evidence"]["reports"][0][
        "dataset_source_failures"
    ] == {"locomo": ["sha256_mismatch"]}
    assert "public_benchmark_dataset_evidence_failed" in evidence["evidence_gaps"]


def test_memory_quality_scorecard_rejects_invalid_public_benchmark_source_metadata() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    public_benchmark = _public_benchmark_report()
    public_benchmark["dataset_sources"]["locomo"].pop("official_url")
    public_benchmark["dataset_sources"]["locomo"].pop("path_label")
    public_benchmark["dataset_sources"]["locomo"]["source_kind"] = "unknown_source"
    suite_results["public-memory-benchmark"] = public_benchmark

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["public_benchmark"]["dataset_evidence_ok"] is False
    assert evidence["public_benchmark"]["dataset_evidence"]["reports"][0][
        "dataset_source_failures"
    ] == {"locomo": ["source_kind_not_allowed", "path_label_missing"]}
    assert "public_benchmark_dataset_evidence_failed" in evidence["evidence_gaps"]


def test_memory_quality_scorecard_requires_official_url_for_official_sources() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    public_benchmark = _public_benchmark_report()
    public_benchmark["dataset_sources"]["locomo"].pop("official_url")
    suite_results["public-memory-benchmark"] = public_benchmark

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["public_benchmark"]["dataset_evidence_ok"] is False
    assert evidence["public_benchmark"]["dataset_evidence"]["reports"][0][
        "dataset_source_failures"
    ] == {"locomo": ["official_url_missing"]}
    assert "public_benchmark_dataset_evidence_failed" in evidence["evidence_gaps"]


def test_memory_quality_scorecard_rejects_public_benchmark_source_case_count_mismatch() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    public_benchmark = _public_benchmark_report()
    public_benchmark["dataset_sources"]["locomo"]["case_count"] = 599
    suite_results["public-memory-benchmark"] = public_benchmark

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["public_benchmark"]["dataset_evidence_ok"] is False
    assert evidence["public_benchmark"]["dataset_evidence"]["reports"][0][
        "dataset_source_failures"
    ] == {"locomo": ["case_count_mismatch"]}
    assert "public_benchmark_dataset_evidence_failed" in evidence["evidence_gaps"]


def test_memory_quality_scorecard_requires_public_benchmark_source_case_count() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    public_benchmark = _public_benchmark_report()
    public_benchmark["dataset_sources"]["locomo"].pop("case_count")
    suite_results["public-memory-benchmark"] = public_benchmark

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["public_benchmark"]["dataset_evidence_ok"] is False
    assert evidence["public_benchmark"]["dataset_evidence"]["reports"][0][
        "dataset_source_failures"
    ] == {"locomo": ["case_count_missing"]}
    assert "public_benchmark_dataset_evidence_failed" in evidence["evidence_gaps"]


def test_memory_quality_scorecard_rejects_public_benchmark_raw_dataset_path() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    public_benchmark = _public_benchmark_report()
    public_benchmark["dataset_path"] = "/Users/alice/private/locomo.json"
    suite_results["public-memory-benchmark"] = public_benchmark

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["public_benchmark"]["dataset_evidence_ok"] is False
    assert evidence["public_benchmark"]["dataset_evidence"]["reports"][0]["report_failures"] == [
        "dataset_path_not_redacted"
    ]
    assert "public_benchmark_dataset_evidence_failed" in evidence["evidence_gaps"]


def test_memory_quality_scorecard_rejects_underpowered_public_benchmark_evidence() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    suite_results["public-memory-benchmark"] = {
        "suite": "public-memory-benchmark",
        "ok": True,
        "benchmarks": [
            {
                "name": "locomo",
                "ok": True,
                "metrics": {"accuracy": 0.94, "case_count": 600},
            },
            {
                "name": "longmemeval",
                "ok": True,
                "metrics": {"accuracy": 0.902, "case_count": 1},
            },
        ],
    }

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert result["gates"]["top_library_external_evidence"] is False
    assert evidence["top_library_comparison_ready"] is False
    assert evidence["public_benchmark"]["ok"] is False
    assert evidence["public_benchmark"]["competitive_floor_ok"] is False
    assert evidence["public_benchmark"]["competitive_floor"]["failed_benchmarks"] == [
        "locomo",
        "longmemeval",
    ]
    assert "public_benchmark_competitive_floor_failed" in evidence["evidence_gaps"]


def test_memory_quality_scorecard_rejects_shallow_full_provider_evidence() -> None:
    suite_results = _scorecard_fixture_results()
    full_provider = _full_provider_canary_report()
    full_provider["checks"]["mcp_search_has_graphiti_fact_after_worker"] = False
    suite_results["infinity-context-full-provider-canary"] = full_provider
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["top_library_comparison_ready"] is False
    assert evidence["full_provider_canary"]["ok"] is False
    assert "full_provider_canary_failed" in evidence["evidence_gaps"]
    assert evidence["full_provider_canary"]["failed_required_checks"] == [
        "mcp_search_has_graphiti_fact_after_worker"
    ]


def test_memory_quality_scorecard_requires_full_provider_mcp_lifecycle() -> None:
    suite_results = _scorecard_fixture_results()
    full_provider = _full_provider_canary_report()
    full_provider["mcp"] = {"skipped": True, "reason": "manual skip"}
    suite_results["infinity-context-full-provider-canary"] = full_provider
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["full_provider_canary"]["required_checks"]["mcp_lifecycle_included"] is False
    assert evidence["full_provider_canary"]["failed_required_checks"] == ["mcp_lifecycle_included"]


def test_memory_quality_scorecard_rejects_weak_agent_behavior_evidence() -> None:
    suite_results = _scorecard_fixture_results()
    agent_behavior = _agent_behavior_benchmark_report()
    agent_behavior["metrics"]["answer_support_rate"] = 0.75
    agent_behavior["metrics"]["secret_leak_count"] = 1
    agent_behavior["gates"]["answer_support_rate_min_0_80"] = False
    agent_behavior["gates"]["secret_leak_count_zero"] = False
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = agent_behavior
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["top_library_comparison_ready"] is False
    assert evidence["agent_behavior_benchmark"]["ok"] is False
    assert evidence["agent_behavior_benchmark"]["quality_floor_ok"] is False
    assert "agent_behavior_benchmark_failed" in evidence["evidence_gaps"]
    assert "agent_behavior_quality_floor_failed" in evidence["evidence_gaps"]
    assert evidence["agent_behavior_benchmark"]["failed_required_checks"] == [
        "all_reported_gates_pass",
        "answer_support_rate_min",
        "secret_leak_count_zero",
    ]


def test_memory_quality_scorecard_requires_non_core_agent_scenario_set() -> None:
    suite_results = _scorecard_fixture_results()
    agent_behavior = _agent_behavior_benchmark_report()
    agent_behavior["scenario_set"] = "core"
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = agent_behavior
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["agent_behavior_benchmark"]["failed_required_checks"] == [
        "scenario_set_all_for_top_evidence",
        "scenario_set_realistic_or_better",
    ]


def test_memory_quality_scorecard_requires_all_agent_scenarios_for_top_evidence() -> None:
    suite_results = _scorecard_fixture_results()
    agent_behavior = _agent_behavior_benchmark_report()
    agent_behavior["scenario_set"] = "realistic"
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = agent_behavior
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["agent_behavior_benchmark"]["failed_required_checks"] == [
        "scenario_set_all_for_top_evidence"
    ]


def test_memory_quality_scorecard_requires_nonzero_agent_case_counts_for_top_evidence() -> None:
    suite_results = _scorecard_fixture_results()
    agent_behavior = _agent_behavior_benchmark_report()
    weak_scenario_count = len(AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS) - 2
    agent_behavior["metrics"]["scenario_count"] = weak_scenario_count
    agent_behavior["metrics"]["live_session_case_count"] = 10
    agent_behavior["metrics"]["transcript_corpus_case_count"] = 4
    agent_behavior["metrics"]["adversarial_case_count"] = 8
    agent_behavior["scenarios"] = _agent_behavior_scenario_reports(
        scenario_count=weak_scenario_count,
        live_session_count=10,
        transcript_corpus_count=4,
        adversarial_count=8,
    )
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = agent_behavior
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["agent_behavior_benchmark"]["failed_required_checks"] == [
        "adversarial_case_count_min_9",
        "canonical_scenario_ids_present",
        "live_session_case_count_min_11",
        f"scenario_count_min_{len(AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS)}",
        f"scenario_report_count_min_{len(AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS)}",
        "transcript_corpus_case_count_min_5",
    ]


def test_memory_quality_scorecard_requires_agent_scenario_reports_for_top_evidence() -> None:
    suite_results = _scorecard_fixture_results()
    agent_behavior = _agent_behavior_benchmark_report()
    agent_behavior["scenarios"] = []
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = agent_behavior
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["agent_behavior_benchmark"]["scenario_evidence"] == {
        "present": True,
        "scenario_count": 0,
        "tag_counts": {
            "live_session": 0,
            "transcript_corpus": 0,
            "adversarial": 0,
        },
        "invalid_entry_count": 0,
        "missing_id_count": 0,
        "duplicate_id_count": 0,
        "non_passed_count": 0,
        "missing_canonical_id_count": len(AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS),
        "missing_canonical_ids": sorted(AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS),
    }
    assert evidence["agent_behavior_benchmark"]["failed_required_checks"] == [
        "adversarial_scenario_report_count_matches_metric",
        "canonical_scenario_ids_present",
        "live_session_scenario_report_count_matches_metric",
        "scenario_report_count_matches_metric",
        f"scenario_report_count_min_{len(AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS)}",
        "transcript_corpus_scenario_report_count_matches_metric",
    ]


def test_memory_quality_scorecard_requires_canonical_agent_scenario_ids() -> None:
    suite_results = _scorecard_fixture_results()
    agent_behavior = _agent_behavior_benchmark_report()
    scenarios = []
    for index, scenario in enumerate(agent_behavior["scenarios"]):
        scenarios.append({**scenario, "id": f"synthetic-agent-scenario-{index}"})
    agent_behavior["scenarios"] = scenarios
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = agent_behavior
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["agent_behavior_benchmark"]["scenario_evidence"][
        "missing_canonical_id_count"
    ] == len(AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS)
    assert evidence["agent_behavior_benchmark"]["failed_required_checks"] == [
        "canonical_scenario_ids_present"
    ]


def test_memory_quality_scorecard_rejects_malformed_agent_scenario_reports() -> None:
    suite_results = _scorecard_fixture_results()
    agent_behavior = _agent_behavior_benchmark_report()
    scenarios = list(agent_behavior["scenarios"])
    scenarios[0] = {**scenarios[0], "status": "failed"}
    scenarios[1] = {**scenarios[1], "id": scenarios[0]["id"]}
    scenarios[2] = {key: value for key, value in scenarios[2].items() if key != "id"}
    scenarios[-1] = "invalid-scenario"
    agent_behavior["scenarios"] = scenarios
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["memory_mcp_agent_behavior"] = agent_behavior
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert evidence["agent_behavior_benchmark"]["scenario_evidence"] == {
        "present": True,
        "scenario_count": len(AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS),
        "tag_counts": {
            "live_session": 11,
            "transcript_corpus": 5,
            "adversarial": 9,
        },
        "invalid_entry_count": 1,
        "missing_id_count": 1,
        "duplicate_id_count": 1,
        "non_passed_count": 1,
        "missing_canonical_id_count": 3,
        "missing_canonical_ids": sorted(
            (
                AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS[1],
                AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS[2],
                AGENT_BEHAVIOR_TOP_EVIDENCE_SCENARIO_IDS[-1],
            )
        ),
    }
    assert evidence["agent_behavior_benchmark"]["failed_required_checks"] == [
        "canonical_scenario_ids_present",
        "scenario_report_ids_present",
        "scenario_report_ids_unique",
        "scenario_reports_all_passed",
        "scenario_reports_well_formed",
    ]


def test_memory_quality_scorecard_can_use_nested_agent_evidence() -> None:
    suite_results = _scorecard_fixture_results()
    full_provider = _full_provider_canary_report()
    agent_behavior = _agent_behavior_benchmark_report()
    agent_behavior["scenario_set"] = "realistic"
    full_provider["agent_behavior"] = agent_behavior
    suite_results["infinity-context-full-provider-canary"] = full_provider

    result = build_memory_quality_scorecard(suite_results)

    assert result["external_evidence"]["confidence_tier"] == (
        "full_provider_and_agent_behavior_evaluated"
    )
    assert result["external_evidence"]["agent_behavior_benchmark"]["scenario_set"] == "realistic"


def test_memory_quality_scorecard_can_use_nested_public_benchmark_evidence() -> None:
    suite_results = _scorecard_fixture_results()
    full_provider = _full_provider_canary_report()
    full_provider["public_benchmark"] = _public_benchmark_report()
    suite_results["infinity-context-full-provider-canary"] = full_provider
    suite_results["infinity-context-multimodal-live-provider-canary"] = (
        _multimodal_live_provider_canary_report()
    )
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    suite_results["infinity-context-agent-live-smoke"] = _agent_live_smoke_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is True
    assert result["gates"]["top_library_external_evidence"] is True
    assert evidence["confidence_tier"] == (
        "full_provider_and_multimodal_live_provider_and_agent_behavior_and_agent_live_smoke_and_public_benchmark_evaluated"
    )
    assert evidence["top_library_comparison_ready"] is True
    assert evidence["evidence_gaps"] == []
    assert evidence["public_benchmark"]["benchmark_count"] == 2
    assert evidence["public_benchmark"]["competitive_floor_ok"] is True
    assert evidence["public_benchmark"]["benchmarks"]["locomo"]["accuracy"] == 0.947
    assert evidence["public_benchmark"]["benchmarks"]["longmemeval"]["accuracy"] == 0.902


def test_memory_quality_scorecard_warns_on_failed_external_evidence() -> None:
    suite_results = _scorecard_fixture_results()
    full_provider = _full_provider_canary_report()
    full_provider["checks"]["providers_are_healthy"] = False
    suite_results["infinity-context-full-provider-canary"] = full_provider

    result = build_memory_quality_scorecard(suite_results)

    assert result["ok"] is True
    assert result["external_evidence"]["confidence_tier"] == "internal_deterministic"
    assert result["external_evidence"]["top_library_comparison_ready"] is False
    assert "full_provider_canary_failed" in result["external_evidence"]["evidence_gaps"]


def test_memory_quality_scorecard_strict_top_evidence_fails_without_external_reports() -> None:
    result = build_memory_quality_scorecard(
        _scorecard_fixture_results(),
        require_top_evidence=True,
    )

    assert result["ok"] is False
    assert result["gates"]["top_library_external_evidence"] is False
    assert result["external_evidence"]["required_for_gate"] is True
    assert result["external_evidence"]["confidence_tier"] == "internal_deterministic"
    assert any(
        failure["case_id"] == "top_library_external_evidence" for failure in result["failures"]
    )


def test_memory_quality_scorecard_strict_top_evidence_requires_provenance() -> None:
    suite_results = _scorecard_fixture_results()
    agent_behavior = _agent_behavior_benchmark_report()
    agent_behavior.pop("provenance")
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["infinity-context-multimodal-live-provider-canary"] = (
        _multimodal_live_provider_canary_report()
    )
    suite_results["memory_mcp_agent_behavior"] = agent_behavior
    suite_results["infinity-context-agent-live-smoke"] = _agent_live_smoke_report()
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    evidence = result["external_evidence"]
    assert result["ok"] is False
    assert result["gates"]["top_library_external_evidence"] is False
    assert evidence["top_library_comparison_ready"] is False
    assert evidence["agent_behavior_benchmark"]["quality_ok"] is True
    assert evidence["agent_behavior_benchmark"]["provenance_ok"] is False
    assert evidence["agent_behavior_benchmark"]["provenance"]["failed_checks"] == [
        "provenance_dirty_state_present",
        "provenance_generator_allowed",
        "provenance_git_clean_or_dirty_allowed",
        "provenance_git_commit_present",
        "provenance_present",
        "provenance_runtime_platform_present",
        "provenance_runtime_python_version_present",
        "provenance_schema_version_1",
        "provenance_suite_allowed",
    ]
    assert "agent_behavior_benchmark_provenance_failed" in evidence["evidence_gaps"]


def test_memory_quality_scorecard_strict_top_evidence_requires_all_report_provenance() -> None:
    for target, summary_key, failed_gap in (
        (
            "infinity-context-full-provider-canary",
            "full_provider_canary",
            "full_provider_canary_provenance_failed",
        ),
        (
            "infinity-context-multimodal-live-provider-canary",
            "multimodal_live_provider",
            "multimodal_live_provider_canary_provenance_failed",
        ),
        (
            "infinity-context-agent-live-smoke",
            "agent_live_smoke",
            "agent_live_smoke_provenance_failed",
        ),
        (
            "public-memory-benchmark",
            "public_benchmark",
            "public_benchmark_provenance_failed",
        ),
    ):
        suite_results = _scorecard_fixture_results()
        suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
        suite_results["infinity-context-multimodal-live-provider-canary"] = (
            _multimodal_live_provider_canary_report()
        )
        suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
        suite_results["infinity-context-agent-live-smoke"] = _agent_live_smoke_report()
        suite_results["public-memory-benchmark"] = _public_benchmark_report()
        suite_results[target].pop("provenance")

        result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

        evidence = result["external_evidence"]
        assert result["ok"] is False
        assert evidence["top_library_comparison_ready"] is False
        assert evidence[summary_key]["quality_ok"] is True
        assert evidence[summary_key]["provenance_ok"] is False
        assert failed_gap in evidence["evidence_gaps"]


def test_memory_quality_scorecard_strict_top_evidence_rejects_sensitive_reports() -> None:
    for target, summary_key, failed_gap in (
        (
            "infinity-context-full-provider-canary",
            "full_provider_canary",
            "full_provider_canary_safety_failed",
        ),
        (
            "infinity-context-multimodal-live-provider-canary",
            "multimodal_live_provider",
            "multimodal_live_provider_canary_safety_failed",
        ),
        (
            "memory_mcp_agent_behavior",
            "agent_behavior_benchmark",
            "agent_behavior_benchmark_safety_failed",
        ),
        (
            "infinity-context-agent-live-smoke",
            "agent_live_smoke",
            "agent_live_smoke_safety_failed",
        ),
        (
            "public-memory-benchmark",
            "public_benchmark",
            "public_benchmark_safety_failed",
        ),
    ):
        suite_results = _scorecard_fixture_results()
        suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
        suite_results["infinity-context-multimodal-live-provider-canary"] = (
            _multimodal_live_provider_canary_report()
        )
        suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
        suite_results["infinity-context-agent-live-smoke"] = _agent_live_smoke_report()
        suite_results["public-memory-benchmark"] = _public_benchmark_report()
        suite_results[target]["debug"] = {"unsafe_note": "REPORT_TOKEN=abcdefghijklmnopqrstuvwxyz"}

        result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

        evidence = result["external_evidence"]
        assert result["ok"] is False
        assert evidence["top_library_comparison_ready"] is False
        assert evidence[summary_key]["quality_ok"] is True
        assert evidence[summary_key]["safety_ok"] is False
        assert evidence[summary_key]["safety"]["failed_checks"] == ["no_sensitive_text"]
        assert evidence[summary_key]["safety"]["sensitive_path_count"] == 1
        assert failed_gap in evidence["evidence_gaps"]


def test_memory_quality_scorecard_strict_top_evidence_rejects_local_home_paths() -> None:
    for target, summary_key, failed_gap in (
        (
            "infinity-context-full-provider-canary",
            "full_provider_canary",
            "full_provider_canary_safety_failed",
        ),
        (
            "infinity-context-multimodal-live-provider-canary",
            "multimodal_live_provider",
            "multimodal_live_provider_canary_safety_failed",
        ),
        (
            "memory_mcp_agent_behavior",
            "agent_behavior_benchmark",
            "agent_behavior_benchmark_safety_failed",
        ),
        (
            "infinity-context-agent-live-smoke",
            "agent_live_smoke",
            "agent_live_smoke_safety_failed",
        ),
        (
            "public-memory-benchmark",
            "public_benchmark",
            "public_benchmark_safety_failed",
        ),
    ):
        suite_results = _scorecard_fixture_results()
        suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
        suite_results["infinity-context-multimodal-live-provider-canary"] = (
            _multimodal_live_provider_canary_report()
        )
        suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
        suite_results["infinity-context-agent-live-smoke"] = _agent_live_smoke_report()
        suite_results["public-memory-benchmark"] = _public_benchmark_report()
        suite_results[target]["debug"] = {"local_path": "/Users/alice/private/report.json"}

        result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

        evidence = result["external_evidence"]
        assert result["ok"] is False
        assert evidence["top_library_comparison_ready"] is False
        assert evidence[summary_key]["quality_ok"] is True
        assert evidence[summary_key]["safety_ok"] is False
        assert evidence[summary_key]["safety"]["failed_checks"] == ["no_local_home_paths"]
        assert evidence[summary_key]["safety"]["local_path_count"] == 1
        assert evidence[summary_key]["safety"]["local_paths"] == ["$.debug.local_path"]
        assert "/Users/alice" not in repr(evidence[summary_key]["safety"])
        assert failed_gap in evidence["evidence_gaps"]


def test_memory_quality_scorecard_strict_top_evidence_passes_with_reports() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["infinity-context-full-provider-canary"] = _full_provider_canary_report()
    suite_results["infinity-context-multimodal-live-provider-canary"] = (
        _multimodal_live_provider_canary_report()
    )
    suite_results["memory_mcp_agent_behavior"] = _agent_behavior_benchmark_report()
    suite_results["infinity-context-agent-live-smoke"] = _agent_live_smoke_report()
    suite_results["public-memory-benchmark"] = _public_benchmark_report()

    result = build_memory_quality_scorecard(suite_results, require_top_evidence=True)

    assert result["ok"] is True
    assert result["gates"]["top_library_external_evidence"] is True
    assert result["external_evidence"]["required_for_gate"] is True
    assert result["external_evidence"]["full_provider_canary"]["provenance_ok"] is True
    assert result["external_evidence"]["full_provider_canary"]["safety_ok"] is True
    assert result["external_evidence"]["multimodal_live_provider"]["provenance_ok"] is True
    assert result["external_evidence"]["multimodal_live_provider"]["safety_ok"] is True
    assert result["external_evidence"]["agent_behavior_benchmark"]["provenance_ok"] is True
    assert result["external_evidence"]["agent_behavior_benchmark"]["safety_ok"] is True
    assert result["external_evidence"]["agent_live_smoke"]["provenance_ok"] is True
    assert result["external_evidence"]["agent_live_smoke"]["safety_ok"] is True
    assert result["external_evidence"]["public_benchmark"]["provenance_ok"] is True
    assert result["external_evidence"]["public_benchmark"]["safety_ok"] is True
    assert result["external_evidence"]["public_benchmark"]["dataset_evidence_ok"] is True
    assert result["external_evidence"]["confidence_tier"] == (
        "full_provider_and_multimodal_live_provider_and_agent_behavior_and_agent_live_smoke_and_public_benchmark_evaluated"
    )


def test_memory_quality_scorecard_fails_on_undercovered_suite() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["auto-memory-golden"]["metrics"]["extraction_case_count"] = 12

    result = build_memory_quality_scorecard(suite_results)

    assert result["ok"] is False
    assert result["capabilities"]["coverage_floors"]["ok"] is False
    assert (
        "auto_memory_extraction_case_count"
        in result["capabilities"]["coverage_floors"]["failed_checks"]
    )
    assert result["gates"]["all_capabilities_ok"] is False


def test_memory_quality_scorecard_fails_on_semantic_linking_regression() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["semantic-linking-golden"]["metrics"].update(
        {
            "ranking_accuracy": 0.0,
            "event_linking_accuracy": 0.0,
            "temporal_intent_recall": 0.0,
            "document_chunk_linking_accuracy": 0.0,
            "anchor_recall_rate": 0.5,
            "anchor_disambiguation_rate": 0.0,
            "mixed_script_event_anchor_rate": 0.0,
            "anchor_review_evidence_rate": 0.0,
            "high_impact_relation_policy_safety": 0.0,
            "evidence_relation_policy_safety": 0.0,
            "mentions_relation_policy_safety": 0.0,
            "review_approval_rate": 0.0,
            "false_positive_count": 1,
            "cross_scope_leak_count": 1,
        }
    )

    result = build_memory_quality_scorecard(suite_results)

    assert result["ok"] is False
    assert result["capabilities"]["semantic_linking"]["ok"] is False
    assert result["capabilities"]["semantic_linking"]["failed_checks"] == [
        "anchor_disambiguation_rate",
        "anchor_recall_rate",
        "anchor_review_evidence_rate",
        "cross_scope_leak_count",
        "document_chunk_linking_accuracy",
        "event_linking_accuracy",
        "evidence_relation_policy_safety",
        "false_positive_count",
        "high_impact_relation_policy_safety",
        "mentions_relation_policy_safety",
        "mixed_script_event_anchor_rate",
        "ranking_accuracy",
        "review_approval_rate",
        "temporal_intent_recall",
    ]
    assert result["metrics"]["semantic_linking_ranking_accuracy"] == 0.0
    assert result["metrics"]["semantic_linking_event_linking_accuracy"] == 0.0
    assert result["metrics"]["semantic_linking_temporal_intent_recall"] == 0.0
    assert result["metrics"]["semantic_linking_document_chunk_linking_accuracy"] == 0.0
    assert result["metrics"]["semantic_linking_anchor_disambiguation_rate"] == 0.0
    assert result["metrics"]["semantic_linking_mixed_script_event_anchor_rate"] == 0.0
    assert result["metrics"]["semantic_linking_anchor_review_evidence_rate"] == 0.0
    assert result["metrics"]["semantic_linking_high_impact_relation_policy_safety"] == 0.0
    assert result["metrics"]["semantic_linking_evidence_relation_policy_safety"] == 0.0
    assert result["metrics"]["semantic_linking_mentions_relation_policy_safety"] == 0.0
    assert result["metrics"]["semantic_linking_false_positive_count"] == 1
    assert result["metrics"]["semantic_linking_cross_scope_leak_count"] == 1
    assert result["gates"]["all_capabilities_ok"] is False


def test_memory_quality_scorecard_fails_on_missing_semantic_linking_safety_check() -> None:
    suite_results = _scorecard_fixture_results()
    del suite_results["semantic-linking-golden"]["checks"][
        "unrelated_capture_has_no_candidates"
    ]

    result = build_memory_quality_scorecard(suite_results)

    assert result["ok"] is False
    assert result["capabilities"]["semantic_linking"]["ok"] is False
    assert (
        "semantic_check_unrelated_capture_has_no_candidates"
        in result["capabilities"]["semantic_linking"]["failed_checks"]
    )
    assert result["metrics"]["semantic_linking_false_positive_count"] == 0


def test_memory_quality_scorecard_fails_on_dedup_merge_conflict_regression() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["quality-golden"]["cases"] = [
        case
        for case in suite_results["quality-golden"]["cases"]
        if case["case_id"] != "pending_duplicate_merge_review_visible"
    ]
    suite_results["auto-memory-golden"]["cases"] = [
        case
        for case in suite_results["auto-memory-golden"]["cases"]
        if case["case_id"] != "approved_fact_creates_duplicate_merge_review"
    ]
    suite_results["auto-memory-golden"]["metrics"].update(
        {
            "duplicate_suggestion_count": 1,
            "replay_duplicate_suggestion_count": 1,
            "target_resolution_violation_count": 1,
            "review_operation_violation_count": 1,
        }
    )
    suite_results["semantic-linking-golden"]["checks"][
        "weak_overlap_below_review_threshold_denied"
    ] = False

    result = build_memory_quality_scorecard(suite_results)

    assert result["ok"] is False
    capability = result["capabilities"]["dedup_merge_conflict_resolution"]
    assert capability["ok"] is False
    assert capability["failed_checks"] == [
        "auto_memory_case_approved_fact_creates_duplicate_merge_review",
        "auto_memory_duplicate_suggestion_count",
        "auto_memory_replay_duplicate_suggestion_count",
        "auto_memory_review_operation_violation_count",
        "auto_memory_target_resolution_violation_count",
        "quality_case_pending_duplicate_merge_review_visible",
        "semantic_check_weak_overlap_below_review_threshold_denied",
    ]
    assert result["metrics"]["auto_duplicate_suggestion_count"] == 1
    assert result["metrics"]["auto_replay_duplicate_suggestion_count"] == 1
    assert result["gates"]["all_capabilities_ok"] is False


def test_memory_quality_scorecard_fails_on_multimodal_metadata_regression() -> None:
    suite_results = _scorecard_fixture_results()
    multimodal = suite_results[MULTIMODAL_OFFLINE_GOLDEN_SUITE]
    multimodal["checks"]["evidence_metadata_exposed"] = False
    multimodal["gates"]["evidence_metadata_exposed"] = False

    result = build_memory_quality_scorecard(suite_results)

    assert result["ok"] is False
    capability = result["capabilities"]["multimodal_evidence_retrieval"]
    assert capability["ok"] is False
    assert "check_evidence_metadata_exposed" in capability["failed_checks"]
    assert "gate_evidence_metadata_exposed" in capability["failed_checks"]
    assert result["gates"]["all_capabilities_ok"] is False


def test_memory_quality_scorecard_fails_on_multimodal_retrieval_profile_regression() -> None:
    suite_results = _scorecard_fixture_results()
    multimodal = suite_results[MULTIMODAL_OFFLINE_GOLDEN_SUITE]
    multimodal["checks"]["retrieval_evidence_coverage_profile"] = False
    multimodal["gates"]["retrieval_evidence_coverage_profile"] = False
    multimodal["metrics"]["retrieval_evidence_location_coverage_rate"] = 0.5
    multimodal["metrics"]["retrieval_evidence_location_gap_count"] = 2

    result = build_memory_quality_scorecard(suite_results)

    assert result["ok"] is False
    capability = result["capabilities"]["multimodal_evidence_retrieval"]
    assert capability["ok"] is False
    assert "check_retrieval_evidence_coverage_profile" in capability["failed_checks"]
    assert "gate_retrieval_evidence_coverage_profile" in capability["failed_checks"]
    assert "retrieval_evidence_location_coverage_rate" in capability["failed_checks"]
    assert "retrieval_evidence_location_gap_count" in capability["failed_checks"]
    assert result["gates"]["all_capabilities_ok"] is False


def test_memory_quality_scorecard_fails_on_missing_required_golden_cases() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["quality-golden"]["metrics"].update(
        {
            "required_case_coverage_rate": 0.8889,
            "missing_required_case_count": 1,
        }
    )
    suite_results["semantic-linking-golden"]["metrics"].update(
        {
            "required_case_coverage_rate": round(
                (len(SEMANTIC_LINKING_REQUIRED_CASE_IDS) - 1)
                / len(SEMANTIC_LINKING_REQUIRED_CASE_IDS),
                4,
            ),
            "missing_required_case_count": 1,
        }
    )

    result = build_memory_quality_scorecard(suite_results)

    assert result["ok"] is False
    assert result["capabilities"]["coverage_floors"]["ok"] is False
    assert result["capabilities"]["coverage_floors"]["failed_checks"] == [
        "quality_missing_required_case_count",
        "quality_required_case_coverage_rate",
        "semantic_linking_missing_required_case_count",
        "semantic_linking_required_case_coverage_rate",
    ]
    assert result["metrics"]["quality_required_case_coverage_rate"] == 0.8889
    assert result["metrics"]["quality_missing_required_case_count"] == 1
    assert result["metrics"]["semantic_linking_required_case_coverage_rate"] == round(
        (len(SEMANTIC_LINKING_REQUIRED_CASE_IDS) - 1) / len(SEMANTIC_LINKING_REQUIRED_CASE_IDS),
        4,
    )
    assert result["metrics"]["semantic_linking_missing_required_case_count"] == 1


def test_memory_quality_scorecard_fails_when_report_omits_required_case_ids() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["quality-golden"]["cases"] = [
        case
        for case in suite_results["quality-golden"]["cases"]
        if case["case_id"] != "hybrid_document_beats_single_source"
    ]
    suite_results["semantic-linking-golden"]["cases"] = [
        case
        for case in suite_results["semantic-linking-golden"]["cases"]
        if case["case_id"] != "unrelated_capture_has_no_candidates"
    ]

    result = build_memory_quality_scorecard(suite_results)

    assert result["ok"] is False
    assert result["capabilities"]["coverage_floors"]["ok"] is False
    assert (
        "quality_required_case_hybrid_document_beats_single_source"
        in result["capabilities"]["coverage_floors"]["failed_checks"]
    )
    assert (
        "quality_required_case_hybrid_document_beats_single_source"
        in result["capabilities"]["coverage_floors"]["failed_checks"]
    )
    assert (
        "semantic-linking-golden_case_count"
        in result["capabilities"]["coverage_floors"]["failed_checks"]
    )
    assert (
        "semantic_linking_required_case_unrelated_capture_has_no_candidates"
        in result["capabilities"]["coverage_floors"]["failed_checks"]
    )


def test_memory_quality_scorecard_fails_on_undercovered_semantic_linking_suite() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["semantic-linking-golden"]["cases"] = suite_results[
        "semantic-linking-golden"
    ]["cases"][:1]

    result = build_memory_quality_scorecard(suite_results)

    assert result["ok"] is False
    assert result["capabilities"]["coverage_floors"]["ok"] is False
    assert (
        "semantic-linking-golden_case_count"
        in result["capabilities"]["coverage_floors"]["failed_checks"]
    )
    assert result["gates"]["all_capabilities_ok"] is False


def test_memory_quality_scorecard_rejects_duplicate_suite_reports(tmp_path: Path) -> None:
    first = tmp_path / "small-one.json"
    second = tmp_path / "small-two.json"
    payload = _scorecard_fixture_results()["small-golden"]
    first.write_text(json.dumps(payload), encoding="utf-8")
    second.write_text(json.dumps(payload), encoding="utf-8")

    try:
        run_memory_quality_scorecard(suite_report_paths=(first, second))
    except ValueError as exc:
        assert "Duplicate scorecard suite report" in str(exc)
    else:
        raise AssertionError("Expected duplicate suite report to fail")


def test_memory_quality_scorecard_fails_on_graph_safety_regression() -> None:
    suite_results = _scorecard_fixture_results()
    suite_results["graph-native-golden"]["metrics"]["graph_safety_leak_count"] = 1

    result = build_memory_quality_scorecard(suite_results)

    assert result["ok"] is False
    assert result["capabilities"]["graph_native_recall"]["ok"] is False
    assert result["capabilities"]["scope_and_safety"]["ok"] is False
    assert result["metrics"]["safety_leak_count"] == 1
    assert (
        "graph_safety_leak_count" in result["capabilities"]["graph_native_recall"]["failed_checks"]
    )
