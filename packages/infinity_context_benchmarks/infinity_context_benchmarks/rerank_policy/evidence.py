"""Benchmark-owned evidence scoring policy."""

from __future__ import annotations

from infinity_context_benchmarks.rerank_policy.common import (
    _has_measured_locality_below,
    _has_positive_boost,
    _reason_codes,
    _rounded_boosts,
)
from infinity_context_benchmarks.rerank_policy.contracts import (
    RerankPolicyContribution,
    RerankPolicyFeatures,
)


class EntitySpeakerPolicy:
    name = "EntitySpeakerPolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        lexical_boost = min(0.16, 0.035 * len(features.overlap_terms))
        entity_boost = min(0.12, 0.055 * len(features.entity_hits))
        speaker_boost = min(0.12, 0.08 * len(features.speaker_hits))
        speaker_grounding_boost = 0.045 if _speaker_grounding_eligible(features) else 0.0
        return RerankPolicyContribution(
            policy=self.name,
            score=(lexical_boost + entity_boost + speaker_boost + speaker_grounding_boost),
            signals={
                "benchmark_query_overlap_boost": round(lexical_boost, 6),
                "benchmark_entity_boost": round(entity_boost, 6),
                "benchmark_speaker_boost": round(speaker_boost, 6),
                "benchmark_speaker_grounding_boost": round(
                    speaker_grounding_boost,
                    6,
                ),
                "benchmark_speaker_grounding_evidence": bool(speaker_grounding_boost),
            },
            reason_codes=_reason_codes(
                ("query_overlap", lexical_boost),
                ("entity_hit", entity_boost),
                ("speaker_hit", speaker_boost),
                ("speaker_grounding", speaker_grounding_boost),
            ),
        )


class RelationCoveragePolicy:
    name = "RelationCoveragePolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        relation_boost = _relation_boost(features)
        relation_coverage_boost = _relation_coverage_boost(features)
        relation_category_boost = _relation_category_coverage_boost(features)
        strong_relation_evidence = (
            len(features.relation_hits) >= 4
            or features.high_signal_relation_hit_count > 0
            or (bool(features.relation_category_hits) and len(features.relation_hits) >= 2)
        )
        return RerankPolicyContribution(
            policy=self.name,
            score=relation_boost + relation_coverage_boost + relation_category_boost,
            signals={
                "benchmark_relation_boost": round(relation_boost, 6),
                "benchmark_relation_coverage_boost": round(
                    relation_coverage_boost,
                    6,
                ),
                "benchmark_relation_category_coverage_boost": round(
                    relation_category_boost,
                    6,
                ),
                "benchmark_relation_categories": list(features.relation_categories),
                "benchmark_relation_category_hits": list(features.relation_category_hits),
                "benchmark_relation_category_coverage_ratio": round(
                    features.relation_category_coverage_ratio,
                    6,
                ),
                "benchmark_relation_variant_hit_count": len(features.relation_hits),
                "benchmark_strong_relation_evidence": strong_relation_evidence,
            },
            reason_codes=_reason_codes(
                ("relation_hit", relation_boost),
                ("relation_coverage", relation_coverage_boost),
                ("relation_category_coverage", relation_category_boost),
                ("strong_relation_evidence", float(strong_relation_evidence)),
            ),
        )


class FocusedTurnPolicy:
    name = "FocusedTurnPolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        focused_density_boost = _focused_relation_density_boost(features)
        direct_speaker_relation_evidence = _direct_speaker_relation_grounded(
            features,
            relation_hit_count=2,
        )
        rich_direct_speaker_relation_evidence = _direct_speaker_relation_grounded(
            features,
            relation_hit_count=3,
        )
        direct_speaker_relation_boost = (
            0.12
            if rich_direct_speaker_relation_evidence
            else 0.08
            if direct_speaker_relation_evidence
            else 0.0
        )
        communication_direction_boost = 0.09 if features.communication_direction_grounded else 0.0
        communication_direction_penalty = (
            -0.06 if features.communication_direction_ungrounded else 0.0
        )
        return RerankPolicyContribution(
            policy=self.name,
            score=(
                features.focused_turn_boost
                + focused_density_boost
                + direct_speaker_relation_boost
                + communication_direction_boost
                + communication_direction_penalty
            ),
            signals={
                "benchmark_focused_turn_boost": round(
                    features.focused_turn_boost,
                    6,
                ),
                "benchmark_focused_relation_density_boost": round(
                    focused_density_boost,
                    6,
                ),
                "benchmark_direct_speaker_relation_boost": round(
                    direct_speaker_relation_boost,
                    6,
                ),
                "benchmark_direct_speaker_relation_evidence": (direct_speaker_relation_evidence),
                "benchmark_rich_direct_speaker_relation_evidence": (
                    rich_direct_speaker_relation_evidence
                ),
                "benchmark_communication_direction_boost": round(
                    communication_direction_boost,
                    6,
                ),
                "benchmark_communication_direction_penalty": round(
                    communication_direction_penalty,
                    6,
                ),
                "benchmark_communication_direction_grounded": (
                    features.communication_direction_grounded
                ),
                "benchmark_communication_direction_ungrounded": (
                    features.communication_direction_ungrounded
                ),
                "benchmark_communication_query_direction": (features.communication_query_direction),
            },
            reason_codes=_reason_codes(
                ("focused_turn", features.focused_turn_boost),
                ("focused_relation_density", focused_density_boost),
                ("direct_speaker_relation", direct_speaker_relation_boost),
                ("communication_direction_grounded", communication_direction_boost),
                (
                    "communication_direction_ungrounded",
                    abs(communication_direction_penalty),
                ),
            ),
        )


class EvidenceBundlePolicy:
    name = "EvidenceBundlePolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        visual_grounded = _visual_evidence_grounded(features)
        visual_boost = (
            0.16
            if features.has_visual_terms and features.has_visual_evidence and visual_grounded
            else 0.0
        )
        shape_boosts = _rounded_boosts(features.shape_boosts)
        direct_provenance_boost = (
            0.025
            if features.direct_speaker_turn
            and not features.broad_summary
            and (features.source_ref_count > 0 or features.turn_ref_count > 0)
            else 0.0
        )
        return RerankPolicyContribution(
            policy=self.name,
            score=visual_boost + direct_provenance_boost + sum(shape_boosts.values()),
            signals={
                "benchmark_visual_evidence_boost": round(visual_boost, 6),
                "benchmark_visual_evidence_grounded": visual_grounded,
                "benchmark_direct_provenance_boost": round(
                    direct_provenance_boost,
                    6,
                ),
                **shape_boosts,
            },
            reason_codes=(
                *_reason_codes(
                    ("visual_evidence", visual_boost),
                    ("direct_provenance", direct_provenance_boost),
                ),
                *(f"evidence_shape:{key}" for key, value in shape_boosts.items() if value > 0),
            ),
        )


class SourceGroundingPolicy:
    name = "SourceGroundingPolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        grounded = _source_grounding_evidence_grounded(features)
        plausible_ungrounded = _source_grounding_plausible_but_ungrounded(
            features,
            grounded=grounded,
        )
        evidence_boost = (
            0.11
            if features.source_grounding_query and grounded and features.direct_speaker_turn
            else 0.075
            if features.source_grounding_query and grounded
            else 0.0
        )
        ungrounded_penalty = -0.08 if plausible_ungrounded else 0.0
        return RerankPolicyContribution(
            policy=self.name,
            score=evidence_boost + ungrounded_penalty,
            signals={
                "benchmark_source_grounding_query": features.source_grounding_query,
                "benchmark_source_grounding_evidence": grounded,
                "benchmark_source_grounding_support": (features.source_grounding_support),
                "benchmark_source_grounding_support_reason": (
                    features.source_grounding_support_reason
                ),
                "benchmark_source_grounding_quote_relevant": (
                    features.source_grounding_quote_relevant
                ),
                "benchmark_source_grounding_boost": round(evidence_boost, 6),
                "benchmark_source_grounding_ungrounded_penalty": round(
                    ungrounded_penalty,
                    6,
                ),
            },
            reason_codes=(
                *_reason_codes(("source_grounding_evidence", evidence_boost)),
                *(("source_grounding_plausible_ungrounded",) if ungrounded_penalty < 0 else ()),
            ),
        )


def _relation_boost(features: RerankPolicyFeatures) -> float:
    relation_hit_count = len(features.relation_hits)
    if relation_hit_count >= 4:
        return 0.16 if features.entity_hits or not features.query_has_entities else 0.14
    if relation_hit_count >= 3:
        return 0.14 if features.entity_hits or not features.query_has_entities else 0.105
    if features.relation_hits and (features.entity_hits or not features.query_has_entities):
        return 0.11 if relation_hit_count >= 2 else 0.055
    if relation_hit_count >= 2:
        return 0.075
    return 0.0


def _relation_coverage_boost(features: RerankPolicyFeatures) -> float:
    if features.high_signal_relation_hit_count >= 2:
        return 0.065
    relation_hit_count = len(features.relation_hits)
    if relation_hit_count >= 10:
        return 0.12
    if relation_hit_count >= 8:
        return 0.09
    if relation_hit_count >= 6:
        return 0.055
    return 0.0


def _relation_category_coverage_boost(features: RerankPolicyFeatures) -> float:
    if not features.relation_categories or not features.relation_category_hits:
        return 0.0
    if len(features.relation_hits) < 2 and features.high_signal_relation_hit_count == 0:
        if (
            features.direct_speaker_turn
            and ("activity" in features.relation_terms or "hike" in features.relation_terms)
            and features.relation_category_coverage_ratio >= 1.0
        ):
            return 0.045
        return 0.0
    base = 0.025
    if features.relation_category_coverage_ratio >= 1.0:
        base += 0.02
    elif features.relation_category_coverage_ratio >= 0.5:
        base += 0.01
    if features.direct_speaker_turn:
        base += 0.01
    return min(0.06, base)


def _focused_relation_density_boost(features: RerankPolicyFeatures) -> float:
    if features.focused_turn_boost <= 0:
        return 0.0
    if {"write", "career"}.issubset(set(features.relation_terms)):
        return 0.0
    relation_hit_count = len(features.relation_hits)
    if relation_hit_count >= 5 and features.high_signal_relation_hit_count >= 1:
        return 0.08
    if relation_hit_count >= 4:
        return 0.06
    if relation_hit_count >= 3 and features.high_signal_relation_hit_count >= 1:
        return 0.05
    return 0.0


def _speaker_grounding_eligible(features: RerankPolicyFeatures) -> bool:
    return bool(
        features.query_has_entities
        and features.speaker_hits
        and features.direct_speaker_turn
        and not features.broad_summary
        and not _has_measured_locality_below(features, 0.65)
        and not _has_positive_boost(features.policy_boosts)
        and not _has_positive_boost(features.shape_boosts)
    )


def _visual_evidence_grounded(features: RerankPolicyFeatures) -> bool:
    if not features.has_visual_evidence:
        return False
    if features.broad_summary:
        return False
    if 0 < features.source_locality_score < 0.65:
        return False
    if features.query_has_entities and not (features.entity_hits or features.speaker_hits):
        return False
    return bool(
        features.direct_speaker_turn or features.source_ref_count > 0 or features.turn_ref_count > 0
    )


def _source_grounding_evidence_grounded(features: RerankPolicyFeatures) -> bool:
    if not features.source_grounding_query:
        return False
    if not features.source_grounding_support:
        return False
    if features.broad_summary:
        return False
    if (
        _has_measured_locality_below(features, 0.65)
        and not features.source_grounding_quote_relevant
    ):
        return False
    if not (
        features.direct_speaker_turn or features.turn_ref_count > 0 or features.source_ref_count > 0
    ):
        return False
    if features.query_has_entities and not (features.entity_hits or features.speaker_hits):
        return False
    return bool(
        features.speaker_hits
        or features.relation_hits
        or features.relation_category_hits
        or features.covered_answer_unit_shapes
        or len(features.overlap_terms) >= 2
    )


def _source_grounding_plausible_but_ungrounded(
    features: RerankPolicyFeatures,
    *,
    grounded: bool,
) -> bool:
    if not features.source_grounding_query or grounded:
        return False
    if features.broad_summary:
        return True
    plausible_answer = bool(
        features.entity_hits
        or features.speaker_hits
        or features.relation_hits
        or len(features.overlap_terms) >= 2
    )
    if not plausible_answer:
        return False
    return bool(
        not features.direct_speaker_turn
        or _has_measured_locality_below(features, 0.65)
        or (features.source_ref_count == 0 and features.turn_ref_count == 0)
    )


def _direct_speaker_relation_grounded(
    features: RerankPolicyFeatures,
    *,
    relation_hit_count: int,
) -> bool:
    return bool(
        features.speaker_hits
        and len(features.relation_hits) >= relation_hit_count
        and features.direct_speaker_turn
        and not features.broad_summary
        and not _has_measured_locality_below(features, 0.65)
    )
