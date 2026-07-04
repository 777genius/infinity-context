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
    selection_would_fill_bundle: bool = True,
) -> bool:
    candidate = item.candidate
    alternative_query_support_terms = (
        _candidate_query_support_terms(candidate)
        if adds_query_support_terms and selection_would_fill_bundle
        else frozenset()
    )
    return bool(
        item.role == "supporting"
        and not adds_required_terms
        and _has_redundant_query_support(
            candidate,
            remaining,
            selected,
            adds_query_support_terms=adds_query_support_terms,
            selection_would_fill_bundle=selection_would_fill_bundle,
            source_proximity_window=source_proximity_window,
        )
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
            query_support_terms=alternative_query_support_terms,
            source_proximity_window=source_proximity_window,
        )
    )


def _has_redundant_query_support(
    candidate: Any,
    remaining: Sequence[Any],
    selected: Sequence[Any],
    *,
    adds_query_support_terms: bool,
    selection_would_fill_bundle: bool,
    source_proximity_window: int,
) -> bool:
    if not adds_query_support_terms:
        return True
    if not selection_would_fill_bundle:
        return False
    if _candidate_has_local_query_evidence(candidate):
        return False
    query_support_terms = _candidate_query_support_terms(candidate)
    if not query_support_terms:
        return True
    return _has_distinct_source_window_alternative(
        remaining,
        selected,
        query_support_terms=query_support_terms,
        source_proximity_window=source_proximity_window,
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
        if item.role != "primary"
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
    *,
    source_proximity_window: int,
    query_support_terms: frozenset[str] = frozenset(),
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
        if query_support_terms and not query_support_terms.issubset(
            _candidate_query_support_terms(item.candidate)
        ):
            continue
        source_groups = set(_candidate_source_groups(item.candidate))
        if source_groups and any(
            not _source_group_is_covered(source_group, selected_source_groups)
            for source_group in source_groups
        ):
            return True
        if source_groups and not _candidate_has_redundant_source_window(
            item.candidate,
            selected,
            source_proximity_window=source_proximity_window,
        ):
            return True
    return False


def _candidate_query_support_terms(candidate: Any) -> frozenset[str]:
    return frozenset(
        str(term).strip().casefold()
        for term in getattr(candidate, "query_support_terms", ())
        if str(term).strip()
    )


def _candidate_has_local_query_evidence(candidate: Any) -> bool:
    return bool(
        getattr(candidate, "direct_speaker_turn", False)
        or float(getattr(candidate, "focused_evidence_score", 0.0) or 0.0) > 0
        or tuple(getattr(candidate, "relation_hits", ()))
        or tuple(getattr(candidate, "relation_category_hits", ()))
        or tuple(getattr(candidate, "entity_hits", ()))
        or tuple(getattr(candidate, "speaker_hits", ()))
    )


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
        if _source_groups_compatible(comparison_ref[:2], candidate_ref[:2])
    ]
    if not distances:
        return None
    return min(distances)


def _source_group_is_covered(
    source_group: tuple[str, int],
    selected_source_groups: set[tuple[str, int]],
) -> bool:
    return any(
        _source_groups_compatible(source_group, selected_source_group)
        for selected_source_group in selected_source_groups
    )


def _source_groups_compatible(
    left: tuple[str, int],
    right: tuple[str, int],
) -> bool:
    left_session, left_dialogue = left
    right_session, right_dialogue = right
    return left_dialogue == right_dialogue and (
        left_session == right_session or not left_session or not right_session
    )


def _candidate_turn_refs(candidate: Any) -> tuple[tuple[str, int, int], ...]:
    refs: list[tuple[str, int, int]] = []
    for value in (*candidate.source_refs, candidate.dedupe_key):
        for match in _TURN_REF_PARTS_RE.finditer(str(value)):
            session = str(match.group("session") or "")
            dialogue = int(match.group("dialogue"))
            turn = int(match.group("turn"))
            refs.append((session, dialogue, turn))
    return tuple(dict.fromkeys(refs))
