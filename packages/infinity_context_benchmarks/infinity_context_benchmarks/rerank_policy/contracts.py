"""Benchmark-owned contracts scoring policy."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class BenchmarkRerankFeatures:
    """Question-only candidate features used by benchmark rerank policies."""

    overlap_terms: tuple[str, ...]
    entity_hits: tuple[str, ...]
    speaker_hits: tuple[str, ...]
    relation_hits: tuple[str, ...]
    relation_terms: tuple[str, ...]
    query_has_entities: bool
    high_signal_relation_hit_count: int
    is_temporal_query: bool
    has_temporal_surface: bool
    has_sequence_surface: bool
    is_preference_query: bool
    has_preference_evidence: bool
    has_visual_terms: bool
    has_visual_evidence: bool
    focused_turn_boost: float
    has_multi_hop_markers: bool
    relation_categories: tuple[str, ...] = ()
    relation_category_hits: tuple[str, ...] = ()
    relation_category_coverage_ratio: float = 0.0
    communication_direction_grounded: bool = False
    communication_direction_ungrounded: bool = False
    communication_query_direction: str = ""
    exact_count_evidence: bool = False
    list_item_count: int = 0
    policy_boosts: Mapping[str, float] = field(default_factory=dict)
    shape_boosts: Mapping[str, float] = field(default_factory=dict)
    source_type: str = "unknown"
    source_ref_count: int = 0
    turn_ref_count: int = 0
    source_ref_density: float = 0.0
    source_locality_score: float = 1.0
    direct_speaker_turn: bool = False
    broad_summary: bool = False
    conflict_or_stale: bool = False
    negation_surface: bool = False
    currentness_surface: bool = False
    stale_surface: bool = False
    contrast_surface: bool = False
    answerability_score: float = 0.0
    answerability_reason_codes: tuple[str, ...] = ()
    evidence_need: tuple[str, ...] = ()
    query_roles: tuple[str, ...] = ()
    temporal_query_terms: tuple[str, ...] = ()
    current_state_query: bool = False
    time_intent_kind: str = ""
    has_duration_surface: bool = False
    has_relative_time_surface: bool = False
    has_explicit_time_surface: bool = False
    has_explicit_time_content_surface: bool = False
    has_temporal_sequence_surface: bool = False
    temporal_sequence_direction: str = ""
    covered_answer_unit_shapes: tuple[str, ...] = ()
    source_grounding_query: bool = False
    source_grounding_support: bool = False
    source_grounding_support_reason: str = ""
    source_grounding_quote_relevant: bool = False


@dataclass(frozen=True)
class BenchmarkRerankScore:
    """Final bounded boost and diagnostics for a rerank candidate."""

    boost: float
    signals: dict[str, object]


class RerankPolicyFeatures(Protocol):
    overlap_terms: tuple[str, ...]
    entity_hits: tuple[str, ...]
    speaker_hits: tuple[str, ...]
    relation_hits: tuple[str, ...]
    relation_terms: tuple[str, ...]
    relation_categories: tuple[str, ...]
    relation_category_hits: tuple[str, ...]
    relation_category_coverage_ratio: float
    covered_answer_unit_shapes: tuple[str, ...]
    exact_count_evidence: bool
    list_item_count: int
    query_has_entities: bool
    high_signal_relation_hit_count: int
    communication_direction_grounded: bool
    communication_direction_ungrounded: bool
    communication_query_direction: str
    is_temporal_query: bool
    time_intent_kind: str
    has_temporal_surface: bool
    has_sequence_surface: bool
    has_duration_surface: bool
    has_relative_time_surface: bool
    has_explicit_time_surface: bool
    has_explicit_time_content_surface: bool
    has_temporal_sequence_surface: bool
    temporal_sequence_direction: str
    is_preference_query: bool
    has_preference_evidence: bool
    has_visual_terms: bool
    has_visual_evidence: bool
    focused_turn_boost: float
    has_multi_hop_markers: bool
    policy_boosts: Mapping[str, float]
    shape_boosts: Mapping[str, float]
    source_type: str
    source_ref_count: int
    turn_ref_count: int
    source_ref_density: float
    source_locality_score: float
    direct_speaker_turn: bool
    broad_summary: bool
    conflict_or_stale: bool
    negation_surface: bool
    currentness_surface: bool
    stale_surface: bool
    contrast_surface: bool
    answerability_score: float
    answerability_reason_codes: tuple[str, ...]
    evidence_need: tuple[str, ...]
    query_roles: tuple[str, ...]
    temporal_query_terms: tuple[str, ...]
    current_state_query: bool
    source_grounding_query: bool
    source_grounding_support: bool
    source_grounding_support_reason: str
    source_grounding_quote_relevant: bool


@dataclass(frozen=True)
class RerankPolicyContribution:
    """One bounded policy contribution with diagnostics."""

    policy: str
    score: float
    signals: Mapping[str, object]
    reason_codes: tuple[str, ...]

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "policy": self.policy,
            "score": round(self.score, 6),
            "reason_codes": list(self.reason_codes),
            "signals": dict(self.signals),
        }


@dataclass(frozen=True)
class RerankPolicyPlan:
    """All policy contributions for one rerank candidate."""

    contributions: tuple[RerankPolicyContribution, ...]

    @property
    def score_signals(self) -> dict[str, object]:
        signals: dict[str, object] = {}
        for contribution in self.contributions:
            signals.update(contribution.signals)
        return signals

    @property
    def total_score(self) -> float:
        return round(sum(contribution.score for contribution in self.contributions), 6)

    def to_diagnostics(self) -> dict[str, object]:
        active = tuple(
            contribution
            for contribution in self.contributions
            if contribution.score != 0 or contribution.reason_codes
        )
        return {
            "schema_version": "benchmark_rerank_policy.v2",
            "total_raw_score": self.total_score,
            "active_policy_count": len(active),
            "contributions": [contribution.to_diagnostics() for contribution in self.contributions],
            "reason_codes_by_policy": {
                contribution.policy: list(contribution.reason_codes) for contribution in active
            },
        }


class RerankPolicy(Protocol):
    name: str

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        """Score one policy for a candidate."""
