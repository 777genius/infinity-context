"""Bounded required-role repair and replacement preferences."""

from __future__ import annotations

from collections.abc import (
    Sequence,
)

from infinity_context_benchmarks.evidence_bundle.models import (
    PlannedEvidenceItem,
)
from infinity_context_benchmarks.evidence_bundle.ordering import (
    _candidate_sort_key,
    _explicit_relation_role_sort_key,
    _person_grounding_selection_sort_key,
    _planned_sort_key,
    _role_order,
    _source_overlap_selection_sort_key,
    _source_proximity_selection_sort_key,
)
from infinity_context_benchmarks.evidence_bundle.role_support import (
    _item_can_satisfy_required_role_in_selection,
    _satisfied_required_roles,
    _selected_required_roles,
)


def _repair_required_role_selection(
    selected: Sequence[PlannedEvidenceItem],
    planned: Sequence[PlannedEvidenceItem],
    *,
    required_roles: Sequence[str],
    max_items: int,
) -> tuple[tuple[PlannedEvidenceItem, ...], tuple[str, ...]]:
    if not required_roles or not planned:
        return tuple(selected), ()

    selected_items = list(selected)
    repaired_roles: list[str] = []
    for _ in range(len(required_roles)):
        missing_roles = _missing_required_roles(
            selected_items,
            required_roles=required_roles,
        )
        if not missing_roles:
            break
        repaired_this_pass = False
        for role in missing_roles:
            candidate = _best_required_role_candidate(
                planned,
                selected_items,
                role=role,
            )
            if candidate is None:
                continue
            if len(selected_items) < max_items:
                selected_items.append(candidate)
                repaired_roles.append(role)
                repaired_this_pass = True
                break
            replace_index = _replaceable_item_index(
                selected_items,
                required_roles=required_roles,
            )
            if replace_index is None:
                continue
            selected_items[replace_index] = candidate
            repaired_roles.append(role)
            repaired_this_pass = True
            break
        if not repaired_this_pass:
            break

    if not repaired_roles:
        return tuple(selected), ()
    return tuple(sorted(selected_items, key=_planned_sort_key)), tuple(
        dict.fromkeys(repaired_roles)
    )


def _missing_required_roles(
    selected: Sequence[PlannedEvidenceItem],
    *,
    required_roles: Sequence[str],
) -> tuple[str, ...]:
    satisfied = set(
        _satisfied_required_roles(selected, required_roles=required_roles)
    )
    return tuple(role for role in required_roles if role not in satisfied)


def _best_required_role_candidate(
    planned: Sequence[PlannedEvidenceItem],
    selected: Sequence[PlannedEvidenceItem],
    *,
    role: str,
) -> PlannedEvidenceItem | None:
    selected_ids = {id(item) for item in selected}
    candidates = [
        item
        for item in planned
        if id(item) not in selected_ids
        and _item_can_satisfy_required_role_in_selection(item, role, selected)
    ]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: _required_role_candidate_sort_key(item, selected),
    )[0]


def _replaceable_item_index(
    selected: Sequence[PlannedEvidenceItem],
    *,
    required_roles: Sequence[str],
) -> int | None:
    replaceable = [
        (index, item)
        for index, item in enumerate(selected)
        if not _selected_required_roles(
            item,
            required_roles=required_roles,
            selected=selected,
        )
    ]
    if not replaceable:
        return None
    return sorted(
        replaceable,
        key=lambda pair: _replacement_sort_key(pair[1], selected),
    )[0][0]


def _required_role_candidate_sort_key(
    item: PlannedEvidenceItem,
    selected: Sequence[PlannedEvidenceItem] = (),
) -> tuple[float, ...]:
    return (
        *_source_overlap_selection_sort_key(item, selected),
        *_explicit_relation_role_sort_key(item),
        *_source_proximity_selection_sort_key(item, selected),
        *_person_grounding_selection_sort_key(item, selected),
        *_candidate_sort_key(item.candidate),
        _role_order(item),
    )


def _replacement_sort_key(
    item: PlannedEvidenceItem,
    selected: Sequence[PlannedEvidenceItem],
) -> tuple[float, ...]:
    other_required_terms = {
        term
        for other in selected
        if other is not item
        for term in other.candidate.required_terms
    }
    other_support_terms = {
        term
        for other in selected
        if other is not item
        for term in other.candidate.query_support_terms
        if str(term).strip()
    }
    unique_required_gain = len(
        item.candidate.required_terms.difference(other_required_terms)
    )
    unique_support_gain = len(
        set(item.candidate.query_support_terms).difference(other_support_terms)
    )
    return (
        _replacement_role_order(item),
        float(unique_required_gain),
        float(unique_support_gain),
        item.candidate.answerability_score,
        item.candidate.source_locality_score,
        item.candidate.bundle_strength_score,
        float(item.candidate.retrieval_order),
        float(item.candidate.rank),
    )


def _replacement_role_order(item: PlannedEvidenceItem) -> float:
    role_order = {
        "supporting": 0,
        "entity_disambiguation": 1,
        "causal_support": 2,
        "communication_support": 2,
        "event_support": 2,
        "exchange_support": 2,
        "inference_support": 2,
        "negative_support": 2,
        "emotion_response_support": 2,
        "symbolic_meaning_support": 2,
        "preference_support": 2,
        "temporal_support": 2,
        "duration_temporal_support": 2,
        "explicit_temporal_support": 2,
        "relative_temporal_support": 2,
        "temporal_sequence_support": 2,
        "visual_temporal_support": 2,
        "value_support": 2,
        "count_support": 2,
        "list_support": 2,
        "visual_support": 2,
        "contrast": 3,
        "bridge": 4,
        "location_support": 4,
        "primary": 5,
    }
    return float(role_order.get(item.role, 9))
