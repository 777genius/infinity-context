"""Source-backed Memo Stack vs Memora comparison model.

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
    memo_stack_score: float
    memora_score: float
    memo_stack_rationale: str
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
        memo_stack_score=9.1,
        memora_score=9.0,
        memo_stack_rationale=(
            "memory_remember_fact, canonical facts, idempotency, source refs, "
            "canonical category/tags/TTL, suggestions, MCP tools and HTTP API "
            "are verified by local quality and MCP e2e gates."
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
        memo_stack_score=9.2,
        memora_score=8.1,
        memo_stack_rationale=(
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
        memo_stack_score=9.3,
        memora_score=7.8,
        memo_stack_rationale=(
            "MCP defaults are suggestion-first, delete can be disabled, and "
            "fact/suggestion/capture review tools plus read-only memory_insights "
            "are first-class."
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
        memo_stack_score=9.4,
        memora_score=9.0,
        memo_stack_rationale=(
            "Context API, memory_search, memory_digest, ranking, token packing "
            "canonical category plus tags_any/tags_all/tags_none filters, TTL hiding "
            "and graph/vector adapters are covered by deterministic gates."
        ),
        memora_rationale=(
            "Memora has hybrid search, semantic search, memory_digest, related "
            "hops, lineage and tag/date/metadata filters."
        ),
        requirement="fact_retrieval",
    ),
    Dimension(
        id="large_docs_and_architecture_notes",
        label="Large documents and architecture notes",
        weight=0.10,
        memo_stack_score=9.4,
        memora_score=9.1,
        memo_stack_rationale=(
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
        memo_stack_score=9.2,
        memora_score=8.4,
        memo_stack_rationale=(
            "Graphiti/Neo4j is modeled as a temporal derived graph adapter with "
            "canonical Postgres as source of truth, plus portable graph.json "
            "export for canonical facts, documents, fragments and evidence links."
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
        memo_stack_score=9.0,
        memora_score=7.8,
        memo_stack_rationale=(
            "Repo includes plugin-kit-ai generated artifacts, MCP doctor, stdio "
            "e2e, hook capture tests and CLI memory operations for agent workflows."
        ),
        memora_rationale=(
            "Memora ships MCP config and Claude/Cursor integration examples. "
            "Public docs do not show the same multi-agent generated plugin gate."
        ),
        requirement="coding_agent_integration",
    ),
    Dimension(
        id="scope_isolation_team_profiles",
        label="Project/team/profile isolation",
        weight=0.10,
        memo_stack_score=9.2,
        memora_score=7.5,
        memo_stack_rationale=(
            "Space/profile/thread is a first-class contract, with category/tags "
            "inside each profile, auth scope and cross-profile/thread leak checks."
        ),
        memora_rationale=(
            "Tags and metadata filters can model scope, and D1/S3/R2 can sync, "
            "but public docs do not expose a hard profile/thread isolation model."
        ),
        requirement="scope_isolation",
    ),
    Dimension(
        id="ops_and_production_evidence",
        label="Operational confidence and benchmark evidence",
        weight=0.10,
        memo_stack_score=9.2,
        memora_score=7.7,
        memo_stack_rationale=(
            "Quality scorecard, full-provider canary, public benchmark canary, "
            "agent behavior benchmark, secret/top-evidence gates, and portable "
            "profile snapshot export/import with manifest verification plus "
            "memory insights via API, SDK, MCP and CLI exist."
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
        memo_stack_score=9.1,
        memora_score=6.8,
        memo_stack_rationale=(
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
) -> dict[str, Any]:
    """Build a deterministic comparison report.

    The report intentionally separates source-backed claims from direct-run
    evidence. This prevents accidental overclaiming when Memora is not executed
    locally with the same provider mode as Memo Stack.
    """

    direct_smoke = _summarize_memora_direct_smoke(memora_direct_smoke)
    dimensions = [_dimension_to_report(dimension) for dimension in DIMENSIONS]
    memo_stack_weighted = _weighted_score("memo_stack_score")
    memora_weighted = _weighted_score("memora_score")
    gap = round(memo_stack_weighted - memora_weighted, 2)

    return {
        "suite": "memo-stack-vs-agentic-box-memora-agent-memory-comparison",
        "version": 1,
        "evidence_policy": {
            "competitor_direct_run": direct_smoke["status"],
            "competitor_direct_run_mode": direct_smoke.get("mode"),
            "competitor_paid_openai_llm_mode_verified": False,
            "do_not_claim": [
                "Do not claim Memora failed production OpenAI mode.",
                "Do not claim Memo Stack beats Memora on simple local setup.",
                "Do not claim Memora architecture score is proven by source audit.",
            ],
        },
        "sources": {
            "memora_public": list(MEMORA_PUBLIC_SOURCES),
            "memo_stack_local": [
                "tests/architecture/test_memory_boundaries.py",
                "tests/unit/test_import_boundaries.py",
                "tests/unit/test_document_fragments.py",
                "tests/unit/test_document_fragment_api.py",
                "tests/unit/test_fact_taxonomy_api.py",
                "tests/unit/test_cli_memory_commands.py",
                "tests/unit/test_memory_insights_api.py",
                "tests/unit/test_graph_export_api.py",
                "tests/unit/test_profile_snapshot_api.py",
                "memo_stack_core.profile_snapshots",
                "tests/e2e/test_memory_quality_e2e.py",
                "tests/e2e/test_memo_stack_agent_behavior_bench_e2e.py",
                "tests/e2e/test_memo_stack_agent_plugin_e2e.py",
                "scripts/clean_full_smoke.py",
            ],
        },
        "direct_memora_smoke": direct_smoke,
        "dimensions": dimensions,
        "overall": {
            "memo_stack_score": round(memo_stack_weighted, 2),
            "memora_score": round(memora_weighted, 2),
            "gap": gap,
            "winner": "memo_stack" if gap > 0.25 else "tie",
            "decision": (
                "Memo Stack is stronger as a governed, extensible team/coding "
                "agent memory platform. Memora is stronger as a ready-to-use "
                "personal MCP memory with rich local UX and document fragments."
            ),
        },
        "recommendations": [
            {
                "case": "Personal local coding-agent memory today",
                "winner": "memora",
                "reason": "Simpler install and richer out-of-the-box local graph UI.",
            },
            {
                "case": "Team/project memory with strict scopes and review gates",
                "winner": "memo_stack",
                "reason": "Space/profile/thread, canonical lifecycle and safer write policy.",
            },
            {
                "case": "Reusable platform behind multiple apps and agents",
                "winner": "memo_stack",
                "reason": (
                    "Ports/adapters keep Graphiti, Qdrant, Cognee and future engines replaceable."
                ),
            },
        ],
    }


def _dimension_to_report(dimension: Dimension) -> dict[str, Any]:
    gap = round(dimension.memo_stack_score - dimension.memora_score, 2)
    if gap > 0.25:
        winner = "memo_stack"
    elif gap < -0.25:
        winner = "memora"
    else:
        winner = "tie"
    return {
        "id": dimension.id,
        "label": dimension.label,
        "requirement": dimension.requirement,
        "weight": dimension.weight,
        "memo_stack_score": dimension.memo_stack_score,
        "memora_score": dimension.memora_score,
        "gap": gap,
        "winner": winner,
        "memo_stack_rationale": dimension.memo_stack_rationale,
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
        "required_checks": list(DIRECT_MEMORA_SMOKE_REQUIREMENTS),
        "passed_checks": passed,
        "failed_checks": failed,
    }


def _scenario_count(value: object) -> int | None:
    if isinstance(value, list):
        return len(value)
    return None


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
    args = parser.parse_args(argv)

    smoke = _load_json(args.memora_smoke_report) if args.memora_smoke_report else None
    print(json.dumps(build_memora_agent_memory_comparison(memora_direct_smoke=smoke), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
