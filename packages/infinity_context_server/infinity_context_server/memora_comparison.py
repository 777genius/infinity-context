"""Source-backed Infinity Context vs Memora comparison model.

This module intentionally lives in the server/reporting layer. A competitor
benchmark is not part of the memory domain model, so the core package stays
free from Memora-specific knowledge and runtime dependencies.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Dimension:
    id: str
    label: str
    weight: float
    infinity_context_score: float
    memora_score: float
    infinity_context_rationale: str
    memora_rationale: str
    requirement: str


MEMORA_PUBLIC_SOURCES: tuple[dict[str, str], ...] = (
    {
        "title": "agentic-box/memora GitHub README",
        "url": "https://github.com/agentic-box/memora",
        "claim": (
            "MCP memory layer with persistent storage, semantic retrieval, graph "
            "relations, source-backed memory_digest, documents, LLM dedup, "
            "linking, live graph and cloud sync."
        ),
    },
    {
        "title": "MCP Servers index: Memora",
        "url": "https://mcpservers.org/servers/agentic-mcp-tools/memora",
        "claim": (
            "Lists SQLite persistence, S3/R2/D1 sync, hierarchical sections, "
            "hybrid search, document fragments, graph UI, events and history."
        ),
    },
    {
        "title": "Protodex MCP index: agentic-box/memora",
        "url": "https://protodex.io/servers/agentic-box-memora.html",
        "claim": (
            "Shows Memora as a Python MCP server for Claude, Claude Code and "
            "Cursor with persistent memory, knowledge graph, RAG and semantic "
            "search topics."
        ),
    },
)


DIRECT_MEMORA_SMOKE_REQUIREMENTS: tuple[str, ...] = (
    "has_core_tools",
    "create_and_filtered_search",
    "update_searches_new_fact",
    "old_text_not_primary_after_update",
    "metadata_scope_filter_excludes_other_project",
    "document_fragment_recall",
    "digest_returns_source_backed_context",
    "digest_mentions_updated_architecture",
    "delete_removes_fact_from_search",
    "export_available",
)


DIMENSIONS: tuple[Dimension, ...] = (
    Dimension(
        id="remember_durable_facts",
        label="Remember durable coding facts",
        weight=0.12,
        infinity_context_score=9.2,
        memora_score=9.0,
        infinity_context_rationale=(
            "memory_remember_fact, canonical facts, idempotency, source refs, "
            "canonical category/tags/TTL, exact and conservative semantic-equivalent "
            "duplicate preflight, conflict-aware auto-apply gating, suggestions, "
            "bounded batch suggestion create, MCP tools and HTTP API are verified "
            "by local quality and MCP e2e gates."
        ),
        memora_rationale=(
            "Direct MCP smoke and public docs show simple memory_create, batch "
            "create, absorb and semantic/hybrid recall."
        ),
        requirement="fact_remembering",
    ),
    Dimension(
        id="update_and_temporal_lifecycle",
        label="Update facts without stale answers",
        weight=0.14,
        infinity_context_score=9.2,
        memora_score=8.1,
        infinity_context_rationale=(
            "Fact update uses canonical lifecycle/versioning, expected_version, "
            "forget semantics and derived Graphiti/Qdrant projection."
        ),
        memora_rationale=(
            "Memora supports memory_update, supersedes links and supersession "
            "detection. Direct schema did not expose optimistic concurrency."
        ),
        requirement="fact_updating",
    ),
    Dimension(
        id="forget_delete_and_review_control",
        label="Forget/delete and review-gated control",
        weight=0.12,
        infinity_context_score=9.5,
        memora_score=7.8,
        infinity_context_rationale=(
            "MCP defaults are suggestion-first, delete can be disabled, and "
            "fact/suggestion/capture review tools, bounded batch suggestion "
            "review with per-item failures, DB-enforced race-safe pending "
            "suggestion dedupe, semantic-equivalent duplicate suppression, plus read-only "
            "memory_insights with "
            "recent activity, duplicate/similar fact review actions and a safe "
            "consolidation plan are first-class."
        ),
        memora_rationale=(
            "Memora has delete, batch delete, document fragment guards and "
            "action history, but public tool surface is more direct-write first."
        ),
        requirement="memory_management",
    ),
    Dimension(
        id="retrieval_and_digest_quality",
        label="Retrieve the right facts for a coding agent",
        weight=0.14,
        infinity_context_score=7.8,
        memora_score=8.4,
        infinity_context_rationale=(
            "Context API, memory_search, memory_digest, ranking, token packing "
            "canonical category plus tags_any/tags_all/tags_none filters, "
            "memory_related_facts with explainable relation reasons, TTL hiding "
            "and graph/vector adapters are covered by deterministic gates. "
            "Semantic-equivalent duplicate checks now run in core consolidation "
            "and MCP preflight, while conflict-aware auto-apply keeps competing "
            "decisions in review before they pollute recall. Current confidence "
            "is provisional: internal smoke/golden gates are strong, but a fresh "
            "large public LoCoMo/LongMemEval run is required before claiming "
            "top-tier retrieval quality."
        ),
        memora_rationale=(
            "Memora has hybrid search, semantic search, memory_digest, related "
            "hops, lineage and tag/date/metadata filters, plus direct local MCP "
            "smoke evidence. Its paid/OpenAI mode was not verified here."
        ),
        requirement="fact_retrieval",
    ),
    Dimension(
        id="large_docs_and_architecture_notes",
        label="Large documents and architecture notes",
        weight=0.10,
        infinity_context_score=9.4,
        memora_score=9.1,
        infinity_context_rationale=(
            "Document ingest now extracts typed markdown fragments for claims, "
            "plan items, risks and references, while Cognee/Qdrant remain "
            "replaceable derived RAG adapters for stronger document recall."
        ),
        memora_rationale=(
            "Structured markdown documents become searchable fragment trees "
            "with claim, plan_item, reference, risk and section_chunk nodes, "
            "plus polished local graph/export UX."
        ),
        requirement="document_memory",
    ),
    Dimension(
        id="graph_relationships",
        label="Graph relationships and temporal context",
        weight=0.10,
        infinity_context_score=9.5,
        memora_score=8.4,
        infinity_context_rationale=(
            "Graphiti/Neo4j is modeled as a temporal derived graph adapter with "
            "canonical Postgres as source of truth, plus portable graph.json "
            "export for canonical facts, documents, fragments and evidence links "
            "and durable typed fact links through API, SDK and MCP. MemoryScope "
            "snapshot export/import preserves those links for backup/git-sync "
            "without depending on derived Graphiti/Cognee runtime state."
        ),
        memora_rationale=(
            "Memora has typed links, clusters, crossrefs and graph UI, but not "
            "Graphiti-style temporal graph as the primary engine."
        ),
        requirement="graph_memory",
    ),
    Dimension(
        id="agent_hooks_and_plugin_distribution",
        label="Agent hooks, plugins and real agent ergonomics",
        weight=0.10,
        infinity_context_score=8.8,
        memora_score=8.4,
        infinity_context_rationale=(
            "Repo includes plugin-kit-ai generated artifacts, MCP doctor, stdio "
            "e2e, hook capture tests, CLI memory operations and bounded MCP batch "
            "suggestion create/review for agent workflows. Local onboarding now "
            "exposes quickstart/doctor local_experience readiness, but the first-use "
            "flow is still less polished than Memora's graph-first MCP setup."
        ),
        memora_rationale=(
            "Memora ships MCP config, Claude/Cursor/Codex examples and a graph UI "
            "that is immediately useful after local setup. Public docs do not show "
            "the same multi-agent generated plugin gate."
        ),
        requirement="coding_agent_integration",
    ),
    Dimension(
        id="local_mcp_visual_ux",
        label="Local MCP setup and visual memory UX",
        weight=0.10,
        infinity_context_score=7.8,
        memora_score=9.3,
        infinity_context_rationale=(
            "Infinity Context now has quickstart, generated MCP config, doctor, "
            "ui --open, a browser Capture panel, graph, review and timeline, plus "
            "structured local_experience readiness in quickstart/doctor. The flow "
            "is usable but still needs a more polished zero-to-first-memory path."
        ),
        memora_rationale=(
            "Memora's README and direct smoke show a simpler local MCP server path "
            "with built-in live graph, timeline, history and chat-oriented memory UI."
        ),
        requirement="local_mcp_visual_experience",
    ),
    Dimension(
        id="scope_isolation_team_memory_scopes",
        label="Project/team/memory_scope isolation",
        weight=0.10,
        infinity_context_score=9.2,
        memora_score=7.5,
        infinity_context_rationale=(
            "Space/memory_scope/thread is a first-class contract, with category/tags "
            "inside each memory_scope, auth scope and cross-memory_scope/thread leak checks."
        ),
        memora_rationale=(
            "Tags and metadata filters can model scope, and D1/S3/R2 can sync, "
            "but public docs do not expose a hard memory_scope/thread isolation model."
        ),
        requirement="scope_isolation",
    ),
    Dimension(
        id="ops_and_production_evidence",
        label="Operational confidence and benchmark evidence",
        weight=0.10,
        infinity_context_score=8.6,
        memora_score=7.7,
        infinity_context_rationale=(
            "Quality scorecard, full-provider canary, public benchmark canary, "
            "agent behavior benchmark, secret/top-evidence gates, and portable "
            "memory_scope snapshot export/import with manifest verification plus "
            "dedicated read-only import previews via API, SDK, MCP and CLI exist. "
            "MemoryScope snapshots now include durable typed fact relations. Memory "
            "insights, recent activity, duplicate/similar fact review actions and "
            "safe consolidation plans are available via API, SDK, MCP and CLI. "
            "This is capped below 9 until live provider proof and a large public "
            "retrieval benchmark are current on the latest commit."
        ),
        memora_rationale=(
            "Direct temp-db smoke passed and public repo is active, but we did "
            "not verify its paid OpenAI/LLM/cloud modes in this run."
        ),
        requirement="production_reliability",
    ),
    Dimension(
        id="clean_architecture_extensibility",
        label="Clean Architecture and extensibility",
        weight=0.08,
        infinity_context_score=9.1,
        memora_score=6.8,
        infinity_context_rationale=(
            "Core, ports, adapters, MCP, SDK and server are split, with static "
            "architecture tests enforcing forbidden imports."
        ),
        memora_rationale=(
            "Memora is feature-rich and easy to install. We did not audit its "
            "internal architecture deeply enough to claim equivalent boundaries."
        ),
        requirement="clean_architecture",
    ),
)


def build_memora_agent_memory_comparison(
    *,
    memora_direct_smoke: Mapping[str, Any] | None = None,
    public_benchmark_report: Mapping[str, Any] | None = None,
    production_goal_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic comparison report.

    The report intentionally separates source-backed claims from direct-run
    evidence. This prevents accidental overclaiming when Memora is not executed
    locally with the same provider mode as Infinity Context.
    """

    direct_smoke = _summarize_memora_direct_smoke(memora_direct_smoke)
    public_benchmark = _summarize_public_benchmark_report(public_benchmark_report)
    production_audit = _summarize_production_goal_audit(production_goal_audit)
    dimensions = [_dimension_to_report(dimension) for dimension in DIMENSIONS]
    infinity_context_weighted = _weighted_score("infinity_context_score")
    memora_weighted = _weighted_score("memora_score")
    gap = round(infinity_context_weighted - memora_weighted, 2)

    return {
        "suite": "infinity-context-vs-agentic-box-memora-agent-memory-comparison",
        "version": 1,
        "evidence_policy": {
            "competitor_direct_run": direct_smoke["status"],
            "competitor_direct_run_mode": direct_smoke.get("mode"),
            "competitor_paid_openai_llm_mode_verified": False,
            "do_not_claim": [
                "Do not claim Memora failed production OpenAI mode.",
                "Do not claim Infinity Context beats Memora on simple local setup.",
                "Do not claim Memora architecture score is proven by source audit.",
                (
                    "Do not claim Infinity Context live provider proof is current "
                    "unless production audit passes."
                ),
                (
                    "Do not claim Infinity Context has top-tier public retrieval "
                    "quality without a fresh large LoCoMo/LongMemEval report."
                ),
            ],
        },
        "sources": {
            "memora_public": list(MEMORA_PUBLIC_SOURCES),
            "infinity_context_local": [
                "tests/architecture/test_memory_boundaries.py",
                "tests/unit/test_import_boundaries.py",
                "tests/unit/test_document_fragments.py",
                "tests/unit/test_document_fragment_api.py",
                "tests/unit/test_semantic_dedupe.py",
                "tests/unit/test_capture_semantic_dedupe.py",
                "tests/unit/test_fact_taxonomy_api.py",
                "tests/unit/test_cli_memory_commands.py",
                "tests/unit/test_memory_insights_api.py",
                "tests/unit/test_graph_export_api.py",
                "tests/unit/test_mcp_related_facts.py",
                "tests/unit/test_mcp_fact_relations.py",
                "tests/unit/test_mcp_suggestion_batch_review.py",
                "tests/unit/test_suggestions_api.py",
                "tests/unit/test_memory_scope_snapshot_api.py",
                "tests/unit/test_mcp_memory_scope_snapshot_preview.py",
                "infinity_context_core.memory_scope_snapshots",
                "infinity_context_core.memory_scope_snapshot_preview",
                "tests/e2e/test_memory_quality_e2e.py",
                "tests/e2e/test_infinity_context_agent_behavior_bench_e2e.py",
                "tests/e2e/test_infinity_context_agent_plugin_e2e.py",
                "scripts/clean_full_smoke.py",
                ".e2e-artifacts/public-benchmark-full-600-current.json",
                ".e2e-artifacts/multimodal-production-goal-audit.json",
            ],
        },
        "direct_memora_smoke": direct_smoke,
        "infinity_context_public_benchmark": public_benchmark,
        "infinity_context_production_audit": production_audit,
        "dimensions": dimensions,
        "overall": {
            "infinity_context_score": round(infinity_context_weighted, 2),
            "memora_score": round(memora_weighted, 2),
            "gap": gap,
            "winner": "infinity_context" if gap > 0.25 else "tie",
            "decision": (
                "Infinity Context is stronger as a governed, extensible team/coding "
                "agent memory platform. Memora is stronger as a ready-to-use "
                "personal MCP memory with rich local UX, action history and document fragments."
            ),
        },
        "current_gaps": _current_gaps(
            public_benchmark=public_benchmark,
            production_audit=production_audit,
        ),
        "recommendations": [
            {
                "case": "Personal local coding-agent memory today",
                "winner": "memora",
                "reason": "Simpler install and richer out-of-the-box local graph UI.",
            },
            {
                "case": "Team/project memory with strict scopes and review gates",
                "winner": "infinity_context",
                "reason": "Space/memory_scope/thread, canonical lifecycle and safer write policy.",
            },
            {
                "case": "Reusable platform behind multiple apps and agents",
                "winner": "infinity_context",
                "reason": (
                    "Ports/adapters keep Graphiti, Qdrant, Cognee and future engines replaceable."
                ),
            },
            {
                "case": "Multimodal evidence-backed capture and review",
                "winner": "infinity_context",
                "reason": (
                    "Current local proofs cover document/image/audio/video evidence, "
                    "artifact previews, suggestions and review flow."
                ),
            },
        ],
    }


def _dimension_to_report(dimension: Dimension) -> dict[str, Any]:
    gap = round(dimension.infinity_context_score - dimension.memora_score, 2)
    if gap > 0.25:
        winner = "infinity_context"
    elif gap < -0.25:
        winner = "memora"
    else:
        winner = "tie"
    return {
        "id": dimension.id,
        "label": dimension.label,
        "requirement": dimension.requirement,
        "weight": dimension.weight,
        "infinity_context_score": dimension.infinity_context_score,
        "memora_score": dimension.memora_score,
        "gap": gap,
        "winner": winner,
        "infinity_context_rationale": dimension.infinity_context_rationale,
        "memora_rationale": dimension.memora_rationale,
    }


def _weighted_score(score_field: str) -> float:
    total_weight = sum(dimension.weight for dimension in DIMENSIONS)
    return (
        sum(getattr(dimension, score_field) * dimension.weight for dimension in DIMENSIONS)
        / total_weight
    )


def _summarize_memora_direct_smoke(
    memora_direct_smoke: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not memora_direct_smoke:
        return {
            "status": "not_run",
            "required_checks": list(DIRECT_MEMORA_SMOKE_REQUIREMENTS),
            "passed_checks": [],
            "failed_checks": [],
            "note": "Run scripts/memora_direct_mcp_smoke.py for direct MCP evidence.",
        }

    checks = memora_direct_smoke.get("checks")
    check_map = checks if isinstance(checks, Mapping) else {}
    failed = [
        check_id
        for check_id in DIRECT_MEMORA_SMOKE_REQUIREMENTS
        if check_map.get(check_id) is not True
    ]
    passed = [
        check_id for check_id in DIRECT_MEMORA_SMOKE_REQUIREMENTS if check_map.get(check_id) is True
    ]
    ok = memora_direct_smoke.get("ok") is True and not failed
    return {
        "status": "passed" if ok else "failed",
        "system": memora_direct_smoke.get("system", "agentic-box/memora"),
        "mode": memora_direct_smoke.get("mode"),
        "scenario_set": memora_direct_smoke.get("scenario_set"),
        "scenario_count": _scenario_count(memora_direct_smoke.get("scenarios")),
        "embedding_model": memora_direct_smoke.get("embedding_model"),
        "llm_enabled": memora_direct_smoke.get("llm_enabled"),
        "tool_count": memora_direct_smoke.get("tool_count"),
        "document_fragment_count": memora_direct_smoke.get("document_fragment_count"),
        "provenance": _provenance_summary(memora_direct_smoke.get("provenance")),
        "required_checks": list(DIRECT_MEMORA_SMOKE_REQUIREMENTS),
        "passed_checks": passed,
        "failed_checks": failed,
    }


def _scenario_count(value: object) -> int | None:
    if isinstance(value, list):
        return len(value)
    return None


def _provenance_summary(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    git = value.get("git")
    runtime = value.get("runtime")
    return {
        "schema_version": value.get("schema_version"),
        "generated_by": value.get("generated_by"),
        "suite": value.get("suite"),
        "run_id": value.get("run_id"),
        "project": value.get("project"),
        "git": git if isinstance(git, Mapping) else None,
        "runtime": runtime if isinstance(runtime, Mapping) else None,
    }


def _summarize_public_benchmark_report(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if not value:
        return {
            "status": "not_provided",
            "note": "Pass --public-benchmark-report for fresh LoCoMo/LongMemEval evidence.",
        }
    metrics = value.get("metrics")
    metrics_map = metrics if isinstance(metrics, Mapping) else {}
    provenance = value.get("provenance")
    checks = value.get("checks")
    return {
        "status": "passed" if value.get("ok") is True else "failed",
        "suite": value.get("suite"),
        "case_count": metrics_map.get("case_count"),
        "accuracy": metrics_map.get("accuracy"),
        "locomo_accuracy": metrics_map.get("locomo_accuracy"),
        "longmemeval_accuracy": metrics_map.get("longmemeval_accuracy"),
        "duplicate_case_id_count": metrics_map.get("duplicate_case_id_count"),
        "checks": dict(checks) if isinstance(checks, Mapping) else {},
        "provenance": _provenance_summary(provenance),
        "weakest_capabilities": _weakest_capabilities(value),
    }


def _weakest_capabilities(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    breakdowns: list[dict[str, Any]] = []
    benchmarks = value.get("benchmarks")
    if not isinstance(benchmarks, list):
        return breakdowns
    for benchmark in benchmarks:
        if not isinstance(benchmark, Mapping):
            continue
        capability_breakdown = benchmark.get("capability_breakdown")
        if not isinstance(capability_breakdown, Mapping):
            continue
        for capability, metrics in capability_breakdown.items():
            if not isinstance(capability, str) or not isinstance(metrics, Mapping):
                continue
            accuracy = metrics.get("accuracy")
            if isinstance(accuracy, int | float):
                breakdowns.append(
                    {
                        "benchmark": benchmark.get("name"),
                        "capability": capability,
                        "accuracy": round(float(accuracy), 4),
                        "case_count": metrics.get("case_count"),
                    }
                )
    return sorted(breakdowns, key=lambda item: item["accuracy"])[:5]


def _summarize_production_goal_audit(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if not value:
        return {
            "status": "not_provided",
            "note": "Pass --production-goal-audit for current production proof blockers.",
        }
    failures = value.get("failures")
    blocked_requirements = value.get("blocked_requirements")
    reports = value.get("reports")
    return {
        "status": "passed" if value.get("ok") is True else "blocked",
        "git": value.get("git") if isinstance(value.get("git"), Mapping) else None,
        "failures": list(failures) if isinstance(failures, list) else [],
        "blocked_requirements": (
            list(blocked_requirements) if isinstance(blocked_requirements, list) else []
        ),
        "reports": dict(reports) if isinstance(reports, Mapping) else {},
    }


def _current_gaps(
    *,
    public_benchmark: Mapping[str, Any],
    production_audit: Mapping[str, Any],
) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    if production_audit.get("status") == "blocked":
        gaps.append(
            {
                "id": "current_live_provider_proof",
                "severity": "high",
                "summary": "Live provider proof is not current for the latest commit.",
            }
        )
    locomo_accuracy = public_benchmark.get("locomo_accuracy")
    if isinstance(locomo_accuracy, int | float) and float(locomo_accuracy) < 0.8:
        gaps.append(
            {
                "id": "locomo_retrieval_reasoning",
                "severity": "high",
                "summary": "LoCoMo retrieval/reasoning is below the desired competitive floor.",
            }
        )
    return gaps


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--memora-smoke-report",
        type=Path,
        help="Optional JSON output from scripts/memora_direct_mcp_smoke.py.",
    )
    parser.add_argument(
        "--public-benchmark-report",
        type=Path,
        help="Optional JSON output from official public memory benchmark proof.",
    )
    parser.add_argument(
        "--production-goal-audit",
        type=Path,
        help="Optional JSON output from multimodal production goal audit.",
    )
    args = parser.parse_args(argv)

    smoke = _load_json(args.memora_smoke_report) if args.memora_smoke_report else None
    public_benchmark = (
        _load_json(args.public_benchmark_report) if args.public_benchmark_report else None
    )
    production_audit = (
        _load_json(args.production_goal_audit) if args.production_goal_audit else None
    )
    print(
        json.dumps(
            build_memora_agent_memory_comparison(
                memora_direct_smoke=smoke,
                public_benchmark_report=public_benchmark,
                production_goal_audit=production_audit,
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
