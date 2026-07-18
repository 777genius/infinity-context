"""Pure admission and bounded reservation policy for aggregation evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AggregationIntent(StrEnum):
    COUNT = "count"
    LIST = "list"
    SEQUENCE = "sequence"


class AggregationAdmissionReason(StrEnum):
    SUFFICIENT_RELEVANCE = "sufficient_relevance"
    RELAXED_DISTINCTIVE_SUPPORT = "relaxed_distinctive_support"
    MISSING_INTENT = "missing_intent"
    ZERO_OVERLAP = "zero_overlap"
    NUMERIC_ONLY = "numeric_only"
    MISSING_REQUESTED_SLOT = "missing_requested_slot"
    MISSING_SOURCE_FAMILY = "missing_source_family"
    ANCHOR_CONFLICT = "anchor_conflict"
    TEMPORAL_CONFLICT = "temporal_conflict"
    INSUFFICIENT_SUPPORT = "insufficient_support"


@dataclass(frozen=True)
class AggregationAdmissionSignals:
    """Provider-independent signals normalized by the application layer."""

    intent: AggregationIntent | None
    relevance_sufficient: bool
    distinctive_hits: int
    unique_hits: int
    query_plan_slot: str
    source_family: str
    anchor_conflict: bool = False
    temporal_conflict: bool = False
    numeric_corroboration: bool = False

    def __post_init__(self) -> None:
        if self.distinctive_hits < 0 or self.unique_hits < 0:
            raise ValueError("aggregation admission hit counts cannot be negative")


@dataclass(frozen=True)
class AggregationAdmissionCandidate:
    candidate_id: str
    signals: AggregationAdmissionSignals

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise ValueError("aggregation admission candidate_id is required")


@dataclass(frozen=True)
class AggregationAdmissionDecision:
    candidate_id: str
    admitted: bool
    relaxed: bool
    reason: AggregationAdmissionReason


@dataclass(frozen=True)
class AggregationAdmissionSelection:
    selected_ids: tuple[str, ...]
    reserved_ids: tuple[str, ...]
    decisions: tuple[AggregationAdmissionDecision, ...]


class AggregationAdmissionPolicy:
    """Admit grounded aggregation evidence and reserve supported source slots."""

    def decide(self, candidate: AggregationAdmissionCandidate) -> AggregationAdmissionDecision:
        signals = candidate.signals
        reason = self._rejection_reason(signals)
        if reason is not None:
            return AggregationAdmissionDecision(candidate.candidate_id, False, False, reason)
        if signals.relevance_sufficient and signals.distinctive_hits > 0:
            return AggregationAdmissionDecision(
                candidate.candidate_id,
                True,
                False,
                AggregationAdmissionReason.SUFFICIENT_RELEVANCE,
            )
        if signals.distinctive_hits <= 0:
            reason = (
                AggregationAdmissionReason.NUMERIC_ONLY
                if signals.numeric_corroboration
                else AggregationAdmissionReason.ZERO_OVERLAP
            )
            return AggregationAdmissionDecision(candidate.candidate_id, False, False, reason)
        if signals.anchor_conflict:
            reason = AggregationAdmissionReason.ANCHOR_CONFLICT
            return AggregationAdmissionDecision(candidate.candidate_id, False, False, reason)
        if signals.temporal_conflict:
            reason = AggregationAdmissionReason.TEMPORAL_CONFLICT
            return AggregationAdmissionDecision(candidate.candidate_id, False, False, reason)
        if signals.unique_hits > 0:
            return AggregationAdmissionDecision(
                candidate.candidate_id,
                True,
                True,
                AggregationAdmissionReason.RELAXED_DISTINCTIVE_SUPPORT,
            )
        return AggregationAdmissionDecision(
            candidate.candidate_id,
            False,
            False,
            AggregationAdmissionReason.INSUFFICIENT_SUPPORT,
        )

    def select(
        self,
        candidates: tuple[AggregationAdmissionCandidate, ...],
        *,
        limit: int,
        source_family_cap: int,
        reservation_limit: int | None = None,
        reserve_supported_slots: bool = True,
        selected_source_families: tuple[str, ...] = (),
    ) -> AggregationAdmissionSelection:
        decisions = tuple(self.decide(candidate) for candidate in candidates)
        if limit <= 0 or source_family_cap <= 0:
            return AggregationAdmissionSelection((), (), decisions)
        admitted = tuple(
            candidate
            for candidate, decision in zip(candidates, decisions, strict=True)
            if decision.admitted
        )
        selected: list[str] = []
        reserved: list[str] = []
        selected_ids: set[str] = set()
        family_counts: dict[str, int] = {}
        for family in selected_source_families:
            family_counts[family] = family_counts.get(family, 0) + 1
        reserved_slots: set[tuple[str, str]] = set()

        def add(candidate: AggregationAdmissionCandidate, *, reserve: bool) -> bool:
            candidate_id = candidate.candidate_id
            family = candidate.signals.source_family
            if candidate_id in selected_ids or family_counts.get(family, 0) >= source_family_cap:
                return False
            selected.append(candidate_id)
            selected_ids.add(candidate_id)
            family_counts[family] = family_counts.get(family, 0) + 1
            if reserve:
                reserved.append(candidate_id)
            return True

        bounded_reservation_limit = max(limit, reservation_limit or limit)
        if reserve_supported_slots:
            reserved_plan_slots: set[str] = set()
            for candidate in admitted:
                plan_slot = candidate.signals.query_plan_slot
                slot = (plan_slot, candidate.signals.source_family)
                if plan_slot in reserved_plan_slots or slot in reserved_slots:
                    continue
                if add(candidate, reserve=True):
                    reserved_plan_slots.add(plan_slot)
                    reserved_slots.add(slot)
                if len(selected) >= bounded_reservation_limit:
                    break
            for candidate in admitted:
                if len(selected) >= bounded_reservation_limit:
                    break
                slot = (candidate.signals.query_plan_slot, candidate.signals.source_family)
                if slot in reserved_slots:
                    continue
                reserved_slots.add(slot)
                add(candidate, reserve=True)
        if len(selected) < limit:
            for candidate in admitted:
                add(candidate, reserve=False)
                if len(selected) >= limit:
                    break
        return AggregationAdmissionSelection(tuple(selected), tuple(reserved), decisions)

    @staticmethod
    def _rejection_reason(
        signals: AggregationAdmissionSignals,
    ) -> AggregationAdmissionReason | None:
        if signals.intent is None:
            return AggregationAdmissionReason.MISSING_INTENT
        if not signals.query_plan_slot.strip():
            return AggregationAdmissionReason.MISSING_REQUESTED_SLOT
        if not signals.source_family.strip():
            return AggregationAdmissionReason.MISSING_SOURCE_FAMILY
        return None
