"""Pure bounded marginal-coverage selection independent of candidate providers."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.features.context_building.domain.evidence_obligations import (
    EvidenceClaim,
    EvidenceObligation,
    EvidenceObligationConfidence,
    EvidenceObligationId,
)


@dataclass(frozen=True, slots=True)
class CoverageReservationCandidate:
    """Provider-neutral candidate costs, capacity key, and coverage claims."""

    candidate_id: str
    source_key: str
    rank: int
    token_cost: int
    character_cost: int
    claims: tuple[EvidenceClaim, ...]
    eligible: bool = True

    def __post_init__(self) -> None:
        if not self.candidate_id:
            raise ValueError("Coverage candidate requires an id")
        if not self.source_key:
            raise ValueError("Coverage candidate requires a source key")
        if self.rank < 0:
            raise ValueError("Coverage candidate rank cannot be negative")
        if self.token_cost < 0 or self.character_cost < 0:
            raise ValueError("Coverage candidate costs cannot be negative")


@dataclass(frozen=True, slots=True)
class CoverageReservationBudget:
    """Hard capacity available to reservation before ordinary selection."""

    max_items: int
    token_budget: int
    character_budget: int
    max_items_per_source: int

    def __post_init__(self) -> None:
        if (
            min(
                self.max_items,
                self.token_budget,
                self.character_budget,
                self.max_items_per_source,
            )
            < 0
        ):
            raise ValueError("Coverage reservation budget cannot be negative")


@dataclass(frozen=True, slots=True)
class CoverageReservation:
    candidate_id: str
    obligation_id: EvidenceObligationId


@dataclass(frozen=True, slots=True)
class CoverageReservationResult:
    reservations: tuple[CoverageReservation, ...]
    eligible_obligation_ids: tuple[EvidenceObligationId, ...]
    claims_considered: int


class CoverageReservationSelector:
    """Reserve at most one marginal candidate per high-confidence obligation."""

    def select(
        self,
        *,
        obligations: tuple[EvidenceObligation, ...],
        candidates: tuple[CoverageReservationCandidate, ...],
        budget: CoverageReservationBudget,
    ) -> CoverageReservationResult:
        eligible_obligations = tuple(
            obligation
            for obligation in _dedupe_obligations(obligations)
            if obligation.confidence is EvidenceObligationConfidence.HIGH
        )
        candidate_by_id = _dedupe_candidates(candidates)
        claims_considered = sum(
            len(candidate.claims) for candidate in candidate_by_id if candidate.eligible
        )
        if budget.max_items == 0:
            return CoverageReservationResult(
                reservations=(),
                eligible_obligation_ids=tuple(
                    obligation.obligation_id for obligation in eligible_obligations
                ),
                claims_considered=claims_considered,
            )

        reservations: list[CoverageReservation] = []
        selected_ids: set[str] = set()
        source_counts: dict[str, int] = {}
        tokens_used = 0
        characters_used = 0
        for obligation in eligible_obligations:
            if len(reservations) >= budget.max_items:
                break
            ranked = _ranked_claimants(
                obligation.obligation_id,
                candidate_by_id,
                selected_ids=selected_ids,
                source_counts=source_counts,
            )
            for candidate in ranked:
                if source_counts.get(candidate.source_key, 0) >= budget.max_items_per_source:
                    continue
                if tokens_used + candidate.token_cost > budget.token_budget:
                    continue
                if characters_used + candidate.character_cost > budget.character_budget:
                    continue
                reservations.append(
                    CoverageReservation(
                        candidate_id=candidate.candidate_id,
                        obligation_id=obligation.obligation_id,
                    )
                )
                selected_ids.add(candidate.candidate_id)
                source_counts[candidate.source_key] = source_counts.get(candidate.source_key, 0) + 1
                tokens_used += candidate.token_cost
                characters_used += candidate.character_cost
                break

        return CoverageReservationResult(
            reservations=tuple(reservations),
            eligible_obligation_ids=tuple(
                obligation.obligation_id for obligation in eligible_obligations
            ),
            claims_considered=claims_considered,
        )


def _dedupe_obligations(
    obligations: tuple[EvidenceObligation, ...],
) -> tuple[EvidenceObligation, ...]:
    seen: set[EvidenceObligationId] = set()
    result: list[EvidenceObligation] = []
    for obligation in obligations:
        if obligation.obligation_id in seen:
            continue
        seen.add(obligation.obligation_id)
        result.append(obligation)
    return tuple(result)


def _dedupe_candidates(
    candidates: tuple[CoverageReservationCandidate, ...],
) -> tuple[CoverageReservationCandidate, ...]:
    by_id: dict[str, CoverageReservationCandidate] = {}
    for candidate in candidates:
        current = by_id.get(candidate.candidate_id)
        if current is None or _candidate_identity_key(candidate) < _candidate_identity_key(current):
            by_id[candidate.candidate_id] = candidate
    return tuple(sorted(by_id.values(), key=_candidate_identity_key))


def _ranked_claimants(
    obligation_id: EvidenceObligationId,
    candidates: tuple[CoverageReservationCandidate, ...],
    *,
    selected_ids: set[str],
    source_counts: dict[str, int],
) -> tuple[CoverageReservationCandidate, ...]:
    ranked: list[tuple[tuple[object, ...], CoverageReservationCandidate]] = []
    for candidate in candidates:
        if not candidate.eligible or candidate.candidate_id in selected_ids:
            continue
        strength = max(
            (claim.strength for claim in candidate.claims if claim.obligation_id == obligation_id),
            default=-1.0,
        )
        if strength < 0.0:
            continue
        ranked.append(
            (
                (
                    source_counts.get(candidate.source_key, 0),
                    -strength,
                    candidate.character_cost,
                    candidate.token_cost,
                    candidate.rank,
                    candidate.candidate_id,
                ),
                candidate,
            )
        )
    return tuple(candidate for _, candidate in sorted(ranked, key=lambda item: item[0]))


def _candidate_identity_key(
    candidate: CoverageReservationCandidate,
) -> tuple[int, str, str]:
    return (candidate.rank, candidate.candidate_id, candidate.source_key)


__all__ = (
    "CoverageReservation",
    "CoverageReservationBudget",
    "CoverageReservationCandidate",
    "CoverageReservationResult",
    "CoverageReservationSelector",
)
