"""Question-derived source-distinct reservations for paired ranked evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from math import isfinite

from infinity_context_core.application.context_evidence_reservation_safety import (
    evidence_reservation_candidate_is_eligible,
)
from infinity_context_core.application.context_lexical import query_terms
from infinity_context_core.application.context_packer_diagnostics import (
    diagnostic_score_signals,
)
from infinity_context_core.application.context_paired_evidence_requirements import (
    PairedEvidenceKind,
    PairedEvidenceRequirement,
    paired_evidence_requirement,
)
from infinity_context_core.application.context_paired_evidence_roles import (
    paired_evidence_role_memberships,
)
from infinity_context_core.application.context_source_family import (
    SourceFamilyIdentity,
    canonical_source_family_identity,
)
from infinity_context_core.application.context_state_evidence import state_evidence_markers
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
_STATE_HISTORY_RE = re.compile(
    r"\b(?:before|formerly|previously|prior|old|used\s+to|no\s+longer|"
    r"superseded|deprecated)\b",
    re.IGNORECASE,
)
_MEASUREMENT_RELATION_RE = re.compile(
    r"\b(?:per|for\s+(?:each|every)|ratio)\b",
    re.IGNORECASE,
)
_MEASUREMENT_VALUE_RE = re.compile(
    r"(?<![\w.])(?:\d+(?:[.,]\d+)?|zero|one|two|three|four|five|six|"
    r"seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
    r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
    r"sixty|seventy|eighty|ninety|hundred)(?![\w.])",
    re.IGNORECASE,
)
_STATE_QUERY_STOP_TERMS = frozenset(
    {
        "change",
        "current",
        "did",
        "for",
        "from",
        "less",
        "more",
        "per",
        "previous",
        "ratio",
        "switch",
        "switched",
        "the",
        "to",
    }
)
_PER_UNIT_RE = re.compile(r"\bper\s+(?P<unit>[^\s,;?.!]{3,})", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class PairedEvidenceReservation:
    """Stable reordered candidates plus bounded reservation observability."""

    items: tuple[ContextItem, ...]
    reservation_count: int = 0
    claims_considered: int = 0
    requirement_kind: PairedEvidenceKind | None = None


TemporalIntervalEvidenceReservation = PairedEvidenceReservation


def reserve_paired_evidence_head(
    items: tuple[ContextItem, ...],
    *,
    query: str,
    max_items: int,
    max_tokens: int,
    max_chars: int,
) -> PairedEvidenceReservation:
    """Move at most two source-distinct question-required items to the head."""

    requirement = paired_evidence_requirement(query)
    if requirement is None or min(max_items, max_tokens, max_chars) <= 0:
        return PairedEvidenceReservation(items=items)

    obligations = tuple(
        EvidenceObligation(
            obligation_id=EvidenceObligationId(f"o-pe{index}"),
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
            requirement=requirement,
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
        int(reservation.candidate_id.removeprefix("paired-evidence-"))
        for reservation in selection.reservations
    )
    if not reserved_indexes:
        return PairedEvidenceReservation(
            items=items,
            claims_considered=selection.claims_considered,
            requirement_kind=requirement.kind,
        )
    reserved_index_set = set(reserved_indexes)
    return PairedEvidenceReservation(
        items=(
            *(items[index] for index in reserved_indexes),
            *(item for index, item in enumerate(items) if index not in reserved_index_set),
        ),
        reservation_count=len(reserved_indexes),
        claims_considered=selection.claims_considered,
        requirement_kind=requirement.kind,
    )


def reserve_temporal_interval_evidence_head(
    items: tuple[ContextItem, ...],
    *,
    query: str,
    max_items: int,
    max_tokens: int,
    max_chars: int,
) -> TemporalIntervalEvidenceReservation:
    """Compatibility entry point for the prior interval-only reservation API."""

    return reserve_paired_evidence_head(
        items,
        query=query,
        max_items=max_items,
        max_tokens=max_tokens,
        max_chars=max_chars,
    )


def _reservation_candidate(
    item: ContextItem,
    *,
    rank: int,
    source_family: SourceFamilyIdentity | None,
    source_family_ambiguous: bool,
    obligations: tuple[EvidenceObligation, ...],
    requirement: PairedEvidenceRequirement,
) -> CoverageReservationCandidate:
    source_key = source_family.reservation_key if source_family is not None else ""
    eligible = bool(
        source_key
        and not source_family_ambiguous
        and evidence_reservation_candidate_is_eligible(item)
    )
    claims = (
        _requirement_claims(item, obligations=obligations, requirement=requirement)
        if eligible
        else ()
    )
    return CoverageReservationCandidate(
        candidate_id=f"paired-evidence-{rank}",
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


def _requirement_claims(
    item: ContextItem,
    *,
    obligations: tuple[EvidenceObligation, ...],
    requirement: PairedEvidenceRequirement,
) -> tuple[EvidenceClaim, ...]:
    claims: list[EvidenceClaim] = []
    for obligation, role_id, retrieval_reason, role_query in zip(
        obligations,
        requirement.role_ids,
        requirement.retrieval_reasons,
        requirement.role_queries,
        strict=True,
    ):
        strength = (
            _state_claim_strength(item, role_id=role_id, query=role_query)
            if requirement.kind is PairedEvidenceKind.STATE_TRANSITION
            else _typed_endpoint_claim_strength(
                item,
                endpoint_slot=retrieval_reason,
                endpoint_query=role_query,
            )
        )
        if strength is not None:
            claims.append(EvidenceClaim(obligation.obligation_id, strength=strength))
    return tuple(claims)


def _typed_endpoint_claim_strength(
    item: ContextItem,
    *,
    endpoint_slot: str | None,
    endpoint_query: str,
) -> float | None:
    """Reuse producer relevance only; lexical overlap is never a new claim."""

    signals = diagnostic_score_signals(item)
    if (
        not endpoint_slot
        or not endpoint_query.strip()
        or endpoint_slot not in paired_evidence_role_memberships(signals)
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


def _state_claim_strength(
    item: ContextItem,
    *,
    role_id: str,
    query: str,
) -> float | None:
    """Require direct measurement evidence; time only resolves otherwise-safe ties."""

    if not _has_direct_measurement_relation(item.text, query=query):
        return None
    markers = state_evidence_markers(item)
    if role_id == "previous_state":
        historical_label = bool(_STATE_HISTORY_RE.search(item.text))
        if not (markers.text_stale or markers.text_transition or historical_label):
            return None
        return 0.95 if markers.text_stale or historical_label else 0.85
    if role_id == "current_state":
        if markers.metadata_stale or (markers.text_stale and not markers.text_transition):
            return None
        return 0.95 if markers.has_active_state else 0.85 if markers.text_transition else 0.7
    return None


def _has_direct_measurement_relation(text: str, *, query: str) -> bool:
    units = _measurement_unit_terms(query)
    if (
        not units
        or not _MEASUREMENT_RELATION_RE.search(text)
        or not _MEASUREMENT_VALUE_RE.search(text)
    ):
        return False
    item_terms = {term.raw for term in query_terms(text, min_chars=3, max_terms=96)}
    if not units.intersection(item_terms):
        return False
    subject_terms = {
        term.raw
        for term in query_terms(query, min_chars=3, max_terms=48)
        if term.raw not in _STATE_QUERY_STOP_TERMS and term.raw not in units
    }
    return bool(subject_terms.intersection(item_terms))


def _measurement_unit_terms(query: str) -> frozenset[str]:
    match = _PER_UNIT_RE.search(query)
    if match is None:
        return frozenset()
    return frozenset(
        term.raw for term in query_terms(match.group("unit"), min_chars=3, max_terms=2)
    )


def _non_negative_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _unit_interval(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    parsed = float(value)
    return parsed if isfinite(parsed) and 0.0 <= parsed <= 1.0 else None


__all__ = (
    "PairedEvidenceReservation",
    "TemporalIntervalEvidenceReservation",
    "reserve_paired_evidence_head",
    "reserve_temporal_interval_evidence_head",
)
