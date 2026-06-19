"""Shared constants for Infinity Context eval runners."""

from __future__ import annotations

from pathlib import Path

PROMPT_CONTRACT_SUITE = "prompt-contract"
SMALL_GOLDEN_SUITE = "small-golden"
QUALITY_GOLDEN_SUITE = "quality-golden"
SEMANTIC_LINKING_GOLDEN_SUITE = "semantic-linking-golden"
MULTIMODAL_OFFLINE_GOLDEN_SUITE = "multimodal-offline-golden"
LONG_MEMORY_GOLDEN_SUITE = "long-memory-golden"
AUTO_MEMORY_GOLDEN_SUITE = "auto-memory-golden"
GRAPH_NATIVE_GOLDEN_SUITE = "graph-native-golden"
MEMORY_QUALITY_SCORECARD_SUITE = "memory-quality-scorecard"
FULL_PROVIDER_CANARY_SUITE = "infinity-context-full-provider-canary"
AGENT_BEHAVIOR_BENCH_SUITE = "memory_mcp_agent_behavior"
AGENT_LIVE_SMOKE_SUITE = "infinity-context-agent-live-smoke"
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
    MULTIMODAL_OFFLINE_GOLDEN_SUITE,
    LONG_MEMORY_GOLDEN_SUITE,
    AUTO_MEMORY_GOLDEN_SUITE,
    GRAPH_NATIVE_GOLDEN_SUITE,
    PROMPT_CONTRACT_SUITE,
)
_MEMORY_QUALITY_SCORECARD_MIN_CASE_COUNTS = {
    SMALL_GOLDEN_SUITE: 8,
    QUALITY_GOLDEN_SUITE: 16,
    SEMANTIC_LINKING_GOLDEN_SUITE: 14,
    MULTIMODAL_OFFLINE_GOLDEN_SUITE: 10,
    LONG_MEMORY_GOLDEN_SUITE: 16,
    AUTO_MEMORY_GOLDEN_SUITE: 13,
    GRAPH_NATIVE_GOLDEN_SUITE: 8,
    PROMPT_CONTRACT_SUITE: 10,
}
QUALITY_GOLDEN_REQUIRED_CASE_IDS = (
    "updated_provider_current_only",
    "temporal_supersedes_current_only",
    "relative_time_current_fact_not_last_week_fact",
    "contradicted_fact_hidden_by_default",
    "contradicted_fact_visible_only_in_stale_review",
    "document_architecture_precision",
    "document_source_diversity_preserves_secondary_source",
    "hybrid_document_beats_single_source",
    "context_diversity_preserves_fact_and_chunk_evidence",
    "multimodal_source_refs_recall_with_citations",
    "multilingual_multimodal_source_refs_recall",
    "multimodal_evidence_metadata_contract",
    "pending_duplicate_merge_review_visible",
    "canonical_project_anchor_recall_with_citation",
    "canonical_event_anchor_recall_by_identity",
    "person_event_project_precision",
    "multilingual_recent_person_project_recall",
    "wrong_project_anchor_deflects_generic_match",
    "identifier_like_query_deflects_partial_marker",
    "unrelated_query_returns_no_context_items",
    "cross_memory_scope_secret_hidden",
    "multi_memory_scope_explicit_recall",
    "prompt_injection_evidence_only",
)
SEMANTIC_LINKING_REQUIRED_CASE_IDS = (
    "specific_target_beats_similar_project",
    "person_project_and_org_anchors_suggested",
    "anchor_evidence_confidence_and_observed_at_exposed",
    "same_name_person_project_anchors_separate",
    "cross_script_project_anchor_resolves_canonical",
    "high_impact_relation_requires_explicit_signal",
    "weak_overlap_below_review_threshold_denied",
    "evidence_relation_requires_source_signal",
    "mentions_relation_requires_entity_signal",
    "event_call_beats_recent_chat",
    "temporal_intent_links_recent_fact_without_text_match",
    "screenshot_note_links_uploaded_document_chunk",
    "unrelated_capture_has_no_candidates",
    "cross_scope_exact_match_fact_not_suggested",
)
_MEMORY_QUALITY_SCORECARD_MIN_EXTRACTION_CASES = 78
_MEMORY_QUALITY_SCORECARD_MIN_SEMANTIC_EXTRACTION_CASES = 18
_FULL_PROVIDER_CANARY_SUITE_ALIASES = (
    FULL_PROVIDER_CANARY_SUITE,
    "infinity_context_full_provider_canary",
    "infinity-context-clean-full-smoke",
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
