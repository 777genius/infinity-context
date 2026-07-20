"""Bounded final priority for explicit application answer evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from infinity_context_core.application.dto import ContextItem

_MAX_PRIORITY_ITEMS = 8
_PRIORITY_SCORE = 0.99
_ORDINARY_BOUNDARY_SCORE = 0.9899


def apply_context_evidence_priority(
    items: tuple[ContextItem, ...],
    *,
    max_priority_items: int = _MAX_PRIORITY_ITEMS,
) -> tuple[tuple[ContextItem, ...], dict[str, object]]:
    """Reserve a bounded score band for query-supported direct evidence.

    Candidate producers own the evidence contracts. This final application
    policy neither interprets source text nor infers priority from action-word
    overlap. Existing deterministic penalties remain recorded and unresolved
    conflict/currentness evidence is never promoted.
    """

    limit = max(0, max_priority_items)
    eligible = tuple(item for item in items if _evidence_priority_tier(item) is not None)
    prioritized_keys = {
        _item_key(item) for item in _source_diverse_priority_items(eligible, limit=limit)
    }
    if not prioritized_keys:
        return items, _diagnostics(
            considered=len(items),
            eligible=len(eligible),
            prioritized=0,
            adjusted=0,
            limit=limit,
        )

    adjusted = 0
    prioritized_items: list[ContextItem] = []
    for item in items:
        key = _item_key(item)
        if key in prioritized_keys:
            prioritized = _with_priority_score(item)
        elif _should_apply_ordinary_boundary(item, eligible_keys=prioritized_keys):
            prioritized = _with_ordinary_boundary_score(item)
        else:
            prioritized = item
        adjusted += prioritized != item
        prioritized_items.append(prioritized)
    return tuple(prioritized_items), _diagnostics(
        considered=len(items),
        eligible=len(eligible),
        prioritized=len(prioritized_keys),
        adjusted=adjusted,
        limit=limit,
    )


def _evidence_priority_tier(item: ContextItem) -> int | None:
    if item.is_instruction or has_unresolved_rerank_rejection(item):
        return None
    signals = _score_signals(item)
    contract_tier = _non_negative_int(signals.get("application_evidence_contract_tier"))
    if contract_tier in {1, 2}:
        return contract_tier - 1
    return None


def _eligible_order_key(item: ContextItem) -> tuple[int, float, str, str]:
    tier = _evidence_priority_tier(item)
    return (
        tier if tier is not None else 99,
        -round(item.score, 8),
        item.item_type,
        item.item_id,
    )


def _source_diverse_priority_items(
    eligible: tuple[ContextItem, ...],
    *,
    limit: int,
) -> tuple[ContextItem, ...]:
    """Allocate at most one bounded slot to each canonical source."""

    if limit <= 0:
        return ()
    selected: list[ContextItem] = []
    seen_sources: set[tuple[str, str, str]] = set()
    for item in sorted(eligible, key=_eligible_order_key):
        source_key = _canonical_source_key(item)
        if source_key in seen_sources:
            continue
        seen_sources.add(source_key)
        selected.append(item)
        if len(selected) >= limit:
            break
    return tuple(selected)


def _canonical_source_key(item: ContextItem) -> tuple[str, str, str]:
    diagnostics = item.diagnostics
    memory_scope_id = ""
    if isinstance(diagnostics, Mapping):
        memory_scope_id = str(diagnostics.get("memory_scope_id") or "")
    if item.source_refs:
        primary_ref = item.source_refs[0]
        return memory_scope_id, primary_ref.source_type, primary_ref.source_id
    return memory_scope_id, item.item_type, item.item_id


def has_unresolved_rerank_rejection(item: ContextItem) -> bool:
    """Return whether item-local rerank evidence records a hard conflict."""

    signals = _score_signals(item)
    if _positive(signals.get("current_conflict_earlier_assertion_penalty")):
        return True
    diagnostics = item.diagnostics
    if not isinstance(diagnostics, Mapping):
        return False
    raw_provenance = diagnostics.get("provenance")
    provenance = dict(raw_provenance) if isinstance(raw_provenance, Mapping) else {}
    reasons = provenance.get("deterministic_rerank_reasons")
    if not isinstance(reasons, list | tuple):
        return False
    projection_verified = (
        provenance.get("distinct_set_projection_verified") is True
        and (
            _positive(signals.get("distinct_set_projection_verified"))
            or _positive(signals.get("keyword_aggregation_distinct_member_support"))
        )
    )
    return any(
        _is_unresolved_conflict_reason(
            str(reason),
            projection_verified=projection_verified,
        )
        for reason in reasons
    )


def _is_unresolved_conflict_reason(
    reason: str,
    *,
    projection_verified: bool,
) -> bool:
    if projection_verified and reason == "aggregation_subject_mismatch":
        return False
    unresolved_conflict = (
        "conflict" in reason
        and "overridden" not in reason
        and not reason.endswith("_finality_evidence")
    )
    return (
        unresolved_conflict
        or reason.endswith("_mismatch")
        or reason.startswith("relation_requirement_")
    )


def _should_apply_ordinary_boundary(
    item: ContextItem,
    *,
    eligible_keys: set[tuple[str, str, str]],
) -> bool:
    return (
        _item_key(item) not in eligible_keys
        and item.score >= _PRIORITY_SCORE
        and not item.is_instruction
        and not has_unresolved_rerank_rejection(item)
        and not _is_current_finality_evidence(item)
    )


def _is_current_finality_evidence(item: ContextItem) -> bool:
    signals = _score_signals(item)
    return _positive(signals.get("current_conflict_finality_boost"))


def _with_priority_score(item: ContextItem) -> ContextItem:
    score = max(item.score, _PRIORITY_SCORE)
    return _with_boundary_diagnostics(
        item,
        score=score,
        priority=1,
        adjustment=score - item.score,
    )


def _with_ordinary_boundary_score(item: ContextItem) -> ContextItem:
    score = min(item.score, _ORDINARY_BOUNDARY_SCORE)
    return _with_boundary_diagnostics(
        item,
        score=score,
        priority=0,
        adjustment=score - item.score,
    )


def _with_boundary_diagnostics(
    item: ContextItem,
    *,
    score: float,
    priority: int,
    adjustment: float,
) -> ContextItem:
    diagnostics = dict(item.diagnostics or {})
    diagnostics["score_signals"] = {
        **_score_signals(item),
        "application_evidence_priority": priority,
        "application_evidence_priority_adjustment": round(adjustment, 4),
        "final_score": round(score, 4),
    }
    return replace(item, score=round(score, 4), diagnostics=diagnostics)


def _score_signals(item: ContextItem) -> dict[str, object]:
    diagnostics = item.diagnostics
    if not isinstance(diagnostics, Mapping):
        return {}
    signals = diagnostics.get("score_signals")
    return dict(signals) if isinstance(signals, Mapping) else {}


def _item_key(item: ContextItem) -> tuple[str, str, str]:
    return item.item_type, item.item_id, item.text


def _positive(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and float(value) > 0


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    numeric = float(value)
    if not numeric.is_integer():
        return None
    return max(0, int(numeric))


def _diagnostics(
    *,
    considered: int,
    eligible: int,
    prioritized: int,
    adjusted: int,
    limit: int,
) -> dict[str, object]:
    return {
        "evidence_priority_items_considered": considered,
        "evidence_priority_items_eligible": eligible,
        "evidence_priority_items_prioritized": prioritized,
        "evidence_priority_items_adjusted": adjusted,
        "evidence_priority_item_limit": limit,
    }
