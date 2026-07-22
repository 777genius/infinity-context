"""Bounded, text-free stage timings for context assembly diagnostics."""

from __future__ import annotations

from math import isfinite
from time import perf_counter

MAX_CONTEXT_STAGE_DURATION_MS = 86_400_000.0

# Tuple order is the stable public order. Callers cannot add request-derived labels.
CONTEXT_STAGE_NAMES = (
    "scope_resolution",
    "planning_expansion",
    "canonical_collect",
    "vector_collect",
    "graph_collect",
    "rag_collect",
    "artifact_evidence",
    "enrichment_hydration",
    "final_rank",
    "rerank",
    "pack",
    "response_mapping",
    "total",
    "keyword_aggregation_seed",
    "keyword_chunk_rank",
    "keyword_aggregation",
    "keyword_neighbors",
    "keyword_source_siblings",
    "exact_source_ref_hydration",
    "dedupe_hydrate",
    "temporal_relations",
    "stale_review",
    "pending_review",
    "context_links",
    "linked_temporal_relations",
    "final_rank_source_merge",
    "final_rank_temporal_boost",
    "final_rank_anchor_boost",
    "final_rank_requirement_boost",
    "final_rank_bm25",
    "final_rank_fusion",
    "final_rank_deterministic",
    "final_rank_dedupe",
)
MAX_CONTEXT_STAGE_TIMINGS = len(CONTEXT_STAGE_NAMES)


def record_context_stage_timing(
    diagnostics: dict[str, object],
    stage: str,
    started_at: float,
) -> None:
    """Record elapsed time for one allowlisted stage."""
    record_context_stage_interval(
        diagnostics,
        stage=stage,
        started_at=started_at,
        finished_at=perf_counter(),
    )


def record_context_stage_interval(
    diagnostics: dict[str, object],
    *,
    stage: str,
    started_at: float,
    finished_at: float,
) -> None:
    """Record an explicit interval so sequential stage boundaries stay testable."""
    record_context_stage_duration(
        diagnostics,
        stage=stage,
        duration_ms=(finished_at - started_at) * 1000,
    )


def record_context_stage_duration(
    diagnostics: dict[str, object],
    *,
    stage: str,
    duration_ms: object,
) -> None:
    """Record one fixed-name duration and reject dynamic stage labels."""
    if stage not in CONTEXT_STAGE_NAMES:
        return
    timings = diagnostics.get("stage_timings_ms")
    if not isinstance(timings, dict):
        timings = {}
        diagnostics["stage_timings_ms"] = timings
    if len(timings) >= MAX_CONTEXT_STAGE_TIMINGS and stage not in timings:
        return
    timings[stage] = _bounded_duration(duration_ms)


def normalize_context_stage_timings(value: object) -> dict[str, float]:
    """Return only allowlisted names with bounded numeric values."""
    if not isinstance(value, dict):
        return {}
    return {
        stage: _bounded_duration(value[stage]) for stage in CONTEXT_STAGE_NAMES if stage in value
    }


def _bounded_duration(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    duration = float(value)
    if not isfinite(duration):
        return 0.0
    return round(min(MAX_CONTEXT_STAGE_DURATION_MS, max(0.0, duration)), 2)
