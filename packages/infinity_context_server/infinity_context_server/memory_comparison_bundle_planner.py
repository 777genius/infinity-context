"""Evidence bundle planning for memory comparison benchmark retrieval."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from infinity_context_server.memory_comparison_bundle_partial_support import (
    has_partial_required_role_support,
)
from infinity_context_server.memory_comparison_bundle_source_windows import (
    is_redundant_source_window_filler,
)
from infinity_context_server.memory_comparison_source_identity import (
    source_identity_refs_from_dedupe_key as _source_identity_refs_from_dedupe_key,
)
from infinity_context_server.memory_comparison_source_identity import (
    source_identity_refs_from_source_refs as _source_identity_refs_from_source_refs,
)

BundleRole = str
_TURN_REF_PARTS_RE = re.compile(
    r"\b(?:(?P<session>session_\d+):)?D(?P<dialogue>\d+):(?P<turn>\d+)\b"
)
_SOURCE_PROXIMITY_WINDOW = 3
_COMPACT_SOURCE_REF_MAX_TURNS = 2
_COMPACT_SOURCE_REF_MAX_SPAN = _SOURCE_PROXIMITY_WINDOW
_TYPED_RELATION_SUPPORT_CATEGORIES = {
    "action_support": frozenset({"action_event"}),
    "activity_support": frozenset({"activity_profile"}),
    "age_support": frozenset({"age_profile"}),
    "alias_support": frozenset({"alias_profile"}),
    "commitment_support": frozenset({"commitment_profile"}),
    "contact_support": frozenset({"contact_profile"}),
    "current_goal_support": frozenset({"current_goal"}),
    "date_support": frozenset({"date_profile"}),
    "diet_support": frozenset({"diet_profile"}),
    "education_support": frozenset({"education_profile"}),
    "employment_support": frozenset({"employment_profile"}),
    "favorite_support": frozenset({"favorite_preference"}),
    "health_support": frozenset({"health_profile"}),
    "identity_support": frozenset({"identity_profile"}),
    "pet_support": frozenset({"pet_profile"}),
    "skill_support": frozenset({"skill_profile"}),
    "status_support": frozenset({"status_profile"}),
    "support_goal_support": frozenset({"support_goal"}),
    "vehicle_support": frozenset({"vehicle_profile"}),
}
_PREDICATE_REQUIRED_ROLES = frozenset(
    {
        "causal_support",
        "communication_support",
        "contrast",
        "emotion_response_support",
        "event_support",
        "exchange_support",
        "inference_support",
        "count_support",
        "location_support",
        "list_support",
        "preference_support",
        "symbolic_meaning_support",
        "temporal_support",
        "value_support",
        "visual_support",
        *_TYPED_RELATION_SUPPORT_CATEGORIES,
    }
)
_NEGATIVE_ABSENCE_ROLES = frozenset({"absence_support", "negative_support"})
_TYPED_TEMPORAL_SUPPORT_ROLES = frozenset(
    {
        "duration_temporal_support",
        "explicit_temporal_support",
        "relative_temporal_support",
        "temporal_sequence_support",
        "visual_temporal_support",
    }
)
_TEMPORAL_TIME_KIND_ROLES = {
    "duration": "duration_temporal_support",
    "explicit_time": "explicit_temporal_support",
    "relative_time": "relative_temporal_support",
    "temporal_sequence": "temporal_sequence_support",
}
_DIVERSITY_EXEMPT_ROLES = frozenset(
    {
        "bridge",
        "entity_disambiguation",
        "negative_support",
        "primary",
        *_TYPED_TEMPORAL_SUPPORT_ROLES,
        *_PREDICATE_REQUIRED_ROLES,
    }
)


@dataclass(frozen=True)
class EvidenceBundleCandidate:
    """Typed candidate used to build a compact evidence bundle."""

    rank: int
    retrieval_order: int
    item_id: str
    covered_expected_terms: tuple[str, ...]
    covered_evidence_terms: tuple[str, ...]
    query_support_terms: tuple[str, ...]
    query_support_score: float
    bundle_strength_score: float
    focused_evidence_score: float
    primary_signal: bool
    dedupe_key: str
    source_refs: tuple[str, ...] = ()
    source_type: str = "unknown"
    source_types: tuple[str, ...] = ()
    retrieval_sources: tuple[str, ...] = ()
    direct_speaker_turn: bool = False
    broad_summary: bool = False
    time_intent_kind: str = ""
    has_temporal_surface: bool = False
    has_sequence_surface: bool = False
    has_duration_surface: bool = False
    has_relative_time_surface: bool = False
    has_explicit_time_surface: bool = False
    has_explicit_time_content_surface: bool = False
    has_temporal_sequence_surface: bool = False
    conflict_or_stale: bool = False
    negation_surface: bool = False
    currentness_surface: bool = False
    stale_surface: bool = False
    contrast_surface: bool = False
    answerability_score: float = 0.0
    answerability_reason_codes: tuple[str, ...] = ()
    source_locality_score: float = 0.0
    relation_hits: tuple[str, ...] = ()
    relation_categories: tuple[str, ...] = ()
    relation_category_hits: tuple[str, ...] = ()
    covered_answer_unit_shapes: tuple[str, ...] = ()
    exact_count_evidence: bool = False
    list_item_count: int = 0
    entity_hits: tuple[str, ...] = ()
    speaker_hits: tuple[str, ...] = ()
    query_has_entities: bool = False
    has_preference_evidence: bool = False
    has_visual_evidence: bool = False
    query_roles: tuple[str, ...] = ()
    bridge_query_hit: bool = False
    eligibility_reason_codes: tuple[str, ...] = ()

    @property
    def required_terms(self) -> frozenset[str]:
        return frozenset((*self.covered_expected_terms, *self.covered_evidence_terms))


@dataclass(frozen=True)
class PlannedEvidenceItem:
    """A selected evidence item with its bundle role and reason codes."""

    candidate: EvidenceBundleCandidate
    role: BundleRole
    reason_codes: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "rank": self.candidate.rank,
            "retrieval_order": self.candidate.retrieval_order,
            "id": self.candidate.item_id,
            "role": self.role,
            "covered_expected_terms": list(self.candidate.covered_expected_terms),
            "covered_evidence_terms": list(self.candidate.covered_evidence_terms),
            "query_support_terms": list(self.candidate.query_support_terms),
            "query_support_score": self.candidate.query_support_score,
            "bundle_strength_score": self.candidate.bundle_strength_score,
            "focused_evidence_score": self.candidate.focused_evidence_score,
            "answerability_score": round(self.candidate.answerability_score, 6),
            "answerability_reason_codes": list(
                self.candidate.answerability_reason_codes
            ),
            "time_intent_kind": self.candidate.time_intent_kind,
            "has_duration_surface": self.candidate.has_duration_surface,
            "has_relative_time_surface": self.candidate.has_relative_time_surface,
            "has_explicit_time_surface": self.candidate.has_explicit_time_surface,
            "has_explicit_time_content_surface": (
                self.candidate.has_explicit_time_content_surface
            ),
            "has_temporal_sequence_surface": (
                self.candidate.has_temporal_sequence_surface
            ),
            "covered_answer_unit_shapes": list(
                self.candidate.covered_answer_unit_shapes
            ),
            "exact_count_evidence": self.candidate.exact_count_evidence,
            "list_item_count": self.candidate.list_item_count,
            "source_locality_score": round(self.candidate.source_locality_score, 6),
            "negation_surface": self.candidate.negation_surface,
            "currentness_surface": self.candidate.currentness_surface,
            "stale_surface": self.candidate.stale_surface,
            "contrast_surface": self.candidate.contrast_surface,
            "source_refs": list(self.candidate.source_refs),
            "dedupe_key": self.candidate.dedupe_key,
            "planner_reason_codes": list(self.reason_codes),
        }
        if self.candidate.dedupe_key.startswith(
            ("source_refs:", "source_turn_refs:", "source_session_turn_refs:")
        ):
            payload["source_ref_dedupe_key"] = self.candidate.dedupe_key
        if self.candidate.source_type != "unknown":
            payload["source_type"] = self.candidate.source_type
        if self.candidate.source_types:
            payload["source_types"] = list(self.candidate.source_types)
        if self.candidate.retrieval_sources:
            payload["retrieval_sources"] = list(self.candidate.retrieval_sources)
        if self.candidate.query_roles:
            payload["query_roles"] = list(self.candidate.query_roles)
        if self.candidate.relation_categories:
            payload["relation_categories"] = list(self.candidate.relation_categories)
        if self.candidate.relation_category_hits:
            payload["relation_category_hits"] = list(
                self.candidate.relation_category_hits
            )
        if self.candidate.entity_hits:
            payload["entity_hits"] = list(self.candidate.entity_hits)
        if self.candidate.speaker_hits:
            payload["speaker_hits"] = list(self.candidate.speaker_hits)
        if self.candidate.has_preference_evidence:
            payload["has_preference_evidence"] = True
        if self.candidate.has_visual_evidence:
            payload["has_visual_evidence"] = True
        if self.candidate.bridge_query_hit:
            payload["bridge_query_hit"] = True
        if self.candidate.eligibility_reason_codes:
            payload["eligibility_reason_codes"] = list(
                self.candidate.eligibility_reason_codes
            )
        return payload


@dataclass(frozen=True)
class EvidenceBundlePlan:
    """Planner output and diagnostics for selected evidence items."""

    items: tuple[PlannedEvidenceItem, ...]
    candidate_count: int
    deduplicated_item_count: int
    dropped_duplicate_keys: tuple[str, ...]
    dropped_diversity_count: int
    dropped_source_type_diversity_count: int
    dropped_retrieval_source_diversity_count: int
    dropped_source_ref_overlap_count: int
    dropped_source_ref_overlap_keys: tuple[str, ...]
    dropped_noisy_source_overlap_count: int
    dropped_noisy_source_overlap_keys: tuple[str, ...]
    role_counts: Mapping[str, int]
    source_type_counts: Mapping[str, int]
    retrieval_source_counts: Mapping[str, int]
    required_roles: tuple[str, ...]
    satisfied_required_roles: tuple[str, ...]
    missing_required_roles: tuple[str, ...]
    primary_selection_reason_codes: tuple[str, ...]
    repaired_required_roles: tuple[str, ...] = ()

    @property
    def role_requirement_complete(self) -> bool:
        return not self.missing_required_roles

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "schema_version": "evidence_bundle_planner.v1",
            "candidate_count": self.candidate_count,
            "selected_item_count": len(self.items),
            "deduplicated_item_count": self.deduplicated_item_count,
            "dropped_duplicate_keys": list(self.dropped_duplicate_keys),
            "dropped_diversity_count": self.dropped_diversity_count,
            "dropped_source_type_diversity_count": (
                self.dropped_source_type_diversity_count
            ),
            "dropped_retrieval_source_diversity_count": (
                self.dropped_retrieval_source_diversity_count
            ),
            "dropped_source_ref_overlap_count": (
                self.dropped_source_ref_overlap_count
            ),
            "dropped_source_ref_overlap_keys_sample": list(
                self.dropped_source_ref_overlap_keys[:12]
            ),
            "dropped_noisy_source_overlap_count": (
                self.dropped_noisy_source_overlap_count
            ),
            "dropped_noisy_source_overlap_keys_sample": list(
                self.dropped_noisy_source_overlap_keys[:12]
            ),
            "role_counts": dict(self.role_counts),
            "required_roles": list(self.required_roles),
            "satisfied_required_roles": list(self.satisfied_required_roles),
            "missing_required_roles": list(self.missing_required_roles),
            "role_requirement_complete": self.role_requirement_complete,
            "required_role_repair_count": len(self.repaired_required_roles),
            "repaired_required_roles": list(self.repaired_required_roles),
            "source_type_counts": dict(self.source_type_counts),
            "retrieval_source_counts": dict(self.retrieval_source_counts),
            "covered_required_term_count": len(
                {
                    term
                    for item in self.items
                    for term in item.candidate.required_terms
                }
            ),
            "covered_query_support_term_count": len(
                {
                    term
                    for item in self.items
                    for term in item.candidate.query_support_terms
                }
            ),
            "max_answerability_score": round(
                max((item.candidate.answerability_score for item in self.items), default=0.0),
                6,
            ),
            "average_selected_answerability_score": round(
                (
                    sum(item.candidate.answerability_score for item in self.items)
                    / len(self.items)
                )
                if self.items
                else 0.0,
                6,
            ),
            "average_measured_selected_answerability_score": round(
                _avg_positive_scores(
                    tuple(item.candidate.answerability_score for item in self.items)
                ),
                6,
            ),
            "unmeasured_selected_answerability_count": sum(
                1 for item in self.items if item.candidate.answerability_score <= 0
            ),
            "average_selected_source_locality_score": round(
                (
                    sum(item.candidate.source_locality_score for item in self.items)
                    / len(self.items)
                )
                if self.items
                else 0.0,
                6,
            ),
            "average_measured_selected_source_locality_score": round(
                _avg_positive_scores(
                    tuple(item.candidate.source_locality_score for item in self.items)
                ),
                6,
            ),
            "unmeasured_selected_source_locality_count": sum(
                1 for item in self.items if item.candidate.source_locality_score <= 0
            ),
            "selected_dedupe_keys": [
                item.candidate.dedupe_key for item in self.items
            ],
            "primary_selection_reason_codes": list(
                self.primary_selection_reason_codes
            ),
            "bundle_quality": _bundle_quality_diagnostics(
                self.items,
                missing_required_roles=self.missing_required_roles,
            ),
        }


class EvidenceBundlePlanner:
    """Select and label evidence while preserving provenance diversity."""

    def __init__(
        self,
        *,
        max_items: int = 8,
        max_items_per_source_type: int = 3,
        max_items_per_retrieval_source: int = 3,
    ) -> None:
        self._max_items = max(1, max_items)
        self._max_items_per_source_type = max(1, max_items_per_source_type)
        self._max_items_per_retrieval_source = max(1, max_items_per_retrieval_source)

    def plan(
        self,
        candidates: Sequence[EvidenceBundleCandidate],
        *,
        case_group: str,
        required_roles: Sequence[str] = (),
    ) -> EvidenceBundlePlan:
        deduped, dropped_duplicate_keys = self._dedupe(candidates)
        primary = self._primary_candidate(deduped)
        required_role_values = _required_role_values(required_roles)
        planned = tuple(
            self._planned_item(
                candidate,
                primary=primary,
                case_group=case_group,
                required_roles=required_role_values,
            )
            for candidate in deduped
        )
        (
            selected,
            dropped_diversity_count,
            dropped_source_type_diversity_count,
            dropped_retrieval_source_diversity_count,
            dropped_source_ref_overlap_count,
            dropped_source_ref_overlap_keys,
            dropped_noisy_source_overlap_count,
            dropped_noisy_source_overlap_keys,
        ) = self._select_with_diversity(planned)
        selected, repaired_required_roles = _repair_required_role_selection(
            selected,
            planned,
            required_roles=required_role_values,
            max_items=self._max_items,
        )
        role_counts = Counter(item.role for item in selected)
        satisfied_required_roles = _satisfied_required_roles(
            selected,
            required_roles=required_role_values,
        )
        missing_required_roles = tuple(
            role for role in required_role_values if role not in satisfied_required_roles
        )
        source_type_counts: Counter[str] = Counter()
        for item in selected:
            source_type_counts.update(_source_type_keys(item.candidate))
        retrieval_source_counts: Counter[str] = Counter()
        for item in selected:
            retrieval_source_counts.update(_retrieval_source_keys(item.candidate))
        primary_reasons = next(
            (
                item.reason_codes
                for item in selected
                if item.role == "primary"
            ),
            (),
        )
        return EvidenceBundlePlan(
            items=tuple(selected),
            candidate_count=len(candidates),
            deduplicated_item_count=len(dropped_duplicate_keys),
            dropped_duplicate_keys=tuple(dropped_duplicate_keys),
            dropped_diversity_count=dropped_diversity_count,
            dropped_source_type_diversity_count=dropped_source_type_diversity_count,
            dropped_retrieval_source_diversity_count=(
                dropped_retrieval_source_diversity_count
            ),
            dropped_source_ref_overlap_count=dropped_source_ref_overlap_count,
            dropped_source_ref_overlap_keys=dropped_source_ref_overlap_keys,
            dropped_noisy_source_overlap_count=dropped_noisy_source_overlap_count,
            dropped_noisy_source_overlap_keys=dropped_noisy_source_overlap_keys,
            role_counts=dict(role_counts),
            source_type_counts=dict(source_type_counts),
            retrieval_source_counts=dict(retrieval_source_counts),
            required_roles=required_role_values,
            satisfied_required_roles=satisfied_required_roles,
            missing_required_roles=missing_required_roles,
            primary_selection_reason_codes=primary_reasons,
            repaired_required_roles=repaired_required_roles,
        )

    def _dedupe(
        self,
        candidates: Sequence[EvidenceBundleCandidate],
    ) -> tuple[tuple[EvidenceBundleCandidate, ...], tuple[str, ...]]:
        by_key: dict[str, EvidenceBundleCandidate] = {}
        dropped_keys: list[str] = []
        for candidate in candidates:
            current = by_key.get(candidate.dedupe_key)
            if current is None:
                by_key[candidate.dedupe_key] = candidate
                continue
            dropped_keys.append(candidate.dedupe_key)
            if _candidate_sort_key(candidate) < _candidate_sort_key(current):
                by_key[candidate.dedupe_key] = candidate
        return tuple(by_key.values()), tuple(dropped_keys)

    def _primary_candidate(
        self,
        candidates: Sequence[EvidenceBundleCandidate],
    ) -> EvidenceBundleCandidate | None:
        primary_candidates = tuple(
            candidate for candidate in candidates if _primary_candidate_eligible(candidate)
        )
        if not primary_candidates:
            return None
        non_contrast_candidates = tuple(
            candidate
            for candidate in primary_candidates
            if not _candidate_has_contrast_support(candidate)
        )
        current_primary_candidates = tuple(
            candidate
            for candidate in non_contrast_candidates
            if not _candidate_has_obsolete_primary_surface(candidate)
        )
        candidates_to_rank = (
            current_primary_candidates
            or non_contrast_candidates
            or primary_candidates
        )
        return sorted(candidates_to_rank, key=_primary_sort_key)[0]

    def _planned_item(
        self,
        candidate: EvidenceBundleCandidate,
        *,
        primary: EvidenceBundleCandidate | None,
        case_group: str,
        required_roles: Sequence[str],
    ) -> PlannedEvidenceItem:
        role = _role_for_candidate(
            candidate,
            primary=primary,
            case_group=case_group,
            required_roles=required_roles,
        )
        return PlannedEvidenceItem(
            candidate=candidate,
            role=role,
            reason_codes=_reason_codes(candidate, role=role, case_group=case_group),
        )

    def _select_with_diversity(
        self,
        planned: Sequence[PlannedEvidenceItem],
    ) -> tuple[
        tuple[PlannedEvidenceItem, ...],
        int,
        int,
        int,
        int,
        tuple[str, ...],
        int,
        tuple[str, ...],
    ]:
        selected: list[PlannedEvidenceItem] = []
        source_type_counts: Counter[str] = Counter()
        retrieval_source_counts: Counter[str] = Counter()
        selected_source_ref_keys: set[str] = set()
        covered_terms: set[str] = set()
        covered_support_terms: set[str] = set()
        dropped_diversity_count = 0
        dropped_source_type_diversity_count = 0
        dropped_retrieval_source_diversity_count = 0
        dropped_source_ref_overlap_count = 0
        dropped_source_ref_overlap_keys: list[str] = []
        dropped_noisy_source_overlap_count = 0
        dropped_noisy_source_overlap_keys: list[str] = []
        remaining = list(planned)
        while remaining and len(selected) < self._max_items:
            remaining.sort(
                key=lambda item: _planned_coverage_sort_key(
                    item,
                    covered_terms=covered_terms,
                    covered_support_terms=covered_support_terms,
                    selected=selected,
                )
            )
            item = remaining.pop(0)
            source_type_keys = _source_type_keys(item.candidate)
            retrieval_source_keys = _retrieval_source_keys(item.candidate)
            source_ref_keys = _source_ref_overlap_keys(item.candidate)
            adds_required_terms = not item.candidate.required_terms.issubset(
                covered_terms
            )
            adds_query_support_terms = not set(
                item.candidate.query_support_terms
            ).issubset(covered_support_terms)
            adds_answer_support = adds_required_terms or adds_query_support_terms
            source_ref_overlap_full = bool(source_ref_keys) and set(
                source_ref_keys
            ).issubset(selected_source_ref_keys)
            source_ref_overlap_any = bool(
                set(source_ref_keys).intersection(selected_source_ref_keys)
            )
            noisy_source_overlap = (
                source_ref_overlap_any
                and _candidate_has_noisy_source_overlap_risk(item.candidate)
                and not adds_required_terms
            )
            redundant_source_window = is_redundant_source_window_filler(
                item,
                remaining=remaining,
                selected=selected,
                adds_required_terms=adds_required_terms,
                adds_query_support_terms=adds_query_support_terms,
                has_answer_evidence=_candidate_has_answer_evidence(item.candidate),
                source_type_keys=source_type_keys,
                retrieval_source_keys=retrieval_source_keys,
                source_type_counts=source_type_counts,
                retrieval_source_counts=retrieval_source_counts,
                source_proximity_window=_SOURCE_PROXIMITY_WINDOW,
                selection_would_fill_bundle=len(selected) + 1 >= self._max_items,
            )
            source_type_diversity_full = any(
                source_type_counts[source_type] >= self._max_items_per_source_type
                for source_type in source_type_keys
            )
            retrieval_source_diversity_full = any(
                retrieval_source_counts[source] >= self._max_items_per_retrieval_source
                for source in retrieval_source_keys
            )
            diversity_exempt = item.role in _DIVERSITY_EXEMPT_ROLES
            if (
                not diversity_exempt
                and source_type_diversity_full
                and not adds_answer_support
            ) or (
                not diversity_exempt
                and retrieval_source_diversity_full
                and not adds_answer_support
            ) or (
                source_ref_overlap_full
                and not adds_required_terms
                and not adds_query_support_terms
            ) or noisy_source_overlap or redundant_source_window:
                dropped_diversity_count += 1
                if source_type_diversity_full and not diversity_exempt:
                    dropped_source_type_diversity_count += 1
                if retrieval_source_diversity_full and not diversity_exempt:
                    dropped_retrieval_source_diversity_count += 1
                if source_ref_overlap_full:
                    dropped_source_ref_overlap_count += 1
                    dropped_source_ref_overlap_keys.extend(source_ref_keys)
                elif source_ref_overlap_any:
                    dropped_source_ref_overlap_count += 1
                    dropped_source_ref_overlap_keys.extend(
                        key
                        for key in source_ref_keys
                        if key in selected_source_ref_keys
                    )
                if noisy_source_overlap:
                    dropped_noisy_source_overlap_count += 1
                    dropped_noisy_source_overlap_keys.extend(
                        key
                        for key in source_ref_keys
                        if key in selected_source_ref_keys
                    )
                continue
            selected.append(item)
            source_type_counts.update(source_type_keys)
            retrieval_source_counts.update(retrieval_source_keys)
            selected_source_ref_keys.update(source_ref_keys)
            covered_terms.update(item.candidate.required_terms)
            covered_support_terms.update(item.candidate.query_support_terms)
        if remaining:
            (
                max_dropped_count,
                max_dropped_source_type_count,
                max_dropped_retrieval_source_count,
            ) = _max_item_drop_counts(
                remaining,
                source_type_counts=source_type_counts,
                retrieval_source_counts=retrieval_source_counts,
                max_items_per_source_type=self._max_items_per_source_type,
                max_items_per_retrieval_source=self._max_items_per_retrieval_source,
            )
            dropped_diversity_count += max_dropped_count
            dropped_source_type_diversity_count += max_dropped_source_type_count
            dropped_retrieval_source_diversity_count += max_dropped_retrieval_source_count
            for item in remaining:
                source_ref_keys = _source_ref_overlap_keys(item.candidate)
                overlapped_keys = [
                    key for key in source_ref_keys if key in selected_source_ref_keys
                ]
                if not overlapped_keys:
                    continue
                dropped_source_ref_overlap_count += 1
                dropped_source_ref_overlap_keys.extend(overlapped_keys)
                if _candidate_has_noisy_source_overlap_risk(item.candidate):
                    dropped_noisy_source_overlap_count += 1
                    dropped_noisy_source_overlap_keys.extend(overlapped_keys)
        return (
            tuple(selected),
            dropped_diversity_count,
            dropped_source_type_diversity_count,
            dropped_retrieval_source_diversity_count,
            dropped_source_ref_overlap_count,
            tuple(dict.fromkeys(dropped_source_ref_overlap_keys)),
            dropped_noisy_source_overlap_count,
            tuple(dict.fromkeys(dropped_noisy_source_overlap_keys)),
        )


def _role_for_candidate(
    candidate: EvidenceBundleCandidate,
    *,
    primary: EvidenceBundleCandidate | None,
    case_group: str,
    required_roles: Sequence[str] = (),
) -> BundleRole:
    if primary is not None and candidate.dedupe_key == primary.dedupe_key:
        return "primary"
    if candidate.conflict_or_stale or candidate.contrast_surface:
        return "contrast"
    if _is_bridge_candidate(candidate, case_group=case_group):
        return "bridge"
    if _candidate_has_negative_absence_support(candidate):
        return "negative_support"
    if _candidate_has_location_support(candidate):
        return "location_support"
    if (
        "favorite_support" in set(required_roles)
        and _candidate_has_favorite_support(candidate)
    ):
        return "favorite_support"
    if (
        "preference_support" in set(required_roles)
        and _candidate_has_preference_support(candidate)
    ):
        return "preference_support"
    if (
        "visual_support" in set(required_roles)
        and _candidate_has_visual_support(candidate)
    ):
        return "visual_support"
    if (
        "emotion_response_support" in set(required_roles)
        and _candidate_has_emotion_response_support(candidate)
    ):
        return "emotion_response_support"
    if (
        "symbolic_meaning_support" in set(required_roles)
        and _candidate_has_symbolic_meaning_support(candidate)
    ):
        return "symbolic_meaning_support"
    if (
        "event_support" in set(required_roles)
        and _candidate_has_event_support(candidate)
    ):
        return "event_support"
    if (
        "communication_support" in set(required_roles)
        and _candidate_has_communication_support(candidate)
    ):
        return "communication_support"
    if (
        "exchange_support" in set(required_roles)
        and _candidate_has_exchange_support(candidate)
    ):
        return "exchange_support"
    if (
        "causal_support" in set(required_roles)
        and _candidate_has_causal_support(candidate)
    ):
        return "causal_support"
    typed_temporal_role = _typed_temporal_role_for_candidate(
        candidate,
        required_roles=required_roles,
    )
    if typed_temporal_role:
        return typed_temporal_role
    if (
        "value_support" in set(required_roles)
        and _candidate_has_value_support(candidate)
    ):
        return "value_support"
    if (
        "count_support" in set(required_roles)
        and _candidate_has_count_support(candidate)
    ):
        return "count_support"
    if (
        "list_support" in set(required_roles)
        and _candidate_has_list_support(candidate)
    ):
        return "list_support"
    if (
        "inference_support" in set(required_roles)
        and _candidate_has_inference_support(candidate)
    ):
        return "inference_support"
    for role in required_roles:
        if _candidate_has_typed_relation_support(candidate, str(role)):
            return str(role)
    if (
        candidate.has_temporal_surface
        or candidate.has_sequence_surface
        or candidate.has_duration_surface
        or candidate.has_relative_time_surface
        or candidate.has_explicit_time_surface
        or candidate.has_temporal_sequence_surface
        or candidate.currentness_surface
    ):
        return "temporal_support"
    if case_group == "temporal" and candidate.query_support_terms:
        return "temporal_support"
    if (
        (candidate.entity_hits or candidate.speaker_hits)
        and not candidate.covered_expected_terms
        and not candidate.covered_evidence_terms
    ):
        return "entity_disambiguation"
    return "supporting"


def _is_bridge_candidate(
    candidate: EvidenceBundleCandidate,
    *,
    case_group: str,
) -> bool:
    if case_group != "multi-hop":
        return False
    return _candidate_has_bridge_grounding(candidate)


def _candidate_has_bridge_grounding(candidate: EvidenceBundleCandidate) -> bool:
    if candidate.conflict_or_stale or candidate.broad_summary:
        return False
    if _candidate_has_measured_weak_source_locality(candidate):
        return False
    if _is_measured_low_answerability(candidate.answerability_score):
        return False
    support_term_count = len(tuple(dict.fromkeys(candidate.query_support_terms)))
    if support_term_count < 2:
        return False
    return bool(
        _candidate_has_relation_grounding(candidate)
        and _candidate_has_person_grounding(candidate)
    )


def _required_role_values(required_roles: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(role for role in required_roles if role.strip()))


def _satisfied_required_roles(
    selected: Sequence[PlannedEvidenceItem],
    *,
    required_roles: Sequence[str],
) -> tuple[str, ...]:
    satisfied: set[str] = set()
    selected_roles = {item.role for item in selected}
    for role in required_roles:
        if role == "temporal_support" and any(
            _candidate_has_temporal_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
            continue
        if role in _TYPED_TEMPORAL_SUPPORT_ROLES and any(
            _candidate_has_typed_temporal_support(item.candidate, role)
            for item in selected
        ):
            satisfied.add(role)
            continue
        if role == "bridge":
            if _selection_has_bridge_support(selected):
                satisfied.add(role)
            continue
        if role in selected_roles and role not in _PREDICATE_REQUIRED_ROLES:
            satisfied.add(role)
            continue
        if role == "contrast" and any(
            _candidate_has_contrast_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
            continue
        if role in _NEGATIVE_ABSENCE_ROLES and any(
            _candidate_has_negative_absence_support(item.candidate)
            for item in selected
        ):
            satisfied.add(role)
            continue
        if role == "location_support" and any(
            _candidate_has_location_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
        if role == "value_support" and any(
            _candidate_has_value_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
        if role == "count_support" and any(
            _candidate_has_count_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
        if role == "list_support" and any(
            _candidate_has_list_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
        if role == "preference_support" and any(
            _candidate_has_preference_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
        if role == "visual_support" and any(
            _candidate_has_visual_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
        if role == "emotion_response_support" and any(
            _candidate_has_emotion_response_support(item.candidate)
            for item in selected
        ):
            satisfied.add(role)
        if role == "symbolic_meaning_support" and any(
            _candidate_has_symbolic_meaning_support(item.candidate)
            for item in selected
        ):
            satisfied.add(role)
        if role == "event_support" and any(
            _candidate_has_event_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
        if role == "communication_support" and any(
            _candidate_has_communication_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
        if role == "exchange_support" and any(
            _candidate_has_exchange_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
        if role == "inference_support" and any(
            _candidate_has_inference_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
        if role == "causal_support" and any(
            _candidate_has_causal_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
        if role in _TYPED_RELATION_SUPPORT_CATEGORIES and any(
            _candidate_has_typed_relation_support(item.candidate, role)
            for item in selected
        ):
            satisfied.add(role)
    return tuple(role for role in required_roles if role in satisfied)


def _repair_required_role_selection(
    selected: Sequence[PlannedEvidenceItem],
    planned: Sequence[PlannedEvidenceItem],
    *,
    required_roles: Sequence[str],
    max_items: int,
) -> tuple[tuple[PlannedEvidenceItem, ...], tuple[str, ...]]:
    if not required_roles or not planned:
        return tuple(selected), ()

    selected_items = list(selected)
    repaired_roles: list[str] = []
    for _ in range(len(required_roles)):
        missing_roles = _missing_required_roles(
            selected_items,
            required_roles=required_roles,
        )
        if not missing_roles:
            break
        repaired_this_pass = False
        for role in missing_roles:
            candidate = _best_required_role_candidate(
                planned,
                selected_items,
                role=role,
            )
            if candidate is None:
                continue
            if len(selected_items) < max_items:
                selected_items.append(candidate)
                repaired_roles.append(role)
                repaired_this_pass = True
                break
            replace_index = _replaceable_item_index(
                selected_items,
                required_roles=required_roles,
            )
            if replace_index is None:
                continue
            selected_items[replace_index] = candidate
            repaired_roles.append(role)
            repaired_this_pass = True
            break
        if not repaired_this_pass:
            break

    if not repaired_roles:
        return tuple(selected), ()
    return tuple(sorted(selected_items, key=_planned_sort_key)), tuple(
        dict.fromkeys(repaired_roles)
    )


def _missing_required_roles(
    selected: Sequence[PlannedEvidenceItem],
    *,
    required_roles: Sequence[str],
) -> tuple[str, ...]:
    satisfied = set(
        _satisfied_required_roles(selected, required_roles=required_roles)
    )
    return tuple(role for role in required_roles if role not in satisfied)


def _best_required_role_candidate(
    planned: Sequence[PlannedEvidenceItem],
    selected: Sequence[PlannedEvidenceItem],
    *,
    role: str,
) -> PlannedEvidenceItem | None:
    selected_ids = {id(item) for item in selected}
    candidates = [
        item
        for item in planned
        if id(item) not in selected_ids
        and _item_can_satisfy_required_role(item, role)
    ]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: _required_role_candidate_sort_key(item, selected),
    )[0]


def _replaceable_item_index(
    selected: Sequence[PlannedEvidenceItem],
    *,
    required_roles: Sequence[str],
) -> int | None:
    replaceable = [
        (index, item)
        for index, item in enumerate(selected)
        if not _selected_required_roles(item, required_roles=required_roles)
    ]
    if not replaceable:
        return None
    return sorted(
        replaceable,
        key=lambda pair: _replacement_sort_key(pair[1], selected),
    )[0][0]


def _selected_required_roles(
    item: PlannedEvidenceItem,
    *,
    required_roles: Sequence[str],
) -> tuple[str, ...]:
    return tuple(
        role
        for role in required_roles
        if _item_can_satisfy_required_role(item, role)
    )


def _item_can_satisfy_required_role(
    item: PlannedEvidenceItem,
    role: str,
) -> bool:
    if role == "temporal_support":
        return _candidate_has_temporal_support(item.candidate)
    if role in _TYPED_TEMPORAL_SUPPORT_ROLES:
        return _candidate_has_typed_temporal_support(item.candidate, role)
    if role == "contrast":
        return _candidate_has_contrast_support(item.candidate)
    if role in _NEGATIVE_ABSENCE_ROLES:
        return _candidate_has_negative_absence_support(item.candidate)
    if role == "bridge":
        return item.role == "bridge"
    if role == "location_support":
        return _candidate_has_location_support(item.candidate)
    if role == "value_support":
        return _candidate_has_value_support(item.candidate)
    if role == "count_support":
        return _candidate_has_count_support(item.candidate)
    if role == "list_support":
        return _candidate_has_list_support(item.candidate)
    if role == "preference_support":
        return _candidate_has_preference_support(item.candidate)
    if role == "visual_support":
        return _candidate_has_visual_support(item.candidate)
    if role == "emotion_response_support":
        return _candidate_has_emotion_response_support(item.candidate)
    if role == "symbolic_meaning_support":
        return _candidate_has_symbolic_meaning_support(item.candidate)
    if role == "event_support":
        return _candidate_has_event_support(item.candidate)
    if role == "communication_support":
        return _candidate_has_communication_support(item.candidate)
    if role == "exchange_support":
        return _candidate_has_exchange_support(item.candidate)
    if role == "inference_support":
        return _candidate_has_inference_support(item.candidate)
    if role == "causal_support":
        return _candidate_has_causal_support(item.candidate)
    if role in _TYPED_RELATION_SUPPORT_CATEGORIES:
        return _candidate_has_typed_relation_support(item.candidate, role)
    return item.role == role


def _required_role_candidate_sort_key(
    item: PlannedEvidenceItem,
    selected: Sequence[PlannedEvidenceItem] = (),
) -> tuple[float, ...]:
    return (
        *_source_overlap_selection_sort_key(item, selected),
        *_explicit_relation_role_sort_key(item),
        *_source_proximity_selection_sort_key(item, selected),
        *_person_grounding_selection_sort_key(item, selected),
        *_candidate_sort_key(item.candidate),
        _role_order(item),
    )


def _replacement_sort_key(
    item: PlannedEvidenceItem,
    selected: Sequence[PlannedEvidenceItem],
) -> tuple[float, ...]:
    other_required_terms = {
        term
        for other in selected
        if other is not item
        for term in other.candidate.required_terms
    }
    other_support_terms = {
        term
        for other in selected
        if other is not item
        for term in other.candidate.query_support_terms
        if str(term).strip()
    }
    unique_required_gain = len(
        item.candidate.required_terms.difference(other_required_terms)
    )
    unique_support_gain = len(
        set(item.candidate.query_support_terms).difference(other_support_terms)
    )
    return (
        _replacement_role_order(item),
        float(unique_required_gain),
        float(unique_support_gain),
        item.candidate.answerability_score,
        item.candidate.source_locality_score,
        item.candidate.bundle_strength_score,
        float(item.candidate.retrieval_order),
        float(item.candidate.rank),
    )


def _replacement_role_order(item: PlannedEvidenceItem) -> float:
    role_order = {
        "supporting": 0,
        "entity_disambiguation": 1,
        "causal_support": 2,
        "communication_support": 2,
        "event_support": 2,
        "exchange_support": 2,
        "inference_support": 2,
        "negative_support": 2,
        "emotion_response_support": 2,
        "symbolic_meaning_support": 2,
        "preference_support": 2,
        "temporal_support": 2,
        "duration_temporal_support": 2,
        "explicit_temporal_support": 2,
        "relative_temporal_support": 2,
        "temporal_sequence_support": 2,
        "visual_temporal_support": 2,
        "value_support": 2,
        "count_support": 2,
        "list_support": 2,
        "visual_support": 2,
        "contrast": 3,
        "bridge": 4,
        "location_support": 4,
        "primary": 5,
    }
    return float(role_order.get(item.role, 9))


def _candidate_has_temporal_support(candidate: EvidenceBundleCandidate) -> bool:
    if not _candidate_has_temporal_grounding(candidate):
        return False
    time_kind = str(candidate.time_intent_kind or "").strip()
    if time_kind == "duration":
        return candidate.has_duration_surface
    if time_kind == "temporal_sequence":
        return candidate.has_temporal_sequence_surface or candidate.has_sequence_surface
    if time_kind == "explicit_time":
        return candidate.has_explicit_time_content_surface
    if time_kind == "relative_time":
        return bool(
            candidate.has_relative_time_surface
            or candidate.currentness_surface
            or candidate.has_temporal_surface
        )
    return bool(
        candidate.has_temporal_surface
        or candidate.has_sequence_surface
        or candidate.has_duration_surface
        or candidate.has_relative_time_surface
        or candidate.has_explicit_time_content_surface
        or candidate.has_temporal_sequence_surface
        or candidate.currentness_surface
    )


def _typed_temporal_role_for_candidate(
    candidate: EvidenceBundleCandidate,
    *,
    required_roles: Sequence[str],
) -> str:
    required_role_set = set(required_roles)
    for role in sorted(_TYPED_TEMPORAL_SUPPORT_ROLES):
        if role in required_role_set and _candidate_has_typed_temporal_support(
            candidate,
            role,
        ):
            return role
    return ""


def _candidate_has_typed_temporal_support(
    candidate: EvidenceBundleCandidate,
    role: str,
) -> bool:
    if not _candidate_has_temporal_support(candidate):
        return False
    if role == "visual_temporal_support":
        return _candidate_has_visual_support(candidate)
    return _TEMPORAL_TIME_KIND_ROLES.get(str(candidate.time_intent_kind or "")) == role


def _candidate_has_temporal_grounding(candidate: EvidenceBundleCandidate) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if (
        _candidate_has_measured_weak_source_locality(candidate)
        and candidate.focused_evidence_score <= 0
    ):
        return False
    if candidate.answerability_score and candidate.answerability_score < 0.55:
        return False
    if candidate.query_has_entities and not (
        candidate.entity_hits or candidate.speaker_hits
    ):
        return False
    if candidate.query_has_entities and not _candidate_has_relation_or_answer_grounding(
        candidate
    ):
        return False
    return bool(
        candidate.entity_hits
        or candidate.speaker_hits
        or candidate.relation_hits
        or candidate.query_support_terms
        or candidate.direct_speaker_turn
        or candidate.focused_evidence_score > 0
    )


def _candidate_has_relation_or_answer_grounding(
    candidate: EvidenceBundleCandidate,
) -> bool:
    return bool(
        candidate.relation_hits
        or candidate.relation_category_hits
        or candidate.covered_expected_terms
        or candidate.covered_evidence_terms
        or candidate.has_preference_evidence
        or candidate.has_visual_evidence
        or candidate.exact_count_evidence
        or candidate.list_item_count > 0
        or candidate.covered_answer_unit_shapes
    )


def _candidate_has_contrast_support(candidate: EvidenceBundleCandidate) -> bool:
    if not _candidate_has_contrast_grounding(candidate):
        return False
    return bool(
        candidate.contrast_surface
        or (
            candidate.currentness_surface
            and (candidate.stale_surface or candidate.negation_surface)
        )
    )


def _candidate_has_contrast_grounding(candidate: EvidenceBundleCandidate) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if (
        _candidate_has_measured_weak_source_locality(candidate)
        and candidate.focused_evidence_score <= 0
    ):
        return False
    if candidate.answerability_score and candidate.answerability_score < 0.55:
        return False
    return not candidate.query_has_entities or bool(
        candidate.entity_hits or candidate.speaker_hits
    )


def _candidate_has_negative_absence_support(
    candidate: EvidenceBundleCandidate,
) -> bool:
    if not candidate.negation_surface:
        return False
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if _candidate_has_measured_weak_source_locality(candidate):
        return False
    if candidate.answerability_score and candidate.answerability_score < 0.55:
        return False
    if candidate.query_has_entities and not (
        candidate.entity_hits or candidate.speaker_hits
    ):
        return False
    return bool(
        candidate.direct_speaker_turn
        or candidate.focused_evidence_score > 0
        or candidate.relation_hits
        or candidate.relation_category_hits
        or candidate.query_support_terms
        or candidate.entity_hits
        or candidate.speaker_hits
        or candidate.source_refs
    )


def _candidate_has_location_support(candidate: EvidenceBundleCandidate) -> bool:
    if not _candidate_has_typed_relation_grounding(candidate):
        return False
    return "location_transition" in set(candidate.relation_category_hits)


def _candidate_has_value_support(candidate: EvidenceBundleCandidate) -> bool:
    if not _candidate_has_answer_unit_support_grounding(candidate):
        return False
    return "quantity_dollar" in set(candidate.covered_answer_unit_shapes)


def _candidate_has_count_support(candidate: EvidenceBundleCandidate) -> bool:
    if not _candidate_has_answer_unit_support_grounding(candidate):
        return False
    return candidate.exact_count_evidence or candidate.list_item_count >= 2


def _candidate_has_list_support(candidate: EvidenceBundleCandidate) -> bool:
    if not _candidate_has_answer_unit_support_grounding(candidate):
        return False
    return candidate.list_item_count >= 2


def _candidate_has_answer_unit_support_grounding(
    candidate: EvidenceBundleCandidate,
) -> bool:
    if not _candidate_has_typed_relation_grounding(candidate):
        return False
    return bool(
        candidate.source_refs
        or _candidate_turn_refs(candidate)
        or candidate.direct_speaker_turn
        or candidate.focused_evidence_score > 0
        or candidate.relation_hits
        or candidate.relation_category_hits
        or candidate.entity_hits
        or candidate.speaker_hits
    )


def _candidate_has_preference_support(candidate: EvidenceBundleCandidate) -> bool:
    if not _candidate_has_typed_relation_grounding(candidate):
        return False
    return bool(
        candidate.has_preference_evidence
        or "preference" in set(candidate.relation_category_hits)
    )


def _candidate_has_favorite_support(candidate: EvidenceBundleCandidate) -> bool:
    if not _candidate_has_typed_relation_grounding(candidate):
        return False
    return "favorite_preference" in set(candidate.relation_category_hits)


def _candidate_has_visual_support(candidate: EvidenceBundleCandidate) -> bool:
    if not _candidate_has_typed_relation_grounding(candidate):
        return False
    return bool(
        candidate.has_visual_evidence
        or "visual" in set(candidate.relation_category_hits)
    )


def _candidate_has_emotion_response_support(
    candidate: EvidenceBundleCandidate,
) -> bool:
    if not _candidate_has_typed_relation_grounding(candidate):
        return False
    return "emotion_response" in set(candidate.relation_category_hits)


def _candidate_has_symbolic_meaning_support(
    candidate: EvidenceBundleCandidate,
) -> bool:
    if not _candidate_has_typed_relation_grounding(candidate):
        return False
    return "symbolic_meaning" in set(candidate.relation_category_hits)


def _candidate_has_event_support(candidate: EvidenceBundleCandidate) -> bool:
    if not _candidate_has_typed_relation_grounding(candidate):
        return False
    return bool(
        {"registration_event", "participation_event"}
        & set(candidate.relation_category_hits)
    )


def _candidate_has_communication_support(candidate: EvidenceBundleCandidate) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if _candidate_has_measured_weak_source_locality(candidate):
        return False
    if candidate.answerability_score and candidate.answerability_score < 0.55:
        return False
    if candidate.query_has_entities and not candidate.speaker_hits:
        return False
    if not (candidate.speaker_hits or candidate.direct_speaker_turn):
        return False
    return "communication" in set(candidate.relation_category_hits)


def _candidate_has_exchange_support(candidate: EvidenceBundleCandidate) -> bool:
    if not _candidate_has_typed_relation_grounding(candidate):
        return False
    return "exchange" in set(candidate.relation_category_hits)


def _candidate_has_typed_relation_grounding(
    candidate: EvidenceBundleCandidate,
) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if _candidate_has_measured_weak_source_locality(candidate):
        return False
    if candidate.answerability_score and candidate.answerability_score < 0.55:
        return False
    if not candidate.query_has_entities:
        return True
    return bool(candidate.entity_hits or candidate.speaker_hits)


def _candidate_has_inference_support(candidate: EvidenceBundleCandidate) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if not (candidate.entity_hits or candidate.speaker_hits):
        return False
    if _candidate_has_measured_weak_source_locality(candidate):
        return False
    if candidate.answerability_score and candidate.answerability_score < 0.55:
        return False
    return bool(candidate.relation_hits or candidate.relation_category_hits)


def _candidate_has_causal_support(candidate: EvidenceBundleCandidate) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if not (candidate.entity_hits or candidate.speaker_hits):
        return False
    if _candidate_has_measured_weak_source_locality(candidate):
        return False
    if candidate.answerability_score and candidate.answerability_score < 0.55:
        return False
    if "causal" in set(candidate.relation_category_hits):
        return True
    causal_terms = {
        "because",
        "cause",
        "caused",
        "choose",
        "chose",
        "decision",
        "feel",
        "fit",
        "reason",
        "realize",
        "realized",
        "reaction",
        "response",
        "spoke",
        "think",
        "thought",
        "value",
    }
    return bool(causal_terms.intersection(candidate.relation_hits))


def _candidate_has_typed_relation_support(
    candidate: EvidenceBundleCandidate,
    role: str,
) -> bool:
    required_categories = _TYPED_RELATION_SUPPORT_CATEGORIES.get(role)
    if not required_categories:
        return False
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if role == "support_goal_support" and not (
        candidate.relation_category_hits or candidate.entity_hits or candidate.speaker_hits
    ):
        support_terms = set(candidate.query_support_terms)
        return bool(
            "support" in support_terms
            and {"adoption", "agency", "individual", "help"} & support_terms
        )
    if not (candidate.entity_hits or candidate.speaker_hits):
        return False
    if _candidate_has_measured_weak_source_locality(candidate):
        return False
    if candidate.answerability_score and candidate.answerability_score < 0.55:
        return False
    return bool(required_categories.intersection(candidate.relation_category_hits))


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


def _avg_positive_scores(scores: Sequence[float]) -> float:
    measured = [score for score in scores if score > 0]
    if not measured:
        return 0.0
    return sum(measured) / len(measured)


def _selection_has_bridge_support(selected: Sequence[PlannedEvidenceItem]) -> bool:
    if len(selected) < 2:
        return False
    if not any(item.role == "primary" for item in selected):
        return False
    return any(_candidate_has_bridge_grounding(item.candidate) for item in selected)


def _primary_candidate_eligible(candidate: EvidenceBundleCandidate) -> bool:
    if candidate.conflict_or_stale:
        return False
    if candidate.primary_signal:
        return True
    if candidate.broad_summary:
        return False
    if not candidate.direct_speaker_turn:
        return False
    if _candidate_has_measured_source_locality_below(candidate, 0.65):
        return False
    if _candidate_has_measured_answerability_below(candidate, 0.75):
        return False
    return bool(
        candidate.query_support_terms
        or candidate.relation_hits
        or candidate.entity_hits
        or candidate.speaker_hits
    )


def _candidate_has_obsolete_primary_surface(
    candidate: EvidenceBundleCandidate,
) -> bool:
    return bool(
        candidate.stale_surface
        and not candidate.currentness_surface
        and not candidate.contrast_surface
    )


def _retrieval_source_keys(candidate: EvidenceBundleCandidate) -> tuple[str, ...]:
    if candidate.retrieval_sources:
        return tuple(
            dict.fromkeys(
                source
                for source in candidate.retrieval_sources
                if str(source).strip()
            )
        )
    source_types = _source_type_keys(candidate)
    if source_types:
        return tuple(f"source_type:{source_type}" for source_type in source_types)
    return (f"source_type:{candidate.source_type}",)


def _source_type_keys(candidate: EvidenceBundleCandidate) -> tuple[str, ...]:
    values = candidate.source_types or (candidate.source_type,)
    return tuple(
        dict.fromkeys(
            value
            for value in values
            if str(value).strip() and str(value).strip() != "unknown"
        )
    )


def _source_ref_overlap_keys(candidate: EvidenceBundleCandidate) -> tuple[str, ...]:
    return _candidate_turn_ref_strings(candidate)


def _reason_codes(
    candidate: EvidenceBundleCandidate,
    *,
    role: BundleRole,
    case_group: str,
) -> tuple[str, ...]:
    reasons: list[str] = [f"role:{role}"]
    if candidate.primary_signal:
        reasons.append("primary_signal")
    elif role == "primary":
        reasons.append("answerable_direct_primary")
    if candidate.covered_expected_terms:
        reasons.append("expected_terms")
    if candidate.covered_evidence_terms:
        reasons.append("evidence_terms")
    if candidate.query_support_terms:
        reasons.append("query_support")
    if _candidate_has_answer_evidence(candidate):
        reasons.append("answer_evidence")
    if candidate.bridge_query_hit:
        reasons.append("bridge_query_hit")
    if role == "bridge":
        reasons.append("multi_hop_bridge")
        if candidate.relation_hits:
            reasons.append("bridge_relation_hits")
        if candidate.entity_hits or candidate.speaker_hits:
            reasons.append("bridge_entity_hits")
    if role == "inference_support":
        reasons.append("inference_support")
        if candidate.relation_hits:
            reasons.append("inference_relation_hits")
        if candidate.relation_category_hits:
            reasons.append("inference_relation_category_hits")
        if candidate.entity_hits or candidate.speaker_hits:
            reasons.append("inference_entity_hits")
    if role == "causal_support":
        reasons.append("causal_support")
        if candidate.relation_hits:
            reasons.append("causal_relation_hits")
        if candidate.relation_category_hits:
            reasons.append("causal_relation_category_hits")
        if candidate.entity_hits or candidate.speaker_hits:
            reasons.append("causal_entity_hits")
    if role == "location_support":
        reasons.append("location_support")
        if candidate.relation_category_hits:
            reasons.append("location_relation_category_hits")
        if candidate.relation_hits:
            reasons.append("location_relation_hits")
    if role == "negative_support":
        reasons.append("negative_absence_support")
    if role == "preference_support":
        reasons.append("preference_support")
        if candidate.has_preference_evidence:
            reasons.append("preference_evidence")
        if candidate.relation_category_hits:
            reasons.append("preference_relation_category_hits")
    if role == "visual_support":
        reasons.append("visual_support")
        if candidate.has_visual_evidence:
            reasons.append("visual_evidence")
        if candidate.relation_category_hits:
            reasons.append("visual_relation_category_hits")
    if role == "emotion_response_support":
        reasons.append("emotion_response_support")
        if candidate.relation_category_hits:
            reasons.append("emotion_response_relation_category_hits")
    if role == "symbolic_meaning_support":
        reasons.append("symbolic_meaning_support")
        if candidate.relation_category_hits:
            reasons.append("symbolic_meaning_relation_category_hits")
    if role == "event_support":
        reasons.append("event_support")
        if candidate.relation_category_hits:
            reasons.append("event_relation_category_hits")
    if role == "communication_support":
        reasons.append("communication_support")
        if candidate.relation_category_hits:
            reasons.append("communication_relation_category_hits")
        if candidate.speaker_hits:
            reasons.append("communication_speaker_hits")
        if candidate.direct_speaker_turn:
            reasons.append("communication_direct_speaker_turn")
    if role == "exchange_support":
        reasons.append("exchange_support")
        if candidate.relation_category_hits:
            reasons.append("exchange_relation_category_hits")
        if candidate.relation_hits:
            reasons.append("exchange_relation_hits")
    if role in _TYPED_RELATION_SUPPORT_CATEGORIES:
        reasons.append(role)
        if candidate.relation_category_hits:
            reasons.append("typed_relation_category_hits")
    if role in _TYPED_TEMPORAL_SUPPORT_ROLES:
        reasons.append("temporal_support")
        reasons.append(role)
    if candidate.focused_evidence_score > 0:
        reasons.append("focused_turn")
    if candidate.answerability_score >= 0.8:
        reasons.append("high_answerability")
    elif candidate.answerability_score >= 0.55:
        reasons.append("medium_answerability")
    if candidate.direct_speaker_turn:
        reasons.append("direct_speaker_turn")
    if candidate.broad_summary:
        reasons.append("broad_summary")
    if candidate.has_temporal_surface:
        reasons.append("temporal_surface")
    if candidate.has_sequence_surface:
        reasons.append("sequence_surface")
    if candidate.has_duration_surface:
        reasons.append("duration_surface")
    if candidate.has_relative_time_surface:
        reasons.append("relative_time_surface")
    if candidate.has_explicit_time_surface:
        reasons.append("explicit_time_surface")
    if candidate.has_explicit_time_content_surface:
        reasons.append("explicit_time_content_surface")
    if candidate.has_temporal_sequence_surface:
        reasons.append("temporal_sequence_surface")
    if candidate.conflict_or_stale:
        reasons.append("conflict_or_stale")
    if candidate.negation_surface:
        reasons.append("negation_surface")
    if candidate.currentness_surface:
        reasons.append("currentness_surface")
    if candidate.stale_surface:
        reasons.append("stale_surface")
    if candidate.contrast_surface:
        reasons.append("contrast_surface")
    if candidate.entity_hits:
        reasons.append("entity_hits")
    if candidate.speaker_hits:
        reasons.append("speaker_hits")
    if case_group:
        reasons.append(f"case_group:{case_group}")
    return tuple(reasons)


def _planned_sort_key(item: PlannedEvidenceItem) -> tuple[float, ...]:
    return (
        _role_order(item),
        *_candidate_sort_key(item.candidate),
    )


def _role_order(item: PlannedEvidenceItem) -> float:
    role_order = {
        "primary": 0,
        "bridge": 1,
        "contrast": 2,
        "negative_support": 3,
        "location_support": 3,
        "communication_support": 3,
        "event_support": 3,
        "exchange_support": 3,
        "emotion_response_support": 3,
        "symbolic_meaning_support": 3,
        "preference_support": 3,
        "temporal_support": 3,
        "duration_temporal_support": 3,
        "explicit_temporal_support": 3,
        "relative_temporal_support": 3,
        "temporal_sequence_support": 3,
        "visual_temporal_support": 3,
        "value_support": 3,
        "count_support": 3,
        "list_support": 3,
        "visual_support": 3,
        "causal_support": 4,
        "inference_support": 4,
        "entity_disambiguation": 5,
        "supporting": 5,
    }
    if item.role in _TYPED_RELATION_SUPPORT_CATEGORIES:
        return 3.0
    return float(role_order.get(item.role, 9))


def _planned_coverage_sort_key(
    item: PlannedEvidenceItem,
    *,
    covered_terms: set[str],
    covered_support_terms: set[str],
    selected: Sequence[PlannedEvidenceItem] = (),
) -> tuple[float, ...]:
    required_gain = len(item.candidate.required_terms.difference(covered_terms))
    support_gain = len(
        set(item.candidate.query_support_terms).difference(covered_support_terms)
    )
    return (
        _role_order(item),
        -float(required_gain),
        *_source_overlap_selection_sort_key(item, selected),
        *_source_ref_compactness_selection_sort_key(item),
        float(_answer_evidence_sort_bucket(item.candidate)),
        *_explicit_relation_role_sort_key(item),
        *_source_proximity_selection_sort_key(item, selected),
        *_person_grounding_selection_sort_key(item, selected),
        *_selection_precision_sort_key(item),
        -float(support_gain),
        *_candidate_sort_key(item.candidate),
    )


def _source_overlap_selection_sort_key(
    item: PlannedEvidenceItem,
    selected: Sequence[PlannedEvidenceItem],
) -> tuple[float]:
    if item.role == "primary" or not selected:
        return (0.0,)
    item_turn_refs = set(_candidate_turn_ref_strings(item.candidate))
    if not item_turn_refs:
        return (0.0,)
    selected_turn_refs = {
        turn_ref
        for selected_item in selected
        for turn_ref in _candidate_turn_ref_strings(selected_item.candidate)
    }
    return (1.0 if item_turn_refs.intersection(selected_turn_refs) else 0.0,)


def _source_proximity_selection_sort_key(
    item: PlannedEvidenceItem,
    selected: Sequence[PlannedEvidenceItem],
) -> tuple[float, float]:
    if item.role == "primary":
        return (1.0, float("inf"))
    if not _candidate_has_source_proximity_diagnostic_support(item.candidate):
        return (1.0, float("inf"))
    selected_turn_refs = tuple(
        turn_ref
        for selected_item in selected
        if _candidate_has_source_proximity_diagnostic_support(
            selected_item.candidate
        )
        for turn_ref in _candidate_turn_refs(selected_item.candidate)
    )
    if not selected_turn_refs:
        return (1.0, float("inf"))
    closest_distance = _closest_turn_ref_distance(
        item.candidate,
        comparison_turn_refs=selected_turn_refs,
    )
    if closest_distance is None or closest_distance > _SOURCE_PROXIMITY_WINDOW:
        return (1.0, float("inf"))
    return (0.0, float(closest_distance))


def _person_grounding_selection_sort_key(
    item: PlannedEvidenceItem,
    selected: Sequence[PlannedEvidenceItem],
) -> tuple[float, float]:
    if item.role == "primary" or not selected:
        return (0.0, 0.0)
    selected_terms = {
        term
        for selected_item in selected
        for term in _candidate_person_grounding_terms(selected_item.candidate)
    }
    if not selected_terms:
        return (1.0, 0.0)
    candidate_terms = set(_candidate_person_grounding_terms(item.candidate))
    if not candidate_terms:
        return (1.0, 0.0)
    overlap_count = len(candidate_terms.intersection(selected_terms))
    if _candidate_prefers_distinct_person_grounding(item.candidate):
        new_count = len(candidate_terms.difference(selected_terms))
        if new_count:
            return (0.0, -float(new_count))
        if overlap_count:
            return (1.0, -float(overlap_count))
        return (2.0, 0.0)
    if overlap_count:
        return (0.0, -float(overlap_count))
    return (2.0, 0.0)


def _candidate_prefers_distinct_person_grounding(
    candidate: EvidenceBundleCandidate,
) -> bool:
    if candidate.query_has_entities:
        return False
    return bool(candidate.entity_hits or candidate.speaker_hits)


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


def _source_ref_compactness_selection_sort_key(
    item: PlannedEvidenceItem,
) -> tuple[float, float, float]:
    if item.role == "primary":
        return (0.0, 0.0, 0.0)
    turn_refs = _candidate_turn_refs(item.candidate)
    if not turn_refs:
        return (0.0, 0.0, 0.0)
    if not _candidate_has_diffuse_source_refs(item.candidate):
        return (0.0, 0.0, 0.0)
    return (
        1.0,
        float(_turn_ref_span(turn_refs)),
        float(len(turn_refs)),
    )


def _selection_precision_sort_key(item: PlannedEvidenceItem) -> tuple[float, ...]:
    candidate = item.candidate
    return (
        float(_answer_evidence_sort_bucket(candidate)),
        1.0 if _candidate_has_noisy_source_overlap_risk(candidate) else 0.0,
        1.0 if _candidate_has_diffuse_source_refs(candidate) else 0.0,
        1.0 if _candidate_has_measured_answerability_below(candidate, 0.75) else 0.0,
        -candidate.answerability_score if candidate.answerability_score > 0 else 0.0,
        (
            -candidate.source_locality_score
            if candidate.source_locality_score > 0
            else 0.0
        ),
    )


def _explicit_relation_role_sort_key(item: PlannedEvidenceItem) -> tuple[float]:
    return (
        0.0 if _item_has_explicit_relation_or_role_grounding(item) else 1.0,
    )


def _item_has_explicit_relation_or_role_grounding(
    item: PlannedEvidenceItem,
) -> bool:
    candidate = item.candidate
    if candidate.relation_hits or candidate.relation_category_hits:
        return True
    if item.role == "temporal_support":
        return _candidate_has_temporal_support(candidate)
    if item.role == "contrast":
        return _candidate_has_contrast_support(candidate)
    if item.role == "negative_support":
        return _candidate_has_negative_absence_support(candidate)
    if item.role in _PREDICATE_REQUIRED_ROLES:
        return _item_can_satisfy_required_role(item, item.role)
    return False


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


def _max_item_drop_counts(
    remaining: Sequence[PlannedEvidenceItem],
    *,
    source_type_counts: Counter[str],
    retrieval_source_counts: Counter[str],
    max_items_per_source_type: int,
    max_items_per_retrieval_source: int,
) -> tuple[int, int, int]:
    source_type_drops = 0
    retrieval_source_drops = 0
    for item in remaining:
        if item.role in _DIVERSITY_EXEMPT_ROLES:
            continue
        if any(
            source_type_counts[source_type] >= max_items_per_source_type
            for source_type in _source_type_keys(item.candidate)
        ):
            source_type_drops += 1
        if any(
            retrieval_source_counts[source] >= max_items_per_retrieval_source
            for source in _retrieval_source_keys(item.candidate)
        ):
            retrieval_source_drops += 1
    return len(remaining), source_type_drops, retrieval_source_drops


def _bundle_quality_diagnostics(
    items: Sequence[PlannedEvidenceItem],
    *,
    missing_required_roles: Sequence[str] = (),
) -> dict[str, object]:
    missing_roles = tuple(
        dict.fromkeys(role for role in missing_required_roles if str(role).strip())
    )
    if not items:
        return {
            "schema_version": "evidence_bundle_quality.v1",
            "confidence_score": 0.0,
            "confidence_band": "none",
            "component_scores": {},
            "risk_penalty": 0.0,
            "reason_codes": ["empty_bundle"],
            "selected_item_count": 0,
            "primary_count": 0,
            "supporting_count": 0,
            "focused_item_count": 0,
            "direct_speaker_count": 0,
            "source_ref_item_count": 0,
            "source_ref_support_item_count": 0,
            "source_ref_support_ref_count": 0,
            "source_identity_item_count": 0,
            "source_identity_ref_count": 0,
            "source_identity_support_item_count": 0,
            "source_identity_support_ref_count": 0,
            "source_type_diversity": 0,
            "retrieval_source_diversity": 0,
            "source_type_support_diversity": 0,
            "retrieval_source_support_diversity": 0,
            "low_answerability_count": 0,
            "measured_answerability_count": 0,
            "unmeasured_answerability_count": 0,
            "average_measured_answerability_score": 0.0,
            "measured_source_locality_count": 0,
            "unmeasured_source_locality_count": 0,
            "average_measured_source_locality_score": 0.0,
            "bridge_count": 0,
            "bridge_query_hit_count": 0,
            "person_grounding_item_count": 0,
            "person_grounding_ref_count": 0,
            "distinct_person_grounding_count": 0,
            "repeated_person_grounding_count": 0,
            "causal_support_count": 0,
            "communication_support_count": 0,
            "event_support_count": 0,
            "exchange_support_count": 0,
            "inference_support_count": 0,
            "location_support_count": 0,
            "emotion_response_support_count": 0,
            "symbolic_meaning_support_count": 0,
            "preference_support_count": 0,
            "favorite_support_count": 0,
            "visual_support_count": 0,
            "typed_relation_support_count": 0,
            "typed_relation_support_counts": {},
            "partial_required_role_support_count": 0,
            "partial_required_role_support_counts": {},
            "location_relation_category_hit_count": 0,
            "source_proximity_support_count": 0,
            "source_chain_proximity_support_count": 0,
            "source_proximity_closest_distance": None,
            "source_chain_proximity_closest_distance": None,
            "source_proximity_distance_counts": {},
            "source_chain_proximity_distance_counts": {},
            "source_proximity_window": _SOURCE_PROXIMITY_WINDOW,
            "diffuse_source_ref_count": 0,
            "missing_required_role_count": len(missing_roles),
            "missing_required_roles": list(missing_roles),
            "contrast_count": 0,
            "negative_absence_support_count": 0,
            "contrast_surface_count": 0,
            "negation_surface_count": 0,
            "currentness_surface_count": 0,
            "stale_surface_count": 0,
            "broad_summary_count": 0,
            "conflict_or_stale_count": 0,
        }

    primary_count = sum(1 for item in items if item.role == "primary")
    supporting_count = sum(1 for item in items if item.role != "primary")
    focused_count = sum(
        1 for item in items if item.candidate.focused_evidence_score > 0
    )
    direct_speaker_count = sum(1 for item in items if item.candidate.direct_speaker_turn)
    source_ref_item_count = sum(1 for item in items if item.candidate.source_refs)
    source_ref_support_item_count = sum(
        1
        for item in items
        if item.candidate.source_refs
        and _candidate_has_source_identity_quality_support(item.candidate)
    )
    source_ref_support_ref_count = sum(
        len(item.candidate.source_refs)
        for item in items
        if item.candidate.source_refs
        and _candidate_has_source_identity_quality_support(item.candidate)
    )
    source_identity_refs = tuple(_source_identity_refs(item.candidate) for item in items)
    source_identity_item_count = sum(1 for refs in source_identity_refs if refs)
    source_identity_ref_count = sum(len(refs) for refs in source_identity_refs)
    source_identity_support_refs = tuple(
        refs
        for item, refs in zip(items, source_identity_refs, strict=False)
        if refs and _candidate_has_source_identity_quality_support(item.candidate)
    )
    source_identity_support_item_count = len(source_identity_support_refs)
    source_identity_support_ref_count = sum(
        len(refs) for refs in source_identity_support_refs
    )
    source_types = {
        source_type
        for item in items
        for source_type in _source_type_keys(item.candidate)
    }
    retrieval_sources = {
        source for item in items for source in _retrieval_source_keys(item.candidate)
    }
    source_type_supports = {
        source_type
        for item in items
        if _candidate_has_source_identity_quality_support(item.candidate)
        for source_type in _source_type_keys(item.candidate)
    }
    retrieval_source_supports = {
        source
        for item in items
        if _candidate_has_source_identity_quality_support(item.candidate)
        for source in _retrieval_source_keys(item.candidate)
    }
    answerability_scores = [item.candidate.answerability_score for item in items]
    avg_answerability = sum(answerability_scores) / len(answerability_scores)
    measured_answerability_scores = [
        score for score in answerability_scores if score > 0
    ]
    avg_measured_answerability = _avg_positive_scores(answerability_scores)
    max_answerability = max(answerability_scores)
    low_answerability_count = sum(
        _is_measured_low_answerability(score) for score in answerability_scores
    )
    unmeasured_answerability_count = sum(
        1 for score in answerability_scores if score <= 0
    )
    source_locality_scores = [item.candidate.source_locality_score for item in items]
    measured_source_locality_scores = [
        score for score in source_locality_scores if score > 0
    ]
    avg_measured_source_locality = _avg_positive_scores(source_locality_scores)
    unmeasured_source_locality_count = sum(
        1 for score in source_locality_scores if score <= 0
    )
    bridge_count = sum(1 for item in items if item.role == "bridge")
    bridge_query_hit_count = sum(1 for item in items if item.candidate.bridge_query_hit)
    person_grounding_terms_by_item = tuple(
        _candidate_person_grounding_terms(item.candidate) for item in items
    )
    person_grounding_item_count = sum(
        1 for terms in person_grounding_terms_by_item if terms
    )
    person_grounding_ref_count = sum(
        len(terms) for terms in person_grounding_terms_by_item
    )
    distinct_person_grounding_terms = tuple(
        dict.fromkeys(
            term for terms in person_grounding_terms_by_item for term in terms
        )
    )
    distinct_person_grounding_count = len(distinct_person_grounding_terms)
    repeated_person_grounding_count = max(
        0,
        person_grounding_ref_count - distinct_person_grounding_count,
    )
    causal_support_count = sum(1 for item in items if item.role == "causal_support")
    communication_support_count = sum(
        1 for item in items if item.role == "communication_support"
    )
    event_support_count = sum(1 for item in items if item.role == "event_support")
    exchange_support_count = sum(1 for item in items if item.role == "exchange_support")
    inference_support_count = sum(
        1 for item in items if item.role == "inference_support"
    )
    location_support_count = sum(1 for item in items if item.role == "location_support")
    emotion_response_support_count = sum(
        1 for item in items if item.role == "emotion_response_support"
    )
    symbolic_meaning_support_count = sum(
        1 for item in items if item.role == "symbolic_meaning_support"
    )
    preference_support_count = sum(
        1 for item in items if item.role == "preference_support"
    )
    favorite_support_count = sum(1 for item in items if item.role == "favorite_support")
    visual_support_count = sum(1 for item in items if item.role == "visual_support")
    typed_relation_support_counts = Counter(
        item.role for item in items if item.role in _TYPED_RELATION_SUPPORT_CATEGORIES
    )
    typed_relation_support_count = sum(typed_relation_support_counts.values())
    typed_relation_quality_count = (
        typed_relation_support_count - favorite_support_count
    )
    partial_required_role_support_counts = Counter(
        role
        for role in missing_roles
        for item in items
        if _item_has_partial_required_role_support(item, role)
    )
    partial_required_role_support_count = sum(
        partial_required_role_support_counts.values()
    )
    location_relation_category_hit_count = sum(
        1
        for item in items
        if "location_transition" in set(item.candidate.relation_category_hits)
    )
    source_proximity_distances = _source_proximity_distances(
        items,
        missing_required_roles=missing_roles,
    )
    source_proximity_support_count = len(source_proximity_distances)
    source_chain_proximity_distances = _source_chain_proximity_distances(items)
    source_chain_proximity_support_count = len(source_chain_proximity_distances)
    diffuse_source_ref_count = sum(
        1 for item in items if _candidate_has_diffuse_source_refs(item.candidate)
    )
    contrast_count = sum(
        1 for item in items if _candidate_has_contrast_support(item.candidate)
    )
    negative_absence_support_count = sum(
        1
        for item in items
        if _candidate_has_negative_absence_support(item.candidate)
    )
    contrast_surface_count = sum(1 for item in items if item.candidate.contrast_surface)
    negation_surface_count = sum(1 for item in items if item.candidate.negation_surface)
    currentness_surface_count = sum(
        1 for item in items if item.candidate.currentness_surface
    )
    stale_surface_count = sum(1 for item in items if item.candidate.stale_surface)
    broad_summary_count = sum(1 for item in items if item.candidate.broad_summary)
    conflict_or_stale_count = sum(
        1 for item in items if item.candidate.conflict_or_stale
    )

    component_scores = {
        "primary": 0.18 if primary_count else 0.0,
        "supporting": min(0.14, 0.07 * supporting_count),
        "focused_or_direct": min(
            0.16,
            (0.08 * focused_count) + (0.08 * direct_speaker_count),
        ),
        "source_refs": min(0.16, 0.08 * source_identity_support_item_count),
        "source_diversity": (
            (0.06 if len(source_type_supports) >= 2 else 0.0)
            + (0.06 if len(retrieval_source_supports) >= 2 else 0.0)
        ),
        "answerability": min(
            0.24,
            (0.14 * max_answerability) + (0.10 * avg_answerability),
        ),
        "bridge_support": min(0.1, 0.1 * bridge_count),
        "causal_support": min(0.08, 0.08 * causal_support_count),
        "communication_support": min(0.08, 0.08 * communication_support_count),
        "event_support": min(0.08, 0.08 * event_support_count),
        "exchange_support": min(0.08, 0.08 * exchange_support_count),
        "inference_support": min(0.08, 0.08 * inference_support_count),
        "location_support": min(0.08, 0.08 * location_support_count),
        "emotion_response_support": min(0.08, 0.08 * emotion_response_support_count),
        "symbolic_meaning_support": min(
            0.08,
            0.08 * symbolic_meaning_support_count,
        ),
        "preference_support": min(0.08, 0.08 * preference_support_count),
        "favorite_support": min(0.08, 0.08 * favorite_support_count),
        "typed_relation_support": min(0.08, 0.08 * typed_relation_quality_count),
        "visual_support": min(0.08, 0.08 * visual_support_count),
        "negative_absence_support": min(
            0.08,
            0.08 * negative_absence_support_count,
        ),
        "source_proximity": (
            min(0.06, 0.03 * source_proximity_support_count)
            if not missing_roles
            else 0.0
        ),
        "contrast_support": min(0.08, 0.08 * contrast_count),
    }
    risk_penalty = min(
        0.48,
        (0.08 * low_answerability_count)
        + (0.05 * broad_summary_count)
        + (0.04 * diffuse_source_ref_count)
        + (0.08 * conflict_or_stale_count)
        + (0.08 if broad_summary_count == len(items) else 0.0)
        + (0.08 if conflict_or_stale_count == len(items) else 0.0)
        + min(0.3, 0.18 * len(missing_roles)),
    )
    confidence_score = round(
        max(0.0, min(1.0, sum(component_scores.values()) - risk_penalty)),
        6,
    )
    return {
        "schema_version": "evidence_bundle_quality.v1",
        "confidence_score": confidence_score,
        "confidence_band": _confidence_band(confidence_score),
        "component_scores": {
            key: round(value, 6) for key, value in sorted(component_scores.items())
        },
        "risk_penalty": round(risk_penalty, 6),
        "reason_codes": _bundle_quality_reason_codes(
            primary_count=primary_count,
            supporting_count=supporting_count,
            focused_count=focused_count,
            direct_speaker_count=direct_speaker_count,
            source_ref_item_count=source_ref_item_count,
            source_ref_support_item_count=source_ref_support_item_count,
            source_identity_item_count=source_identity_item_count,
            source_identity_support_item_count=source_identity_support_item_count,
            source_type_diversity=len(source_types),
            retrieval_source_diversity=len(retrieval_sources),
            source_type_support_diversity=len(source_type_supports),
            retrieval_source_support_diversity=len(retrieval_source_supports),
            max_answerability=max_answerability,
            low_answerability_count=low_answerability_count,
            bridge_count=bridge_count,
            distinct_person_grounding_count=distinct_person_grounding_count,
            causal_support_count=causal_support_count,
            communication_support_count=communication_support_count,
            event_support_count=event_support_count,
            exchange_support_count=exchange_support_count,
            inference_support_count=inference_support_count,
            location_support_count=location_support_count,
            emotion_response_support_count=emotion_response_support_count,
            symbolic_meaning_support_count=symbolic_meaning_support_count,
            preference_support_count=preference_support_count,
            favorite_support_count=favorite_support_count,
            visual_support_count=visual_support_count,
            typed_relation_support_counts=typed_relation_support_counts,
            partial_required_role_support_counts=(
                partial_required_role_support_counts
            ),
            location_relation_category_hit_count=location_relation_category_hit_count,
            source_proximity_support_count=source_proximity_support_count,
            source_chain_proximity_support_count=(
                source_chain_proximity_support_count
            ),
            missing_required_roles=missing_roles,
            contrast_count=contrast_count,
            negative_absence_support_count=negative_absence_support_count,
            contrast_surface_count=contrast_surface_count,
            negation_surface_count=negation_surface_count,
            currentness_surface_count=currentness_surface_count,
            stale_surface_count=stale_surface_count,
            broad_summary_count=broad_summary_count,
            diffuse_source_ref_count=diffuse_source_ref_count,
            conflict_or_stale_count=conflict_or_stale_count,
            selected_item_count=len(items),
        ),
        "selected_item_count": len(items),
        "primary_count": primary_count,
        "supporting_count": supporting_count,
        "focused_item_count": focused_count,
        "direct_speaker_count": direct_speaker_count,
        "source_ref_item_count": source_ref_item_count,
        "source_ref_support_item_count": source_ref_support_item_count,
        "source_ref_support_ref_count": source_ref_support_ref_count,
        "source_identity_item_count": source_identity_item_count,
        "source_identity_ref_count": source_identity_ref_count,
        "source_identity_support_item_count": source_identity_support_item_count,
        "source_identity_support_ref_count": source_identity_support_ref_count,
        "source_type_diversity": len(source_types),
        "retrieval_source_diversity": len(retrieval_sources),
        "source_type_support_diversity": len(source_type_supports),
        "retrieval_source_support_diversity": len(retrieval_source_supports),
        "average_answerability_score": round(avg_answerability, 6),
        "average_measured_answerability_score": round(
            avg_measured_answerability,
            6,
        ),
        "max_answerability_score": round(max_answerability, 6),
        "low_answerability_count": low_answerability_count,
        "measured_answerability_count": len(measured_answerability_scores),
        "unmeasured_answerability_count": unmeasured_answerability_count,
        "average_measured_source_locality_score": round(
            avg_measured_source_locality,
            6,
        ),
        "measured_source_locality_count": len(measured_source_locality_scores),
        "unmeasured_source_locality_count": unmeasured_source_locality_count,
        "bridge_count": bridge_count,
        "bridge_query_hit_count": bridge_query_hit_count,
        "person_grounding_item_count": person_grounding_item_count,
        "person_grounding_ref_count": person_grounding_ref_count,
        "distinct_person_grounding_count": distinct_person_grounding_count,
        "repeated_person_grounding_count": repeated_person_grounding_count,
        "causal_support_count": causal_support_count,
        "communication_support_count": communication_support_count,
        "event_support_count": event_support_count,
        "exchange_support_count": exchange_support_count,
        "inference_support_count": inference_support_count,
        "location_support_count": location_support_count,
        "emotion_response_support_count": emotion_response_support_count,
        "symbolic_meaning_support_count": symbolic_meaning_support_count,
        "preference_support_count": preference_support_count,
        "favorite_support_count": favorite_support_count,
        "visual_support_count": visual_support_count,
        "typed_relation_support_count": typed_relation_support_count,
        "typed_relation_support_counts": dict(
            sorted(typed_relation_support_counts.items())
        ),
        "partial_required_role_support_count": partial_required_role_support_count,
        "partial_required_role_support_counts": dict(
            sorted(partial_required_role_support_counts.items())
        ),
        "location_relation_category_hit_count": (
            location_relation_category_hit_count
        ),
        "source_proximity_support_count": source_proximity_support_count,
        "source_chain_proximity_support_count": (
            source_chain_proximity_support_count
        ),
        "source_proximity_closest_distance": (
            min(source_proximity_distances) if source_proximity_distances else None
        ),
        "source_chain_proximity_closest_distance": (
            min(source_chain_proximity_distances)
            if source_chain_proximity_distances
            else None
        ),
        "source_proximity_distance_counts": dict(
            sorted(
                Counter(str(distance) for distance in source_proximity_distances).items()
            )
        ),
        "source_chain_proximity_distance_counts": dict(
            sorted(
                Counter(
                    str(distance) for distance in source_chain_proximity_distances
                ).items()
            )
        ),
        "source_proximity_window": _SOURCE_PROXIMITY_WINDOW,
        "diffuse_source_ref_count": diffuse_source_ref_count,
        "missing_required_role_count": len(missing_roles),
        "missing_required_roles": list(missing_roles),
        "contrast_count": contrast_count,
        "negative_absence_support_count": negative_absence_support_count,
        "contrast_surface_count": contrast_surface_count,
        "negation_surface_count": negation_surface_count,
        "currentness_surface_count": currentness_surface_count,
        "stale_surface_count": stale_surface_count,
        "broad_summary_count": broad_summary_count,
        "conflict_or_stale_count": conflict_or_stale_count,
    }


def _source_proximity_distances(
    items: Sequence[PlannedEvidenceItem],
    *,
    missing_required_roles: Sequence[str] = (),
) -> tuple[int, ...]:
    primary_turn_refs = tuple(
        turn_ref
        for item in items
        if item.role == "primary"
        if _candidate_has_source_proximity_diagnostic_support(item.candidate)
        for turn_ref in _candidate_turn_refs(item.candidate)
    )
    if not primary_turn_refs:
        return ()
    distances: list[int] = []
    for item in items:
        if item.role == "primary":
            continue
        lacks_explicit_grounding = not _item_has_explicit_relation_or_role_grounding(
            item
        )
        if (
            missing_required_roles
            and lacks_explicit_grounding
            and not _candidate_has_focused_source_proximity_support(item.candidate)
        ):
            continue
        if not _candidate_has_source_proximity_diagnostic_support(item.candidate):
            continue
        closest_distance = _closest_turn_ref_distance(
            item.candidate,
            comparison_turn_refs=primary_turn_refs,
        )
        if closest_distance is None or closest_distance > _SOURCE_PROXIMITY_WINDOW:
            continue
        distances.append(closest_distance)
    return tuple(distances)


def _source_chain_proximity_distances(
    items: Sequence[PlannedEvidenceItem],
) -> tuple[int, ...]:
    primary_turn_refs = tuple(
        turn_ref
        for item in items
        if item.role == "primary"
        if _candidate_has_source_proximity_diagnostic_support(item.candidate)
        for turn_ref in _candidate_turn_refs(item.candidate)
    )
    previously_selected_turn_refs: list[tuple[str, int, int]] = []
    distances: list[int] = []
    for item in items:
        item_turn_refs = _candidate_turn_refs(item.candidate)
        if item.role == "primary":
            if _candidate_has_source_proximity_diagnostic_support(item.candidate):
                previously_selected_turn_refs.extend(item_turn_refs)
            continue
        if not _candidate_has_source_proximity_diagnostic_support(item.candidate):
            continue
        primary_distance = _closest_turn_ref_distance(
            item.candidate,
            comparison_turn_refs=primary_turn_refs,
        )
        if (
            primary_distance is not None
            and primary_distance <= _SOURCE_PROXIMITY_WINDOW
        ):
            previously_selected_turn_refs.extend(item_turn_refs)
            continue
        closest_distance = _closest_turn_ref_distance(
            item.candidate,
            comparison_turn_refs=previously_selected_turn_refs,
        )
        if closest_distance is not None and closest_distance <= _SOURCE_PROXIMITY_WINDOW:
            distances.append(closest_distance)
        previously_selected_turn_refs.extend(item_turn_refs)
    return tuple(distances)


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


def _bundle_quality_reason_codes(
    *,
    primary_count: int,
    supporting_count: int,
    focused_count: int,
    direct_speaker_count: int,
    source_ref_item_count: int,
    source_ref_support_item_count: int,
    source_identity_item_count: int,
    source_identity_support_item_count: int,
    source_type_diversity: int,
    retrieval_source_diversity: int,
    source_type_support_diversity: int,
    retrieval_source_support_diversity: int,
    max_answerability: float,
    low_answerability_count: int,
    bridge_count: int,
    distinct_person_grounding_count: int,
    causal_support_count: int,
    communication_support_count: int,
    event_support_count: int,
    exchange_support_count: int,
    inference_support_count: int,
    location_support_count: int,
    emotion_response_support_count: int,
    symbolic_meaning_support_count: int,
    preference_support_count: int,
    favorite_support_count: int,
    visual_support_count: int,
    typed_relation_support_counts: Mapping[str, int],
    partial_required_role_support_counts: Mapping[str, int],
    location_relation_category_hit_count: int,
    source_proximity_support_count: int,
    source_chain_proximity_support_count: int,
    missing_required_roles: Sequence[str],
    contrast_count: int,
    negative_absence_support_count: int,
    contrast_surface_count: int,
    negation_surface_count: int,
    currentness_surface_count: int,
    stale_surface_count: int,
    broad_summary_count: int,
    diffuse_source_ref_count: int,
    conflict_or_stale_count: int,
    selected_item_count: int,
) -> list[str]:
    reasons: list[str] = []
    if primary_count:
        reasons.append("has_primary_evidence")
    if supporting_count:
        reasons.append("has_supporting_evidence")
    if focused_count:
        reasons.append("has_focused_evidence")
    if direct_speaker_count:
        reasons.append("has_direct_speaker_evidence")
    if source_ref_support_item_count:
        reasons.append("has_source_refs")
    elif source_identity_support_item_count:
        reasons.append("has_source_identity")
    if source_type_support_diversity >= 2:
        reasons.append("source_type_diverse")
    if retrieval_source_support_diversity >= 2:
        reasons.append("retrieval_source_diverse")
    if max_answerability >= 0.8:
        reasons.append("high_answerability")
    elif max_answerability >= 0.55:
        reasons.append("medium_answerability")
    if low_answerability_count:
        reasons.append("risk:low_answerability")
    if bridge_count:
        reasons.append("has_bridge_evidence")
    if distinct_person_grounding_count >= 2:
        reasons.append("has_distinct_person_grounding")
    if causal_support_count:
        reasons.append("has_causal_support_evidence")
    if communication_support_count:
        reasons.append("has_communication_support_evidence")
    if event_support_count:
        reasons.append("has_event_support_evidence")
    if exchange_support_count:
        reasons.append("has_exchange_support_evidence")
    if inference_support_count:
        reasons.append("has_inference_support_evidence")
    if location_support_count:
        reasons.append("has_location_support_evidence")
    if emotion_response_support_count:
        reasons.append("has_emotion_response_support_evidence")
    if symbolic_meaning_support_count:
        reasons.append("has_symbolic_meaning_support_evidence")
    if preference_support_count:
        reasons.append("has_preference_support_evidence")
    if favorite_support_count:
        reasons.append("has_favorite_support_evidence")
    if visual_support_count:
        reasons.append("has_visual_support_evidence")
    if typed_relation_support_counts:
        reasons.append("has_typed_relation_support_evidence")
        reasons.extend(
            f"has_{role}_evidence"
            for role, count in sorted(typed_relation_support_counts.items())
            if count > 0
        )
    if partial_required_role_support_counts:
        reasons.append("has_partial_required_role_support")
        reasons.extend(
            f"partial_required_{role}"
            for role, count in sorted(partial_required_role_support_counts.items())
            if count > 0
        )
    if location_relation_category_hit_count:
        reasons.append("has_location_relation_category_evidence")
    if source_proximity_support_count:
        reasons.append("has_source_proximity_support")
    if source_chain_proximity_support_count:
        reasons.append("has_source_chain_proximity_support")
    if missing_required_roles:
        reasons.append("risk:missing_required_role")
        reasons.extend(
            f"risk:missing_required_{role}" for role in missing_required_roles
        )
    if contrast_count:
        reasons.append("has_contrast_evidence")
    if negative_absence_support_count:
        reasons.append("has_negative_absence_evidence")
    if contrast_surface_count:
        reasons.append("has_contrast_surface")
    if negation_surface_count:
        reasons.append("has_negation_surface")
    if currentness_surface_count:
        reasons.append("has_currentness_evidence")
    if stale_surface_count:
        reasons.append("has_stale_evidence")
    if broad_summary_count:
        reasons.append("risk:broad_summary")
    if selected_item_count and broad_summary_count == selected_item_count:
        reasons.append("risk:all_broad_summary")
    if diffuse_source_ref_count:
        reasons.append("risk:diffuse_source_refs")
    if conflict_or_stale_count:
        reasons.append("risk:conflict_or_stale")
    if selected_item_count and conflict_or_stale_count == selected_item_count:
        reasons.append("risk:all_conflict_or_stale")
    return reasons or ["weak_bundle"]


def _item_has_partial_required_role_support(
    item: PlannedEvidenceItem,
    role: str,
) -> bool:
    return has_partial_required_role_support(
        item.candidate,
        item_role=item.role,
        role=role,
        complete_support=_item_can_satisfy_required_role(item, role),
        typed_relation_support_categories=_TYPED_RELATION_SUPPORT_CATEGORIES,
    )


def _confidence_band(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.55:
        return "medium"
    if score > 0:
        return "low"
    return "none"


def _primary_sort_key(candidate: EvidenceBundleCandidate) -> tuple[float, ...]:
    return (
        0.0 if candidate.direct_speaker_turn else 1.0,
        0.0 if not candidate.broad_summary else 1.0,
        -candidate.focused_evidence_score,
        0.0 if candidate.required_terms else 1.0,
        float(_answer_evidence_sort_bucket(candidate)),
        -candidate.answerability_score,
        -candidate.source_locality_score,
        -candidate.bundle_strength_score,
        0.0 if not candidate.conflict_or_stale else 1.0,
        float(candidate.retrieval_order),
        float(candidate.rank),
    )


def _candidate_sort_key(candidate: EvidenceBundleCandidate) -> tuple[float, ...]:
    return (
        0.0 if candidate.primary_signal else 1.0,
        float(_answer_evidence_sort_bucket(candidate)),
        0.0 if candidate.direct_speaker_turn else 1.0,
        0.0 if not candidate.broad_summary else 1.0,
        -candidate.focused_evidence_score,
        -candidate.answerability_score,
        -candidate.source_locality_score,
        -candidate.bundle_strength_score,
        0.0 if not candidate.conflict_or_stale else 1.0,
        float(candidate.retrieval_order),
        float(candidate.rank),
    )


def _answer_evidence_sort_bucket(candidate: EvidenceBundleCandidate) -> int:
    if _candidate_has_answer_evidence(candidate):
        return 0
    if _candidate_has_direct_or_focused_grounding(candidate):
        return 1
    if _candidate_has_relation_grounding(candidate) or _candidate_has_person_grounding(
        candidate
    ):
        return 2
    if candidate.query_support_terms:
        return 3
    return 4


def _candidate_has_answer_evidence(candidate: EvidenceBundleCandidate) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if _candidate_has_measured_source_locality_below(candidate, 0.65):
        return False
    if _candidate_has_measured_answerability_below(candidate, 0.75):
        return False
    if not _candidate_has_relation_grounding(candidate):
        return False
    if candidate.query_has_entities and not _candidate_has_person_grounding(candidate):
        return False
    return bool(
        candidate.direct_speaker_turn
        or candidate.focused_evidence_score > 0
        or candidate.answerability_score >= 0.75
    )


def _candidate_has_direct_or_focused_grounding(
    candidate: EvidenceBundleCandidate,
) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if not (candidate.direct_speaker_turn or candidate.focused_evidence_score > 0):
        return False
    if candidate.query_has_entities and not _candidate_has_person_grounding(candidate):
        return False
    return bool(
        candidate.query_support_terms
        or _candidate_has_relation_grounding(candidate)
        or _candidate_has_person_grounding(candidate)
        or candidate.source_refs
    )


def _candidate_has_relation_grounding(candidate: EvidenceBundleCandidate) -> bool:
    return bool(candidate.relation_hits or candidate.relation_category_hits)


def _candidate_has_person_grounding(candidate: EvidenceBundleCandidate) -> bool:
    return bool(candidate.entity_hits or candidate.speaker_hits)
