"""Shared constants for memory comparison benchmark reports."""

from __future__ import annotations

MEMORY_COMPARISON_SUITE = "memory-comparison-benchmark"
MEMORY_COMPARISON_SCHEMA_VERSION = "memory-comparison-benchmark-v1"
MEMORY_COMPARISON_MODE = "ingest_search_answer_judge"
MEMORY_COMPARISON_REPLAY_MODE = "evaluate_only_replay"
MEMORY_COMPARISON_CASE_SET_ALL = "all"
MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST = "locomo-fast"
MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_MULTI_HOP = "locomo-fast-multi-hop"
MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_TEMPORAL = "locomo-fast-temporal"
MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_OPEN_DOMAIN = "locomo-fast-open-domain"
MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_SINGLE_HOP = "locomo-fast-single-hop"
MEMORY_COMPARISON_CASE_SETS = (
    MEMORY_COMPARISON_CASE_SET_ALL,
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST,
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_MULTI_HOP,
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_TEMPORAL,
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_OPEN_DOMAIN,
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_SINGLE_HOP,
)
MEMORY_COMPARISON_REPORT_FULL = "full"
MEMORY_COMPARISON_REPORT_COMPACT = "compact"
MEMORY_COMPARISON_REPORT_MODES = (
    MEMORY_COMPARISON_REPORT_FULL,
    MEMORY_COMPARISON_REPORT_COMPACT,
)

_LOCOMO_FAST_CASES_PER_GROUP = 10
_MAX_COMPACT_REQUESTED_CASE_IDS = 50
_MAX_COMPACT_REQUESTED_CAPABILITIES = 20
_MAX_COMPACT_FAILURE_SEQUENCE_ITEMS = 8
_MAX_COMPACT_FAILURE_MAPPING_ITEMS = 40
_MAX_COMPACT_FAILURE_TEXT_CHARS = 240
_MAX_COMPACT_SAMPLE_TEXT_CHARS = 180
_MAX_COMPACT_SOURCE_REF_TEXT_CHARS = 128
_COMPACT_REDACTED_TEXT = "[redacted]"
_COMPACT_OMIT = object()
_COMPACT_UNSAFE_TEXT_PREFIXES = (
    "backend:",
    "graphiti:",
    "mem0:",
    "memory://",
    "openai:",
    "provider:",
    "provider-ref-",
    "qdrant:",
)
_COMPACT_UNSAFE_TEXT_MARKERS = (
    "conv-private",
    "locomo:",
    "private-token",
    "provider-secret",
    "provider_payload",
    "raw_provider",
    "turn-secret",
)
_COMPACT_RAW_PAYLOAD_KEYS = frozenset(
    {
        "payload",
        "provider_payload",
        "raw_payload",
        "raw_provider",
        "raw_provider_payload",
    }
)
_COMPACT_BACKEND_METRIC_KEYS = frozenset(
    {
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
)
_LOCOMO_FAST_CASE_SET_GROUPS = {
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST: (
        "multi-hop",
        "temporal",
        "open-domain",
        "single-hop",
    ),
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_MULTI_HOP: ("multi-hop",),
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_TEMPORAL: ("temporal",),
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_OPEN_DOMAIN: ("open-domain",),
    MEMORY_COMPARISON_CASE_SET_LOCOMO_FAST_SINGLE_HOP: ("single-hop",),
}

