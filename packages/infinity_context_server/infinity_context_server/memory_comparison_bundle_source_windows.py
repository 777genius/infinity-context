"""Source-window diversity policy for memory comparison evidence bundles."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from typing import Any

_TURN_REF_PARTS_RE = re.compile(
    r"\b(?:(?P<session>session_\d+):)?D(?P<dialogue>\d+):(?P<turn>\d+)\b"
)


def is_redundant_source_window_filler(
    item: Any,
    *,
    remaining: Sequence[Any],
    selected: Sequence[Any],
    adds_required_terms: bool,
    adds_query_support_terms: bool,
    has_answer_evidence: bool,
    source_type_keys: Sequence[str],
    retrieval_source_keys: Sequence[str],
    source_type_counts: Counter[str],
    retrieval_source_counts: Counter[str],
    source_proximity_window: int,
) -> bool:
    candidate = item.candidate
    return bool(
        item.role == "supporting"
        and not adds_required_terms
        and not adds_query_support_terms
        and not has_answer_evidence
        and not any(source_type_counts[key] == 0 for key in source_type_keys)
        and not any(retrieval_source_counts[key] == 0 for key in retrieval_source_keys)
        and _candidate_has_redundant_source_window(
            candidate,
            selected,
            source_proximity_window=source_proximity_window,
        )
        and _has_distinct_source_window_alternative(
            remaining,
            selected,
        )
    )


def _candidate_has_redundant_source_window(
    candidate: Any,
    selected: Sequence[Any],
    *,
    source_proximity_window: int,
) -> bool:
    if not candidate.source_refs:
        return False
    if not _candidate_has_source_proximity_support(candidate):
        return False
    selected_turn_refs = tuple(
        turn_ref
        for item in selected
        if item.candidate.source_refs
        if _candidate_has_source_proximity_support(item.candidate)
        for turn_ref in _candidate_turn_refs(item.candidate)
    )
    if not selected_turn_refs:
        return False
    closest_distance = _closest_turn_ref_distance(
        candidate,
        comparison_turn_refs=selected_turn_refs,
    )
    return closest_distance is not None and closest_distance <= source_proximity_window


def _has_distinct_source_window_alternative(
    remaining: Sequence[Any],
    selected: Sequence[Any],
) -> bool:
    selected_source_groups = {
        source_group
        for item in selected
        if item.candidate.source_refs
        for source_group in _candidate_source_groups(item.candidate)
    }
    if not selected_source_groups:
        return False
    for item in remaining:
        if item.role == "primary" or not item.candidate.source_refs:
            continue
        if not _candidate_has_source_proximity_support(item.candidate):
            continue
        source_groups = set(_candidate_source_groups(item.candidate))
        if source_groups and not source_groups.issubset(selected_source_groups):
            return True
    return False


def _candidate_has_source_proximity_support(candidate: Any) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if 0 < candidate.source_locality_score < 0.45:
        return False
    return not 0 < candidate.answerability_score < 0.55


def _candidate_source_groups(candidate: Any) -> tuple[tuple[str, int], ...]:
    return tuple(
        dict.fromkeys(turn_ref[:2] for turn_ref in _candidate_turn_refs(candidate))
    )


def _closest_turn_ref_distance(
    candidate: Any,
    *,
    comparison_turn_refs: Sequence[tuple[str, int, int]],
) -> int | None:
    candidate_turn_refs = _candidate_turn_refs(candidate)
    distances = [
        abs(comparison_ref[2] - candidate_ref[2])
        for comparison_ref in comparison_turn_refs
        for candidate_ref in candidate_turn_refs
        if comparison_ref[:2] == candidate_ref[:2]
    ]
    if not distances:
        return None
    return min(distances)


def _candidate_turn_refs(candidate: Any) -> tuple[tuple[str, int, int], ...]:
    refs: list[tuple[str, int, int]] = []
    for value in (*candidate.source_refs, candidate.dedupe_key):
        for match in _TURN_REF_PARTS_RE.finditer(str(value)):
            session = str(match.group("session") or "")
            dialogue = int(match.group("dialogue"))
            turn = int(match.group("turn"))
            refs.append((session, dialogue, turn))
    return tuple(dict.fromkeys(refs))
