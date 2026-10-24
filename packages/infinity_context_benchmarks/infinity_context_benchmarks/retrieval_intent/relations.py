"""Benchmark-owned relations policy."""

from __future__ import annotations

from infinity_context_benchmarks.retrieval_intent.comparison_patterns import _has_contrast_intent
from infinity_context_benchmarks.retrieval_intent.contracts import (
    RetrievalRelationIntent,
    RetrievalTimeIntent,
)
from infinity_context_benchmarks.retrieval_intent.event_facets import _EVENT_FACETS
from infinity_context_benchmarks.retrieval_intent.event_patterns import (
    _has_action_event_intent,
    _has_adoption_reaction_intent,
    _has_causal_support_intent,
    _has_communication_intent,
    _has_community_membership_intent,
    _has_current_goal_intent,
    _has_direct_support_role_question,
    _has_exchange_intent,
    _has_location_transition_intent,
    _has_participation_event_intent,
    _has_support_goal_intent,
)
from infinity_context_benchmarks.retrieval_intent.profile_facets import _PROFILE_FACETS
from infinity_context_benchmarks.retrieval_intent.profile_patterns import (
    _has_activity_profile_intent,
    _has_commitment_profile_intent,
    _has_contact_profile_intent,
    _has_date_profile_intent,
    _has_diet_profile_intent,
    _has_education_profile_intent,
    _has_employment_profile_intent,
    _has_health_profile_intent,
    _has_pet_profile_intent,
    _has_skill_profile_intent,
    _has_status_profile_intent,
    _has_vehicle_profile_intent,
)


def infer_relation_intents(
    *,
    question: str = "",
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    time_intent: RetrievalTimeIntent,
    visual_terms: tuple[str, ...],
    multi_hop_markers: tuple[str, ...],
) -> tuple[RetrievalRelationIntent, ...]:
    """Classify relation terms into stable retrieval facets."""

    relation_set = set(relation_terms)
    variant_set = set(relation_variant_terms)
    facets: list[RetrievalRelationIntent] = []
    for category, config in _RELATION_FACET_CONFIG.items():
        if (
            category == "causal"
            and not _has_causal_support_intent(
                question=question,
                relation_terms=relation_terms,
                multi_hop_markers=multi_hop_markers,
                time_intent=time_intent,
            )
            and not _has_adoption_reaction_intent(relation_terms=relation_terms)
        ):
            continue
        if category == "location_transition" and not _has_location_transition_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "current_goal" and not _has_current_goal_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "action_event" and not _has_action_event_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "exchange" and not _has_exchange_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "participation_event" and not _has_participation_event_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "activity_profile" and not _has_activity_profile_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "education_profile" and not _has_education_profile_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "employment_profile" and not _has_employment_profile_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "health_profile" and not _has_health_profile_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "contact_profile" and not _has_contact_profile_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "diet_profile" and not _has_diet_profile_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "pet_profile" and not _has_pet_profile_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "skill_profile" and not _has_skill_profile_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "vehicle_profile" and not _has_vehicle_profile_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "date_profile" and not _has_date_profile_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "communication" and not _has_communication_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "status_profile" and not _has_status_profile_intent(
            question=question,
            relation_terms=relation_terms,
            time_intent=time_intent,
        ):
            continue
        if category == "support_goal" and not _has_support_goal_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "community_membership" and not _has_community_membership_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        if category == "commitment_profile" and not _has_commitment_profile_intent(
            question=question,
            relation_terms=relation_terms,
        ):
            continue
        contrast_intent = category == "contrast" and _has_contrast_intent(
            question=question,
            relation_terms=relation_terms,
            multi_hop_markers=multi_hop_markers,
        )
        if category == "contrast" and not contrast_intent:
            continue
        terms = tuple(term for term in relation_terms if term in config["terms"])
        variants = tuple(term for term in relation_variant_terms if term in config["variants"])
        marker_hit = bool(set(config["markers"]) & set(multi_hop_markers))
        if not terms and not marker_hit and not contrast_intent:
            continue
        facets.append(
            RetrievalRelationIntent(
                category=category,
                terms=terms,
                variant_terms=variants,
                evidence_need=str(config["evidence_need"]),
                reason_codes=_relation_facet_reason_codes(
                    category=category,
                    question=question,
                    terms=terms,
                    variants=variants,
                    marker_hit=marker_hit,
                ),
            )
        )
    if time_intent.is_temporal:
        facets.append(
            RetrievalRelationIntent(
                category="temporal",
                terms=tuple(term for term in relation_terms if term in relation_set),
                variant_terms=tuple(
                    term
                    for term in relation_variant_terms
                    if term in variant_set and term in _TEMPORAL_SUPPORT_VARIANTS
                ),
                evidence_need=(
                    "temporal_sequence"
                    if time_intent.kind == "temporal_sequence"
                    else "temporal_support"
                ),
                reason_codes=("time_intent", f"time_kind:{time_intent.kind}"),
            )
        )
    if visual_terms:
        facets.append(
            RetrievalRelationIntent(
                category="visual",
                terms=visual_terms,
                variant_terms=(),
                evidence_need="visual_evidence",
                reason_codes=("visual_terms",),
            )
        )
    return tuple(_dedupe_relation_intents(facets))


_TEMPORAL_SUPPORT_VARIANTS = frozenset(
    {
        "age",
        "ago",
        "anniversary",
        "birthday",
        "born",
        "current",
        "date",
        "duration",
        "event",
        "month",
        "planned",
        "registered",
        "session",
        "signed",
        "time",
        "week",
        "weekend",
        "year",
        "years",
    }
)


def _relation_facet_reason_codes(
    *,
    category: str,
    question: str,
    terms: tuple[str, ...],
    variants: tuple[str, ...],
    marker_hit: bool,
) -> tuple[str, ...]:
    reasons: list[str] = [f"category:{category}"]
    if terms:
        reasons.append("relation_terms")
    if variants:
        reasons.append("relation_variants")
    if marker_hit:
        reasons.append("question_marker")
    if category == "support_goal" and _has_direct_support_role_question(
        " ".join(str(question or "").casefold().split())
    ):
        reasons.append("direct_support_question")
    return tuple(reasons)


def _dedupe_relation_intents(
    facets: tuple[RetrievalRelationIntent, ...] | list[RetrievalRelationIntent],
) -> tuple[RetrievalRelationIntent, ...]:
    by_category: dict[str, RetrievalRelationIntent] = {}
    for facet in facets:
        current = by_category.get(facet.category)
        if current is None:
            by_category[facet.category] = facet
            continue
        by_category[facet.category] = RetrievalRelationIntent(
            category=facet.category,
            terms=tuple(dict.fromkeys((*current.terms, *facet.terms))),
            variant_terms=tuple(dict.fromkeys((*current.variant_terms, *facet.variant_terms))),
            evidence_need=current.evidence_need,
            reason_codes=tuple(dict.fromkeys((*current.reason_codes, *facet.reason_codes))),
        )
    return tuple(by_category.values())


_RELATION_FACET_CONFIG: dict[str, dict[str, object]] = {
    key: (_PROFILE_FACETS[key] if key in _PROFILE_FACETS else _EVENT_FACETS[key])
    for key in (
        "activity",
        "action_event",
        "favorite_preference",
        "preference",
        "activity_profile",
        "current_goal",
        "identity_profile",
        "community_membership",
        "status_profile",
        "causal",
        "emotion_response",
        "support_goal",
        "education_profile",
        "employment_profile",
        "health_profile",
        "contact_profile",
        "commitment_profile",
        "diet_profile",
        "age_profile",
        "alias_profile",
        "date_profile",
        "pet_profile",
        "skill_profile",
        "vehicle_profile",
        "exchange",
        "symbolic_meaning",
        "registration_event",
        "participation_event",
        "communication",
        "location_transition",
        "contrast",
    )
}
