"""Explicit compatibility exports for benchmark-owned candidate scoring.

Canonical metadata names the benchmark implementation owner. Historical imports
and pickles continue resolving through these aliases, including typed delegates
for private helpers whose concrete/protocol annotations intentionally differ.
"""

from __future__ import annotations

# ruff: noqa: F401
from collections.abc import Mapping
from dataclasses import dataclass, field

from infinity_context_benchmarks.rerank_policy.common import _rounded_boosts
from infinity_context_benchmarks.rerank_policy.contracts import (
    BenchmarkRerankFeatures,
    BenchmarkRerankScore,
)
from infinity_context_benchmarks.rerank_policy.scoring import (
    _apply_provenance_safety_cap,
    _bool_signal,
    _boost_cap,
    _current_goal_temporal_context_grounded,
    _float_signal,
    _focused_relation_density_boost,
    _has_contrast_grounding,
    _has_count_list_answer_grounding,
    _has_precise_grounding,
    _has_role_specific_grounding,
    _has_temporal_sequence_direction_conflict,
    _has_unmeasured_source_ref_locality,
    _partial_commitment_status_evidence,
    _provenance_safety_cap,
    _relation_boost,
    _relation_coverage_boost,
    _stale_only_current_state_evidence,
    score_benchmark_rerank_candidate,
    score_rerank_policy_contributions,
)
