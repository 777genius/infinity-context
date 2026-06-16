"""Shared constants for Memo Stack eval runners."""

from __future__ import annotations

from pathlib import Path

PROMPT_CONTRACT_SUITE = "prompt-contract"
SMALL_GOLDEN_SUITE = "small-golden"
QUALITY_GOLDEN_SUITE = "quality-golden"
SEMANTIC_LINKING_GOLDEN_SUITE = "semantic-linking-golden"
LONG_MEMORY_GOLDEN_SUITE = "long-memory-golden"
AUTO_MEMORY_GOLDEN_SUITE = "auto-memory-golden"
GRAPH_NATIVE_GOLDEN_SUITE = "graph-native-golden"
MEMORY_QUALITY_SCORECARD_SUITE = "memory-quality-scorecard"
FULL_PROVIDER_CANARY_SUITE = "memo-stack-full-provider-canary"
AGENT_BEHAVIOR_BENCH_SUITE = "memory_mcp_agent_behavior"
AGENT_LIVE_SMOKE_SUITE = "memo-stack-agent-live-smoke"
PUBLIC_MEMORY_BENCHMARK_SUITE = "public-memory-benchmark"
LOCOMO_BENCHMARK_SUITE = "locomo"
LONGMEMEVAL_BENCHMARK_SUITE = "longmemeval"
PROMPT_CONTRACT_SNAPSHOT_VERSION = 1
PROMPT_CONTRACT_SNAPSHOT_FILE = "prompt_contract.json"
_DEFAULT_SNAPSHOT_DIR = Path("tests/snapshots")
_FORBIDDEN_SNAPSHOT_MARKERS = (
    "PRIVATE_",
    "Bearer ",
    "sk-",
    "api_key",
    "password",
    "secret_token",
)
_SMALL_GOLDEN_RECALL_GATE = 0.85
_SMALL_GOLDEN_PRECISION_GATE = 0.70
_QUALITY_GOLDEN_RECALL_GATE = 0.95
_QUALITY_GOLDEN_PRECISION_GATE = 0.90
_LONG_MEMORY_RECALL_GATE = 0.95
_LONG_MEMORY_PRECISION_GATE = 0.90
_MEMORY_QUALITY_SCORECARD_MIN_SCORE_10 = 9.0
_MEMORY_QUALITY_SCORECARD_REQUIRED_SUITES = (
    SMALL_GOLDEN_SUITE,
    QUALITY_GOLDEN_SUITE,
    SEMANTIC_LINKING_GOLDEN_SUITE,
    LONG_MEMORY_GOLDEN_SUITE,
    AUTO_MEMORY_GOLDEN_SUITE,
    GRAPH_NATIVE_GOLDEN_SUITE,
    PROMPT_CONTRACT_SUITE,
)
_MEMORY_QUALITY_SCORECARD_MIN_CASE_COUNTS = {
    SMALL_GOLDEN_SUITE: 8,
    QUALITY_GOLDEN_SUITE: 16,
    SEMANTIC_LINKING_GOLDEN_SUITE: 3,
    LONG_MEMORY_GOLDEN_SUITE: 16,
    AUTO_MEMORY_GOLDEN_SUITE: 13,
    GRAPH_NATIVE_GOLDEN_SUITE: 8,
    PROMPT_CONTRACT_SUITE: 10,
}
_MEMORY_QUALITY_SCORECARD_MIN_EXTRACTION_CASES = 78
_MEMORY_QUALITY_SCORECARD_MIN_SEMANTIC_EXTRACTION_CASES = 18
_FULL_PROVIDER_CANARY_SUITE_ALIASES = (
    FULL_PROVIDER_CANARY_SUITE,
    "memo_stack_full_provider_canary",
    "memo-stack-clean-full-smoke",
    "clean-full-smoke",
    "clean_full_smoke",
)
_FULL_PROVIDER_REQUIRED_ADAPTERS = ("qdrant", "graphiti", "embeddings")
_FULL_PROVIDER_REQUIRED_CHECK_KEYS = (
    "fact_created",
    "updated_fact_versioned",
    "forgotten_fact_deleted",
    "providers_are_healthy",
    "context_provider_status_ok",
    "mcp_provider_diagnostics_ok",
    "mcp_search_has_graphiti_fact_after_worker",
    "mcp_search_has_qdrant_document_chunk_after_worker",
    "mcp_search_hides_old_fact_after_update",
    "mcp_search_hides_deleted_fact",
    "outbox_has_no_pending_or_dead",
    "mcp_outbox_has_no_pending_or_dead",
)
_PUBLIC_MEMORY_BENCHMARK_SUITE_ALIASES = (
    PUBLIC_MEMORY_BENCHMARK_SUITE,
    "public_memory_benchmark",
    "memory-public-benchmarks",
)
_PUBLIC_MEMORY_BENCHMARK_REQUIRED = (
    LOCOMO_BENCHMARK_SUITE,
    LONGMEMEVAL_BENCHMARK_SUITE,
)
_PUBLIC_MEMORY_BENCHMARK_COMPETITIVE_FLOORS = {
    LOCOMO_BENCHMARK_SUITE: {"min_accuracy": 0.947, "min_case_count": 600},
    LONGMEMEVAL_BENCHMARK_SUITE: {"min_accuracy": 0.902, "min_case_count": 500},
}
_PUBLIC_MEMORY_BENCHMARK_DATASET_SOURCE_KINDS = (
    "official_download",
    "local_override",
    "local_dataset",
)
_PUBLIC_MEMORY_BENCHMARK_OFFICIAL_SOURCE_KINDS = (
    "official_download",
    "local_override",
)
_AGENT_BEHAVIOR_ACCEPTED_SCENARIO_SETS = ("realistic", "live", "transcript", "all")
_AGENT_BEHAVIOR_RATE_FLOORS = {
    "tool_choice_accuracy": 0.80,
    "search_before_write_rate": 0.90,
    "update_vs_duplicate_rate": 0.80,
    "document_routing_accuracy": 0.80,
    "answer_support_rate": 0.80,
    "live_session_pass_rate": 0.80,
    "transcript_corpus_pass_rate": 0.80,
    "adversarial_pass_rate": 0.90,
}
_AGENT_BEHAVIOR_ZERO_COUNT_METRICS = (
    "unsafe_write_count",
    "secret_leak_count",
    "cross_scope_leak_count",
    "stale_leak_count",
    "deleted_leak_count",
    "critical_safety_failures",
)
_AGENT_LIVE_SMOKE_SUITE_ALIASES = (
    AGENT_LIVE_SMOKE_SUITE,
    "memory-agent-live-smoke",
)
_AGENT_LIVE_SMOKE_REQUIRED_GENERATED_MCP_CHECKS = (
    "codex_claude_cursor_package",
    "gemini",
    "opencode",
    "cursor_workspace",
)
_AGENT_LIVE_SMOKE_REQUIRED_AGENT_CLI_CHECKS = (
    "claude",
    "gemini",
    "opencode",
    "codex",
)
_PUBLIC_MEMORY_BENCHMARK_NAME_ALIASES = {
    LOCOMO_BENCHMARK_SUITE: frozenset(("locomo", "lo_co_mo", "long-context-memory")),
    LONGMEMEVAL_BENCHMARK_SUITE: frozenset(
        ("longmemeval", "longmem_eval", "longmem-eval", "long_memory_eval")
    ),
}
