"""Budgeted source-faithful evidence selection for non-prompt consumers."""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, replace

from infinity_context_core.application.context_ranked_activity_reservation import (
    reserve_activity_inventory_head,
)
from infinity_context_core.application.context_ranked_evidence_coverage_reservation import (
    reserve_temporal_interval_evidence_head,
)
from infinity_context_core.application.context_ranked_evidence_priority_reservation import (
    reserve_application_evidence_head,
)
from infinity_context_core.application.dto import ContextBundle, ContextItem
from infinity_context_core.application.normalize import estimate_tokens
from infinity_context_core.domain.entities import SourceRef

_MARKER_RE = re.compile(r"\bD(?P<dialogue>\d+)[:-](?P<turn>\d+)\b", re.IGNORECASE)
_SPEAKER_RE = re.compile(r"\s+[^:\n]{1,80}:")
_DIALOGUE_LABEL_RE = re.compile(r"D\d+", re.IGNORECASE)
_MAX_ITEMS = 200


@dataclass(frozen=True, slots=True)
class RankedEvidenceBudget:
    max_items: int
    max_tokens: int
    max_chars: int

    def normalized(self) -> RankedEvidenceBudget:
        return RankedEvidenceBudget(
            max_items=min(_MAX_ITEMS, max(0, self.max_items)),
            max_tokens=max(0, self.max_tokens),
            max_chars=max(0, self.max_chars),
        )


@dataclass(frozen=True, slots=True)
class RankedEvidenceResult:
    bundle: ContextBundle
    dropped_count: int


def select_ranked_evidence(
    *,
    bundle_id: str,
    items: tuple[ContextItem, ...],
    query: str,
    budget: RankedEvidenceBudget,
) -> RankedEvidenceResult:
    """Preserve parent rank fairly and admit only bounded, source-backed evidence."""

    limits = budget.normalized()
    selected: list[ContextItem] = []
    selected_sources: set[str] = set()
    rendered_text = ""
    used_chars = 0
    selectable_candidate_count = 0
    eligible_candidate_count = 0
    counters = {
        "instruction": 0,
        "unsafe_source": 0,
        "source_dedupe": 0,
        "item_budget": 0,
        "token_budget": 0,
        "char_budget": 0,
        "projection_candidate": 0,
    }
    candidate_groups: list[tuple[ContextItem, ...]] = []
    for parent in items:
        projections = _exact_turn_projections(parent)
        candidates = projections or (parent,)
        candidate_groups.append(candidates)
        selectable_candidate_count += len(candidates)
        counters["projection_candidate"] += len(projections)
    ordinarily_ordered_candidates = reserve_application_evidence_head(
        reserve_activity_inventory_head(
            tuple(_parent_fair_atomic_candidates(tuple(candidate_groups))),
            query=query,
        )
    )
    temporal_interval_reservation = reserve_temporal_interval_evidence_head(
        ordinarily_ordered_candidates,
        query=query,
        max_items=limits.max_items,
        max_tokens=limits.max_tokens,
        max_chars=limits.max_chars,
    )
    ordered_candidates = temporal_interval_reservation.items
    for candidate in ordered_candidates:
        if candidate.is_instruction:
            counters["instruction"] += 1
            continue
        source_keys = _canonical_source_keys(candidate.source_refs)
        if not candidate.text.strip() or not source_keys:
            counters["unsafe_source"] += 1
            continue
        if source_keys <= selected_sources:
            counters["source_dedupe"] += 1
            continue
        # Eligible means the atomic candidate passed instruction, source-safety,
        # and selected-source dedupe checks and therefore reached budget admission.
        eligible_candidate_count += 1
        if len(selected) >= limits.max_items:
            counters["item_budget"] += 1
            continue
        prospective_rendered_text = (
            f"{rendered_text}\n\n{candidate.text}" if rendered_text else candidate.text
        )
        prospective_token_estimate = estimate_tokens(prospective_rendered_text)
        prospective_char_count = len(prospective_rendered_text)
        if prospective_token_estimate > limits.max_tokens:
            counters["token_budget"] += 1
            continue
        if prospective_char_count > limits.max_chars:
            counters["char_budget"] += 1
            continue
        selected.append(candidate)
        selected_sources.update(source_keys)
        rendered_text = prospective_rendered_text
        used_chars = prospective_char_count

    selected_items = tuple(selected)
    compact_count = sum(
        bool((item.diagnostics or {}).get("ranked_evidence_compact_projection"))
        for item in selected_items
    )
    budget_drop_count = sum(counters[key] for key in ("item_budget", "token_budget", "char_budget"))
    diagnostics = {
        "ranked_evidence_candidate_count": len(items),
        "ranked_evidence_projection_candidate_count": counters["projection_candidate"],
        "ranked_evidence_selectable_candidate_count": selectable_candidate_count,
        "ranked_evidence_eligible_candidate_count": eligible_candidate_count,
        "ranked_evidence_returned_count": len(selected_items),
        "ranked_evidence_compact_projection_count": compact_count,
        "ranked_evidence_source_diversity_count": len(selected_sources),
        "ranked_evidence_budget_drop_count": budget_drop_count,
        "ranked_evidence_item_budget_drop_count": counters["item_budget"],
        "ranked_evidence_token_budget_drop_count": counters["token_budget"],
        "ranked_evidence_char_budget_drop_count": counters["char_budget"],
        "ranked_evidence_instruction_drop_count": counters["instruction"],
        "ranked_evidence_unsafe_source_drop_count": counters["unsafe_source"],
        "ranked_evidence_source_dedupe_drop_count": counters["source_dedupe"],
        "ranked_evidence_temporal_interval_reservation_count": (
            temporal_interval_reservation.reservation_count
        ),
        "items_considered": len(items),
        "items_used": len(selected_items),
        "rendered_chars": used_chars,
        "max_rendered_chars": limits.max_chars,
    }
    return RankedEvidenceResult(
        bundle=ContextBundle(
            bundle_id=bundle_id,
            rendered_text=rendered_text,
            items=selected_items,
            token_estimate=estimate_tokens(rendered_text) if rendered_text else 0,
            diagnostics=diagnostics,
        ),
        dropped_count=max(0, selectable_candidate_count - len(selected_items)),
    )


def _parent_fair_atomic_candidates(
    candidate_groups: tuple[tuple[ContextItem, ...], ...],
) -> Iterator[ContextItem]:
    """Yield stable rank-preserving rounds across parent candidate groups."""

    active = deque(iter(candidates) for candidates in candidate_groups if candidates)
    while active:
        candidates = active.popleft()
        try:
            candidate = next(candidates)
        except StopIteration:
            continue
        yield candidate
        active.append(candidates)


def _exact_turn_projections(item: ContextItem) -> tuple[ContextItem, ...]:
    matches = tuple(
        match
        for match in _MARKER_RE.finditer(item.text)
        if _has_direct_speaker(item.text, marker=match)
    )
    if len(matches) < 2:
        return ()
    projections: list[ContextItem] = []
    for index, match in enumerate(matches):
        marker = _canonical_marker(match.group(0))
        refs = tuple(ref for ref in item.source_refs if _canonical_marker(ref.source_id) == marker)
        if len(refs) != 1:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(item.text)
        text = item.text[match.start() : end].strip()
        if not text or len(text) >= len(item.text):
            continue
        diagnostics = dict(item.diagnostics or {})
        diagnostics["ranked_evidence_compact_projection"] = 1
        diagnostics["ranked_evidence_parent_item_id"] = item.item_id
        projections.append(
            replace(
                item,
                item_id=f"{item.item_id}:ranked_evidence_exact:{index}",
                text=text,
                source_refs=refs,
                diagnostics=diagnostics,
            )
        )
    return tuple(projections)


def _has_direct_speaker(text: str, *, marker: re.Match[str]) -> bool:
    speaker = _SPEAKER_RE.match(text[marker.end() : marker.end() + 96])
    if speaker is None or _MARKER_RE.search(speaker.group(0)) is not None:
        return False
    speaker_label = speaker.group(0).strip().removesuffix(":").strip()
    return _DIALOGUE_LABEL_RE.fullmatch(speaker_label) is None


def _canonical_source_keys(refs: tuple[SourceRef, ...]) -> frozenset[str]:
    keys: set[str] = set()
    for ref in refs:
        source_type = ref.source_type.strip().casefold()
        source_id = ref.source_id.strip()
        if not source_type or not source_id:
            continue
        marker = _canonical_marker(source_id)
        if not marker:
            keys.add(f"{source_type}:{source_id.casefold()}")
            continue
        match = _MARKER_RE.search(source_id)
        assert match is not None
        prefix = source_id[: match.start()].rstrip(":").casefold()
        keys.add(f"{source_type}:{prefix}:{marker}" if prefix else f"{source_type}:{marker}")
    return frozenset(keys)


def _canonical_marker(value: str) -> str:
    match = _MARKER_RE.search(value)
    if match is None:
        return ""
    return f"D{int(match.group('dialogue'))}:{int(match.group('turn'))}"


__all__ = ("RankedEvidenceBudget", "RankedEvidenceResult", "select_ranked_evidence")
