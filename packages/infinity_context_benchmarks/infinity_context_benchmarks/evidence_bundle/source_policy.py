"""Source identity, locality and grounding predicates for evidence bundles."""

from __future__ import annotations

import re
from collections.abc import (
    Sequence,
)

from infinity_context_benchmarks.evidence_bundle.models import (
    EvidenceBundleCandidate,
    _safe_source_labels_for_output,
)
from infinity_context_benchmarks.source_identity import (
    safe_source_label_for_output as _safe_source_label_for_output,
)
from infinity_context_benchmarks.source_identity import (
    source_identity_refs_from_dedupe_key as _source_identity_refs_from_dedupe_key,
)
from infinity_context_benchmarks.source_identity import (
    source_identity_refs_from_source_refs as _source_identity_refs_from_source_refs,
)

_TURN_REF_PARTS_RE = re.compile(
    r"\b(?:(?P<session>session_\d+):)?D(?P<dialogue>\d+):(?P<turn>\d+)\b"
)


_SOURCE_PROXIMITY_WINDOW = 3


_COMPACT_SOURCE_REF_MAX_TURNS = 2


_COMPACT_SOURCE_REF_MAX_SPAN = _SOURCE_PROXIMITY_WINDOW


def _candidate_has_measured_weak_source_locality(
    candidate: EvidenceBundleCandidate,
) -> bool:
    return _candidate_has_measured_source_locality_below(candidate, 0.45)


def _candidate_has_measured_source_locality_below(
    candidate: EvidenceBundleCandidate,
    threshold: float,
) -> bool:
    return 0 < candidate.source_locality_score < threshold


def _candidate_has_measured_answerability_below(
    candidate: EvidenceBundleCandidate,
    threshold: float,
) -> bool:
    return 0 < candidate.answerability_score < threshold


def _is_measured_low_answerability(score: float) -> bool:
    return 0 < score < 0.55


def _retrieval_source_keys(candidate: EvidenceBundleCandidate) -> tuple[str, ...]:
    if candidate.retrieval_sources:
        sources = _safe_source_labels_for_output(candidate.retrieval_sources)
        if sources:
            return sources
    source_types = _source_type_keys(candidate)
    if source_types:
        return tuple(f"source_type:{source_type}" for source_type in source_types)
    source_type = _safe_source_label_for_output(candidate.source_type)
    if source_type and source_type != "unknown":
        return (f"source_type:{source_type}",)
    return ()


def _source_type_keys(candidate: EvidenceBundleCandidate) -> tuple[str, ...]:
    values = candidate.source_types or (candidate.source_type,)
    return _safe_source_labels_for_output(
        tuple(value for value in values if str(value).strip() != "unknown")
    )


def _source_ref_overlap_keys(candidate: EvidenceBundleCandidate) -> tuple[str, ...]:
    return _candidate_turn_ref_strings(candidate)


def _candidate_person_grounding_terms(
    candidate: EvidenceBundleCandidate,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            term.strip().casefold()
            for term in (*candidate.entity_hits, *candidate.speaker_hits)
            if term.strip()
        )
    )


def _closest_turn_ref_distance(
    candidate: EvidenceBundleCandidate,
    *,
    comparison_turn_refs: Sequence[tuple[str, int, int]],
) -> int | None:
    candidate_turn_refs = _candidate_turn_refs(candidate)
    distances = [
        abs(comparison_ref[2] - candidate_ref[2])
        for comparison_ref in comparison_turn_refs
        for candidate_ref in candidate_turn_refs
        if _turn_refs_same_source(comparison_ref, candidate_ref)
    ]
    if not distances:
        return None
    return min(distances)


def _turn_refs_same_source(
    left: tuple[str, int, int],
    right: tuple[str, int, int],
) -> bool:
    left_session, left_dialogue, _ = left
    right_session, right_dialogue, _ = right
    return left_dialogue == right_dialogue and (
        left_session == right_session or not left_session or not right_session
    )


def _candidate_has_focused_source_proximity_support(
    candidate: EvidenceBundleCandidate,
) -> bool:
    return bool(
        candidate.covered_expected_terms
        or candidate.covered_evidence_terms
        or candidate.direct_speaker_turn
        or candidate.focused_evidence_score > 0
    )


def _candidate_has_source_proximity_diagnostic_support(
    candidate: EvidenceBundleCandidate,
) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if _candidate_has_measured_weak_source_locality(candidate):
        return False
    return not _is_measured_low_answerability(candidate.answerability_score)


def _candidate_has_source_identity_quality_support(
    candidate: EvidenceBundleCandidate,
) -> bool:
    if candidate.broad_summary:
        return False
    if _candidate_has_measured_weak_source_locality(candidate):
        return False
    if _is_measured_low_answerability(candidate.answerability_score):
        return False
    if candidate.conflict_or_stale:
        return bool(
            candidate.contrast_surface
            or candidate.currentness_surface
            or candidate.stale_surface
        )
    if not candidate.source_refs and _candidate_turn_refs(candidate):
        return True
    return _candidate_has_source_identity_grounding(candidate)


def _candidate_has_generic_measured_answerability(
    candidate: EvidenceBundleCandidate,
) -> bool:
    if _is_measured_low_answerability(candidate.answerability_score):
        return False
    if candidate.answerability_score <= 0:
        return False
    return not _candidate_has_source_identity_grounding(candidate)


def _candidate_has_source_identity_grounding(
    candidate: EvidenceBundleCandidate,
) -> bool:
    return bool(
        candidate.covered_expected_terms
        or candidate.covered_evidence_terms
        or candidate.direct_speaker_turn
        or candidate.focused_evidence_score > 0
        or candidate.relation_hits
        or candidate.relation_category_hits
        or candidate.entity_hits
        or candidate.speaker_hits
        or candidate.exact_count_evidence
        or candidate.list_item_count > 0
        or candidate.has_preference_evidence
        or candidate.has_visual_evidence
        or candidate.has_temporal_surface
        or candidate.has_sequence_surface
        or candidate.has_duration_surface
        or candidate.has_relative_time_surface
        or candidate.has_explicit_time_content_surface
        or candidate.has_temporal_sequence_surface
        or candidate.negation_surface
        or candidate.currentness_surface
        or candidate.contrast_surface
    )


def _candidate_has_diffuse_source_refs(candidate: EvidenceBundleCandidate) -> bool:
    turn_refs = _candidate_turn_refs(candidate)
    if len(turn_refs) > _COMPACT_SOURCE_REF_MAX_TURNS:
        return True
    if not turn_refs:
        return False
    source_count = len({turn_ref[:2] for turn_ref in turn_refs})
    return source_count > 1 or _turn_ref_span(turn_refs) > _COMPACT_SOURCE_REF_MAX_SPAN


def _turn_ref_span(turn_refs: Sequence[tuple[str, int, int]]) -> int:
    if not turn_refs:
        return 0
    spans = []
    for source_ref in {turn_ref[:2] for turn_ref in turn_refs}:
        turns = [turn_ref[2] for turn_ref in turn_refs if turn_ref[:2] == source_ref]
        if turns:
            spans.append(max(turns) - min(turns))
    return max(spans, default=0)


def _candidate_has_noisy_source_overlap_risk(
    candidate: EvidenceBundleCandidate,
) -> bool:
    if (
        candidate.conflict_or_stale
        or candidate.contrast_surface
        or candidate.currentness_surface
        or candidate.stale_surface
    ):
        return False
    return bool(
        candidate.broad_summary
        or _candidate_has_measured_weak_source_locality(candidate)
        or _is_measured_low_answerability(candidate.answerability_score)
    )


def _source_identity_refs(candidate: EvidenceBundleCandidate) -> tuple[str, ...]:
    source_ref_identities = _source_identity_refs_from_source_refs(
        candidate.source_refs
    )
    source_identity_values = source_ref_identities or candidate.source_refs
    return tuple(
        dict.fromkeys(
            (
                *source_identity_values,
                *_source_identity_refs_from_dedupe_key(candidate.dedupe_key),
            )
        )
    )


def _candidate_turn_refs(candidate: EvidenceBundleCandidate) -> tuple[tuple[str, int, int], ...]:
    refs: list[tuple[str, int, int]] = []
    for turn_ref in _candidate_turn_ref_strings(candidate):
        for match in _TURN_REF_PARTS_RE.finditer(turn_ref):
            session = str(match.group("session") or "")
            dialogue = int(match.group("dialogue"))
            turn = int(match.group("turn"))
            refs.append((session, dialogue, turn))
    return tuple(dict.fromkeys(refs))


def _candidate_turn_ref_strings(candidate: EvidenceBundleCandidate) -> tuple[str, ...]:
    session_refs: list[str] = []
    turn_refs: list[str] = []
    qualified_turn_refs: set[str] = set()
    for value in (*candidate.source_refs, candidate.dedupe_key):
        for match in _TURN_REF_PARTS_RE.finditer(str(value)):
            turn_ref = f"D{match.group('dialogue')}:{match.group('turn')}"
            if session := match.group("session"):
                session_refs.append(f"{session}:{turn_ref}")
                qualified_turn_refs.add(turn_ref)
            else:
                turn_refs.append(turn_ref)
    unresolved_turn_refs = (
        turn_ref for turn_ref in turn_refs if turn_ref not in qualified_turn_refs
    )
    return tuple(dict.fromkeys((*session_refs, *unresolved_turn_refs)))


def _candidate_has_relation_grounding(candidate: EvidenceBundleCandidate) -> bool:
    return bool(candidate.relation_hits or candidate.relation_category_hits)


def _candidate_has_person_grounding(candidate: EvidenceBundleCandidate) -> bool:
    return bool(candidate.entity_hits or candidate.speaker_hits)
