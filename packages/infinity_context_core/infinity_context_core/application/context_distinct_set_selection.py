"""Packing prepass for bounded distinct-set member evidence."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from infinity_context_core.application.context_diagnostics import (
    safe_diagnostic_mapping,
    safe_score_signals,
)
from infinity_context_core.application.context_distinct_set_evidence import (
    extract_distinct_set_request,
    project_distinct_set_evidence,
)
from infinity_context_core.application.context_evidence_priority import (
    has_unresolved_rerank_rejection,
)
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.distinct_set_membership import (
    DistinctSetMemberCandidate,
    DistinctSetMemberReservationPolicy,
)

_MAX_PACKED_DISTINCT_MEMBER_ITEMS = 8
_RERANK_SIGNAL_PREFIXES = ("deterministic_rerank_", "current_conflict_")
_RERANK_PROVENANCE_KEYS = frozenset(
    {
        "deterministic_rerank_applied",
        "deterministic_rerank_anchor_conflict",
        "deterministic_rerank_reasons",
    }
)


@dataclass(frozen=True)
class DistinctSetSelectionDiagnostics:
    candidates_considered: int = 0
    source_candidates: int = 0
    items_selected: int = 0
    member_slots_selected: int = 0
    redundant_item_keys: frozenset[tuple[str, str]] = frozenset()


@dataclass(frozen=True)
class _ProjectedItem:
    candidate: DistinctSetMemberCandidate
    item: ContextItem
    order: int


def prepare_distinct_set_evidence_for_rerank(
    candidates: tuple[ContextItem, ...],
    *,
    evidence_items: tuple[ContextItem, ...],
) -> tuple[tuple[ContextItem, ...], dict[str, int]]:
    """Place safe exact projections in the candidates evaluated by final reranking."""

    selected = list(candidates)
    index_by_key = {(item.item_type, item.item_id): index for index, item in enumerate(selected)}
    restored = 0
    added = 0
    considered = 0
    rejected = 0
    for evidence_item in evidence_items:
        if not _is_distinct_member_support_item(evidence_item):
            continue
        considered += 1
        key = (evidence_item.item_type, evidence_item.item_id)
        index = index_by_key.get(key)
        existing = selected[index] if index is not None else None
        if has_unresolved_rerank_rejection(evidence_item):
            rejected += 1
        elif existing is None:
            index_by_key[key] = len(selected)
            selected.append(_with_distinct_set_rerank_verification(evidence_item, evidence_item))
            added += 1
        else:
            selected[index] = _with_distinct_set_rerank_verification(existing, evidence_item)
            restored += existing.text != evidence_item.text
        if considered >= _MAX_PACKED_DISTINCT_MEMBER_ITEMS:
            break
    return tuple(selected), {
        "distinct_set_evidence_items_considered": considered,
        "distinct_set_evidence_bodies_restored": restored,
        "distinct_set_evidence_items_added_for_rerank": added,
        "distinct_set_evidence_items_rejected_before_rerank": rejected,
    }


def _with_distinct_set_rerank_verification(
    item: ContextItem,
    evidence_item: ContextItem,
) -> ContextItem:
    """Record projection safety without impersonating the final reranker."""

    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    evidence_diagnostics = safe_diagnostic_mapping(evidence_item.diagnostics)
    existing_signals = safe_score_signals(diagnostics.get("score_signals"))
    evidence_signals = safe_score_signals(evidence_diagnostics.get("score_signals"))
    signals = {
        **{
            key: value
            for key, value in existing_signals.items()
            if not key.startswith(_RERANK_SIGNAL_PREFIXES)
        },
        **evidence_signals,
        "distinct_set_projection_verified": 1,
    }
    provenance = {
        **safe_diagnostic_mapping(diagnostics.get("provenance")),
        **safe_diagnostic_mapping(evidence_diagnostics.get("provenance")),
    }
    provenance = {
        key: value for key, value in provenance.items() if key not in _RERANK_PROVENANCE_KEYS
    }
    diagnostics["score_signals"] = signals
    diagnostics["provenance"] = {
        **provenance,
        "distinct_set_projection_verified": True,
    }
    return replace(
        item,
        text=evidence_item.text,
        source_refs=evidence_item.source_refs[:_MAX_PACKED_DISTINCT_MEMBER_ITEMS],
        diagnostics=diagnostics,
    )


def restore_distinct_set_evidence_items(
    candidates: tuple[ContextItem, ...],
    *,
    query: str,
    evidence_items: tuple[ContextItem, ...],
    ranked_items: tuple[ContextItem, ...] = (),
) -> tuple[tuple[ContextItem, ...], dict[str, int]]:
    """Restore reranked safe projections before the final requirement guard."""

    selected = list(candidates)
    index_by_key = {(item.item_type, item.item_id): index for index, item in enumerate(selected)}
    ranked_by_key = {(item.item_type, item.item_id): item for item in ranked_items}
    restored = 0
    added = 0
    considered = 0
    missing = 0
    rerank_rejected = 0
    for evidence_item in evidence_items:
        if not _is_distinct_member_support_item(evidence_item):
            continue
        considered += 1
        key = (evidence_item.item_type, evidence_item.item_id)
        index = index_by_key.get(key)
        if index is None:
            ranked_item = ranked_by_key.get(key)
            if ranked_item is None:
                missing += 1
            elif _has_unresolved_distinct_set_rejection(ranked_item, query=query):
                rerank_rejected += 1
            else:
                index_by_key[key] = len(selected)
                selected.append(
                    _with_restored_distinct_set_projection(ranked_item, evidence_item)
                )
                added += 1
        elif _has_unresolved_distinct_set_rejection(selected[index], query=query):
            rerank_rejected += 1
        elif selected[index].text != evidence_item.text:
            selected[index] = _with_restored_distinct_set_projection(
                selected[index],
                evidence_item,
            )
            restored += 1
        if considered >= _MAX_PACKED_DISTINCT_MEMBER_ITEMS:
            break
    return tuple(selected), {
        "distinct_set_evidence_items_considered": considered,
        "distinct_set_evidence_bodies_restored": restored,
        "distinct_set_evidence_items_readded": added,
        "distinct_set_evidence_items_missing_after_ranking": missing,
        "distinct_set_evidence_items_rejected_by_rerank": rerank_rejected,
    }


def select_distinct_set_member_items(
    *,
    items: list[ContextItem],
    query: str,
    try_select_item: Callable[[ContextItem], bool],
) -> DistinctSetSelectionDiagnostics:
    """Reserve one best item per source when it contributes a novel member."""

    if extract_distinct_set_request(query) is None:
        return DistinctSetSelectionDiagnostics()
    projected: list[_ProjectedItem] = []
    all_projected: list[_ProjectedItem] = []
    best_by_source: dict[str, _ProjectedItem] = {}
    candidates_considered = 0
    for order, item in enumerate(items):
        projection = project_distinct_set_evidence(query=query, text=item.text)
        if not projection.present:
            continue
        if _has_unresolved_distinct_set_rejection(item, query=query):
            continue
        candidates_considered += 1
        source_family = _source_family(item)
        candidate = DistinctSetMemberCandidate(
            candidate_id=_candidate_id(item),
            source_family=source_family,
            member_ids=projection.member_ids,
        )
        value = _ProjectedItem(candidate=candidate, item=item, order=order)
        all_projected.append(value)
        existing = best_by_source.get(source_family)
        if existing is None or _projected_item_rank(value) < _projected_item_rank(existing):
            best_by_source[source_family] = value
    projected.extend(sorted(best_by_source.values(), key=lambda value: value.order))
    reservation = DistinctSetMemberReservationPolicy().select(
        tuple(value.candidate for value in projected),
        limit=_MAX_PACKED_DISTINCT_MEMBER_ITEMS,
    )
    item_by_id = {value.candidate.candidate_id: value.item for value in projected}
    selected = 0
    selected_member_ids: set[str] = set()
    selected_item_keys: set[tuple[str, str]] = set()
    for candidate_id in reservation.selected_ids:
        selected_projection = next(
            value for value in projected if value.candidate.candidate_id == candidate_id
        )
        item = _with_duplicate_member_source_refs(
            item_by_id[candidate_id],
            selected_projection=selected_projection,
            projected=tuple(projected),
        )
        if not try_select_item(item):
            continue
        selected += 1
        selected_item_keys.add((item.item_type, item.item_id))
        selected_member_ids.update(
            project_distinct_set_evidence(query=query, text=item.text).member_ids
        )
    redundant_item_keys = frozenset(
        (value.item.item_type, value.item.item_id)
        for value in all_projected
        if (value.item.item_type, value.item.item_id) not in selected_item_keys
        and set(value.candidate.member_ids).issubset(selected_member_ids)
    )
    return DistinctSetSelectionDiagnostics(
        candidates_considered=candidates_considered,
        source_candidates=len(projected),
        items_selected=selected,
        member_slots_selected=len(selected_member_ids),
        redundant_item_keys=redundant_item_keys,
    )


def _with_duplicate_member_source_refs(
    item: ContextItem,
    *,
    selected_projection: _ProjectedItem,
    projected: tuple[_ProjectedItem, ...],
) -> ContextItem:
    """Keep bounded corroborating provenance when a duplicate body is omitted."""

    selected_members = set(selected_projection.candidate.member_ids)
    refs = list(dict.fromkeys(item.source_refs))[:_MAX_PACKED_DISTINCT_MEMBER_ITEMS]
    if len(refs) >= _MAX_PACKED_DISTINCT_MEMBER_ITEMS:
        return replace(item, source_refs=tuple(refs))
    for value in projected:
        if value is selected_projection or not set(value.candidate.member_ids).issubset(
            selected_members
        ):
            continue
        for ref in value.item.source_refs:
            if ref not in refs:
                refs.append(ref)
                if len(refs) >= _MAX_PACKED_DISTINCT_MEMBER_ITEMS:
                    return replace(item, source_refs=tuple(refs))
    return replace(item, source_refs=tuple(refs))


def _projected_item_rank(value: _ProjectedItem) -> tuple[int, int]:
    return -len(value.candidate.member_ids), value.order


def _source_family(item: ContextItem) -> str:
    if item.source_refs:
        ref = item.source_refs[0]
        return f"{ref.source_type}:{ref.source_id}"
    return _candidate_id(item)


def _candidate_id(item: ContextItem) -> str:
    return f"{item.item_type}:{item.item_id}"


def _is_distinct_member_support_item(item: ContextItem) -> bool:
    diagnostics = safe_diagnostic_mapping(item.diagnostics)
    signals = safe_score_signals(diagnostics.get("score_signals"))
    value = signals.get("keyword_aggregation_distinct_member_support")
    return isinstance(value, int | float) and not isinstance(value, bool) and value > 0


def _has_unresolved_distinct_set_rejection(item: ContextItem, *, query: str) -> bool:
    """Apply hard rerank vetoes after the projection proves set membership."""

    if not project_distinct_set_evidence(query=query, text=item.text).present:
        return has_unresolved_rerank_rejection(item)
    diagnostics = dict(item.diagnostics or {})
    raw_provenance = diagnostics.get("provenance")
    provenance = dict(raw_provenance) if isinstance(raw_provenance, Mapping) else {}
    reasons = provenance.get("deterministic_rerank_reasons")
    if not isinstance(reasons, list | tuple):
        return has_unresolved_rerank_rejection(item)
    provenance["deterministic_rerank_reasons"] = [
        reason
        for reason in reasons
        if str(reason)
        not in {
            "aggregation_subject_mismatch",
            "relation_requirement_missing_relation",
        }
    ]
    diagnostics["provenance"] = provenance
    return has_unresolved_rerank_rejection(replace(item, diagnostics=diagnostics))


def _with_restored_distinct_set_projection(
    item: ContextItem,
    evidence_item: ContextItem,
) -> ContextItem:
    return replace(
        item,
        text=evidence_item.text,
        source_refs=evidence_item.source_refs[:_MAX_PACKED_DISTINCT_MEMBER_ITEMS],
    )
