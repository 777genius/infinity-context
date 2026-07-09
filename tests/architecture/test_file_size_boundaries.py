"""File size boundaries for maintainable Clean Architecture modules."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

CODE_GLOBS = ("*.py", "*.js", "*.ts", "*.tsx", "*.rs")
CODE_ROOTS = ("packages", "scripts", "tests")
IGNORED_PATH_PARTS = {
    "__pycache__",
    "dist",
    "node_modules",
}

MAX_LINES = 2500
IDEAL_LINES = 1000

LEGACY_OVER_MAX_ALLOWLIST = {
    "packages/infinity_context_core/infinity_context_core/application/context_packer.py",
    "packages/infinity_context_core/infinity_context_core/application/context_packer_answer_support.py",
    "packages/infinity_context_core/infinity_context_core/application/context_query_decomposition.py",
    "packages/infinity_context_core/infinity_context_core/application/context_ranking.py",
    "packages/infinity_context_core/infinity_context_core/application/context_source_siblings.py",
    "packages/infinity_context_core/infinity_context_core/application/use_cases/build_context.py",
    "packages/infinity_context_server/infinity_context_server/eval.py",
    "packages/infinity_context_server/infinity_context_server/eval_scorecard.py",
    "packages/infinity_context_server/infinity_context_server/memory_comparison_answer_context.py",
    "packages/infinity_context_server/infinity_context_server/memory_comparison_bundle_planner.py",
    "packages/infinity_context_server/infinity_context_server/memory_comparison_intent.py",
    "packages/infinity_context_server/infinity_context_server/memory_comparison_quality_diagnostics.py",
    "packages/infinity_context_server/infinity_context_server/memory_comparison_rerank.py",
    "packages/infinity_context_server/infinity_context_server/public_benchmark.py",
    "packages/infinity_context_server/infinity_context_server/web/assets/memory-browser.js",
    "packages/infinity_context_ts_sdk/tests/sdk.test.ts",
    "scripts/clean_full_smoke.py",
    "scripts/multimodal_live_provider_canary.py",
    "tests/unit/test_asset_context_links_api.py",
    "tests/unit/test_asset_extractions_api.py",
    "tests/unit/test_build_context_requirement_guard.py",
    "tests/unit/test_context_packer.py",
    "tests/unit/test_context_provider_consistency.py",
    "tests/unit/test_context_query_expansion.py",
    "tests/unit/test_context_ranking.py",
    "tests/unit/test_context_requirement_coverage.py",
    "tests/unit/test_memory_comparison_answer_context.py",
    "tests/unit/test_memory_comparison_benchmark.py",
    "tests/unit/test_memory_comparison_bundle_planner.py",
    "tests/unit/test_memory_comparison_candidate_features.py",
    "tests/unit/test_memory_comparison_quality_diagnostics.py",
    "tests/unit/test_memory_comparison_quality_support_gaps.py",
    "tests/unit/test_public_benchmark_eval.py",
    "tests/unit/test_sdk_contract.py",
    "tests/unit/test_worker_eval_scorecard.py",
}

IDEAL_OVER_1000_DEBT_ALLOWLIST = {
    *LEGACY_OVER_MAX_ALLOWLIST,
    "packages/infinity_context_adapters/infinity_context_adapters/extraction/content.py",
    "packages/infinity_context_adapters/infinity_context_adapters/postgres/mappers.py",
    "packages/infinity_context_adapters/infinity_context_adapters/postgres/repositories.py",
    "packages/infinity_context_cli/infinity_context_cli/cli.py",
    "packages/infinity_context_core/infinity_context_core/application/anchor_event_extraction.py",
    "packages/infinity_context_core/infinity_context_core/application/anchor_extraction.py",
    "packages/infinity_context_core/infinity_context_core/application/context_action_roles.py",
    "packages/infinity_context_core/infinity_context_core/application/context_collectors.py",
    "packages/infinity_context_core/infinity_context_core/application/context_diagnostics.py",
    "packages/infinity_context_core/infinity_context_core/application/context_domain_rerank_signals.py",
    "packages/infinity_context_core/infinity_context_core/application/context_inference_evidence.py",
    "packages/infinity_context_core/infinity_context_core/application/context_link_expansion.py",
    "packages/infinity_context_core/infinity_context_core/application/context_packer_answer_support_patterns.py",
    "packages/infinity_context_core/infinity_context_core/application/context_packer_answer_support_slots.py",
    "packages/infinity_context_core/infinity_context_core/application/context_query_expansion_rule_catalog_part1.py",
    "packages/infinity_context_core/infinity_context_core/application/context_query_expansion_rule_catalog_part4.py",
    "packages/infinity_context_core/infinity_context_core/application/context_query_intent.py",
    "packages/infinity_context_core/infinity_context_core/application/context_ranking_reason_policy.py",
    "packages/infinity_context_core/infinity_context_core/application/context_requirement_coverage.py",
    "packages/infinity_context_core/infinity_context_core/application/context_source_sibling_answer_evidence_repair.py",
    "packages/infinity_context_core/infinity_context_core/application/context_temporal_query.py",
    "packages/infinity_context_core/infinity_context_core/application/context_temporal_source_turn.py",
    "packages/infinity_context_core/infinity_context_core/application/dto.py",
    "packages/infinity_context_core/infinity_context_core/application/use_cases/anchors.py",
    "packages/infinity_context_core/infinity_context_core/application/use_cases/asset_extractions.py",
    "packages/infinity_context_core/infinity_context_core/application/use_cases/context_link_suggestions.py",
    "packages/infinity_context_core/infinity_context_core/domain/entities.py",
    "packages/infinity_context_mcp/infinity_context_mcp/agent_behavior_bench.py",
    "packages/infinity_context_mcp/infinity_context_mcp/application/service.py",
    "packages/infinity_context_mcp/infinity_context_mcp/domain/models.py",
    "packages/infinity_context_mcp/infinity_context_mcp/plugin_hook.py",
    "packages/infinity_context_mcp/infinity_context_mcp/server.py",
    "packages/infinity_context_sdk/infinity_context_sdk/__init__.py",
    "packages/infinity_context_sdk/infinity_context_sdk/context.py",
    "packages/infinity_context_server/infinity_context_server/admin.py",
    "packages/infinity_context_server/infinity_context_server/eval.py",
    "packages/infinity_context_server/infinity_context_server/eval_auto_memory.py",
    "packages/infinity_context_server/infinity_context_server/eval_case_catalog.py",
    "packages/infinity_context_server/infinity_context_server/eval_case_runner.py",
    "packages/infinity_context_server/infinity_context_server/eval_scorecard.py",
    "packages/infinity_context_server/infinity_context_server/eval_semantic_linking.py",
    "packages/infinity_context_server/infinity_context_server/extraction_capabilities.py",
    "packages/infinity_context_server/infinity_context_server/memory_comparison_answer_context_backfill.py",
    "packages/infinity_context_server/infinity_context_server/memory_comparison_candidate_features.py",
    "packages/infinity_context_server/infinity_context_server/memory_comparison_llm.py",
    "packages/infinity_context_server/infinity_context_server/memory_comparison_preflight.py",
    "packages/infinity_context_server/infinity_context_server/memory_comparison_quality_actionable_gaps.py",
    "packages/infinity_context_server/infinity_context_server/memory_comparison_query_terms.py",
    "packages/infinity_context_server/infinity_context_server/memory_comparison_relation_support.py",
    "packages/infinity_context_server/infinity_context_server/memory_comparison_rerank_policies.py",
    "packages/infinity_context_server/infinity_context_server/memory_comparison_source_identity.py",
    "packages/infinity_context_server/infinity_context_server/public_benchmark.py",
    "packages/infinity_context_server/infinity_context_server/web/assets/memory-browser.js",
    "scripts/clean_full_smoke.py",
    "scripts/locomo_failure_analysis.py",
    "scripts/multimodal_docker_live_proof.py",
    "scripts/multimodal_production_goal_audit.py",
    "tests/e2e/test_memory_scale_chaos_load_e2e.py",
    "tests/server/test_memory_scopes_feature_seams.py",
    "tests/unit/test_admin_tokens.py",
    "tests/unit/test_agent_behavior_bench.py",
    "tests/unit/test_anchor_extraction.py",
    "tests/unit/test_anchor_lifecycle_api.py",
    "tests/unit/test_asset_context_links_api.py",
    "tests/unit/test_asset_extractions_api.py",
    "tests/unit/test_capture_worker.py",
    "tests/unit/test_content_extraction_adapters.py",
    "tests/unit/test_context_action_roles.py",
    "tests/unit/test_context_aggregation.py",
    "tests/unit/test_context_collectors.py",
    "tests/unit/test_context_diagnostics.py",
    "tests/unit/test_context_domain_rerank_signals.py",
    "tests/unit/test_context_packer_answer_support_ordering.py",
    "tests/unit/test_context_provider_consistency.py",
    "tests/unit/test_context_query_decomposition.py",
    "tests/unit/test_context_source_siblings.py",
    "tests/unit/test_context_temporal_query.py",
    "tests/unit/test_context_temporal_source_identity_scoring.py",
    "tests/unit/test_context_temporal_source_turn_order.py",
    "tests/unit/test_health_capabilities.py",
    "tests/unit/test_legacy_and_context_api.py",
    "tests/unit/test_local_runbook.py",
    "tests/unit/test_locomo_failure_analysis.py",
    "tests/unit/test_mcp_adapter.py",
    "tests/unit/test_memory_comparison_evidence.py",
    "tests/unit/test_memory_comparison_failure_diagnostics.py",
    "tests/unit/test_memory_comparison_preflight.py",
    "tests/unit/test_memory_comparison_quality_actionable_gaps.py",
    "tests/unit/test_memory_comparison_reason_candidate_features.py",
    "tests/unit/test_memory_comparison_rerank_policy.py",
    "tests/unit/test_memory_comparison_temporal_grounding.py",
    "tests/unit/test_memory_scope_snapshot_api.py",
    "tests/unit/test_multimodal_docker_live_proof.py",
    "tests/unit/test_multimodal_live_provider_canary.py",
    "tests/unit/test_multimodal_production_goal_audit.py",
    "tests/unit/test_provider_adapters.py",
    "tests/unit/test_quality_evidence_bundle.py",
    "tests/unit/test_schema_migrations.py",
    "tests/unit/test_sdk_contract.py",
    "tests/unit/test_suggestions_api.py",
    "tests/unit/test_worker_eval.py",
    "tests/unit/test_worker_eval_scorecard.py",
}


def test_no_new_file_exceeds_hard_2500_line_ceiling() -> None:
    offenders = [
        f"{relative_path}: {line_count} lines"
        for relative_path, line_count in _code_file_line_counts()
        if line_count > MAX_LINES and relative_path not in LEGACY_OVER_MAX_ALLOWLIST
    ]

    assert offenders == []


def test_files_over_ideal_1000_line_target_are_explicit_debt() -> None:
    offenders = [
        f"{relative_path}: {line_count} lines"
        for relative_path, line_count in _code_file_line_counts()
        if line_count > IDEAL_LINES and relative_path not in IDEAL_OVER_1000_DEBT_ALLOWLIST
    ]

    assert offenders == []


def _code_file_line_counts() -> list[tuple[str, int]]:
    results: list[tuple[str, int]] = []
    for root_name in CODE_ROOTS:
        root = REPO_ROOT / root_name
        if not root.exists():
            continue
        for glob in CODE_GLOBS:
            for path in root.rglob(glob):
                if IGNORED_PATH_PARTS.intersection(path.parts):
                    continue
                relative_path = path.relative_to(REPO_ROOT).as_posix()
                results.append((relative_path, _line_count(path)))
    return sorted(results)


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())
