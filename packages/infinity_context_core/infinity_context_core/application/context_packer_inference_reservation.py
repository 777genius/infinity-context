"""Legacy packer adapter for the feature-owned inference reservation policy."""

from __future__ import annotations

from dataclasses import dataclass

from infinity_context_core.application.context_evidence_priority import (
    has_unresolved_rerank_rejection,
)
from infinity_context_core.application.context_packer_answer_support import (
    _answer_support_diversity_family,
    _answer_support_query_reason,
)
from infinity_context_core.application.context_packer_diagnostics import diagnostic_value
from infinity_context_core.application.context_packer_source_policy import selection_key
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.features.context_building.public import (
    InferenceEvidenceCandidate,
    InferenceEvidenceReservationRequest,
    InferenceReservationPressure,
    reserve_inference_evidence,
)

_CONFLICT_ID_KEYS = ("conflicting_fact_id", "conflict_fact_id")


@dataclass(frozen=True, slots=True)
class InferenceReservationItems:
    reserved: ContextItem
    displaced: ContextItem


def inference_reservation_for_char_pressure(
    *,
    query: str,
    rejected: ContextItem,
    selected: tuple[ContextItem, ...],
    protected_keys: frozenset[tuple[str, str]],
) -> InferenceReservationItems | None:
    """Adapt canonical items only after the caller proves character pressure."""

    candidates = tuple(_candidate(item, rank=rank) for rank, item in enumerate(selected))
    rejected_candidate = _candidate(rejected, rank=len(selected))
    item_by_id = {
        candidate.candidate_id: item for candidate, item in zip(candidates, selected, strict=True)
    }
    item_by_id[rejected_candidate.candidate_id] = rejected
    decision = reserve_inference_evidence(
        InferenceEvidenceReservationRequest(
            query=query,
            pressure=InferenceReservationPressure.CHARACTER_CAP,
            rejected=rejected_candidate,
            selected=candidates,
            protected_candidate_ids=frozenset(
                _candidate_id_from_key(key) for key in protected_keys
            ),
        )
    )
    if decision is None:
        return None
    reservation = InferenceReservationItems(
        reserved=item_by_id[decision.candidate_id],
        displaced=item_by_id[decision.displaced_candidate_id],
    )
    if _answer_support_diversity_family(reservation.reserved) != _answer_support_diversity_family(
        reservation.displaced
    ):
        return None
    return reservation


def _candidate(item: ContextItem, *, rank: int) -> InferenceEvidenceCandidate:
    conflict_ids = frozenset(
        str(value).strip()
        for key in _CONFLICT_ID_KEYS
        if (value := diagnostic_value(item, key)) is not None and str(value).strip()
    )
    if has_unresolved_rerank_rejection(item):
        conflict_ids = conflict_ids | {"unresolved_rerank_rejection"}
    return InferenceEvidenceCandidate(
        candidate_id=_candidate_id_from_key(selection_key(item)),
        text=item.text,
        query_reason=_answer_support_query_reason(item),
        rank=rank,
        score=item.score,
        source_backed=bool(item.source_refs),
        instruction=item.is_instruction,
        conflict_ids=conflict_ids,
        review_only=diagnostic_value(item, "review_only") is True,
    )


def _candidate_id_from_key(key: tuple[str, str]) -> str:
    return f"{key[0]}:{key[1]}"
