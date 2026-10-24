"""Stable coverage, evidence and provenance ordering for bundle selection."""

from __future__ import annotations

from collections.abc import (
    Sequence,
)

from infinity_context_benchmarks.evidence_bundle.candidate_policy import (
    _PREDICATE_REQUIRED_ROLES,
    _TYPED_RELATION_SUPPORT_CATEGORIES,
    _answer_evidence_sort_bucket,
    _candidate_has_contrast_support,
    _candidate_has_negative_absence_support,
    _candidate_has_temporal_support,
    _candidate_list_items,
)
from infinity_context_benchmarks.evidence_bundle.models import (
    EvidenceBundleCandidate,
    PlannedEvidenceItem,
)
from infinity_context_benchmarks.evidence_bundle.role_support import (
    _item_can_satisfy_required_role,
)
from infinity_context_benchmarks.evidence_bundle.source_policy import (
    _SOURCE_PROXIMITY_WINDOW,
    _candidate_has_diffuse_source_refs,
    _candidate_has_measured_answerability_below,
    _candidate_has_noisy_source_overlap_risk,
    _candidate_has_source_proximity_diagnostic_support,
    _candidate_person_grounding_terms,
    _candidate_turn_ref_strings,
    _candidate_turn_refs,
    _closest_turn_ref_distance,
    _turn_ref_span,
)


def _planned_sort_key(item: PlannedEvidenceItem) -> tuple[float, ...]:
    return (
        _role_order(item),
        *_candidate_sort_key(item.candidate),
    )


def _role_order(item: PlannedEvidenceItem) -> float:
    role_order = {
        "primary": 0,
        "bridge": 1,
        "contrast": 2,
        "negative_support": 3,
        "location_support": 3,
        "communication_support": 3,
        "event_support": 3,
        "exchange_support": 3,
        "emotion_response_support": 3,
        "symbolic_meaning_support": 3,
        "preference_support": 3,
        "temporal_support": 3,
        "duration_temporal_support": 3,
        "explicit_temporal_support": 3,
        "relative_temporal_support": 3,
        "temporal_sequence_support": 3,
        "visual_temporal_support": 3,
        "value_support": 3,
        "count_support": 3,
        "list_support": 3,
        "visual_support": 3,
        "causal_support": 4,
        "inference_support": 4,
        "entity_disambiguation": 5,
        "supporting": 5,
    }
    if item.role in _TYPED_RELATION_SUPPORT_CATEGORIES:
        return 3.0
    return float(role_order.get(item.role, 9))


def _planned_coverage_sort_key(
    item: PlannedEvidenceItem,
    *,
    covered_terms: set[str],
    covered_support_terms: set[str],
    covered_list_items: set[str] | None = None,
    selected: Sequence[PlannedEvidenceItem] = (),
) -> tuple[float, ...]:
    required_gain = len(item.candidate.required_terms.difference(covered_terms))
    support_gain = len(
        set(item.candidate.query_support_terms).difference(covered_support_terms)
    )
    list_item_gain = len(
        _candidate_list_items(item.candidate).difference(covered_list_items or set())
    )
    return (
        _role_order(item),
        -float(required_gain),
        -float(list_item_gain),
        *_source_overlap_selection_sort_key(item, selected),
        *_source_ref_compactness_selection_sort_key(item),
        float(_answer_evidence_sort_bucket(item.candidate)),
        *_explicit_relation_role_sort_key(item),
        *_source_proximity_selection_sort_key(item, selected),
        *_person_grounding_selection_sort_key(item, selected),
        *_selection_precision_sort_key(item),
        -float(support_gain),
        *_candidate_sort_key(item.candidate),
    )


def _source_overlap_selection_sort_key(
    item: PlannedEvidenceItem,
    selected: Sequence[PlannedEvidenceItem],
) -> tuple[float]:
    if item.role == "primary" or not selected:
        return (0.0,)
    item_turn_refs = set(_candidate_turn_ref_strings(item.candidate))
    if not item_turn_refs:
        return (0.0,)
    selected_turn_refs = {
        turn_ref
        for selected_item in selected
        for turn_ref in _candidate_turn_ref_strings(selected_item.candidate)
    }
    return (1.0 if item_turn_refs.intersection(selected_turn_refs) else 0.0,)


def _source_proximity_selection_sort_key(
    item: PlannedEvidenceItem,
    selected: Sequence[PlannedEvidenceItem],
) -> tuple[float, float]:
    if item.role == "primary":
        return (1.0, float("inf"))
    if not _candidate_has_source_proximity_diagnostic_support(item.candidate):
        return (1.0, float("inf"))
    selected_turn_refs = tuple(
        turn_ref
        for selected_item in selected
        if _candidate_has_source_proximity_diagnostic_support(
            selected_item.candidate
        )
        for turn_ref in _candidate_turn_refs(selected_item.candidate)
    )
    if not selected_turn_refs:
        return (1.0, float("inf"))
    closest_distance = _closest_turn_ref_distance(
        item.candidate,
        comparison_turn_refs=selected_turn_refs,
    )
    if closest_distance is None or closest_distance > _SOURCE_PROXIMITY_WINDOW:
        return (1.0, float("inf"))
    return (0.0, float(closest_distance))


def _person_grounding_selection_sort_key(
    item: PlannedEvidenceItem,
    selected: Sequence[PlannedEvidenceItem],
) -> tuple[float, float]:
    if item.role == "primary" or not selected:
        return (0.0, 0.0)
    selected_terms = {
        term
        for selected_item in selected
        for term in _candidate_person_grounding_terms(selected_item.candidate)
    }
    if not selected_terms:
        return (1.0, 0.0)
    candidate_terms = set(_candidate_person_grounding_terms(item.candidate))
    if not candidate_terms:
        return (1.0, 0.0)
    overlap_count = len(candidate_terms.intersection(selected_terms))
    if _candidate_prefers_distinct_person_grounding(item.candidate):
        new_count = len(candidate_terms.difference(selected_terms))
        if new_count:
            return (0.0, -float(new_count))
        if overlap_count:
            return (1.0, -float(overlap_count))
        return (2.0, 0.0)
    if overlap_count:
        return (0.0, -float(overlap_count))
    return (2.0, 0.0)


def _candidate_prefers_distinct_person_grounding(
    candidate: EvidenceBundleCandidate,
) -> bool:
    if candidate.query_has_entities:
        return False
    return bool(candidate.entity_hits or candidate.speaker_hits)


def _source_ref_compactness_selection_sort_key(
    item: PlannedEvidenceItem,
) -> tuple[float, float, float]:
    if item.role == "primary":
        return (0.0, 0.0, 0.0)
    turn_refs = _candidate_turn_refs(item.candidate)
    if not turn_refs:
        return (0.0, 0.0, 0.0)
    if not _candidate_has_diffuse_source_refs(item.candidate):
        return (0.0, 0.0, 0.0)
    return (
        1.0,
        float(_turn_ref_span(turn_refs)),
        float(len(turn_refs)),
    )


def _selection_precision_sort_key(item: PlannedEvidenceItem) -> tuple[float, ...]:
    candidate = item.candidate
    return (
        float(_answer_evidence_sort_bucket(candidate)),
        1.0 if _candidate_has_noisy_source_overlap_risk(candidate) else 0.0,
        1.0 if _candidate_has_diffuse_source_refs(candidate) else 0.0,
        1.0 if _candidate_has_measured_answerability_below(candidate, 0.75) else 0.0,
        -candidate.answerability_score if candidate.answerability_score > 0 else 0.0,
        (
            -candidate.source_locality_score
            if candidate.source_locality_score > 0
            else 0.0
        ),
    )


def _explicit_relation_role_sort_key(item: PlannedEvidenceItem) -> tuple[float]:
    return (
        0.0 if _item_has_explicit_relation_or_role_grounding(item) else 1.0,
    )


def _item_has_explicit_relation_or_role_grounding(
    item: PlannedEvidenceItem,
) -> bool:
    candidate = item.candidate
    if candidate.relation_hits or candidate.relation_category_hits:
        return True
    if item.role == "temporal_support":
        return _candidate_has_temporal_support(candidate)
    if item.role == "contrast":
        return _candidate_has_contrast_support(candidate)
    if item.role == "negative_support":
        return _candidate_has_negative_absence_support(candidate)
    if item.role in _PREDICATE_REQUIRED_ROLES:
        return _item_can_satisfy_required_role(item, item.role)
    return False


def _primary_sort_key(candidate: EvidenceBundleCandidate) -> tuple[float, ...]:
    return (
        0.0 if candidate.direct_speaker_turn else 1.0,
        0.0 if not candidate.broad_summary else 1.0,
        -candidate.focused_evidence_score,
        0.0 if candidate.required_terms else 1.0,
        float(_answer_evidence_sort_bucket(candidate)),
        -candidate.answerability_score,
        -candidate.source_locality_score,
        -candidate.bundle_strength_score,
        0.0 if not candidate.conflict_or_stale else 1.0,
        float(candidate.retrieval_order),
        float(candidate.rank),
    )


def _candidate_sort_key(candidate: EvidenceBundleCandidate) -> tuple[float, ...]:
    return (
        0.0 if candidate.primary_signal else 1.0,
        float(_answer_evidence_sort_bucket(candidate)),
        0.0 if candidate.direct_speaker_turn else 1.0,
        0.0 if not candidate.broad_summary else 1.0,
        -candidate.focused_evidence_score,
        -candidate.answerability_score,
        -candidate.source_locality_score,
        -candidate.bundle_strength_score,
        0.0 if not candidate.conflict_or_stale else 1.0,
        float(candidate.retrieval_order),
        float(candidate.rank),
    )
