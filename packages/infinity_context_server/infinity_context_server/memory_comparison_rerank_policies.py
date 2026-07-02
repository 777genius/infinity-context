"""Composable policy contributions for benchmark reranking."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol


class RerankPolicyFeatures(Protocol):
    overlap_terms: tuple[str, ...]
    entity_hits: tuple[str, ...]
    speaker_hits: tuple[str, ...]
    relation_hits: tuple[str, ...]
    relation_terms: tuple[str, ...]
    relation_categories: tuple[str, ...]
    relation_category_hits: tuple[str, ...]
    relation_category_coverage_ratio: float
    query_has_entities: bool
    high_signal_relation_hit_count: int
    is_temporal_query: bool
    time_intent_kind: str
    has_temporal_surface: bool
    has_sequence_surface: bool
    has_duration_surface: bool
    has_relative_time_surface: bool
    has_explicit_time_surface: bool
    has_explicit_time_content_surface: bool
    has_temporal_sequence_surface: bool
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
            "contributions": [
                contribution.to_diagnostics() for contribution in self.contributions
            ],
            "reason_codes_by_policy": {
                contribution.policy: list(contribution.reason_codes)
                for contribution in active
            },
        }


class RerankPolicy(Protocol):
    name: str

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        """Score one policy for a candidate."""


class EntitySpeakerPolicy:
    name = "EntitySpeakerPolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        lexical_boost = min(0.16, 0.035 * len(features.overlap_terms))
        entity_boost = min(0.12, 0.055 * len(features.entity_hits))
        speaker_boost = min(0.12, 0.08 * len(features.speaker_hits))
        speaker_grounding_boost = (
            0.045 if _speaker_grounding_eligible(features) else 0.0
        )
        return RerankPolicyContribution(
            policy=self.name,
            score=(
                lexical_boost
                + entity_boost
                + speaker_boost
                + speaker_grounding_boost
            ),
            signals={
                "benchmark_query_overlap_boost": round(lexical_boost, 6),
                "benchmark_entity_boost": round(entity_boost, 6),
                "benchmark_speaker_boost": round(speaker_boost, 6),
                "benchmark_speaker_grounding_boost": round(
                    speaker_grounding_boost,
                    6,
                ),
                "benchmark_speaker_grounding_evidence": bool(
                    speaker_grounding_boost
                ),
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
            or (
                bool(features.relation_category_hits)
                and len(features.relation_hits) >= 2
            )
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
                "benchmark_relation_category_hits": list(
                    features.relation_category_hits
                ),
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


class TemporalPolicy:
    name = "TemporalPolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        temporal_boost, temporal_reason = _typed_temporal_boost(features)
        sequence_boost = (
            0.055
            if features.is_temporal_query
            and features.has_temporal_sequence_surface
            else 0.0
        )
        currentness_boost = (
            0.04
            if features.is_temporal_query
            and features.currentness_surface
            and (features.entity_hits or features.relation_hits)
            else 0.0
        )
        role_support_boost = (
            0.055
            if _temporal_role_support_eligible(features)
            else 0.0
        )
        return RerankPolicyContribution(
            policy=self.name,
            score=(
                temporal_boost
                + sequence_boost
                + currentness_boost
                + role_support_boost
            ),
            signals={
                "benchmark_time_intent_kind": features.time_intent_kind,
                "benchmark_temporal_query_roles": list(features.query_roles),
                "benchmark_temporal_text_boost": round(temporal_boost, 6),
                "benchmark_temporal_sequence_boost": round(sequence_boost, 6),
                "benchmark_currentness_support_boost": round(
                    currentness_boost,
                    6,
                ),
                "benchmark_temporal_role_support_boost": round(
                    role_support_boost,
                    6,
                ),
                "benchmark_typed_temporal_reason": temporal_reason,
                "benchmark_has_duration_surface": features.has_duration_surface,
                "benchmark_has_relative_time_surface": (
                    features.has_relative_time_surface
                ),
                "benchmark_has_explicit_time_surface": (
                    features.has_explicit_time_surface
                ),
                "benchmark_has_explicit_time_content_surface": (
                    features.has_explicit_time_content_surface
                ),
                "benchmark_has_temporal_sequence_surface": (
                    features.has_temporal_sequence_surface
                ),
            },
            reason_codes=(
                *_reason_codes(
                    (temporal_reason, temporal_boost),
                    (
                        f"time_intent:{features.time_intent_kind}",
                        float(
                            features.is_temporal_query
                            and bool(features.time_intent_kind)
                            and features.time_intent_kind != "none"
                        ),
                    ),
                ),
                *_reason_codes(
                    ("temporal_sequence", sequence_boost),
                    ("currentness_support", currentness_boost),
                    ("temporal_query_role_support", role_support_boost),
                ),
            ),
        )


class PreferenceIntentPolicy:
    name = "PreferenceIntentPolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        grounded = _preference_evidence_grounded(features)
        preference_boost = (
            0.12
            if features.is_preference_query
            and features.has_preference_evidence
            and grounded
            else 0.0
        )
        policy_boosts = _rounded_boosts(features.policy_boosts)
        return RerankPolicyContribution(
            policy=self.name,
            score=preference_boost + sum(policy_boosts.values()),
            signals={
                "benchmark_preference_evidence_boost": round(preference_boost, 6),
                "benchmark_preference_evidence_grounded": grounded,
                **policy_boosts,
            },
            reason_codes=(
                *_reason_codes(("preference_evidence", preference_boost)),
                *(
                    f"focused_intent:{key}"
                    for key, value in policy_boosts.items()
                    if value > 0
                ),
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
        return RerankPolicyContribution(
            policy=self.name,
            score=(
                features.focused_turn_boost
                + focused_density_boost
                + direct_speaker_relation_boost
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
                "benchmark_direct_speaker_relation_evidence": (
                    direct_speaker_relation_evidence
                ),
                "benchmark_rich_direct_speaker_relation_evidence": (
                    rich_direct_speaker_relation_evidence
                ),
            },
            reason_codes=_reason_codes(
                ("focused_turn", features.focused_turn_boost),
                ("focused_relation_density", focused_density_boost),
                ("direct_speaker_relation", direct_speaker_relation_boost),
            ),
        )


class EvidenceBundlePolicy:
    name = "EvidenceBundlePolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        visual_grounded = _visual_evidence_grounded(features)
        visual_boost = (
            0.16
            if features.has_visual_terms
            and features.has_visual_evidence
            and visual_grounded
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
                *(
                    f"evidence_shape:{key}"
                    for key, value in shape_boosts.items()
                    if value > 0
                ),
            ),
        )


class AnswerabilityPolicy:
    name = "AnswerabilityPolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        eligible = _answerability_boost_eligible(features)
        boost = _answerability_boost(features.answerability_score) if eligible else 0.0
        return RerankPolicyContribution(
            policy=self.name,
            score=boost,
            signals={
                "benchmark_answerability_score": round(
                    features.answerability_score,
                    6,
                ),
                "benchmark_answerability_boost": round(boost, 6),
                "benchmark_answerability_boost_eligible": eligible,
                "benchmark_answerability_reason_codes": list(
                    features.answerability_reason_codes
                ),
            },
            reason_codes=tuple(
                reason
                for reason in features.answerability_reason_codes
                if reason
                in {
                    "high_answerability",
                    "medium_answerability",
                    "direct_provenance",
                    "source_provenance",
                    "intent_satisfied",
                    "intent_partial",
                }
            ),
        )


class MultiHopPolicy:
    name = "MultiHopPolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        boost = (
            0.035
            if features.has_multi_hop_markers and len(features.overlap_terms) >= 2
            else 0.0
        )
        return RerankPolicyContribution(
            policy=self.name,
            score=boost,
            signals={"benchmark_multi_hop_support_boost": round(boost, 6)},
            reason_codes=_reason_codes(("multi_hop_support", boost)),
        )


class ContrastIntentPolicy:
    name = "ContrastIntentPolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        penalty = -0.06 if features.conflict_or_stale else 0.0
        support_boost = (
            0.045
            if _contrast_boost_eligible(features)
            else 0.0
        )
        return RerankPolicyContribution(
            policy=self.name,
            score=penalty + support_boost,
            signals={
                "benchmark_contrast_penalty": round(penalty, 6),
                "benchmark_contrast_support_boost": round(support_boost, 6),
                "benchmark_negation_surface": features.negation_surface,
                "benchmark_currentness_surface": features.currentness_surface,
                "benchmark_stale_surface": features.stale_surface,
                "benchmark_contrast_surface": features.contrast_surface,
            },
            reason_codes=(
                *(("conflict_or_stale",) if penalty < 0 else ()),
                *_reason_codes(("contrast_support", support_boost)),
            ),
        )


class LocationIntentPolicy:
    name = "LocationIntentPolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        location_hit_count = len(
            _LOCATION_SUPPORT_TERMS.intersection(features.relation_hits)
        )
        location_need = (
            "location_support" in set(features.evidence_need)
            or "location_transition" in set(features.relation_categories)
        )
        category_hit = "location_transition" in set(features.relation_category_hits)
        precise_provenance = (
            features.direct_speaker_turn
            or (
                features.source_locality_score >= 0.65
                and not features.broad_summary
            )
        )
        evidence_boost = (
            0.05
            if location_need
            and category_hit
            and location_hit_count >= 2
            and precise_provenance
            else 0.0
        )
        role_boost = (
            0.035
            if evidence_boost > 0 and "location_support" in set(features.query_roles)
            else 0.0
        )
        return RerankPolicyContribution(
            policy=self.name,
            score=evidence_boost + role_boost,
            signals={
                "benchmark_location_support_boost": round(evidence_boost, 6),
                "benchmark_location_query_role_boost": round(role_boost, 6),
                "benchmark_location_relation_hit_count": location_hit_count,
                "benchmark_location_relation_category_hit": category_hit,
                "benchmark_location_precise_provenance": precise_provenance,
            },
            reason_codes=(
                *_reason_codes(("location_support", evidence_boost)),
                *_reason_codes(("location_query_role_support", role_boost)),
            ),
        )


class TypedRelationSupportPolicy:
    name = "TypedRelationSupportPolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        support_roles = _typed_relation_support_roles(features)
        category_hits = _typed_relation_support_category_hits(features, support_roles)
        precise_provenance = features.direct_speaker_turn or (
            features.source_locality_score >= 0.65 and not features.broad_summary
        )
        grounded = bool(
            category_hits
            and precise_provenance
            and _typed_relation_support_grounded(features, support_roles)
        )
        evidence_boost = min(0.06, 0.045 * len(category_hits)) if grounded else 0.0
        role_boost = (
            min(0.03, 0.02 * len(support_roles))
            if evidence_boost > 0 and support_roles
            else 0.0
        )
        return RerankPolicyContribution(
            policy=self.name,
            score=evidence_boost + role_boost,
            signals={
                "benchmark_typed_relation_support_boost": round(
                    evidence_boost,
                    6,
                ),
                "benchmark_typed_relation_query_role_boost": round(
                    role_boost,
                    6,
                ),
                "benchmark_typed_relation_support_roles": list(support_roles),
                "benchmark_typed_relation_support_category_hits": list(
                    category_hits
                ),
                "benchmark_typed_relation_support_precise_provenance": (
                    precise_provenance
                ),
            },
            reason_codes=(
                *_reason_codes(("typed_relation_support", evidence_boost)),
                *_reason_codes(("typed_relation_query_role_support", role_boost)),
            ),
        )


def score_rerank_policy_contributions(
    features: RerankPolicyFeatures,
    *,
    policies: Sequence[RerankPolicy] = (),
) -> RerankPolicyPlan:
    active_policies = tuple(policies) or _DEFAULT_POLICIES
    return RerankPolicyPlan(
        contributions=tuple(policy.score(features) for policy in active_policies)
    )


def _relation_boost(features: RerankPolicyFeatures) -> float:
    relation_hit_count = len(features.relation_hits)
    if relation_hit_count >= 4:
        return 0.16 if features.entity_hits or not features.query_has_entities else 0.14
    if relation_hit_count >= 3:
        return 0.14 if features.entity_hits or not features.query_has_entities else 0.105
    if features.relation_hits and (
        features.entity_hits or not features.query_has_entities
    ):
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
            and (
                "activity" in features.relation_terms
                or "hike" in features.relation_terms
            )
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
        and features.source_locality_score >= 0.65
        and not _has_positive_boost(features.policy_boosts)
        and not _has_positive_boost(features.shape_boosts)
    )


def _preference_evidence_grounded(features: RerankPolicyFeatures) -> bool:
    if not features.has_preference_evidence:
        return False
    if features.broad_summary:
        return False
    if features.source_locality_score < 0.65:
        return False
    if features.query_has_entities and not (features.entity_hits or features.speaker_hits):
        return False
    return bool(features.direct_speaker_turn or features.relation_hits)


def _visual_evidence_grounded(features: RerankPolicyFeatures) -> bool:
    if not features.has_visual_evidence:
        return False
    if features.broad_summary:
        return False
    if features.source_locality_score < 0.65:
        return False
    if features.query_has_entities and not (features.entity_hits or features.speaker_hits):
        return False
    return bool(
        features.direct_speaker_turn
        or features.source_ref_count > 0
        or features.turn_ref_count > 0
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
        and features.source_locality_score >= 0.65
    )


def _has_positive_boost(boosts: Mapping[str, float]) -> bool:
    return any(float(value) > 0 for value in boosts.values())


def _rounded_boosts(boosts: Mapping[str, float]) -> dict[str, float]:
    return {key: round(float(value), 6) for key, value in boosts.items()}


def _typed_temporal_boost(features: RerankPolicyFeatures) -> tuple[float, str]:
    if not features.is_temporal_query:
        return 0.0, "not_temporal_query"
    generic_temporal = _has_content_temporal_evidence(features)
    time_kind = features.time_intent_kind
    if time_kind == "duration":
        if features.has_duration_surface:
            return 0.085, "duration_temporal_evidence"
        return (0.025, "duration_temporal_evidence_partial") if generic_temporal else (
            0.0,
            "missing_duration_temporal_evidence",
        )
    if time_kind == "relative_time":
        if features.has_relative_time_surface:
            return 0.08, "relative_temporal_evidence"
        return (0.03, "relative_temporal_evidence_partial") if generic_temporal else (
            0.0,
            "missing_relative_temporal_evidence",
        )
    if time_kind == "explicit_time":
        if features.has_explicit_time_content_surface:
            return 0.08, "explicit_temporal_evidence"
        return (0.03, "explicit_temporal_evidence_partial") if generic_temporal else (
            0.0,
            "missing_explicit_temporal_evidence",
        )
    if time_kind == "temporal_sequence":
        if features.has_temporal_sequence_surface:
            return 0.08, "sequence_temporal_evidence"
        return (0.025, "sequence_temporal_evidence_partial") if generic_temporal else (
            0.0,
            "missing_sequence_temporal_evidence",
        )
    if generic_temporal:
        return 0.07, "generic_temporal_evidence"
    return 0.0, "missing_temporal_evidence"


def _temporal_role_support_eligible(features: RerankPolicyFeatures) -> bool:
    if not features.is_temporal_query:
        return False
    if not _has_temporal_query_role(features.query_roles):
        return False
    if not (
        features.entity_hits
        or features.speaker_hits
        or len(features.overlap_terms) >= 2
    ):
        return False
    return bool(
        features.has_duration_surface
        or features.has_relative_time_surface
        or features.has_explicit_time_content_surface
        or features.has_temporal_sequence_surface
    )


def _has_content_temporal_evidence(features: RerankPolicyFeatures) -> bool:
    return bool(
        features.has_duration_surface
        or features.has_relative_time_surface
        or features.has_explicit_time_content_surface
        or features.has_temporal_sequence_surface
    )


def _has_temporal_query_role(query_roles: Sequence[str]) -> bool:
    return any(
        role
        in {
            "temporal_support",
            "duration_temporal_support",
            "explicit_temporal_support",
            "relative_temporal_support",
            "temporal_sequence_support",
            "visual_temporal_support",
        }
        for role in query_roles
    )


def _answerability_boost(score: float) -> float:
    if score >= 0.86:
        return 0.1
    if score >= 0.74:
        return 0.07
    if score >= 0.58:
        return 0.035
    return 0.0


def _answerability_boost_eligible(features: RerankPolicyFeatures) -> bool:
    if not features.relation_terms:
        return True
    return len(features.relation_hits) >= 2 or features.high_signal_relation_hit_count > 0


def _contrast_boost_eligible(features: RerankPolicyFeatures) -> bool:
    if not features.contrast_surface:
        return False
    if len(features.relation_hits) < 2 and features.high_signal_relation_hit_count == 0:
        return False
    return bool(
        {"contrast", "inference_support", "causal_support", "temporal_sequence"}
        & set(features.evidence_need)
    )


_TYPED_RELATION_SUPPORT_ROLE_CATEGORIES = {
    "causal_support": frozenset({"causal"}),
    "communication_support": frozenset({"communication"}),
    "emotion_response_support": frozenset({"emotion_response"}),
    "event_support": frozenset({"participation_event", "registration_event"}),
    "exchange_support": frozenset({"exchange"}),
    "symbolic_meaning_support": frozenset({"symbolic_meaning"}),
}
_TYPED_RELATION_SUPPORT_NEEDS = {
    "causal_support": frozenset({"causal_support"}),
    "communication_support": frozenset({"communication"}),
    "emotion_response_support": frozenset({"emotion_response"}),
    "event_support": frozenset({"participation_event", "registration_event"}),
    "exchange_support": frozenset({"exchange"}),
    "symbolic_meaning_support": frozenset({"symbolic_meaning"}),
}


def _typed_relation_support_roles(
    features: RerankPolicyFeatures,
) -> tuple[str, ...]:
    evidence_needs = set(features.evidence_need)
    relation_categories = set(features.relation_categories)
    query_roles = set(features.query_roles)
    roles: list[str] = []
    for role, categories in _TYPED_RELATION_SUPPORT_ROLE_CATEGORIES.items():
        role_needed = bool(
            role in query_roles
            or categories & relation_categories
            or _TYPED_RELATION_SUPPORT_NEEDS[role] & evidence_needs
        )
        if role_needed:
            roles.append(role)
    return tuple(roles)


def _typed_relation_support_category_hits(
    features: RerankPolicyFeatures,
    support_roles: Sequence[str],
) -> tuple[str, ...]:
    category_hits = set(features.relation_category_hits)
    hits: list[str] = []
    for role in support_roles:
        hits.extend(
            category
            for category in _TYPED_RELATION_SUPPORT_ROLE_CATEGORIES[role]
            if category in category_hits
        )
    return tuple(dict.fromkeys(hits))


def _typed_relation_support_grounded(
    features: RerankPolicyFeatures,
    support_roles: Sequence[str],
) -> bool:
    if not (features.relation_hits or features.high_signal_relation_hit_count > 0):
        return False
    if "communication_support" in set(support_roles) and features.query_has_entities:
        return bool(features.speaker_hits)
    return bool(
        features.entity_hits
        or features.speaker_hits
        or not features.query_has_entities
    )


_LOCATION_SUPPORT_TERMS = frozenset(
    {
        "city",
        "country",
        "drive",
        "from",
        "home",
        "origin",
        "relocated",
        "travel",
        "trip",
    }
)


def _reason_codes(*pairs: tuple[str, float]) -> tuple[str, ...]:
    return tuple(reason for reason, score in pairs if score > 0)


_DEFAULT_POLICIES: tuple[RerankPolicy, ...] = (
    EntitySpeakerPolicy(),
    RelationCoveragePolicy(),
    TemporalPolicy(),
    PreferenceIntentPolicy(),
    FocusedTurnPolicy(),
    EvidenceBundlePolicy(),
    AnswerabilityPolicy(),
    MultiHopPolicy(),
    ContrastIntentPolicy(),
    TypedRelationSupportPolicy(),
    LocationIntentPolicy(),
)
