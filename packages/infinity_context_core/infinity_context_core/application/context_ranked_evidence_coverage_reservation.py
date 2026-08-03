"""Question-derived temporal-interval reservations for ranked evidence."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from infinity_context_core.application.context_evidence_reservation_safety import (
    evidence_reservation_candidate_is_eligible,
)
from infinity_context_core.application.context_packer_diagnostics import (
    diagnostic_score_signals,
)
from infinity_context_core.application.context_source_family import (
    SourceFamilyIdentity,
    canonical_source_family_identity,
)
from infinity_context_core.application.context_temporal_interval_requirements import (
    temporal_interval_requirements,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.application.normalize import estimate_tokens
from infinity_context_core.features.context_building.public import (
    CoverageReservationBudget,
    CoverageReservationCandidate,
    CoverageReservationSelector,
    EvidenceClaim,
    EvidenceObligation,
    EvidenceObligationConfidence,
    EvidenceObligationId,
)

_MAX_RESERVATIONS = 2
_MIN_TYPED_UNIQUE_TERM_HITS = 2
_MIN_TYPED_DISTINCTIVE_TERM_HITS = 1
_MIN_TYPED_HIT_RATIO = 0.25


@dataclass(frozen=True, slots=True)
class TemporalIntervalEvidenceReservation:
    """Stable reordered candidates plus bounded reservation observability."""

    items: tuple[ContextItem, ...]
    reservation_count: int = 0
    claims_considered: int = 0


def reserve_temporal_interval_evidence_head(
    items: tuple[ContextItem, ...],
    *,
    query: str,
    max_items: int,
    max_tokens: int,
    max_chars: int,
) -> TemporalIntervalEvidenceReservation:
    """Move at most two source-distinct explicit interval boundaries to the head."""

    requirements = temporal_interval_requirements(query)
    endpoints = tuple(requirements.endpoints[:_MAX_RESERVATIONS])
    if len(endpoints) != _MAX_RESERVATIONS or min(max_items, max_tokens, max_chars) <= 0:
        return TemporalIntervalEvidenceReservation(items=items)

    obligations = tuple(
        EvidenceObligation(
            obligation_id=EvidenceObligationId(f"o-ti{index}"),
            confidence=EvidenceObligationConfidence.HIGH,
        )
        for index in range(1, _MAX_RESERVATIONS + 1)
    )
    source_families = tuple(canonical_source_family_identity(item) for item in items)
    ambiguous_source_bases = _mixed_scope_source_bases(source_families)
    candidates = tuple(
        _reservation_candidate(
            item,
            rank=index,
            source_family=source_families[index],
            source_family_ambiguous=(
                source_families[index] is not None
                and source_families[index].base_key in ambiguous_source_bases
            ),
            obligations=obligations,
            endpoint_slots=tuple(endpoint.slot_id for endpoint in endpoints),
            endpoint_queries=tuple(endpoint.query for endpoint in endpoints),
        )
        for index, item in enumerate(items)
    )
    selection = CoverageReservationSelector().select(
        obligations=obligations,
        candidates=candidates,
        budget=CoverageReservationBudget(
            max_items=min(_MAX_RESERVATIONS, max_items),
            token_budget=max_tokens,
            character_budget=max_chars,
            max_items_per_source=1,
        ),
    )
    reserved_indexes = tuple(
        int(reservation.candidate_id.removeprefix("temporal-interval-"))
        for reservation in selection.reservations
    )
    if not reserved_indexes:
        return TemporalIntervalEvidenceReservation(
            items=items,
            claims_considered=selection.claims_considered,
        )
    reserved_index_set = set(reserved_indexes)
    return TemporalIntervalEvidenceReservation(
        items=(
            *(items[index] for index in reserved_indexes),
            *(item for index, item in enumerate(items) if index not in reserved_index_set),
        ),
        reservation_count=len(reserved_indexes),
        claims_considered=selection.claims_considered,
    )


def _reservation_candidate(
    item: ContextItem,
    *,
    rank: int,
    source_family: SourceFamilyIdentity | None,
    source_family_ambiguous: bool,
    obligations: tuple[EvidenceObligation, ...],
    endpoint_slots: tuple[str, ...],
    endpoint_queries: tuple[str, ...],
) -> CoverageReservationCandidate:
    source_key = source_family.reservation_key if source_family is not None else ""
    eligible = bool(
        source_key
        and not source_family_ambiguous
        and evidence_reservation_candidate_is_eligible(item)
    )
    claims = (
        _endpoint_claims(
            item=item,
            obligations=obligations,
            endpoint_slots=endpoint_slots,
            endpoint_queries=endpoint_queries,
        )
        if eligible
        else ()
    )
    return CoverageReservationCandidate(
        candidate_id=f"temporal-interval-{rank}",
        source_key=source_key or f"ineligible-{rank}",
        rank=rank,
        token_cost=estimate_tokens(f"{item.text}\n\n"),
        character_cost=len(item.text) + 2,
        claims=claims,
        eligible=eligible,
    )


def _mixed_scope_source_bases(
    source_families: tuple[SourceFamilyIdentity | None, ...],
) -> frozenset[str]:
    known_scopes_by_base: dict[str, set[str | None]] = {}
    for source_family in source_families:
        if source_family is None:
            continue
        known_scopes_by_base.setdefault(source_family.base_key, set()).add(
            source_family.memory_scope_id
        )
    return frozenset(
        base_key
        for base_key, scopes in known_scopes_by_base.items()
        if None in scopes and any(scope is not None for scope in scopes)
    )


def _endpoint_claims(
    *,
    item: ContextItem,
    obligations: tuple[EvidenceObligation, ...],
    endpoint_slots: tuple[str, ...],
    endpoint_queries: tuple[str, ...],
) -> tuple[EvidenceClaim, ...]:
    claims: list[EvidenceClaim] = []
    for obligation, endpoint_slot, endpoint_query in zip(
        obligations,
        endpoint_slots,
        endpoint_queries,
        strict=True,
    ):
        strength = _typed_endpoint_claim_strength(
            item=item,
            endpoint_slot=endpoint_slot,
            endpoint_query=endpoint_query,
        )
        if strength is not None:
            claims.append(EvidenceClaim(obligation.obligation_id, strength=strength))
    return tuple(claims)


def _typed_endpoint_claim_strength(
    *,
    item: ContextItem,
    endpoint_slot: str,
    endpoint_query: str,
) -> float | None:
    """Reuse producer relevance only; lexical overlap is never a new claim."""

    signals = diagnostic_score_signals(item)
    reason = signals.get("query_expansion_reason")
    if (
        not endpoint_query.strip()
        or not isinstance(reason, str)
        or reason != endpoint_slot
    ):
        return None
    unique_hits = _non_negative_int(signals.get("unique_term_hits"))
    distinctive_hits = _non_negative_int(signals.get("distinctive_term_hits"))
    phrase_hits = _non_negative_int(signals.get("phrase_bigram_hits"))
    hit_ratio = _unit_interval(signals.get("hit_ratio"))
    if (
        unique_hits is None
        or distinctive_hits is None
        or phrase_hits is None
        or hit_ratio is None
        or unique_hits < _MIN_TYPED_UNIQUE_TERM_HITS
        or distinctive_hits < _MIN_TYPED_DISTINCTIVE_TERM_HITS
        or hit_ratio < _MIN_TYPED_HIT_RATIO
        or (phrase_hits <= 0 and distinctive_hits < 2)
    ):
        return None
    return max(hit_ratio, min(1.0, distinctive_hits / max(unique_hits, 1)))


def _non_negative_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _unit_interval(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    parsed = float(value)
    return parsed if isfinite(parsed) and 0.0 <= parsed <= 1.0 else None


__all__ = (
    "TemporalIntervalEvidenceReservation",
    "reserve_temporal_interval_evidence_head",
)
