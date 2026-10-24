"""Benchmark-owned intent scoring policy."""

from __future__ import annotations

from infinity_context_benchmarks.rerank_policy.common import (
    _has_measured_locality_below,
    _has_missing_required_answer_evidence,
    _has_precise_or_unmeasured_source_provenance,
    _reason_codes,
    _rounded_boosts,
)
from infinity_context_benchmarks.rerank_policy.contracts import (
    RerankPolicyContribution,
    RerankPolicyFeatures,
)


class PreferenceIntentPolicy:
    name = "PreferenceIntentPolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        grounded = _preference_evidence_grounded(features)
        reason_required = _preference_reason_required(features)
        reason_grounded = _preference_reason_grounded(features)
        preference_boost = (
            0.12
            if features.is_preference_query
            and features.has_preference_evidence
            and grounded
            and (not reason_required or reason_grounded)
            else 0.0
        )
        policy_boosts = _rounded_boosts(features.policy_boosts)
        return RerankPolicyContribution(
            policy=self.name,
            score=preference_boost + sum(policy_boosts.values()),
            signals={
                "benchmark_preference_evidence_boost": round(preference_boost, 6),
                "benchmark_preference_evidence_grounded": grounded,
                "benchmark_preference_reason_required": reason_required,
                "benchmark_preference_reason_grounded": reason_grounded,
                **policy_boosts,
            },
            reason_codes=(
                *_reason_codes(("preference_evidence", preference_boost)),
                *_reason_codes(
                    (
                        "preference_reason_grounding",
                        float(reason_required and preference_boost > 0),
                    )
                ),
                *(f"focused_intent:{key}" for key, value in policy_boosts.items() if value > 0),
            ),
        )


class MultiHopPolicy:
    name = "MultiHopPolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        boost = (
            0.035 if features.has_multi_hop_markers and len(features.overlap_terms) >= 2 else 0.0
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
        support_boost = 0.045 if _contrast_boost_eligible(features) else 0.0
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


class NegativeAbsencePolicy:
    name = "NegativeAbsencePolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        needed = "negative_absence" in set(features.evidence_need)
        grounded = _negative_absence_evidence_grounded(features)
        support_boost = 0.075 if needed and grounded else 0.0
        positive_topic_penalty = (
            -0.035
            if needed
            and not grounded
            and not (
                features.negation_surface or features.stale_surface or features.contrast_surface
            )
            and (
                features.overlap_terms
                or features.entity_hits
                or features.speaker_hits
                or features.relation_hits
            )
            else 0.0
        )
        return RerankPolicyContribution(
            policy=self.name,
            score=support_boost + positive_topic_penalty,
            signals={
                "benchmark_negative_absence_needed": needed,
                "benchmark_negative_absence_evidence_grounded": grounded,
                "benchmark_negative_absence_support_boost": round(
                    support_boost,
                    6,
                ),
                "benchmark_negative_absence_positive_topic_penalty": round(
                    positive_topic_penalty,
                    6,
                ),
            },
            reason_codes=(
                *_reason_codes(("negative_absence_support", support_boost)),
                *(("negative_absence_positive_topic_conflict",) if positive_topic_penalty else ()),
            ),
        )


class LocationIntentPolicy:
    name = "LocationIntentPolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        location_hit_count = len(_LOCATION_SUPPORT_TERMS.intersection(features.relation_hits))
        location_need = "location_support" in set(
            features.evidence_need
        ) or "location_transition" in set(features.relation_categories)
        category_hit = "location_transition" in set(features.relation_category_hits)
        precise_provenance = _has_precise_or_unmeasured_source_provenance(features)
        evidence_boost = (
            0.05
            if location_need and category_hit and location_hit_count >= 1 and precise_provenance
            else 0.0
        )
        role_boost = (
            0.035 if evidence_boost > 0 and "location_support" in set(features.query_roles) else 0.0
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


def _preference_evidence_grounded(features: RerankPolicyFeatures) -> bool:
    if not features.has_preference_evidence:
        return False
    if features.broad_summary:
        return False
    if 0 < features.source_locality_score < 0.65:
        return False
    if features.query_has_entities and not (features.entity_hits or features.speaker_hits):
        return False
    if _has_typed_preference_relation_hit(features):
        return True
    if not features.direct_speaker_turn:
        return False
    non_preference_hits = set(features.relation_hits) - _PREFERENCE_POLARITY_TERMS
    return bool(non_preference_hits)


def _preference_reason_required(features: RerankPolicyFeatures) -> bool:
    return bool(features.is_preference_query and "causal_support" in set(features.evidence_need))


def _preference_reason_grounded(features: RerankPolicyFeatures) -> bool:
    if not _preference_reason_required(features):
        return True
    category_hits = set(features.relation_category_hits)
    preference_categories = {"preference", "favorite_preference"} & set(
        features.relation_categories
    )
    return bool(
        "causal" in category_hits
        and (not preference_categories or preference_categories & category_hits)
    )


def _has_typed_preference_relation_hit(features: RerankPolicyFeatures) -> bool:
    return bool({"preference", "favorite_preference"} & set(features.relation_category_hits))


def _contrast_boost_eligible(features: RerankPolicyFeatures) -> bool:
    if not features.contrast_surface:
        return False
    if len(features.relation_hits) < 2 and features.high_signal_relation_hit_count == 0:
        return False
    return bool(
        {"contrast", "inference_support", "causal_support", "temporal_sequence"}
        & set(features.evidence_need)
    )


def _negative_absence_evidence_grounded(features: RerankPolicyFeatures) -> bool:
    if not features.negation_surface:
        return False
    if features.broad_summary or features.conflict_or_stale:
        return False
    if _has_measured_locality_below(features, 0.45):
        return False
    if features.query_has_entities and not (features.entity_hits or features.speaker_hits):
        return False
    if _has_missing_required_answer_evidence(features) and not (
        len(features.overlap_terms) >= 2 or features.relation_hits
    ):
        return False
    return bool(
        features.direct_speaker_turn
        or features.source_ref_count > 0
        or features.turn_ref_count > 0
        or features.source_locality_score >= 0.65
        or features.relation_hits
        or len(features.overlap_terms) >= 2
    )


_PREFERENCE_POLARITY_TERMS = frozenset(
    {
        "avoid",
        "avoided",
        "avoids",
        "dislik",
        "dislike",
        "disliked",
        "enjoy",
        "enjoyed",
        "fan",
        "favorite",
        "favourite",
        "hat",
        "hate",
        "hated",
        "hates",
        "interest",
        "interested",
        "like",
        "liked",
        "love",
        "loved",
        "prefer",
        "preferred",
        "preference",
        "prioritize",
    }
)


_LOCATION_SUPPORT_TERMS = frozenset(
    {
        "born",
        "camp",
        "camped",
        "campground",
        "camping",
        "campsite",
        "city",
        "company",
        "country",
        "drive",
        "employer",
        "from",
        "gallery",
        "grew",
        "home",
        "hometown",
        "hotel",
        "museum",
        "office",
        "based",
        "bas",
        "barn",
        "ceremony",
        "live",
        "lived",
        "liv",
        "living",
        "move",
        "moved",
        "origin",
        "originally",
        "place",
        "rais",
        "raise",
        "relocated",
        "stay",
        "stayed",
        "staying",
        "reception",
        "travel",
        "trip",
        "theater",
        "theatre",
        "venue",
        "wedding",
        "work",
        "worked",
        "working",
        "workplace",
    }
)
