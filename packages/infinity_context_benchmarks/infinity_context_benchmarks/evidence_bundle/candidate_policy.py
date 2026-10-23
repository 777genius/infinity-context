"""Candidate eligibility, typed evidence support and role assignment policy."""

from __future__ import annotations

from collections.abc import (
    Sequence,
)

from infinity_context_benchmarks.evidence_bundle.models import (
    BundleRole,
    EvidenceBundleCandidate,
)
from infinity_context_benchmarks.evidence_bundle.source_policy import (
    _candidate_has_diffuse_source_refs,
    _candidate_has_measured_answerability_below,
    _candidate_has_measured_source_locality_below,
    _candidate_has_measured_weak_source_locality,
    _candidate_has_person_grounding,
    _candidate_has_relation_grounding,
    _candidate_person_grounding_terms,
    _candidate_turn_refs,
    _is_measured_low_answerability,
)

_TYPED_RELATION_SUPPORT_CATEGORIES = {
    "action_support": frozenset({"action_event"}),
    "activity_support": frozenset({"activity_profile"}),
    "age_support": frozenset({"age_profile"}),
    "alias_support": frozenset({"alias_profile"}),
    "commitment_support": frozenset({"commitment_profile"}),
    "community_membership_support": frozenset({"community_membership"}),
    "contact_support": frozenset({"contact_profile"}),
    "current_goal_support": frozenset({"current_goal"}),
    "date_support": frozenset({"date_profile"}),
    "diet_support": frozenset({"diet_profile"}),
    "education_support": frozenset({"education_profile"}),
    "employment_support": frozenset({"employment_profile"}),
    "favorite_support": frozenset({"favorite_preference"}),
    "health_support": frozenset({"health_profile"}),
    "identity_support": frozenset({"identity_profile"}),
    "pet_support": frozenset({"pet_profile"}),
    "skill_support": frozenset({"skill_profile"}),
    "status_support": frozenset({"status_profile"}),
    "support_goal_support": frozenset({"support_goal"}),
    "vehicle_support": frozenset({"vehicle_profile"}),
}


_PREDICATE_REQUIRED_ROLES = frozenset(
    {
        "causal_support",
        "communication_support",
        "contrast",
        "emotion_response_support",
        "event_support",
        "exchange_support",
        "inference_support",
        "count_support",
        "location_support",
        "list_support",
        "preference_support",
        "symbolic_meaning_support",
        "temporal_support",
        "value_support",
        "visual_support",
        *_TYPED_RELATION_SUPPORT_CATEGORIES,
    }
)


_NEGATIVE_ABSENCE_ROLES = frozenset({"absence_support", "negative_support"})


_PARTICIPANT_SENSITIVE_REQUIRED_ROLES = frozenset(
    {"activity_support", "event_support", "location_support"}
)


_TYPED_TEMPORAL_SUPPORT_ROLES = frozenset(
    {
        "duration_temporal_support",
        "explicit_temporal_support",
        "relative_temporal_support",
        "temporal_sequence_support",
        "visual_temporal_support",
    }
)


_TEMPORAL_TIME_KIND_ROLES = {
    "duration": "duration_temporal_support",
    "explicit_time": "explicit_temporal_support",
    "relative_time": "relative_temporal_support",
    "temporal_sequence": "temporal_sequence_support",
}


_DIVERSITY_EXEMPT_ROLES = frozenset(
    {
        "bridge",
        "entity_disambiguation",
        "negative_support",
        "primary",
        *_TYPED_TEMPORAL_SUPPORT_ROLES,
        *_PREDICATE_REQUIRED_ROLES,
    }
)


def _role_for_candidate(
    candidate: EvidenceBundleCandidate,
    *,
    primary: EvidenceBundleCandidate | None,
    case_group: str,
    required_roles: Sequence[str] = (),
) -> BundleRole:
    if primary is not None and candidate.dedupe_key == primary.dedupe_key:
        return "primary"
    if (
        _NEGATIVE_ABSENCE_ROLES.intersection(required_roles)
        and _candidate_has_negative_absence_support(candidate)
    ):
        return "negative_support"
    if candidate.conflict_or_stale or candidate.contrast_surface:
        return "contrast"
    if _is_bridge_candidate(candidate, primary=primary, case_group=case_group):
        return "bridge"
    if _candidate_has_negative_absence_support(candidate):
        return "negative_support"
    if _candidate_has_location_support(candidate):
        return "location_support"
    if (
        "favorite_support" in set(required_roles)
        and _candidate_has_favorite_support(candidate)
    ):
        return "favorite_support"
    if (
        "preference_support" in set(required_roles)
        and _candidate_has_preference_support(candidate)
    ):
        return "preference_support"
    if (
        "visual_support" in set(required_roles)
        and _candidate_has_visual_support(candidate)
    ):
        return "visual_support"
    if (
        "emotion_response_support" in set(required_roles)
        and _candidate_has_emotion_response_support(candidate)
    ):
        return "emotion_response_support"
    if (
        "symbolic_meaning_support" in set(required_roles)
        and _candidate_has_symbolic_meaning_support(candidate)
    ):
        return "symbolic_meaning_support"
    if (
        "event_support" in set(required_roles)
        and _candidate_has_event_support(candidate)
    ):
        return "event_support"
    if (
        "communication_support" in set(required_roles)
        and _candidate_has_communication_support(candidate)
    ):
        return "communication_support"
    if (
        "exchange_support" in set(required_roles)
        and _candidate_has_exchange_support(candidate)
    ):
        return "exchange_support"
    if (
        "causal_support" in set(required_roles)
        and _candidate_has_causal_support(candidate)
    ):
        return "causal_support"
    typed_temporal_role = _typed_temporal_role_for_candidate(
        candidate,
        required_roles=required_roles,
    )
    if typed_temporal_role:
        return typed_temporal_role
    if (
        "value_support" in set(required_roles)
        and _candidate_has_value_support(candidate)
    ):
        return "value_support"
    if (
        "count_support" in set(required_roles)
        and _candidate_has_count_support(candidate)
    ):
        return "count_support"
    if (
        "list_support" in set(required_roles)
        and _candidate_has_list_support(candidate)
    ):
        return "list_support"
    if (
        "inference_support" in set(required_roles)
        and _candidate_has_inference_support(candidate)
    ):
        return "inference_support"
    for role in required_roles:
        if _candidate_has_typed_relation_support(candidate, str(role)):
            return str(role)
    if (
        candidate.has_temporal_surface
        or candidate.has_sequence_surface
        or candidate.has_duration_surface
        or candidate.has_relative_time_surface
        or candidate.has_explicit_time_surface
        or candidate.has_temporal_sequence_surface
        or candidate.currentness_surface
    ):
        return "temporal_support"
    if case_group == "temporal" and candidate.query_support_terms:
        return "temporal_support"
    if (
        (candidate.entity_hits or candidate.speaker_hits)
        and not candidate.covered_expected_terms
        and not candidate.covered_evidence_terms
    ):
        return "entity_disambiguation"
    return "supporting"


def _is_bridge_candidate(
    candidate: EvidenceBundleCandidate,
    *,
    primary: EvidenceBundleCandidate | None,
    case_group: str,
) -> bool:
    if case_group != "multi-hop":
        return False
    if primary is not None and not _candidate_has_complementary_bridge_value(
        candidate,
        primary,
    ):
        return False
    return _candidate_has_bridge_grounding(candidate)


def _candidate_has_bridge_grounding(candidate: EvidenceBundleCandidate) -> bool:
    if candidate.conflict_or_stale or candidate.broad_summary:
        return False
    if _candidate_has_measured_weak_source_locality(candidate):
        return False
    if _is_measured_low_answerability(candidate.answerability_score):
        return False
    if not _candidate_has_bridge_support_surface(candidate):
        return False
    if not _candidate_has_local_bridge_grounding(candidate):
        return False
    return bool(
        _candidate_has_relation_grounding(candidate)
        and _candidate_has_person_grounding(candidate)
    )


def _candidate_has_bridge_support_surface(
    candidate: EvidenceBundleCandidate,
) -> bool:
    support_term_count = len(tuple(dict.fromkeys(candidate.query_support_terms)))
    if support_term_count >= 2:
        return True
    return bool(
        support_term_count >= 1 and _candidate_has_bridge_query_provenance(candidate)
    )


def _candidate_has_bridge_query_provenance(
    candidate: EvidenceBundleCandidate,
) -> bool:
    return bool(
        candidate.bridge_query_hit
        or "multi_hop_bridge" in set(candidate.query_roles)
    )


def _candidate_has_complementary_bridge_value(
    candidate: EvidenceBundleCandidate,
    primary: EvidenceBundleCandidate,
) -> bool:
    bridge_terms = _candidate_bridge_value_terms(candidate)
    if not bridge_terms:
        return False
    primary_terms = _candidate_bridge_value_terms(primary)
    if not primary_terms:
        return True
    return bool(bridge_terms.difference(primary_terms))


def _candidate_bridge_value_terms(
    candidate: EvidenceBundleCandidate,
) -> frozenset[str]:
    person_terms = set(_candidate_person_grounding_terms(candidate))
    return frozenset(
        normalized
        for value in (
            *candidate.covered_expected_terms,
            *candidate.covered_evidence_terms,
            *candidate.query_support_terms,
            *candidate.relation_hits,
            *candidate.relation_category_hits,
        )
        for normalized in (str(value).strip().casefold(),)
        if normalized and normalized not in person_terms
    )


def _candidate_has_local_bridge_grounding(
    candidate: EvidenceBundleCandidate,
) -> bool:
    turn_refs = _candidate_turn_refs(candidate)
    if not turn_refs:
        return True
    return not _candidate_has_diffuse_source_refs(candidate)


def _candidate_has_temporal_support(candidate: EvidenceBundleCandidate) -> bool:
    if not _candidate_has_temporal_grounding(candidate):
        return False
    time_kind = str(candidate.time_intent_kind or "").strip()
    if time_kind == "duration":
        return candidate.has_duration_surface
    if time_kind == "temporal_sequence":
        return candidate.has_temporal_sequence_surface or candidate.has_sequence_surface
    if time_kind == "explicit_time":
        return candidate.has_explicit_time_content_surface
    if time_kind == "relative_time":
        return bool(
            candidate.has_relative_time_surface
            or candidate.currentness_surface
            or candidate.has_explicit_time_content_surface
        )
    return bool(
        candidate.has_temporal_surface
        or candidate.has_sequence_surface
        or candidate.has_duration_surface
        or candidate.has_relative_time_surface
        or candidate.has_explicit_time_content_surface
        or candidate.has_temporal_sequence_surface
        or candidate.currentness_surface
    )


def _typed_temporal_role_for_candidate(
    candidate: EvidenceBundleCandidate,
    *,
    required_roles: Sequence[str],
) -> str:
    required_role_set = set(required_roles)
    for role in sorted(_TYPED_TEMPORAL_SUPPORT_ROLES):
        if role in required_role_set and _candidate_has_typed_temporal_support(
            candidate,
            role,
        ):
            return role
    return ""


def _candidate_has_typed_temporal_support(
    candidate: EvidenceBundleCandidate,
    role: str,
) -> bool:
    if not _candidate_has_temporal_support(candidate):
        return False
    if role == "visual_temporal_support":
        return _candidate_has_visual_support(candidate)
    return _TEMPORAL_TIME_KIND_ROLES.get(str(candidate.time_intent_kind or "")) == role


def _candidate_has_temporal_grounding(candidate: EvidenceBundleCandidate) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if (
        _candidate_has_measured_weak_source_locality(candidate)
        and candidate.focused_evidence_score <= 0
    ):
        return False
    if candidate.answerability_score and candidate.answerability_score < 0.55:
        return False
    if candidate.query_has_entities and not (
        candidate.entity_hits or candidate.speaker_hits
    ):
        return False
    if candidate.query_has_entities and not _candidate_has_relation_or_answer_grounding(
        candidate
    ):
        return False
    return bool(
        candidate.entity_hits
        or candidate.speaker_hits
        or candidate.relation_hits
        or candidate.query_support_terms
        or candidate.direct_speaker_turn
        or candidate.focused_evidence_score > 0
    )


def _candidate_has_relation_or_answer_grounding(
    candidate: EvidenceBundleCandidate,
) -> bool:
    return bool(
        candidate.relation_hits
        or candidate.relation_category_hits
        or candidate.covered_expected_terms
        or candidate.covered_evidence_terms
        or candidate.has_preference_evidence
        or candidate.has_visual_evidence
        or candidate.exact_count_evidence
        or candidate.list_item_count > 0
        or candidate.covered_answer_unit_shapes
    )


def _candidate_has_contrast_support(candidate: EvidenceBundleCandidate) -> bool:
    if not _candidate_has_contrast_grounding(candidate):
        return False
    return bool(
        candidate.contrast_surface
        or (
            candidate.currentness_surface
            and (candidate.stale_surface or candidate.negation_surface)
        )
    )


def _candidate_has_contrast_grounding(candidate: EvidenceBundleCandidate) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if (
        _candidate_has_measured_weak_source_locality(candidate)
        and candidate.focused_evidence_score <= 0
    ):
        return False
    if candidate.answerability_score and candidate.answerability_score < 0.55:
        return False
    return not candidate.query_has_entities or bool(
        candidate.entity_hits or candidate.speaker_hits
    )


def _candidate_has_negative_absence_support(
    candidate: EvidenceBundleCandidate,
) -> bool:
    if not candidate.negation_surface:
        return False
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if _candidate_has_measured_weak_source_locality(candidate):
        return False
    if candidate.answerability_score and candidate.answerability_score < 0.55:
        return False
    if candidate.query_has_entities and not (
        candidate.entity_hits or candidate.speaker_hits
    ):
        return False
    return bool(
        candidate.direct_speaker_turn
        or candidate.focused_evidence_score > 0
        or candidate.relation_hits
        or candidate.relation_category_hits
        or candidate.query_support_terms
        or candidate.entity_hits
        or candidate.speaker_hits
        or candidate.source_refs
    )


def _candidate_has_location_support(candidate: EvidenceBundleCandidate) -> bool:
    if not _candidate_has_typed_relation_grounding(candidate):
        return False
    return "location_transition" in set(candidate.relation_category_hits)


def _candidate_has_value_support(candidate: EvidenceBundleCandidate) -> bool:
    if not _candidate_has_answer_unit_support_grounding(candidate):
        return False
    return "quantity_dollar" in set(candidate.covered_answer_unit_shapes)


def _candidate_has_count_support(candidate: EvidenceBundleCandidate) -> bool:
    if not _candidate_has_answer_unit_support_grounding(candidate):
        return False
    return candidate.exact_count_evidence or candidate.list_item_count >= 2


def _candidate_has_list_support(candidate: EvidenceBundleCandidate) -> bool:
    if not _candidate_has_answer_unit_support_grounding(candidate):
        return False
    return candidate.list_item_count >= 2


def _candidate_list_items(candidate: EvidenceBundleCandidate) -> frozenset[str]:
    return frozenset(
        item.strip().casefold() for item in candidate.list_items if item.strip()
    )


def _candidate_has_answer_unit_support_grounding(
    candidate: EvidenceBundleCandidate,
) -> bool:
    if not _candidate_has_typed_relation_grounding(candidate):
        return False
    return bool(
        candidate.source_refs
        or _candidate_turn_refs(candidate)
        or candidate.direct_speaker_turn
        or candidate.focused_evidence_score > 0
        or candidate.relation_hits
        or candidate.relation_category_hits
        or candidate.entity_hits
        or candidate.speaker_hits
    )


def _candidate_has_preference_support(candidate: EvidenceBundleCandidate) -> bool:
    if not _candidate_has_typed_relation_grounding(candidate):
        return False
    if "favorite_preference" in set(candidate.relation_category_hits):
        return True
    return bool(
        "preference" in set(candidate.relation_category_hits)
        or (candidate.has_preference_evidence and len(candidate.relation_hits) >= 2)
    )


def _candidate_has_favorite_support(candidate: EvidenceBundleCandidate) -> bool:
    if not _candidate_has_typed_relation_grounding(candidate):
        return False
    return "favorite_preference" in set(candidate.relation_category_hits)


def _candidate_has_visual_support(candidate: EvidenceBundleCandidate) -> bool:
    if not _candidate_has_typed_relation_grounding(candidate):
        return False
    return bool(
        candidate.has_visual_evidence
        or "visual" in set(candidate.relation_category_hits)
    )


def _candidate_has_emotion_response_support(
    candidate: EvidenceBundleCandidate,
) -> bool:
    if not _candidate_has_typed_relation_grounding(candidate):
        return False
    return "emotion_response" in set(candidate.relation_category_hits)


def _candidate_has_symbolic_meaning_support(
    candidate: EvidenceBundleCandidate,
) -> bool:
    if not _candidate_has_typed_relation_grounding(candidate):
        return False
    return "symbolic_meaning" in set(candidate.relation_category_hits)


def _candidate_has_event_support(candidate: EvidenceBundleCandidate) -> bool:
    if not _candidate_has_typed_relation_grounding(candidate):
        return False
    return bool(
        {"registration_event", "participation_event"}
        & set(candidate.relation_category_hits)
    )


def _candidate_has_communication_support(candidate: EvidenceBundleCandidate) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if _candidate_has_measured_weak_source_locality(candidate):
        return False
    if candidate.answerability_score and candidate.answerability_score < 0.55:
        return False
    if candidate.query_has_entities and not candidate.speaker_hits:
        return False
    if not (candidate.speaker_hits or candidate.direct_speaker_turn):
        return False
    return "communication" in set(candidate.relation_category_hits)


def _candidate_has_exchange_support(candidate: EvidenceBundleCandidate) -> bool:
    if not _candidate_has_typed_relation_grounding(candidate):
        return False
    return "exchange" in set(candidate.relation_category_hits)


def _candidate_has_typed_relation_grounding(
    candidate: EvidenceBundleCandidate,
) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if _candidate_has_measured_weak_source_locality(candidate):
        return False
    if candidate.answerability_score and candidate.answerability_score < 0.55:
        return False
    if not candidate.query_has_entities:
        return True
    return bool(candidate.entity_hits or candidate.speaker_hits)


def _candidate_has_inference_support(candidate: EvidenceBundleCandidate) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if not (candidate.entity_hits or candidate.speaker_hits):
        return False
    if _candidate_has_measured_weak_source_locality(candidate):
        return False
    if candidate.answerability_score and candidate.answerability_score < 0.55:
        return False
    return bool(candidate.relation_hits or candidate.relation_category_hits)


def _candidate_has_causal_support(candidate: EvidenceBundleCandidate) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if not (candidate.entity_hits or candidate.speaker_hits):
        return False
    if _candidate_has_measured_weak_source_locality(candidate):
        return False
    if candidate.answerability_score and candidate.answerability_score < 0.55:
        return False
    if "causal" in set(candidate.relation_category_hits):
        return True
    causal_terms = {
        "because",
        "cause",
        "caused",
        "choose",
        "chose",
        "decision",
        "feel",
        "fit",
        "reason",
        "realize",
        "realized",
        "reaction",
        "response",
        "spoke",
        "think",
        "thought",
        "value",
    }
    return bool(causal_terms.intersection(candidate.relation_hits))


def _candidate_has_typed_relation_support(
    candidate: EvidenceBundleCandidate,
    role: str,
) -> bool:
    required_categories = _TYPED_RELATION_SUPPORT_CATEGORIES.get(role)
    if not required_categories:
        return False
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if _candidate_has_measured_weak_source_locality(candidate):
        return False
    if candidate.answerability_score and candidate.answerability_score < 0.55:
        return False
    if role == "support_goal_support" and not (
        candidate.entity_hits or candidate.speaker_hits
    ):
        return _candidate_has_entityless_support_goal_grounding(candidate)
    if not (candidate.entity_hits or candidate.speaker_hits):
        return False
    return bool(required_categories.intersection(candidate.relation_category_hits))


def _candidate_has_entityless_support_goal_grounding(
    candidate: EvidenceBundleCandidate,
) -> bool:
    if not (
        candidate.source_refs
        or _candidate_turn_refs(candidate)
        or candidate.direct_speaker_turn
        or candidate.focused_evidence_score > 0
    ):
        return False
    if "support_goal" in set(candidate.relation_category_hits):
        return True
    support_terms = set(candidate.query_support_terms)
    return bool(
        "support" in support_terms
        and {"adoption", "agency", "individual", "help"} & support_terms
    )


def _primary_candidate_eligible(candidate: EvidenceBundleCandidate) -> bool:
    if candidate.conflict_or_stale:
        return False
    if candidate.primary_signal:
        return True
    if candidate.broad_summary:
        return False
    if not candidate.direct_speaker_turn:
        return False
    if _candidate_has_measured_source_locality_below(candidate, 0.65):
        return False
    if _candidate_has_measured_answerability_below(candidate, 0.75):
        return False
    return bool(
        candidate.query_support_terms
        or candidate.relation_hits
        or candidate.entity_hits
        or candidate.speaker_hits
    )


def _candidate_has_obsolete_primary_surface(
    candidate: EvidenceBundleCandidate,
) -> bool:
    return bool(
        candidate.stale_surface
        and not candidate.currentness_surface
        and not candidate.contrast_surface
    )


def _answer_evidence_sort_bucket(candidate: EvidenceBundleCandidate) -> int:
    if _candidate_has_answer_evidence(candidate):
        return 0
    if _candidate_has_direct_or_focused_grounding(candidate):
        return 1
    if _candidate_has_relation_grounding(candidate) or _candidate_has_person_grounding(
        candidate
    ):
        return 2
    if candidate.query_support_terms:
        return 3
    return 4


def _candidate_has_answer_evidence(candidate: EvidenceBundleCandidate) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if _candidate_has_measured_source_locality_below(candidate, 0.65):
        return False
    if _candidate_has_measured_answerability_below(candidate, 0.75):
        return False
    if not _candidate_has_relation_grounding(candidate):
        return False
    if candidate.query_has_entities and not _candidate_has_person_grounding(candidate):
        return False
    return bool(
        candidate.direct_speaker_turn
        or candidate.focused_evidence_score > 0
        or candidate.answerability_score >= 0.75
    )


def _candidate_has_direct_or_focused_grounding(
    candidate: EvidenceBundleCandidate,
) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if not (candidate.direct_speaker_turn or candidate.focused_evidence_score > 0):
        return False
    if candidate.query_has_entities and not _candidate_has_person_grounding(candidate):
        return False
    return bool(
        candidate.query_support_terms
        or _candidate_has_relation_grounding(candidate)
        or _candidate_has_person_grounding(candidate)
        or candidate.source_refs
    )
