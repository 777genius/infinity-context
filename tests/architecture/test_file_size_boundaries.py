"""File size boundaries for maintainable Clean Architecture modules."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

CODE_GLOBS = ("*.py", "*.js", "*.ts", "*.tsx", "*.rs")
CODE_ROOTS = ("packages", "scripts", "tests")
IGNORED_PATH_PARTS = {
    "__pycache__",
    "node_modules",
}

ADAPTERS_PACKAGE = "packages/infinity_context_adapters/infinity_context_adapters"
CLI_PACKAGE = "packages/infinity_context_cli/infinity_context_cli"
CORE_PACKAGE = "packages/infinity_context_core/infinity_context_core"
MCP_PACKAGE = "packages/infinity_context_mcp/infinity_context_mcp"
SDK_PACKAGE = "packages/infinity_context_sdk/infinity_context_sdk"
SERVER_PACKAGE = "packages/infinity_context_server/infinity_context_server"
TS_SDK_PACKAGE = "packages/infinity_context_ts_sdk"

MAX_LINES = 2500
IDEAL_LINES = 1000

# Transitional hard-cap debt present before this boundary was tightened.
# These are frozen baselines, not exemptions to grow. Remove entries as files
# are split below the hard 2500-line ceiling.
LEGACY_OVER_MAX_ALLOWED_LINES = {
    f"{CORE_PACKAGE}/application/context_packer.py": 2795,
    f"{CORE_PACKAGE}/application/context_packer_answer_support.py": 3086,
    f"{CORE_PACKAGE}/application/context_query_decomposition.py": 3053,
    f"{CORE_PACKAGE}/application/context_ranking.py": 3657,
    f"{CORE_PACKAGE}/application/context_source_siblings.py": 3189,
    f"{CORE_PACKAGE}/application/use_cases/build_context.py": 3122,
    f"{SERVER_PACKAGE}/eval.py": 3020,
    f"{SERVER_PACKAGE}/eval_scorecard.py": 2627,
    f"{SERVER_PACKAGE}/memory_comparison_answer_context.py": 2859,
    f"{SERVER_PACKAGE}/memory_comparison_benchmark.py": 3103,
    f"{SERVER_PACKAGE}/memory_comparison_bundle_planner.py": 3426,
    f"{SERVER_PACKAGE}/memory_comparison_intent.py": 2838,
    f"{SERVER_PACKAGE}/memory_comparison_quality_diagnostics.py": 2695,
    f"{SERVER_PACKAGE}/memory_comparison_rerank.py": 3179,
    f"{SERVER_PACKAGE}/public_benchmark.py": 2535,
    f"{SERVER_PACKAGE}/web/assets/memory-browser.js": 3299,
    f"{TS_SDK_PACKAGE}/tests/sdk.test.ts": 4448,
    "scripts/clean_full_smoke.py": 2530,
    "scripts/multimodal_live_provider_canary.py": 2854,
    "tests/unit/test_asset_context_links_api.py": 2924,
    "tests/unit/test_asset_extractions_api.py": 3041,
    "tests/unit/test_build_context_requirement_guard.py": 2578,
    "tests/unit/test_context_packer.py": 9931,
    "tests/unit/test_context_provider_consistency.py": 4895,
    "tests/unit/test_context_query_expansion.py": 5720,
    "tests/unit/test_context_ranking.py": 11423,
    "tests/unit/test_context_requirement_coverage.py": 2761,
    "tests/unit/test_memory_comparison_answer_context.py": 3252,
    "tests/unit/test_memory_comparison_benchmark.py": 17761,
    "tests/unit/test_memory_comparison_bundle_planner.py": 4237,
    "tests/unit/test_memory_comparison_quality_diagnostics.py": 4790,
    "tests/unit/test_memory_comparison_quality_support_gaps.py": 3102,
    "tests/unit/test_public_benchmark_eval.py": 4453,
    "tests/unit/test_sdk_contract.py": 3594,
    "tests/unit/test_worker_eval_scorecard.py": 2994,
}

# Review target debt is also frozen at the current line count. New files above
# 1000 lines fail, and existing entries fail if they grow before being split.
IDEAL_OVER_1000_ALLOWED_LINES = {
    **LEGACY_OVER_MAX_ALLOWED_LINES,
    f"{ADAPTERS_PACKAGE}/extraction/content.py": 1120,
    f"{ADAPTERS_PACKAGE}/postgres/mappers.py": 1016,
    f"{CLI_PACKAGE}/cli.py": 1027,
    f"{CORE_PACKAGE}/application/anchor_event_extraction.py": 1571,
    f"{CORE_PACKAGE}/application/anchor_extraction.py": 1134,
    f"{CORE_PACKAGE}/application/context_action_roles.py": 2338,
    f"{CORE_PACKAGE}/application/context_collectors.py": 1382,
    f"{CORE_PACKAGE}/application/context_diagnostics.py": 2020,
    f"{CORE_PACKAGE}/application/context_domain_rerank_signals.py": 2382,
    f"{CORE_PACKAGE}/application/context_inference_evidence.py": 1165,
    f"{CORE_PACKAGE}/application/context_link_expansion.py": 1130,
    f"{CORE_PACKAGE}/application/context_packer_answer_support_patterns.py": 1267,
    f"{CORE_PACKAGE}/application/context_packer_answer_support_slots.py": 1209,
    f"{CORE_PACKAGE}/application/context_query_expansion_rule_catalog_part1.py": 1279,
    f"{CORE_PACKAGE}/application/context_query_expansion_rule_catalog_part4.py": 1334,
    f"{CORE_PACKAGE}/application/context_query_intent.py": 1516,
    f"{CORE_PACKAGE}/application/context_ranking_reason_policy.py": 1325,
    f"{CORE_PACKAGE}/application/context_requirement_coverage.py": 1580,
    f"{CORE_PACKAGE}/application/context_source_sibling_answer_evidence_repair.py": 1833,
    f"{CORE_PACKAGE}/application/context_temporal_query.py": 1298,
    f"{CORE_PACKAGE}/application/dto.py": 1343,
    f"{CORE_PACKAGE}/application/use_cases/anchors.py": 1165,
    f"{CORE_PACKAGE}/application/use_cases/asset_extractions.py": 1454,
    f"{CORE_PACKAGE}/application/use_cases/context_link_suggestions.py": 1060,
    f"{CORE_PACKAGE}/domain/entities.py": 1514,
    f"{MCP_PACKAGE}/agent_behavior_bench.py": 1729,
    f"{MCP_PACKAGE}/application/service.py": 2234,
    f"{MCP_PACKAGE}/plugin_hook.py": 1056,
    f"{MCP_PACKAGE}/server.py": 2023,
    f"{SDK_PACKAGE}/__init__.py": 1054,
    f"{SDK_PACKAGE}/context.py": 1285,
    f"{SERVER_PACKAGE}/api/v1/context.py": 1010,
    f"{SERVER_PACKAGE}/eval_auto_memory.py": 1735,
    f"{SERVER_PACKAGE}/eval_case_catalog.py": 1590,
    f"{SERVER_PACKAGE}/eval_case_runner.py": 1100,
    f"{SERVER_PACKAGE}/eval_semantic_linking.py": 1526,
    f"{SERVER_PACKAGE}/extraction_capabilities.py": 1231,
    f"{SERVER_PACKAGE}/memory_comparison_answer_context_backfill.py": 1001,
    f"{SERVER_PACKAGE}/memory_comparison_candidate_features.py": 1696,
    f"{SERVER_PACKAGE}/memory_comparison_llm.py": 1037,
    f"{SERVER_PACKAGE}/memory_comparison_quality_actionable_gaps.py": 1297,
    f"{SERVER_PACKAGE}/memory_comparison_query_terms.py": 2038,
    f"{SERVER_PACKAGE}/memory_comparison_relation_support.py": 2018,
    f"{SERVER_PACKAGE}/memory_comparison_rerank_policies.py": 1722,
    "scripts/multimodal_docker_live_proof.py": 2196,
    "scripts/multimodal_production_goal_audit.py": 1539,
    "tests/e2e/test_memory_scale_chaos_load_e2e.py": 2048,
    "tests/unit/test_admin_tokens.py": 2212,
    "tests/unit/test_agent_behavior_bench.py": 2063,
    "tests/unit/test_anchor_extraction.py": 1398,
    "tests/unit/test_anchor_lifecycle_api.py": 1722,
    "tests/unit/test_capture_worker.py": 1116,
    "tests/unit/test_content_extraction_adapters.py": 1543,
    "tests/unit/test_context_action_roles.py": 1085,
    "tests/unit/test_context_aggregation.py": 2402,
    "tests/unit/test_context_collectors.py": 1528,
    "tests/unit/test_context_diagnostics.py": 1834,
    "tests/unit/test_context_domain_rerank_signals.py": 1375,
    "tests/unit/test_context_packer_answer_support_ordering.py": 1208,
    "tests/unit/test_context_query_decomposition.py": 2043,
    "tests/unit/test_context_source_siblings.py": 1935,
    "tests/unit/test_context_temporal_query.py": 1563,
    "tests/unit/test_health_capabilities.py": 1562,
    "tests/unit/test_legacy_and_context_api.py": 2274,
    "tests/unit/test_local_runbook.py": 1873,
    "tests/unit/test_mcp_adapter.py": 1149,
    "tests/unit/test_memory_comparison_candidate_features.py": 2490,
    "tests/unit/test_memory_comparison_evidence.py": 1366,
    "tests/unit/test_memory_comparison_quality_actionable_gaps.py": 1007,
    "tests/unit/test_memory_comparison_rerank_policy.py": 1961,
    "tests/unit/test_memory_scope_snapshot_api.py": 1226,
    "tests/unit/test_multimodal_docker_live_proof.py": 1440,
    "tests/unit/test_multimodal_live_provider_canary.py": 1649,
    "tests/unit/test_multimodal_production_goal_audit.py": 1572,
    "tests/unit/test_provider_adapters.py": 1648,
    "tests/unit/test_quality_evidence_bundle.py": 1136,
    "tests/unit/test_schema_migrations.py": 1041,
    "tests/unit/test_suggestions_api.py": 1110,
    "tests/unit/test_worker_eval.py": 2003,
}


def test_no_new_file_exceeds_hard_2500_line_ceiling() -> None:
    line_counts = dict(_code_file_line_counts())

    assert _line_limit_failures(
        line_counts=line_counts,
        limit=MAX_LINES,
        allowed_lines=LEGACY_OVER_MAX_ALLOWED_LINES,
        label="hard 2500-line ceiling",
    ) == []


def test_files_over_ideal_1000_line_target_are_explicit_debt() -> None:
    line_counts = dict(_code_file_line_counts())

    assert _line_limit_failures(
        line_counts=line_counts,
        limit=IDEAL_LINES,
        allowed_lines=IDEAL_OVER_1000_ALLOWED_LINES,
        label="ideal 1000-line review target",
    ) == []


def _line_limit_failures(
    *,
    line_counts: dict[str, int],
    limit: int,
    allowed_lines: dict[str, int],
    label: str,
) -> list[str]:
    failures: list[str] = []

    for relative_path, line_count in sorted(line_counts.items()):
        allowed_count = allowed_lines.get(relative_path)
        if line_count > limit and allowed_count is None:
            failures.append(f"{relative_path}: {line_count} lines exceeds {label}")
        elif allowed_count is not None and line_count > allowed_count:
            failures.append(
                f"{relative_path}: {line_count} lines exceeds frozen debt baseline "
                f"of {allowed_count} for {label}"
            )

    for relative_path in sorted(set(allowed_lines) - set(line_counts)):
        failures.append(f"{relative_path}: transitional allowlist entry points to a missing file")

    for relative_path, allowed_count in sorted(allowed_lines.items()):
        line_count = line_counts.get(relative_path)
        if line_count is not None and line_count <= limit:
            failures.append(
                f"{relative_path}: {line_count} lines is now within {label}; "
                f"remove stale allowlist entry capped at {allowed_count}"
            )

    return failures


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
