"""Benchmark-owned typed relations scoring policy."""

from __future__ import annotations

from collections.abc import Sequence

from infinity_context_benchmarks.rerank_policy.common import (
    _has_precise_or_unmeasured_source_provenance,
    _reason_codes,
)
from infinity_context_benchmarks.rerank_policy.contracts import (
    RerankPolicyContribution,
    RerankPolicyFeatures,
)


class TypedRelationSupportPolicy:
    name = "TypedRelationSupportPolicy"

    def score(self, features: RerankPolicyFeatures) -> RerankPolicyContribution:
        support_roles = _typed_relation_support_roles(features)
        category_hits = _typed_relation_support_category_hits(features, support_roles)
        hit_roles = _typed_relation_support_hit_roles(features, support_roles)
        precise_provenance = _has_precise_or_unmeasured_source_provenance(features)
        grounded = bool(
            category_hits
            and precise_provenance
            and _typed_relation_support_grounded(features, support_roles)
        )
        evidence_boost = min(0.06, 0.045 * len(category_hits)) if grounded else 0.0
        role_boost = min(0.03, 0.02 * len(hit_roles)) if evidence_boost > 0 and hit_roles else 0.0
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
                "benchmark_typed_relation_support_category_hits": list(category_hits),
                "benchmark_typed_relation_support_hit_roles": list(hit_roles),
                "benchmark_typed_relation_support_precise_provenance": (precise_provenance),
            },
            reason_codes=(
                *_reason_codes(("typed_relation_support", evidence_boost)),
                *_reason_codes(("typed_relation_query_role_support", role_boost)),
            ),
        )


_TYPED_RELATION_SUPPORT_ROLE_CATEGORIES = {
    "action_support": frozenset({"action_event"}),
    "causal_support": frozenset({"causal"}),
    "activity_support": frozenset({"activity", "activity_profile"}),
    "age_support": frozenset({"age_profile"}),
    "alias_support": frozenset({"alias_profile"}),
    "commitment_support": frozenset({"commitment_profile"}),
    "community_membership_support": frozenset({"community_membership"}),
    "communication_support": frozenset({"communication"}),
    "contact_support": frozenset({"contact_profile"}),
    "current_goal_support": frozenset({"current_goal"}),
    "date_support": frozenset({"date_profile"}),
    "diet_support": frozenset({"diet_profile"}),
    "education_support": frozenset({"education_profile"}),
    "employment_support": frozenset({"employment_profile"}),
    "emotion_response_support": frozenset({"emotion_response"}),
    "event_support": frozenset({"participation_event", "registration_event"}),
    "exchange_support": frozenset({"exchange"}),
    "favorite_support": frozenset({"favorite_preference"}),
    "health_support": frozenset({"health_profile"}),
    "identity_support": frozenset({"identity_profile"}),
    "pet_support": frozenset({"pet_profile"}),
    "skill_support": frozenset({"skill_profile"}),
    "status_support": frozenset({"status_profile"}),
    "support_goal_support": frozenset({"support_goal"}),
    "symbolic_meaning_support": frozenset({"symbolic_meaning"}),
    "vehicle_support": frozenset({"vehicle_profile"}),
}


_TYPED_RELATION_SUPPORT_NEEDS = {
    "action_support": frozenset({"action_support"}),
    "causal_support": frozenset({"causal_support"}),
    "activity_support": frozenset({"activity_profile", "activity_support"}),
    "age_support": frozenset({"age_profile"}),
    "alias_support": frozenset({"alias_profile"}),
    "commitment_support": frozenset({"commitment_profile"}),
    "community_membership_support": frozenset({"community_membership"}),
    "communication_support": frozenset({"communication"}),
    "contact_support": frozenset({"contact_profile"}),
    "current_goal_support": frozenset({"current_goal"}),
    "date_support": frozenset({"date_profile"}),
    "diet_support": frozenset({"diet_profile"}),
    "education_support": frozenset({"education_profile"}),
    "employment_support": frozenset({"employment_profile"}),
    "emotion_response_support": frozenset({"emotion_response"}),
    "event_support": frozenset({"participation_event", "registration_event"}),
    "exchange_support": frozenset({"exchange"}),
    "favorite_support": frozenset({"favorite_preference"}),
    "health_support": frozenset({"health_profile"}),
    "identity_support": frozenset({"identity_profile"}),
    "pet_support": frozenset({"pet_profile"}),
    "skill_support": frozenset({"skill_profile"}),
    "status_support": frozenset({"status_profile"}),
    "support_goal_support": frozenset({"support_goal"}),
    "symbolic_meaning_support": frozenset({"symbolic_meaning"}),
    "vehicle_support": frozenset({"vehicle_profile"}),
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
        if role == "activity_support" and "activity_profile" in set(features.evidence_need):
            if "activity_profile" in category_hits:
                hits.append("activity_profile")
            continue
        hits.extend(
            category
            for category in _TYPED_RELATION_SUPPORT_ROLE_CATEGORIES[role]
            if category in category_hits
        )
    return tuple(dict.fromkeys(hits))


def _typed_relation_support_hit_roles(
    features: RerankPolicyFeatures,
    support_roles: Sequence[str],
) -> tuple[str, ...]:
    category_hits = set(features.relation_category_hits)
    return tuple(
        role
        for role in support_roles
        if category_hits.intersection(_TYPED_RELATION_SUPPORT_ROLE_CATEGORIES[role])
    )


def _typed_relation_support_grounded(
    features: RerankPolicyFeatures,
    support_roles: Sequence[str],
) -> bool:
    if _support_goal_category_grounded(features, support_roles):
        return True
    if not (
        features.relation_hits
        or features.high_signal_relation_hit_count > 0
        or _typed_profile_category_grounded(features, support_roles)
    ):
        return False
    if "communication_support" in set(support_roles) and features.query_has_entities:
        return bool(features.speaker_hits)
    return bool(features.entity_hits or features.speaker_hits or not features.query_has_entities)


def _support_goal_category_grounded(
    features: RerankPolicyFeatures,
    support_roles: Sequence[str],
) -> bool:
    if "support_goal_support" not in set(support_roles):
        return False
    if "support_goal" not in set(features.relation_category_hits):
        return False
    if features.broad_summary or features.conflict_or_stale:
        return False
    return bool(
        features.direct_speaker_turn
        or features.source_ref_count > 0
        or features.turn_ref_count > 0
        or features.source_locality_score >= 0.65
    )


def _typed_profile_category_grounded(
    features: RerankPolicyFeatures,
    support_roles: Sequence[str],
) -> bool:
    category_hits = set(features.relation_category_hits)
    if not category_hits:
        return False
    for role in support_roles:
        if category_hits.intersection(_TYPED_PROFILE_SUPPORT_CATEGORIES.get(role, ())):
            return True
    return False


_TYPED_PROFILE_SUPPORT_CATEGORIES = {
    role: frozenset(
        category
        for category in categories
        if category.endswith("_profile")
        or category in {"community_membership", "favorite_preference"}
    )
    for role, categories in _TYPED_RELATION_SUPPORT_ROLE_CATEGORIES.items()
}
