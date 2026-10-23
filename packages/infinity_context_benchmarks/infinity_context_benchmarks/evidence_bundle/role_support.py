"""Selection-level required-role and complementary bridge satisfaction."""

from __future__ import annotations

from collections.abc import (
    Sequence,
)

from infinity_context_benchmarks.evidence_bundle.candidate_policy import (
    _NEGATIVE_ABSENCE_ROLES,
    _PARTICIPANT_SENSITIVE_REQUIRED_ROLES,
    _PREDICATE_REQUIRED_ROLES,
    _TYPED_RELATION_SUPPORT_CATEGORIES,
    _TYPED_TEMPORAL_SUPPORT_ROLES,
    _candidate_has_bridge_grounding,
    _candidate_has_causal_support,
    _candidate_has_communication_support,
    _candidate_has_complementary_bridge_value,
    _candidate_has_contrast_support,
    _candidate_has_count_support,
    _candidate_has_emotion_response_support,
    _candidate_has_event_support,
    _candidate_has_exchange_support,
    _candidate_has_inference_support,
    _candidate_has_list_support,
    _candidate_has_local_bridge_grounding,
    _candidate_has_location_support,
    _candidate_has_negative_absence_support,
    _candidate_has_preference_support,
    _candidate_has_symbolic_meaning_support,
    _candidate_has_temporal_support,
    _candidate_has_typed_relation_support,
    _candidate_has_typed_temporal_support,
    _candidate_has_value_support,
    _candidate_has_visual_support,
)
from infinity_context_benchmarks.evidence_bundle.models import (
    EvidenceBundleCandidate,
    PlannedEvidenceItem,
)
from infinity_context_benchmarks.evidence_bundle.partial_support import (
    has_partial_required_role_support,
)
from infinity_context_benchmarks.evidence_bundle.source_policy import (
    _SOURCE_PROXIMITY_WINDOW,
    _candidate_has_measured_weak_source_locality,
    _candidate_has_person_grounding,
    _candidate_has_relation_grounding,
    _candidate_has_source_identity_quality_support,
    _candidate_has_source_proximity_diagnostic_support,
    _candidate_person_grounding_terms,
    _candidate_turn_ref_strings,
    _candidate_turn_refs,
    _closest_turn_ref_distance,
    _is_measured_low_answerability,
    _source_identity_refs,
)


def _required_role_values(required_roles: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(role for role in required_roles if role.strip()))


def _satisfied_required_roles(
    selected: Sequence[PlannedEvidenceItem],
    *,
    required_roles: Sequence[str],
) -> tuple[str, ...]:
    satisfied: set[str] = set()
    selected_roles = {item.role for item in selected}
    for role in required_roles:
        if role == "temporal_support" and any(
            _candidate_has_temporal_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
            continue
        if role in _TYPED_TEMPORAL_SUPPORT_ROLES and any(
            _candidate_has_typed_temporal_support(item.candidate, role)
            for item in selected
        ):
            satisfied.add(role)
            continue
        if role == "bridge":
            if _selection_has_bridge_support(selected):
                satisfied.add(role)
            continue
        if role in selected_roles and role not in _PREDICATE_REQUIRED_ROLES:
            satisfied.add(role)
            continue
        if role == "contrast" and any(
            _candidate_has_contrast_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
            continue
        if role in _NEGATIVE_ABSENCE_ROLES and any(
            _candidate_has_negative_absence_support(item.candidate)
            for item in selected
        ):
            satisfied.add(role)
            continue
        if role == "location_support" and any(
            _item_can_satisfy_required_role_in_selection(item, role, selected)
            for item in selected
        ):
            satisfied.add(role)
        if role == "value_support" and any(
            _candidate_has_value_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
        if role == "count_support" and any(
            _candidate_has_count_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
        if role == "list_support" and any(
            _candidate_has_list_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
        if role == "preference_support" and any(
            _candidate_has_preference_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
        if role == "visual_support" and any(
            _candidate_has_visual_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
        if role == "emotion_response_support" and any(
            _candidate_has_emotion_response_support(item.candidate)
            for item in selected
        ):
            satisfied.add(role)
        if role == "symbolic_meaning_support" and any(
            _candidate_has_symbolic_meaning_support(item.candidate)
            for item in selected
        ):
            satisfied.add(role)
        if role == "event_support" and any(
            _item_can_satisfy_required_role_in_selection(item, role, selected)
            for item in selected
        ):
            satisfied.add(role)
        if role == "communication_support" and any(
            _candidate_has_communication_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
        if role == "exchange_support" and any(
            _candidate_has_exchange_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
        if role == "inference_support" and any(
            _candidate_has_inference_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
        if role == "causal_support" and any(
            _candidate_has_causal_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
        if role in _TYPED_RELATION_SUPPORT_CATEGORIES and any(
            _item_can_satisfy_required_role_in_selection(item, role, selected)
            for item in selected
        ):
            satisfied.add(role)
    return tuple(role for role in required_roles if role in satisfied)


def _selected_required_roles(
    item: PlannedEvidenceItem,
    *,
    required_roles: Sequence[str],
    selected: Sequence[PlannedEvidenceItem] = (),
) -> tuple[str, ...]:
    return tuple(
        role
        for role in required_roles
        if _item_can_satisfy_required_role_in_selection(item, role, selected)
    )


def _item_can_satisfy_required_role_in_selection(
    item: PlannedEvidenceItem,
    role: str,
    selected: Sequence[PlannedEvidenceItem],
) -> bool:
    if not _item_can_satisfy_required_role(item, role):
        return False
    if role not in _PARTICIPANT_SENSITIVE_REQUIRED_ROLES:
        return True
    return _item_has_requested_participant_grounding(item, selected)


def _item_can_satisfy_required_role(
    item: PlannedEvidenceItem,
    role: str,
) -> bool:
    if role == "temporal_support":
        return _candidate_has_temporal_support(item.candidate)
    if role in _TYPED_TEMPORAL_SUPPORT_ROLES:
        return _candidate_has_typed_temporal_support(item.candidate, role)
    if role == "contrast":
        return _candidate_has_contrast_support(item.candidate)
    if role in _NEGATIVE_ABSENCE_ROLES:
        return _candidate_has_negative_absence_support(item.candidate)
    if role == "bridge":
        return item.role == "bridge"
    if role == "location_support":
        return _candidate_has_location_support(item.candidate)
    if role == "value_support":
        return _candidate_has_value_support(item.candidate)
    if role == "count_support":
        return _candidate_has_count_support(item.candidate)
    if role == "list_support":
        return _candidate_has_list_support(item.candidate)
    if role == "preference_support":
        return _candidate_has_preference_support(item.candidate)
    if role == "visual_support":
        return _candidate_has_visual_support(item.candidate)
    if role == "emotion_response_support":
        return _candidate_has_emotion_response_support(item.candidate)
    if role == "symbolic_meaning_support":
        return _candidate_has_symbolic_meaning_support(item.candidate)
    if role == "event_support":
        return _candidate_has_event_support(item.candidate)
    if role == "communication_support":
        return _candidate_has_communication_support(item.candidate)
    if role == "exchange_support":
        return _candidate_has_exchange_support(item.candidate)
    if role == "inference_support":
        return _candidate_has_inference_support(item.candidate)
    if role == "causal_support":
        return _candidate_has_causal_support(item.candidate)
    if role in _TYPED_RELATION_SUPPORT_CATEGORIES:
        return _candidate_has_typed_relation_support(item.candidate, role)
    return item.role == role


def _item_has_requested_participant_grounding(
    item: PlannedEvidenceItem,
    selected: Sequence[PlannedEvidenceItem],
) -> bool:
    candidate = item.candidate
    if not candidate.query_has_entities:
        return True
    requested_terms = _selected_primary_person_grounding_terms(selected)
    if not requested_terms:
        return True
    candidate_terms = set(_candidate_person_grounding_terms(candidate))
    return bool(candidate_terms.intersection(requested_terms))


def _selected_primary_person_grounding_terms(
    selected: Sequence[PlannedEvidenceItem],
) -> frozenset[str]:
    return frozenset(
        term
        for item in selected
        if item.role == "primary"
        for term in _candidate_person_grounding_terms(item.candidate)
    )


def _selection_has_bridge_support(selected: Sequence[PlannedEvidenceItem]) -> bool:
    if len(selected) < 2:
        return False
    primary_items = tuple(item for item in selected if item.role == "primary")
    if not primary_items:
        return False
    non_primary_items = tuple(item for item in selected if item.role != "primary")
    if any(
        _candidate_has_bridge_grounding(item.candidate)
        and _candidate_is_distinct_from_primary(item.candidate, primary_items)
        and _candidate_has_complementary_bridge_value_for_primary_items(
            item.candidate,
            primary_items,
        )
        for item in non_primary_items
    ):
        return True
    return any(
        _candidate_has_distinct_multi_hop_support(item)
        and _candidate_is_distinct_from_primary(item.candidate, primary_items)
        and _candidate_has_complementary_bridge_value_for_primary_items(
            item.candidate,
            primary_items,
        )
        for item in non_primary_items
    ) or _selection_has_source_chain_bridge_support(
        non_primary_items,
        primary_items=primary_items,
    )


def _candidate_has_distinct_multi_hop_support(item: PlannedEvidenceItem) -> bool:
    if item.role == "primary":
        return False
    candidate = item.candidate
    if candidate.conflict_or_stale or candidate.broad_summary:
        return False
    if candidate.covered_evidence_terms or candidate.covered_expected_terms:
        return True
    if _candidate_has_measured_weak_source_locality(candidate):
        return False
    if _is_measured_low_answerability(candidate.answerability_score):
        return False
    if not _candidate_has_local_bridge_grounding(candidate):
        return False
    support_terms = tuple(dict.fromkeys(candidate.query_support_terms))
    return bool(
        candidate.focused_evidence_score > 0 and len(support_terms) >= 2
    )


def _candidate_has_complementary_bridge_value_for_primary_items(
    candidate: EvidenceBundleCandidate,
    primary_items: Sequence[PlannedEvidenceItem],
) -> bool:
    return any(
        _candidate_has_complementary_bridge_value(candidate, primary_item.candidate)
        for primary_item in primary_items
    )


def _selection_has_source_chain_bridge_support(
    non_primary_items: Sequence[PlannedEvidenceItem],
    *,
    primary_items: Sequence[PlannedEvidenceItem],
) -> bool:
    primary_turn_refs = tuple(
        turn_ref
        for item in primary_items
        if _candidate_has_source_proximity_diagnostic_support(item.candidate)
        for turn_ref in _candidate_turn_refs(item.candidate)
    )
    if not primary_turn_refs:
        return False
    previously_selected_turn_refs = list(primary_turn_refs)
    for item in non_primary_items:
        candidate = item.candidate
        item_turn_refs = _candidate_turn_refs(candidate)
        if not _candidate_has_source_proximity_diagnostic_support(candidate):
            continue
        primary_distance = _closest_turn_ref_distance(
            candidate,
            comparison_turn_refs=primary_turn_refs,
        )
        chain_distance = _closest_turn_ref_distance(
            candidate,
            comparison_turn_refs=previously_selected_turn_refs,
        )
        if (
            _candidate_has_source_chain_multi_hop_support(candidate)
            and _candidate_is_distinct_from_primary(candidate, primary_items)
            and _candidate_has_complementary_bridge_value_for_primary_items(
                candidate,
                primary_items,
            )
            and (
                (
                    primary_distance is not None
                    and primary_distance <= _SOURCE_PROXIMITY_WINDOW
                )
                or (
                    chain_distance is not None
                    and chain_distance <= _SOURCE_PROXIMITY_WINDOW
                )
            )
        ):
            return True
        previously_selected_turn_refs.extend(item_turn_refs)
    return False


def _candidate_has_source_chain_multi_hop_support(
    candidate: EvidenceBundleCandidate,
) -> bool:
    support_terms = tuple(dict.fromkeys(candidate.query_support_terms))
    return bool(
        support_terms
        and _candidate_has_source_identity_quality_support(candidate)
        and _candidate_has_local_bridge_grounding(candidate)
        and _candidate_has_relation_grounding(candidate)
        and _candidate_has_person_grounding(candidate)
    )


def _candidate_is_distinct_from_primary(
    candidate: EvidenceBundleCandidate,
    primary_items: Sequence[PlannedEvidenceItem],
) -> bool:
    candidate_turn_refs = set(_candidate_turn_ref_strings(candidate))
    candidate_source_refs = {str(ref).strip() for ref in candidate.source_refs if ref}
    candidate_identities = set(_source_identity_refs(candidate))
    for primary_item in primary_items:
        primary = primary_item.candidate
        if candidate.dedupe_key and candidate.dedupe_key == primary.dedupe_key:
            return False
        primary_turn_refs = set(_candidate_turn_ref_strings(primary))
        if candidate_turn_refs and candidate_turn_refs.intersection(primary_turn_refs):
            return False
        primary_source_refs = {
            str(ref).strip() for ref in primary.source_refs if str(ref).strip()
        }
        if candidate_source_refs and candidate_source_refs.intersection(
            primary_source_refs
        ):
            return False
        primary_identities = set(_source_identity_refs(primary))
        if candidate_identities and candidate_identities.intersection(
            primary_identities
        ):
            return False
    return True


def _item_has_partial_required_role_support(
    item: PlannedEvidenceItem,
    role: str,
    selected: Sequence[PlannedEvidenceItem] = (),
) -> bool:
    return has_partial_required_role_support(
        item.candidate,
        item_role=item.role,
        role=role,
        complete_support=_item_can_satisfy_required_role_in_selection(
            item,
            role,
            selected,
        ),
        typed_relation_support_categories=_TYPED_RELATION_SUPPORT_CATEGORIES,
    )
