"""Post-selection evidence bundle confidence and provenance diagnostics."""

from __future__ import annotations

from collections import (
    Counter,
)
from collections.abc import (
    Mapping,
    Sequence,
)

from infinity_context_benchmarks.evidence_bundle.candidate_policy import (
    _PARTICIPANT_SENSITIVE_REQUIRED_ROLES,
    _TYPED_RELATION_SUPPORT_CATEGORIES,
    _candidate_has_contrast_support,
    _candidate_has_negative_absence_support,
)
from infinity_context_benchmarks.evidence_bundle.models import (
    EvidenceBundleCandidate,
    PlannedEvidenceItem,
)
from infinity_context_benchmarks.evidence_bundle.ordering import (
    _item_has_explicit_relation_or_role_grounding,
)
from infinity_context_benchmarks.evidence_bundle.role_support import (
    _item_can_satisfy_required_role,
    _item_can_satisfy_required_role_in_selection,
    _item_has_partial_required_role_support,
    _item_has_requested_participant_grounding,
    _selected_primary_person_grounding_terms,
)
from infinity_context_benchmarks.evidence_bundle.source_policy import (
    _SOURCE_PROXIMITY_WINDOW,
    _candidate_has_diffuse_source_refs,
    _candidate_has_focused_source_proximity_support,
    _candidate_has_generic_measured_answerability,
    _candidate_has_measured_weak_source_locality,
    _candidate_has_source_identity_quality_support,
    _candidate_has_source_proximity_diagnostic_support,
    _candidate_person_grounding_terms,
    _candidate_turn_ref_strings,
    _candidate_turn_refs,
    _closest_turn_ref_distance,
    _is_measured_low_answerability,
    _retrieval_source_keys,
    _source_identity_refs,
    _source_type_keys,
    _turn_ref_span,
)

_SOURCE_DIAGNOSTIC_SAMPLE_LIMIT = 5


_SOURCE_DIAGNOSTIC_REF_SAMPLE_LIMIT = 4


def _avg_positive_scores(scores: Sequence[float]) -> float:
    measured = [score for score in scores if score > 0]
    if not measured:
        return 0.0
    return sum(measured) / len(measured)


def _bundle_quality_diagnostics(
    items: Sequence[PlannedEvidenceItem],
    *,
    missing_required_roles: Sequence[str] = (),
) -> dict[str, object]:
    missing_roles = tuple(
        dict.fromkeys(role for role in missing_required_roles if str(role).strip())
    )
    if not items:
        return {
            "schema_version": "evidence_bundle_quality.v1",
            "confidence_score": 0.0,
            "confidence_band": "none",
            "component_scores": {},
            "risk_penalty": 0.0,
            "reason_codes": ["empty_bundle"],
            "selected_item_count": 0,
            "primary_count": 0,
            "supporting_count": 0,
            "focused_item_count": 0,
            "direct_speaker_count": 0,
            "source_ref_item_count": 0,
            "source_ref_support_item_count": 0,
            "source_ref_support_ref_count": 0,
            "source_identity_item_count": 0,
            "source_identity_ref_count": 0,
            "source_identity_support_item_count": 0,
            "source_identity_support_ref_count": 0,
            "source_type_diversity": 0,
            "retrieval_source_diversity": 0,
            "source_type_support_diversity": 0,
            "retrieval_source_support_diversity": 0,
            "low_answerability_count": 0,
            "generic_measured_answerability_count": 0,
            "measured_answerability_count": 0,
            "unmeasured_answerability_count": 0,
            "average_measured_answerability_score": 0.0,
            "measured_source_locality_count": 0,
            "unmeasured_source_locality_count": 0,
            "average_measured_source_locality_score": 0.0,
            "bridge_count": 0,
            "bridge_query_hit_count": 0,
            "person_grounding_item_count": 0,
            "person_grounding_ref_count": 0,
            "distinct_person_grounding_count": 0,
            "repeated_person_grounding_count": 0,
            "causal_support_count": 0,
            "communication_support_count": 0,
            "event_support_count": 0,
            "exchange_support_count": 0,
            "inference_support_count": 0,
            "location_support_count": 0,
            "emotion_response_support_count": 0,
            "symbolic_meaning_support_count": 0,
            "preference_support_count": 0,
            "favorite_support_count": 0,
            "visual_support_count": 0,
            "typed_relation_support_count": 0,
            "typed_relation_support_counts": {},
            "partial_required_role_support_count": 0,
            "partial_required_role_support_counts": {},
            "participant_grounding_blocked_required_role_count": 0,
            "participant_grounding_blocked_required_role_counts": {},
            "participant_grounding_blocked_required_role_samples": [],
            "location_relation_category_hit_count": 0,
            "source_proximity_support_count": 0,
            "source_chain_proximity_support_count": 0,
            "source_proximity_closest_distance": None,
            "source_chain_proximity_closest_distance": None,
            "source_proximity_distance_counts": {},
            "source_chain_proximity_distance_counts": {},
            "source_proximity_window": _SOURCE_PROXIMITY_WINDOW,
            "diffuse_source_ref_count": 0,
            "diffuse_source_ref_samples": [],
            "weak_source_locality_count": 0,
            "weak_source_locality_samples": [],
            "missing_required_role_count": len(missing_roles),
            "missing_required_roles": list(missing_roles),
            "contrast_count": 0,
            "negative_absence_support_count": 0,
            "contrast_surface_count": 0,
            "negation_surface_count": 0,
            "currentness_surface_count": 0,
            "stale_surface_count": 0,
            "broad_summary_count": 0,
            "conflict_or_stale_count": 0,
        }

    primary_count = sum(1 for item in items if item.role == "primary")
    supporting_count = sum(1 for item in items if item.role != "primary")
    focused_count = sum(
        1 for item in items if item.candidate.focused_evidence_score > 0
    )
    direct_speaker_count = sum(1 for item in items if item.candidate.direct_speaker_turn)
    source_ref_item_count = sum(1 for item in items if item.candidate.source_refs)
    source_ref_support_item_count = sum(
        1
        for item in items
        if item.candidate.source_refs
        and _candidate_has_source_identity_quality_support(item.candidate)
    )
    source_ref_support_ref_count = sum(
        len(item.candidate.source_refs)
        for item in items
        if item.candidate.source_refs
        and _candidate_has_source_identity_quality_support(item.candidate)
    )
    source_identity_refs = tuple(_source_identity_refs(item.candidate) for item in items)
    source_identity_item_count = sum(1 for refs in source_identity_refs if refs)
    source_identity_ref_count = sum(len(refs) for refs in source_identity_refs)
    source_identity_support_refs = tuple(
        refs
        for item, refs in zip(items, source_identity_refs, strict=False)
        if refs and _candidate_has_source_identity_quality_support(item.candidate)
    )
    source_identity_support_item_count = len(source_identity_support_refs)
    source_identity_support_ref_count = sum(
        len(refs) for refs in source_identity_support_refs
    )
    source_types = {
        source_type
        for item in items
        for source_type in _source_type_keys(item.candidate)
    }
    retrieval_sources = {
        source for item in items for source in _retrieval_source_keys(item.candidate)
    }
    source_type_supports = {
        source_type
        for item in items
        if _candidate_has_source_identity_quality_support(item.candidate)
        for source_type in _source_type_keys(item.candidate)
    }
    retrieval_source_supports = {
        source
        for item in items
        if _candidate_has_source_identity_quality_support(item.candidate)
        for source in _retrieval_source_keys(item.candidate)
    }
    answerability_scores = [item.candidate.answerability_score for item in items]
    avg_answerability = sum(answerability_scores) / len(answerability_scores)
    measured_answerability_scores = [
        score for score in answerability_scores if score > 0
    ]
    avg_measured_answerability = _avg_positive_scores(answerability_scores)
    max_answerability = max(answerability_scores)
    low_answerability_count = sum(
        _is_measured_low_answerability(score) for score in answerability_scores
    )
    generic_measured_answerability_count = sum(
        1
        for item in items
        if _candidate_has_generic_measured_answerability(item.candidate)
    )
    unmeasured_answerability_count = sum(
        1 for score in answerability_scores if score <= 0
    )
    source_locality_scores = [item.candidate.source_locality_score for item in items]
    measured_source_locality_scores = [
        score for score in source_locality_scores if score > 0
    ]
    avg_measured_source_locality = _avg_positive_scores(source_locality_scores)
    unmeasured_source_locality_count = sum(
        1 for score in source_locality_scores if score <= 0
    )
    bridge_count = sum(1 for item in items if item.role == "bridge")
    bridge_query_hit_count = sum(1 for item in items if item.candidate.bridge_query_hit)
    person_grounding_terms_by_item = tuple(
        _candidate_person_grounding_terms(item.candidate) for item in items
    )
    person_grounding_item_count = sum(
        1 for terms in person_grounding_terms_by_item if terms
    )
    person_grounding_ref_count = sum(
        len(terms) for terms in person_grounding_terms_by_item
    )
    distinct_person_grounding_terms = tuple(
        dict.fromkeys(
            term for terms in person_grounding_terms_by_item for term in terms
        )
    )
    distinct_person_grounding_count = len(distinct_person_grounding_terms)
    repeated_person_grounding_count = max(
        0,
        person_grounding_ref_count - distinct_person_grounding_count,
    )
    causal_support_count = sum(1 for item in items if item.role == "causal_support")
    communication_support_count = sum(
        1 for item in items if item.role == "communication_support"
    )
    event_support_count = sum(
        1
        for item in items
        if item.role == "event_support"
        and _item_can_satisfy_required_role_in_selection(
            item,
            "event_support",
            items,
        )
    )
    exchange_support_count = sum(1 for item in items if item.role == "exchange_support")
    inference_support_count = sum(
        1 for item in items if item.role == "inference_support"
    )
    location_support_count = sum(
        1
        for item in items
        if item.role == "location_support"
        and _item_can_satisfy_required_role_in_selection(
            item,
            "location_support",
            items,
        )
    )
    emotion_response_support_count = sum(
        1 for item in items if item.role == "emotion_response_support"
    )
    symbolic_meaning_support_count = sum(
        1 for item in items if item.role == "symbolic_meaning_support"
    )
    preference_support_count = sum(
        1 for item in items if item.role == "preference_support"
    )
    favorite_support_count = sum(1 for item in items if item.role == "favorite_support")
    visual_support_count = sum(1 for item in items if item.role == "visual_support")
    typed_relation_support_counts = Counter(
        item.role
        for item in items
        if item.role in _TYPED_RELATION_SUPPORT_CATEGORIES
        and _item_can_satisfy_required_role_in_selection(item, item.role, items)
    )
    typed_relation_support_count = sum(typed_relation_support_counts.values())
    typed_relation_quality_count = (
        typed_relation_support_count - favorite_support_count
    )
    partial_required_role_support_counts = Counter(
        role
        for role in missing_roles
        for item in items
        if _item_has_partial_required_role_support(item, role, items)
    )
    partial_required_role_support_count = sum(
        partial_required_role_support_counts.values()
    )
    participant_grounding_blocked_required_role_counts = Counter(
        role
        for role in missing_roles
        if role in _PARTICIPANT_SENSITIVE_REQUIRED_ROLES
        for item in items
        if _item_can_satisfy_required_role(item, role)
        and not _item_has_requested_participant_grounding(item, items)
    )
    participant_grounding_blocked_required_role_count = sum(
        participant_grounding_blocked_required_role_counts.values()
    )
    location_relation_category_hit_count = sum(
        1
        for item in items
        if "location_transition" in set(item.candidate.relation_category_hits)
    )
    source_proximity_distances = _source_proximity_distances(
        items,
        missing_required_roles=missing_roles,
    )
    source_proximity_support_count = len(source_proximity_distances)
    source_chain_proximity_distances = _source_chain_proximity_distances(items)
    source_chain_proximity_support_count = len(source_chain_proximity_distances)
    diffuse_source_ref_count = sum(
        1 for item in items if _candidate_has_diffuse_source_refs(item.candidate)
    )
    diffuse_source_ref_items = tuple(
        item for item in items if _candidate_has_diffuse_source_refs(item.candidate)
    )
    weak_source_locality_items = tuple(
        item
        for item in items
        if _candidate_has_measured_weak_source_locality(item.candidate)
    )
    weak_source_locality_count = len(weak_source_locality_items)
    contrast_count = sum(
        1 for item in items if _candidate_has_contrast_support(item.candidate)
    )
    negative_absence_support_count = sum(
        1
        for item in items
        if _candidate_has_negative_absence_support(item.candidate)
    )
    contrast_surface_count = sum(1 for item in items if item.candidate.contrast_surface)
    negation_surface_count = sum(1 for item in items if item.candidate.negation_surface)
    currentness_surface_count = sum(
        1 for item in items if item.candidate.currentness_surface
    )
    stale_surface_count = sum(1 for item in items if item.candidate.stale_surface)
    broad_summary_count = sum(1 for item in items if item.candidate.broad_summary)
    conflict_or_stale_count = sum(
        1 for item in items if item.candidate.conflict_or_stale
    )

    component_scores = {
        "primary": 0.18 if primary_count else 0.0,
        "supporting": min(0.14, 0.07 * supporting_count),
        "focused_or_direct": min(
            0.16,
            (0.08 * focused_count) + (0.08 * direct_speaker_count),
        ),
        "source_refs": min(0.16, 0.08 * source_identity_support_item_count),
        "source_diversity": (
            (0.06 if len(source_type_supports) >= 2 else 0.0)
            + (0.06 if len(retrieval_source_supports) >= 2 else 0.0)
        ),
        "answerability": min(
            0.24,
            (0.14 * max_answerability) + (0.10 * avg_answerability),
        ),
        "bridge_support": min(0.1, 0.1 * bridge_count),
        "causal_support": min(0.08, 0.08 * causal_support_count),
        "communication_support": min(0.08, 0.08 * communication_support_count),
        "event_support": min(0.08, 0.08 * event_support_count),
        "exchange_support": min(0.08, 0.08 * exchange_support_count),
        "inference_support": min(0.08, 0.08 * inference_support_count),
        "location_support": min(0.08, 0.08 * location_support_count),
        "emotion_response_support": min(0.08, 0.08 * emotion_response_support_count),
        "symbolic_meaning_support": min(
            0.08,
            0.08 * symbolic_meaning_support_count,
        ),
        "preference_support": min(0.08, 0.08 * preference_support_count),
        "favorite_support": min(0.08, 0.08 * favorite_support_count),
        "typed_relation_support": min(0.08, 0.08 * typed_relation_quality_count),
        "visual_support": min(0.08, 0.08 * visual_support_count),
        "negative_absence_support": min(
            0.08,
            0.08 * negative_absence_support_count,
        ),
        "source_proximity": (
            min(0.06, 0.03 * source_proximity_support_count)
            if not missing_roles
            else 0.0
        ),
        "contrast_support": min(0.08, 0.08 * contrast_count),
    }
    risk_penalty = min(
        0.48,
        (0.08 * low_answerability_count)
        + (0.07 * generic_measured_answerability_count)
        + (0.05 * broad_summary_count)
        + (0.04 * diffuse_source_ref_count)
        + (0.08 * conflict_or_stale_count)
        + (
            0.08
            if generic_measured_answerability_count == len(items)
            else 0.0
        )
        + (0.08 if broad_summary_count == len(items) else 0.0)
        + (0.08 if conflict_or_stale_count == len(items) else 0.0)
        + min(0.3, 0.18 * len(missing_roles)),
    )
    confidence_score = round(
        max(0.0, min(1.0, sum(component_scores.values()) - risk_penalty)),
        6,
    )
    return {
        "schema_version": "evidence_bundle_quality.v1",
        "confidence_score": confidence_score,
        "confidence_band": _confidence_band(confidence_score),
        "component_scores": {
            key: round(value, 6) for key, value in sorted(component_scores.items())
        },
        "risk_penalty": round(risk_penalty, 6),
        "reason_codes": _bundle_quality_reason_codes(
            primary_count=primary_count,
            supporting_count=supporting_count,
            focused_count=focused_count,
            direct_speaker_count=direct_speaker_count,
            source_ref_item_count=source_ref_item_count,
            source_ref_support_item_count=source_ref_support_item_count,
            source_identity_item_count=source_identity_item_count,
            source_identity_support_item_count=source_identity_support_item_count,
            source_type_diversity=len(source_types),
            retrieval_source_diversity=len(retrieval_sources),
            source_type_support_diversity=len(source_type_supports),
            retrieval_source_support_diversity=len(retrieval_source_supports),
            max_answerability=max_answerability,
            low_answerability_count=low_answerability_count,
            generic_measured_answerability_count=(
                generic_measured_answerability_count
            ),
            bridge_count=bridge_count,
            distinct_person_grounding_count=distinct_person_grounding_count,
            causal_support_count=causal_support_count,
            communication_support_count=communication_support_count,
            event_support_count=event_support_count,
            exchange_support_count=exchange_support_count,
            inference_support_count=inference_support_count,
            location_support_count=location_support_count,
            emotion_response_support_count=emotion_response_support_count,
            symbolic_meaning_support_count=symbolic_meaning_support_count,
            preference_support_count=preference_support_count,
            favorite_support_count=favorite_support_count,
            visual_support_count=visual_support_count,
            typed_relation_support_counts=typed_relation_support_counts,
            partial_required_role_support_counts=(
                partial_required_role_support_counts
            ),
            participant_grounding_blocked_required_role_count=(
                participant_grounding_blocked_required_role_count
            ),
            location_relation_category_hit_count=location_relation_category_hit_count,
            source_proximity_support_count=source_proximity_support_count,
            source_chain_proximity_support_count=(
                source_chain_proximity_support_count
            ),
            missing_required_roles=missing_roles,
            contrast_count=contrast_count,
            negative_absence_support_count=negative_absence_support_count,
            contrast_surface_count=contrast_surface_count,
            negation_surface_count=negation_surface_count,
            currentness_surface_count=currentness_surface_count,
            stale_surface_count=stale_surface_count,
            broad_summary_count=broad_summary_count,
            diffuse_source_ref_count=diffuse_source_ref_count,
            weak_source_locality_count=weak_source_locality_count,
            conflict_or_stale_count=conflict_or_stale_count,
            selected_item_count=len(items),
        ),
        "selected_item_count": len(items),
        "primary_count": primary_count,
        "supporting_count": supporting_count,
        "focused_item_count": focused_count,
        "direct_speaker_count": direct_speaker_count,
        "source_ref_item_count": source_ref_item_count,
        "source_ref_support_item_count": source_ref_support_item_count,
        "source_ref_support_ref_count": source_ref_support_ref_count,
        "source_identity_item_count": source_identity_item_count,
        "source_identity_ref_count": source_identity_ref_count,
        "source_identity_support_item_count": source_identity_support_item_count,
        "source_identity_support_ref_count": source_identity_support_ref_count,
        "source_type_diversity": len(source_types),
        "retrieval_source_diversity": len(retrieval_sources),
        "source_type_support_diversity": len(source_type_supports),
        "retrieval_source_support_diversity": len(retrieval_source_supports),
        "average_answerability_score": round(avg_answerability, 6),
        "average_measured_answerability_score": round(
            avg_measured_answerability,
            6,
        ),
        "max_answerability_score": round(max_answerability, 6),
        "low_answerability_count": low_answerability_count,
        "generic_measured_answerability_count": (
            generic_measured_answerability_count
        ),
        "measured_answerability_count": len(measured_answerability_scores),
        "unmeasured_answerability_count": unmeasured_answerability_count,
        "average_measured_source_locality_score": round(
            avg_measured_source_locality,
            6,
        ),
        "measured_source_locality_count": len(measured_source_locality_scores),
        "unmeasured_source_locality_count": unmeasured_source_locality_count,
        "bridge_count": bridge_count,
        "bridge_query_hit_count": bridge_query_hit_count,
        "person_grounding_item_count": person_grounding_item_count,
        "person_grounding_ref_count": person_grounding_ref_count,
        "distinct_person_grounding_count": distinct_person_grounding_count,
        "repeated_person_grounding_count": repeated_person_grounding_count,
        "causal_support_count": causal_support_count,
        "communication_support_count": communication_support_count,
        "event_support_count": event_support_count,
        "exchange_support_count": exchange_support_count,
        "inference_support_count": inference_support_count,
        "location_support_count": location_support_count,
        "emotion_response_support_count": emotion_response_support_count,
        "symbolic_meaning_support_count": symbolic_meaning_support_count,
        "preference_support_count": preference_support_count,
        "favorite_support_count": favorite_support_count,
        "visual_support_count": visual_support_count,
        "typed_relation_support_count": typed_relation_support_count,
        "typed_relation_support_counts": dict(
            sorted(typed_relation_support_counts.items())
        ),
        "partial_required_role_support_count": partial_required_role_support_count,
        "partial_required_role_support_counts": dict(
            sorted(partial_required_role_support_counts.items())
        ),
        "participant_grounding_blocked_required_role_count": (
            participant_grounding_blocked_required_role_count
        ),
        "participant_grounding_blocked_required_role_counts": dict(
            sorted(participant_grounding_blocked_required_role_counts.items())
        ),
        "participant_grounding_blocked_required_role_samples": (
            _participant_grounding_blocked_required_role_samples(
                items,
                missing_required_roles=missing_roles,
            )
        ),
        "location_relation_category_hit_count": (
            location_relation_category_hit_count
        ),
        "source_proximity_support_count": source_proximity_support_count,
        "source_chain_proximity_support_count": (
            source_chain_proximity_support_count
        ),
        "source_proximity_closest_distance": (
            min(source_proximity_distances) if source_proximity_distances else None
        ),
        "source_chain_proximity_closest_distance": (
            min(source_chain_proximity_distances)
            if source_chain_proximity_distances
            else None
        ),
        "source_proximity_distance_counts": dict(
            sorted(
                Counter(str(distance) for distance in source_proximity_distances).items()
            )
        ),
        "source_chain_proximity_distance_counts": dict(
            sorted(
                Counter(
                    str(distance) for distance in source_chain_proximity_distances
                ).items()
            )
        ),
        "source_proximity_window": _SOURCE_PROXIMITY_WINDOW,
        "diffuse_source_ref_count": diffuse_source_ref_count,
        "diffuse_source_ref_samples": _diffuse_source_ref_samples(
            diffuse_source_ref_items
        ),
        "weak_source_locality_count": weak_source_locality_count,
        "weak_source_locality_samples": _weak_source_locality_samples(
            weak_source_locality_items
        ),
        "missing_required_role_count": len(missing_roles),
        "missing_required_roles": list(missing_roles),
        "contrast_count": contrast_count,
        "negative_absence_support_count": negative_absence_support_count,
        "contrast_surface_count": contrast_surface_count,
        "negation_surface_count": negation_surface_count,
        "currentness_surface_count": currentness_surface_count,
        "stale_surface_count": stale_surface_count,
        "broad_summary_count": broad_summary_count,
        "conflict_or_stale_count": conflict_or_stale_count,
    }


def _source_proximity_distances(
    items: Sequence[PlannedEvidenceItem],
    *,
    missing_required_roles: Sequence[str] = (),
) -> tuple[int, ...]:
    primary_turn_refs = tuple(
        turn_ref
        for item in items
        if item.role == "primary"
        if _candidate_has_source_proximity_diagnostic_support(item.candidate)
        for turn_ref in _candidate_turn_refs(item.candidate)
    )
    if not primary_turn_refs:
        return ()
    distances: list[int] = []
    for item in items:
        if item.role == "primary":
            continue
        lacks_explicit_grounding = not _item_has_explicit_relation_or_role_grounding(
            item
        )
        if (
            missing_required_roles
            and lacks_explicit_grounding
            and not _candidate_has_focused_source_proximity_support(item.candidate)
        ):
            continue
        if not _candidate_has_source_proximity_diagnostic_support(item.candidate):
            continue
        closest_distance = _closest_turn_ref_distance(
            item.candidate,
            comparison_turn_refs=primary_turn_refs,
        )
        if closest_distance is None or closest_distance > _SOURCE_PROXIMITY_WINDOW:
            continue
        distances.append(closest_distance)
    return tuple(distances)


def _source_chain_proximity_distances(
    items: Sequence[PlannedEvidenceItem],
) -> tuple[int, ...]:
    primary_turn_refs = tuple(
        turn_ref
        for item in items
        if item.role == "primary"
        if _candidate_has_source_proximity_diagnostic_support(item.candidate)
        for turn_ref in _candidate_turn_refs(item.candidate)
    )
    previously_selected_turn_refs: list[tuple[str, int, int]] = []
    distances: list[int] = []
    for item in items:
        item_turn_refs = _candidate_turn_refs(item.candidate)
        if item.role == "primary":
            if _candidate_has_source_proximity_diagnostic_support(item.candidate):
                previously_selected_turn_refs.extend(item_turn_refs)
            continue
        if not _candidate_has_source_proximity_diagnostic_support(item.candidate):
            continue
        primary_distance = _closest_turn_ref_distance(
            item.candidate,
            comparison_turn_refs=primary_turn_refs,
        )
        if (
            primary_distance is not None
            and primary_distance <= _SOURCE_PROXIMITY_WINDOW
        ):
            previously_selected_turn_refs.extend(item_turn_refs)
            continue
        closest_distance = _closest_turn_ref_distance(
            item.candidate,
            comparison_turn_refs=previously_selected_turn_refs,
        )
        if closest_distance is not None and closest_distance <= _SOURCE_PROXIMITY_WINDOW:
            distances.append(closest_distance)
        previously_selected_turn_refs.extend(item_turn_refs)
    return tuple(distances)


def _diffuse_source_ref_samples(
    items: Sequence[PlannedEvidenceItem],
) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for item in items[:_SOURCE_DIAGNOSTIC_SAMPLE_LIMIT]:
        turn_refs = _candidate_turn_refs(item.candidate)
        samples.append(
            {
                "id": item.candidate.item_id,
                "role": item.role,
                "source_ref_count": len(item.candidate.source_refs),
                "turn_ref_count": len(turn_refs),
                "source_group_count": len({turn_ref[:2] for turn_ref in turn_refs}),
                "max_turn_span": _turn_ref_span(turn_refs),
                "turn_refs_sample": _source_turn_ref_strings_sample(item.candidate),
            }
        )
    return samples


def _weak_source_locality_samples(
    items: Sequence[PlannedEvidenceItem],
) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for item in items[:_SOURCE_DIAGNOSTIC_SAMPLE_LIMIT]:
        samples.append(
            {
                "id": item.candidate.item_id,
                "role": item.role,
                "source_locality_score": round(
                    item.candidate.source_locality_score,
                    6,
                ),
                "answerability_score": round(item.candidate.answerability_score, 6),
                "source_ref_count": len(item.candidate.source_refs),
                "turn_refs_sample": _source_turn_ref_strings_sample(item.candidate),
            }
        )
    return samples


def _participant_grounding_blocked_required_role_samples(
    items: Sequence[PlannedEvidenceItem],
    *,
    missing_required_roles: Sequence[str],
) -> list[dict[str, object]]:
    requested_terms = _selected_primary_person_grounding_terms(items)
    if not requested_terms:
        return []
    samples: list[dict[str, object]] = []
    for role in missing_required_roles:
        if role not in _PARTICIPANT_SENSITIVE_REQUIRED_ROLES:
            continue
        for item in items:
            if not _item_can_satisfy_required_role(item, role):
                continue
            if _item_has_requested_participant_grounding(item, items):
                continue
            samples.append(
                {
                    "id": item.candidate.item_id,
                    "role": item.role,
                    "required_role": role,
                    "requested_person_terms": list(requested_terms),
                    "candidate_person_terms": list(
                        _candidate_person_grounding_terms(item.candidate)
                    ),
                    "relation_hits": list(item.candidate.relation_hits),
                    "relation_category_hits": list(
                        item.candidate.relation_category_hits
                    ),
                }
            )
            if len(samples) >= _SOURCE_DIAGNOSTIC_SAMPLE_LIMIT:
                return samples
    return samples


def _source_turn_ref_strings_sample(
    candidate: EvidenceBundleCandidate,
) -> list[str]:
    return list(
        _candidate_turn_ref_strings(candidate)[:_SOURCE_DIAGNOSTIC_REF_SAMPLE_LIMIT]
    )


def _bundle_quality_reason_codes(
    *,
    primary_count: int,
    supporting_count: int,
    focused_count: int,
    direct_speaker_count: int,
    source_ref_item_count: int,
    source_ref_support_item_count: int,
    source_identity_item_count: int,
    source_identity_support_item_count: int,
    source_type_diversity: int,
    retrieval_source_diversity: int,
    source_type_support_diversity: int,
    retrieval_source_support_diversity: int,
    max_answerability: float,
    low_answerability_count: int,
    generic_measured_answerability_count: int,
    bridge_count: int,
    distinct_person_grounding_count: int,
    causal_support_count: int,
    communication_support_count: int,
    event_support_count: int,
    exchange_support_count: int,
    inference_support_count: int,
    location_support_count: int,
    emotion_response_support_count: int,
    symbolic_meaning_support_count: int,
    preference_support_count: int,
    favorite_support_count: int,
    visual_support_count: int,
    typed_relation_support_counts: Mapping[str, int],
    partial_required_role_support_counts: Mapping[str, int],
    participant_grounding_blocked_required_role_count: int,
    location_relation_category_hit_count: int,
    source_proximity_support_count: int,
    source_chain_proximity_support_count: int,
    missing_required_roles: Sequence[str],
    contrast_count: int,
    negative_absence_support_count: int,
    contrast_surface_count: int,
    negation_surface_count: int,
    currentness_surface_count: int,
    stale_surface_count: int,
    broad_summary_count: int,
    diffuse_source_ref_count: int,
    weak_source_locality_count: int,
    conflict_or_stale_count: int,
    selected_item_count: int,
) -> list[str]:
    reasons: list[str] = []
    if primary_count:
        reasons.append("has_primary_evidence")
    if supporting_count:
        reasons.append("has_supporting_evidence")
    if focused_count:
        reasons.append("has_focused_evidence")
    if direct_speaker_count:
        reasons.append("has_direct_speaker_evidence")
    if source_ref_support_item_count:
        reasons.append("has_source_refs")
    elif source_identity_support_item_count:
        reasons.append("has_source_identity")
    if source_type_support_diversity >= 2:
        reasons.append("source_type_diverse")
    if retrieval_source_support_diversity >= 2:
        reasons.append("retrieval_source_diverse")
    if max_answerability >= 0.8:
        reasons.append("high_answerability")
    elif max_answerability >= 0.55:
        reasons.append("medium_answerability")
    if low_answerability_count:
        reasons.append("risk:low_answerability")
    if generic_measured_answerability_count:
        reasons.append("risk:generic_measured_answerability")
    if (
        selected_item_count
        and generic_measured_answerability_count == selected_item_count
    ):
        reasons.append("risk:all_generic_measured_answerability")
    if bridge_count:
        reasons.append("has_bridge_evidence")
    if distinct_person_grounding_count >= 2:
        reasons.append("has_distinct_person_grounding")
    if causal_support_count:
        reasons.append("has_causal_support_evidence")
    if communication_support_count:
        reasons.append("has_communication_support_evidence")
    if event_support_count:
        reasons.append("has_event_support_evidence")
    if exchange_support_count:
        reasons.append("has_exchange_support_evidence")
    if inference_support_count:
        reasons.append("has_inference_support_evidence")
    if location_support_count:
        reasons.append("has_location_support_evidence")
    if emotion_response_support_count:
        reasons.append("has_emotion_response_support_evidence")
    if symbolic_meaning_support_count:
        reasons.append("has_symbolic_meaning_support_evidence")
    if preference_support_count:
        reasons.append("has_preference_support_evidence")
    if favorite_support_count:
        reasons.append("has_favorite_support_evidence")
    if visual_support_count:
        reasons.append("has_visual_support_evidence")
    if typed_relation_support_counts:
        reasons.append("has_typed_relation_support_evidence")
        reasons.extend(
            f"has_{role}_evidence"
            for role, count in sorted(typed_relation_support_counts.items())
            if count > 0
        )
    if partial_required_role_support_counts:
        reasons.append("has_partial_required_role_support")
        reasons.extend(
            f"partial_required_{role}"
            for role, count in sorted(partial_required_role_support_counts.items())
            if count > 0
        )
    if participant_grounding_blocked_required_role_count:
        reasons.append("risk:participant_grounding_mismatch")
    if location_relation_category_hit_count:
        reasons.append("has_location_relation_category_evidence")
    if source_proximity_support_count:
        reasons.append("has_source_proximity_support")
    if source_chain_proximity_support_count:
        reasons.append("has_source_chain_proximity_support")
    if missing_required_roles:
        reasons.append("risk:missing_required_role")
        reasons.extend(
            f"risk:missing_required_{role}" for role in missing_required_roles
        )
    if contrast_count:
        reasons.append("has_contrast_evidence")
    if negative_absence_support_count:
        reasons.append("has_negative_absence_evidence")
    if contrast_surface_count:
        reasons.append("has_contrast_surface")
    if negation_surface_count:
        reasons.append("has_negation_surface")
    if currentness_surface_count:
        reasons.append("has_currentness_evidence")
    if stale_surface_count:
        reasons.append("has_stale_evidence")
    if broad_summary_count:
        reasons.append("risk:broad_summary")
    if selected_item_count and broad_summary_count == selected_item_count:
        reasons.append("risk:all_broad_summary")
    if diffuse_source_ref_count:
        reasons.append("risk:diffuse_source_refs")
    if weak_source_locality_count:
        reasons.append("risk:weak_source_locality")
    if conflict_or_stale_count:
        reasons.append("risk:conflict_or_stale")
    if selected_item_count and conflict_or_stale_count == selected_item_count:
        reasons.append("risk:all_conflict_or_stale")
    return reasons or ["weak_bundle"]


def _confidence_band(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.55:
        return "medium"
    if score > 0:
        return "low"
    return "none"
