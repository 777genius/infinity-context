"""Bounded application selection for keyword aggregation evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from infinity_context_core.application.context_distinct_set_evidence import (
    DistinctSetEvidenceProjection,
)
from infinity_context_core.application.context_query_intent import (
    QueryAnchorIntent,
    query_anchor_intent_text_conflicts,
)
from infinity_context_core.domain.aggregation_admission import (
    AggregationAdmissionCandidate,
    AggregationAdmissionDecision,
    AggregationAdmissionPolicy,
    AggregationAdmissionReason,
)
from infinity_context_core.domain.distinct_set_membership import (
    DistinctSetMemberCandidate,
    DistinctSetMemberReservationPolicy,
)
from infinity_context_core.domain.entities import MemoryAnchorKind

_MAX_DISTINCT_MEMBER_RESERVATIONS = 8


def distinct_set_anchor_conflict(
    intent: QueryAnchorIntent,
    *,
    projection: DistinctSetEvidenceProjection,
    fallback_text: str,
) -> bool:
    """Check exact projected evidence after set-specific temporal validation."""

    if projection.subject_conflict:
        return True
    if not projection.present:
        return query_anchor_intent_text_conflicts(intent, fallback_text)
    non_member_intent = QueryAnchorIntent(
        hints=tuple(
            hint
            for hint in intent.hints
            if hint.kind not in {MemoryAnchorKind.EVENT, MemoryAnchorKind.PERSON}
        )
    )
    return query_anchor_intent_text_conflicts(non_member_intent, projection.rendered_text)


class KeywordAggregationCandidateView(Protocol):
    admission: AggregationAdmissionCandidate
    aggregation_reason: str
    group: str
    member_ids: tuple[str, ...]


@dataclass(frozen=True)
class KeywordAggregationCandidateSelection:
    decision_by_id: dict[str, AggregationAdmissionDecision]
    admission_reason_by_id: dict[str, str]
    relaxed_ids: frozenset[str]
    selected_ids: frozenset[str]
    continuity_ids: frozenset[str]
    member_reserved_ids: frozenset[str]
    provenance_admitted_ids: frozenset[str]
    reason_counts: dict[str, int]
    rejected_count: int
    admitted_not_selected: int
    slot_reservation_count: int
    distinct_member_candidate_count: int
    distinct_member_reservation_count: int
    distinct_member_slot_count: int


def select_keyword_aggregation_candidates(
    candidates: tuple[KeywordAggregationCandidateView, ...],
    *,
    ordinary_ids: frozenset[str],
    ordinary_limit: int,
    continuity_limit: int,
    source_family_cap: int,
) -> KeywordAggregationCandidateSelection:
    """Reserve novel set members, then fill the unchanged ordinary/tail bounds."""

    admission_policy = AggregationAdmissionPolicy()
    decisions = tuple(admission_policy.decide(candidate.admission) for candidate in candidates)
    decision_by_id = {decision.candidate_id: decision for decision in decisions}
    member_conflict_reason_by_id = {
        candidate.admission.candidate_id: reason
        for candidate in candidates
        if (reason := _distinct_member_conflict_reason(candidate)) is not None
    }
    eligible_member_candidates = tuple(
        DistinctSetMemberCandidate(
            candidate_id=candidate.admission.candidate_id,
            source_family=candidate.group,
            member_ids=candidate.member_ids,
        )
        for candidate in candidates
        if candidate.member_ids
        and candidate.admission.candidate_id not in member_conflict_reason_by_id
    )
    member_reservation = DistinctSetMemberReservationPolicy().select(
        eligible_member_candidates,
        limit=min(_MAX_DISTINCT_MEMBER_RESERVATIONS, max(0, ordinary_limit)),
    )
    member_reserved_ids = frozenset(member_reservation.selected_ids)
    redundant_member_ids = frozenset(
        candidate.admission.candidate_id
        for candidate in candidates
        if candidate.member_ids
        and candidate.admission.candidate_id not in member_reserved_ids
        and set(candidate.member_ids).issubset(member_reservation.reserved_member_ids)
    )
    member_source_families = tuple(
        candidate.group
        for candidate in candidates
        if candidate.admission.candidate_id in member_reserved_ids
    )
    ordinary_candidates = tuple(
        candidate.admission
        for candidate in candidates
        if candidate.admission.candidate_id in ordinary_ids
        and candidate.admission.candidate_id not in member_reserved_ids
        and candidate.admission.candidate_id not in redundant_member_ids
        and candidate.admission.candidate_id not in member_conflict_reason_by_id
        and decision_by_id[candidate.admission.candidate_id].admitted
    )
    ordinary = admission_policy.select(
        ordinary_candidates,
        limit=max(0, ordinary_limit - len(member_reserved_ids)),
        source_family_cap=source_family_cap,
        selected_source_families=member_source_families,
    )
    ordinary_selected_ids = set(member_reserved_ids) | set(ordinary.selected_ids)
    ordinary_supported_slots = {
        (candidate.aggregation_reason, candidate.group)
        for candidate in candidates
        if candidate.admission.candidate_id in ordinary_selected_ids
    }
    continuity_candidates = tuple(
        candidate.admission
        for candidate in candidates
        if candidate.admission.candidate_id not in ordinary_selected_ids
        and candidate.admission.candidate_id not in redundant_member_ids
        and candidate.admission.candidate_id not in member_conflict_reason_by_id
        and decision_by_id[candidate.admission.candidate_id].admitted
        and (candidate.aggregation_reason, candidate.group) not in ordinary_supported_slots
    )
    continuity = admission_policy.select(
        continuity_candidates,
        limit=continuity_limit,
        source_family_cap=source_family_cap,
        selected_source_families=tuple(
            candidate.group
            for candidate in candidates
            if candidate.admission.candidate_id in ordinary_selected_ids
        ),
    )
    continuity_ids = frozenset(continuity.selected_ids)
    selected_ids = frozenset(ordinary_selected_ids | set(continuity_ids))
    admission_reason_by_id = {
        decision.candidate_id: decision.reason.value for decision in decisions
    }
    admission_reason_by_id.update(
        {candidate_id: "distinct_member_support" for candidate_id in member_reserved_ids}
    )
    admission_reason_by_id.update(member_conflict_reason_by_id)
    relaxed_ids = frozenset(
        decision.candidate_id for decision in decisions if decision.relaxed
    ) | frozenset(
        candidate_id
        for candidate_id in member_reserved_ids
        if not decision_by_id[candidate_id].admitted
    )
    reason_counts: dict[str, int] = {}
    for candidate, decision in zip(candidates, decisions, strict=True):
        reason = (
            "distinct_member_support"
            if candidate.admission.candidate_id in member_reserved_ids
            else member_conflict_reason_by_id.get(
                candidate.admission.candidate_id, decision.reason.value
            )
        )
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    admitted_ids = {
        decision.candidate_id
        for decision in decisions
        if decision.admitted and decision.candidate_id not in redundant_member_ids
        and decision.candidate_id not in member_conflict_reason_by_id
    } | set(member_reserved_ids)
    provenance_admitted_ids = frozenset(
        candidate.admission.candidate_id
        for candidate in candidates
        if candidate.admission.candidate_id not in member_conflict_reason_by_id
        and (
            decision_by_id[candidate.admission.candidate_id].admitted
            or candidate.admission.candidate_id in member_reserved_ids
            or candidate.admission.candidate_id in redundant_member_ids
        )
    )
    rejected_count = len(redundant_member_ids) + len(member_conflict_reason_by_id) + sum(
        not decision.admitted
        and decision.candidate_id not in member_reserved_ids
        and decision.candidate_id not in redundant_member_ids
        and decision.candidate_id not in member_conflict_reason_by_id
        for decision in decisions
    )
    return KeywordAggregationCandidateSelection(
        decision_by_id=decision_by_id,
        admission_reason_by_id=admission_reason_by_id,
        relaxed_ids=relaxed_ids,
        selected_ids=selected_ids,
        continuity_ids=continuity_ids,
        member_reserved_ids=member_reserved_ids,
        provenance_admitted_ids=provenance_admitted_ids,
        reason_counts=reason_counts,
        rejected_count=rejected_count,
        admitted_not_selected=len(admitted_ids - set(selected_ids)),
        slot_reservation_count=len(ordinary_supported_slots) + len(continuity.reserved_ids),
        distinct_member_candidate_count=len(eligible_member_candidates),
        distinct_member_reservation_count=len(member_reserved_ids),
        distinct_member_slot_count=len(member_reservation.reserved_member_ids),
    )


def _distinct_member_conflict_reason(candidate: KeywordAggregationCandidateView) -> str | None:
    if not candidate.member_ids:
        if candidate.admission.signals.temporal_conflict:
            return AggregationAdmissionReason.TEMPORAL_CONFLICT.value
        if candidate.admission.signals.anchor_conflict:
            return AggregationAdmissionReason.ANCHOR_CONFLICT.value
        return None
    if candidate.admission.signals.temporal_conflict:
        return AggregationAdmissionReason.TEMPORAL_CONFLICT.value
    if candidate.admission.signals.anchor_conflict:
        return AggregationAdmissionReason.ANCHOR_CONFLICT.value
    return None
