"""Benchmark-owned evidence policy."""

from __future__ import annotations

from infinity_context_benchmarks.retrieval_intent.comparison_patterns import (
    _has_contrast_intent,
    _has_count_intent,
    _has_list_intent,
    _has_negative_absence_intent,
)
from infinity_context_benchmarks.retrieval_intent.contracts import (
    RetrievalRelationIntent,
    RetrievalTimeIntent,
)
from infinity_context_benchmarks.retrieval_intent.event_patterns import (
    _has_causal_support_intent,
    _has_direct_emotion_response_intent,
    _has_inference_support_intent,
    _has_location_transition_intent,
    _is_direct_support_relation_intent,
)
from infinity_context_benchmarks.retrieval_intent.profile_patterns import _is_kinship_status_lookup


def infer_evidence_need(
    *,
    question: str = "",
    relation_terms: tuple[str, ...],
    time_intent: RetrievalTimeIntent,
    visual_terms: tuple[str, ...],
    multi_hop_markers: tuple[str, ...],
    benchmark_category: int | None = None,
    answer_unit_shapes: tuple[str, ...] = (),
) -> tuple[str, ...]:
    needs: list[str] = []
    relation_set = set(relation_terms)
    answer_unit_set = set(answer_unit_shapes)
    count_intent = _has_count_intent(question) and benchmark_category != 3
    list_intent = _has_list_intent(question) and not _is_kinship_status_lookup(
        question,
        relation_terms,
    )
    direct_emotion_response = _has_direct_emotion_response_intent(
        question=question,
        relation_terms=relation_terms,
    )
    if multi_hop_markers and not direct_emotion_response:
        needs.append("multi_hop")
    if count_intent:
        needs.append("count_support")
    if list_intent:
        needs.append("list_support")
    if "quantity_dollar" in answer_unit_set and "employment" not in relation_set:
        needs.append("value_support")
    if time_intent.is_temporal:
        needs.append(
            "temporal_sequence" if time_intent.kind == "temporal_sequence" else "temporal_support"
        )
    if visual_terms:
        needs.append("visual_evidence")
    if {"favorite", "favourite"} & relation_set:
        needs.append("favorite_preference")
    if {
        "avoid",
        "dislike",
        "favorite",
        "favourite",
        "hate",
        "interest",
        "prefer",
        "preference",
        "enjoy",
        "like",
        "love",
    } & relation_set:
        needs.append("preference")
    if _has_contrast_intent(
        question=question,
        relation_terms=relation_terms,
        multi_hop_markers=multi_hop_markers,
    ):
        needs.append("contrast")
    if _has_negative_absence_intent(question):
        needs.append("negative_absence")
    if _has_inference_support_intent(
        question=question,
        relation_terms=relation_terms,
        benchmark_category=benchmark_category,
    ):
        needs.append("inference_support")
    if not count_intent and _has_causal_support_intent(
        question=question,
        relation_terms=relation_terms,
        multi_hop_markers=multi_hop_markers,
        time_intent=time_intent,
    ):
        needs.append("causal_support")
    if _has_location_transition_intent(
        question=question,
        relation_terms=relation_terms,
    ):
        needs.append("location_support")
    if not needs:
        needs.append("single_fact")
    return tuple(dict.fromkeys(needs))


def infer_bundle_evidence_roles(
    *,
    evidence_need: tuple[str, ...],
    benchmark_category: int | None = None,
) -> tuple[str, ...]:
    roles: list[str] = ["primary"]
    evidence_need_set = set(evidence_need)
    if benchmark_category == 1 or "multi_hop" in evidence_need_set:
        roles.append("bridge")
    if (
        benchmark_category == 2
        or {
            "temporal_support",
            "temporal_sequence",
        }
        & evidence_need_set
    ):
        roles.append("temporal_support")
    if "contrast" in evidence_need_set:
        roles.append("contrast")
    if "negative_absence" in evidence_need_set:
        roles.append("negative_support")
    if "count_support" in evidence_need_set:
        roles.append("count_support")
    if "list_support" in evidence_need_set:
        roles.append("list_support")
    if "value_support" in evidence_need_set:
        roles.append("value_support")
    if "location_support" in evidence_need_set:
        roles.append("location_support")
    if "preference" in evidence_need_set:
        roles.append("preference_support")
    if "favorite_preference" in evidence_need_set:
        roles.append("favorite_support")
    if "visual_evidence" in evidence_need_set:
        roles.append("visual_support")
    if "emotion_response" in evidence_need_set:
        roles.append("emotion_response_support")
    if "symbolic_meaning" in evidence_need_set:
        roles.append("symbolic_meaning_support")
    if "communication" in evidence_need_set:
        roles.append("communication_support")
    profile_role_by_need = {
        "action_support": "action_support",
        "activity_support": "activity_support",
        "activity_profile": "activity_support",
        "age_profile": "age_support",
        "alias_profile": "alias_support",
        "current_goal": "current_goal_support",
        "date_profile": "date_support",
        "education_profile": "education_support",
        "employment_profile": "employment_support",
        "health_profile": "health_support",
        "identity_profile": "identity_support",
        "community_membership": "community_membership_support",
        "pet_profile": "pet_support",
        "skill_profile": "skill_support",
        "status_profile": "status_support",
        "support_goal": "support_goal_support",
        "vehicle_profile": "vehicle_support",
    }
    roles.extend(
        role
        for need, role in profile_role_by_need.items()
        if need in evidence_need_set
        and not (benchmark_category == 1 and need == "activity_support")
    )
    if "commitment_profile" in evidence_need_set:
        roles.append("commitment_support")
    if "contact_profile" in evidence_need_set:
        roles.append("contact_support")
    if "diet_profile" in evidence_need_set:
        roles.append("diet_support")
    if "exchange" in evidence_need_set:
        roles.append("exchange_support")
    if "favorite_preference" in evidence_need_set:
        roles.append("favorite_support")
    if {"registration_event", "participation_event"} & evidence_need_set:
        roles.append("event_support")
    if "causal_support" in evidence_need_set:
        roles.append("causal_support")
    if "inference_support" in evidence_need_set and "multi_hop" not in evidence_need_set:
        roles.append("inference_support")
    return tuple(dict.fromkeys(roles))


def merge_relation_evidence_needs(
    evidence_need: tuple[str, ...],
    relation_intents: tuple[RetrievalRelationIntent, ...],
) -> tuple[str, ...]:
    """Promote selected typed relation-facet needs into bundle planning."""

    category_promoted_needs: set[str] = set()
    promoted_needs = {
        "emotion_response",
        "commitment_profile",
        "contact_profile",
        "diet_profile",
        "education_profile",
        "employment_profile",
        "age_profile",
        "alias_profile",
        "activity_profile",
        "activity_support",
        "action_support",
        "date_profile",
        "health_profile",
        "pet_profile",
        "skill_profile",
        "status_profile",
        "vehicle_profile",
        "communication",
        "current_goal",
        "exchange",
        "favorite_preference",
        "inference_support",
        "identity_profile",
        "community_membership",
        "participation_event",
        "registration_event",
        "support_goal",
        "symbolic_meaning",
    }
    relation_needs: list[str] = []
    for intent in relation_intents:
        if intent.category in category_promoted_needs:
            if "inference_support" not in evidence_need:
                continue
            relation_need = intent.category
        else:
            relation_need = intent.evidence_need
        if relation_need in promoted_needs and relation_need != "inference_support":
            if relation_need == "activity_support" and any(
                relation_intent.category == "activity_profile"
                for relation_intent in relation_intents
            ):
                continue
            if relation_need == "activity_support" and "preference" in evidence_need:
                continue
            if (
                relation_need == "support_goal"
                and {"causal_support", "multi_hop"} & set(evidence_need)
                and not _is_direct_support_relation_intent(intent)
            ):
                continue
            relation_needs.append(relation_need)
    if not relation_needs:
        return evidence_need
    base_needs = tuple(need for need in evidence_need if need != "single_fact")
    return tuple(dict.fromkeys((*base_needs, *relation_needs)))


def infer_risk_flags(
    *,
    entity_count: int,
    relation_terms: tuple[str, ...],
    relation_variant_terms: tuple[str, ...],
    time_intent: RetrievalTimeIntent,
) -> tuple[str, ...]:
    flags: list[str] = []
    if entity_count == 0:
        flags.append("no_entity")
    if entity_count > 2:
        flags.append("ambiguous_entity_scope")
    if not relation_terms and not time_intent.is_temporal:
        flags.append("broad_query")
    if len(relation_variant_terms) > 18:
        flags.append("wide_relation_expansion")
    return tuple(flags)
