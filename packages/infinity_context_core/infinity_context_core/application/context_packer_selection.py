"""Budgeted selection state and shared packing checks."""

from __future__ import annotations

import re
from dataclasses import dataclass

from infinity_context_core.application.context_diagnostics import context_rank_key
from infinity_context_core.application.context_packer_answer_support import (
    _answer_object_rank,
    _answer_support_diversity_family,
    _answer_support_family_item_key,
    _answer_support_query_reason,
    _precise_answer_content_rank,
    _precise_turn_answer_support_rank,
)
from infinity_context_core.application.context_packer_answer_support_patterns import (
    _PRECISE_TURN_ANSWER_SUPPORT_REASONS,
)
from infinity_context_core.application.context_packer_diagnostics import (
    diagnostic_score_signals,
    diagnostic_value,
)
from infinity_context_core.application.context_packer_exact_turn_utils import (
    _canonical_dialogue_marker,
)
from infinity_context_core.application.context_packer_rendering import (
    rendered_context_char_count,
)
from infinity_context_core.application.context_packer_rendering import (
    source_group_key as _source_group_key,
)
from infinity_context_core.application.context_packer_rendering import (
    source_key as _source_key,
)
from infinity_context_core.application.context_packer_source_policy import (
    MAX_ITEMS_PER_SOURCE as _MAX_ITEMS_PER_SOURCE,
)
from infinity_context_core.application.context_packer_source_policy import (
    selection_key as _selection_key,
)
from infinity_context_core.application.context_packer_source_policy import (
    source_cap_applies as _source_cap_applies,
)
from infinity_context_core.application.context_packer_source_policy import (
    source_group_cap as _source_group_cap,
)
from infinity_context_core.application.dto import ContextBundle, ContextItem
from infinity_context_core.application.normalize import estimate_tokens
from infinity_context_core.features.context_building.application.coverage_reservation_selector import (  # noqa: E501
    CoverageReservationBudget,
    CoverageReservationCandidate,
    CoverageReservationSelector,
)
from infinity_context_core.features.context_building.domain.evidence_obligations import (
    EvidenceClaim,
    EvidenceObligation,
    EvidenceObligationConfidence,
    EvidenceObligationId,
)

_DIALOGUE_MARKER_RE = re.compile(r"\bD\d+[:-]\d+\b")
_MAX_COVERAGE_RESERVATIONS = 4
_MIN_COVERAGE_TERM_HITS = 4
_MIN_COVERAGE_HIT_RATIO = 0.60
_MAX_COVERAGE_RERANK_PENALTY = 0.09


@dataclass(frozen=True)
class PackResult:
    bundle: ContextBundle
    dropped_count: int


@dataclass
class _SelectionState:
    selected: list[ContextItem]
    selected_keys: set[tuple[str, str]]
    selected_answer_support_families: set[str]
    selected_chunks_by_source: dict[str, int]
    selected_source_capped_items_by_source: dict[str, int]
    selected_art_style_items_by_source_group: dict[str, int]
    used_tokens: int = 0


def _try_select_item(
    state: _SelectionState,
    *,
    item: ContextItem,
    budget: int,
    char_budget: int,
    mark_answer_support_family: bool = True,
    ignore_source_cap: bool = False,
) -> bool:
    if _selection_key(item) in state.selected_keys:
        return False
    answer_support_family = _answer_support_diversity_family(item)
    if (
        answer_support_family
        and answer_support_family in state.selected_answer_support_families
        and not _adds_answer_support_source_coverage(
            state.selected,
            item=item,
            answer_support_family=answer_support_family,
        )
    ):
        return False
    if _source_cap_applies(item) and not ignore_source_cap:
        source_key = _source_key(item)
        if state.selected_source_capped_items_by_source.get(source_key, 0) >= (
            _MAX_ITEMS_PER_SOURCE
        ):
            return False
        source_group_cap = _source_group_cap(item)
        if source_group_cap is not None:
            source_group_key = _source_group_key(item)
            if (
                state.selected_art_style_items_by_source_group.get(source_group_key, 0)
                >= source_group_cap
            ):
                return False
    item_tokens = estimate_tokens(item.text) + 16
    if state.used_tokens + item_tokens > budget:
        return False
    if _rendered_char_count((*state.selected, item)) > char_budget:
        return False
    _select_item(
        state,
        item=item,
        item_tokens=item_tokens,
        mark_answer_support_family=mark_answer_support_family,
    )
    return True


def _adds_answer_support_source_coverage(
    selected: list[ContextItem],
    *,
    item: ContextItem,
    answer_support_family: str,
) -> bool:
    if not item.source_refs:
        return False
    candidate_refs = _source_coverage_keys(item)
    if not candidate_refs:
        return False
    covered_refs: set[str] = set()
    for selected_item in selected:
        if _answer_support_diversity_family(selected_item) != answer_support_family:
            continue
        covered_refs.update(_source_coverage_keys(selected_item))
    return bool(candidate_refs - covered_refs)


def _source_coverage_keys(item: ContextItem) -> set[str]:
    keys: set[str] = set()
    for ref in item.source_refs:
        if ref.source_id:
            keys.add(f"{ref.source_type}:{ref.source_id}")
            keys.update(
                f"dialogue:{_canonical_dialogue_marker(marker)}"
                for marker in _DIALOGUE_MARKER_RE.findall(ref.source_id)
            )
    keys.update(
        f"dialogue:{_canonical_dialogue_marker(marker)}"
        for marker in _DIALOGUE_MARKER_RE.findall(item.text)
    )
    return keys


def _select_item(
    state: _SelectionState,
    *,
    item: ContextItem,
    item_tokens: int,
    mark_answer_support_family: bool = True,
) -> None:
    state.selected.append(item)
    state.selected_keys.add(_selection_key(item))
    answer_support_family = _answer_support_diversity_family(item)
    if mark_answer_support_family and answer_support_family:
        state.selected_answer_support_families.add(answer_support_family)
    if item.item_type == "chunk":
        source_key = _source_key(item)
        state.selected_chunks_by_source[source_key] = (
            state.selected_chunks_by_source.get(source_key, 0) + 1
        )
    if _source_cap_applies(item):
        source_key = _source_key(item)
        state.selected_source_capped_items_by_source[source_key] = (
            state.selected_source_capped_items_by_source.get(source_key, 0) + 1
        )
        if _source_group_cap(item) is not None:
            source_group_key = _source_group_key(item)
            state.selected_art_style_items_by_source_group[source_group_key] = (
                state.selected_art_style_items_by_source_group.get(source_group_key, 0) + 1
            )
    state.used_tokens += item_tokens


def _item_type_counts(items: tuple[ContextItem, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.item_type] = counts.get(item.item_type, 0) + 1
    return counts


def _context_render_rank_key(item: ContextItem) -> tuple[object, ...]:
    query_reason = _answer_support_query_reason(item)
    if (
        query_reason in _PRECISE_TURN_ANSWER_SUPPORT_REASONS
        and _precise_turn_answer_support_rank(item, query_reason=query_reason) == 0
    ):
        return (
            0,
            _precise_answer_content_rank(item, query_reason=query_reason),
            _answer_object_rank(item, query_reason=query_reason),
            _answer_support_family_item_key(item),
            context_rank_key(item),
        )
    return (1, context_rank_key(item))


def _rendered_char_count(items: tuple[ContextItem, ...]) -> int:
    return rendered_context_char_count(items, rank_key=_context_render_rank_key)


@dataclass(frozen=True, slots=True)
class CoverageReservationDiagnostics:
    obligations_considered: int
    eligible_obligation_ids: tuple[str, ...]
    claims_considered: int
    reservations_selected: int
    selected_obligation_ids: tuple[str, ...]


def reserve_coverage_items(
    state: _SelectionState,
    *,
    items: list[ContextItem],
    budget: int,
    char_budget: int,
) -> CoverageReservationDiagnostics:
    """Adapt visible legacy items into opaque, hard-bounded coverage preferences."""

    obligations, candidates, item_by_candidate_id = _coverage_inputs(items)
    header_characters = _rendered_char_count(())
    result = CoverageReservationSelector().select(
        obligations=obligations,
        candidates=candidates,
        budget=CoverageReservationBudget(
            max_items=_MAX_COVERAGE_RESERVATIONS,
            token_budget=max(0, budget - state.used_tokens),
            character_budget=max(0, char_budget - header_characters),
            max_items_per_source=_MAX_ITEMS_PER_SOURCE,
        ),
    )
    selected_obligation_ids: list[str] = []
    for reservation in result.reservations:
        item = item_by_candidate_id[reservation.candidate_id]
        if _try_select_item(
            state,
            item=item,
            budget=budget,
            char_budget=char_budget,
            mark_answer_support_family=False,
        ):
            selected_obligation_ids.append(str(reservation.obligation_id))
    return CoverageReservationDiagnostics(
        obligations_considered=len(obligations),
        eligible_obligation_ids=tuple(str(value) for value in result.eligible_obligation_ids),
        claims_considered=result.claims_considered,
        reservations_selected=len(selected_obligation_ids),
        selected_obligation_ids=tuple(selected_obligation_ids),
    )


def _coverage_inputs(
    items: list[ContextItem],
) -> tuple[
    tuple[EvidenceObligation, ...],
    tuple[CoverageReservationCandidate, ...],
    dict[str, ContextItem],
]:
    reason_ids: dict[str, EvidenceObligationId] = {}
    raw_candidates: list[tuple[int, ContextItem, str, float]] = []
    for rank, item in enumerate(items):
        if not _coverage_candidate_is_eligible(item):
            continue
        reason = _answer_support_query_reason(item)
        strength = _coverage_claim_strength(item)
        if not reason or strength is None:
            continue
        obligation_id = reason_ids.setdefault(
            reason,
            EvidenceObligationId(f"o-{len(reason_ids):03x}"),
        )
        raw_candidates.append((rank, item, str(obligation_id), strength))

    obligations = tuple(
        EvidenceObligation(
            obligation_id=obligation_id,
            confidence=EvidenceObligationConfidence.HIGH,
        )
        for obligation_id in reason_ids.values()
    )
    item_by_candidate_id: dict[str, ContextItem] = {}
    candidates: list[CoverageReservationCandidate] = []
    header_characters = _rendered_char_count(())
    for rank, item, obligation_value, strength in raw_candidates:
        candidate_id = _coverage_candidate_id(item)
        if candidate_id in item_by_candidate_id:
            continue
        item_by_candidate_id[candidate_id] = item
        candidates.append(
            CoverageReservationCandidate(
                candidate_id=candidate_id,
                source_key=_source_key(item),
                rank=rank,
                token_cost=estimate_tokens(item.text) + 16,
                character_cost=max(
                    0,
                    _rendered_char_count((item,)) - header_characters,
                ),
                claims=(
                    EvidenceClaim(
                        obligation_id=EvidenceObligationId(obligation_value),
                        strength=strength,
                    ),
                ),
            )
        )
    return obligations, tuple(candidates), item_by_candidate_id


def _coverage_candidate_is_eligible(item: ContextItem) -> bool:
    if item.is_instruction or not item.source_refs:
        return False
    if diagnostic_value(item, "review_only") is True:
        return False
    return diagnostic_value(item, "conflicting_fact_id") is None


def _coverage_claim_strength(item: ContextItem) -> float | None:
    signals = diagnostic_score_signals(item)
    hits = signals.get("unique_term_hits")
    ratio = signals.get("hit_ratio")
    penalty = signals.get("deterministic_rerank_penalty", 0.0)
    net_adjustment = signals.get("deterministic_rerank_net_adjustment")
    if isinstance(hits, bool) or not isinstance(hits, int):
        return None
    if isinstance(ratio, bool) or not isinstance(ratio, int | float):
        return None
    if isinstance(penalty, bool) or not isinstance(penalty, int | float):
        return None
    if net_adjustment is not None and (
        isinstance(net_adjustment, bool) or not isinstance(net_adjustment, int | float)
    ):
        return None
    bounded_ratio = max(0.0, min(1.0, float(ratio)))
    if (
        hits < _MIN_COVERAGE_TERM_HITS
        or bounded_ratio < _MIN_COVERAGE_HIT_RATIO
        or float(penalty) > _MAX_COVERAGE_RERANK_PENALTY
        or (net_adjustment is not None and float(net_adjustment) >= 0.0)
    ):
        return None
    return bounded_ratio


def _coverage_candidate_id(item: ContextItem) -> str:
    item_type, item_id = _selection_key(item)
    return f"{item_type}:{item_id}"
