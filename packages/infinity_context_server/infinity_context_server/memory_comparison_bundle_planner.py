"""Evidence bundle planning orchestration and compatible public exports."""

# Explicit imports retain the original public and private compatibility exports.
# ruff: noqa: F401

from __future__ import annotations

import re
from collections import (
    Counter,
)
from collections.abc import (
    Mapping,
    Sequence,
)
from dataclasses import (
    dataclass,
)

from infinity_context_benchmarks.evidence_bundle.candidate_policy import (
    _DIVERSITY_EXEMPT_ROLES,
    _NEGATIVE_ABSENCE_ROLES,
    _PARTICIPANT_SENSITIVE_REQUIRED_ROLES,
    _PREDICATE_REQUIRED_ROLES,
    _TEMPORAL_TIME_KIND_ROLES,
    _TYPED_RELATION_SUPPORT_CATEGORIES,
    _TYPED_TEMPORAL_SUPPORT_ROLES,
    _answer_evidence_sort_bucket,
    _candidate_bridge_value_terms,
    _candidate_has_answer_evidence,
    _candidate_has_answer_unit_support_grounding,
    _candidate_has_bridge_grounding,
    _candidate_has_bridge_query_provenance,
    _candidate_has_bridge_support_surface,
    _candidate_has_causal_support,
    _candidate_has_communication_support,
    _candidate_has_complementary_bridge_value,
    _candidate_has_contrast_grounding,
    _candidate_has_contrast_support,
    _candidate_has_count_support,
    _candidate_has_direct_or_focused_grounding,
    _candidate_has_emotion_response_support,
    _candidate_has_entityless_support_goal_grounding,
    _candidate_has_event_support,
    _candidate_has_exchange_support,
    _candidate_has_favorite_support,
    _candidate_has_inference_support,
    _candidate_has_list_support,
    _candidate_has_local_bridge_grounding,
    _candidate_has_location_support,
    _candidate_has_negative_absence_support,
    _candidate_has_obsolete_primary_surface,
    _candidate_has_preference_support,
    _candidate_has_relation_or_answer_grounding,
    _candidate_has_symbolic_meaning_support,
    _candidate_has_temporal_grounding,
    _candidate_has_temporal_support,
    _candidate_has_typed_relation_grounding,
    _candidate_has_typed_relation_support,
    _candidate_has_typed_temporal_support,
    _candidate_has_value_support,
    _candidate_has_visual_support,
    _candidate_list_items,
    _is_bridge_candidate,
    _primary_candidate_eligible,
    _role_for_candidate,
    _typed_temporal_role_for_candidate,
)
from infinity_context_benchmarks.evidence_bundle.models import (
    BundleRole,
    EvidenceBundleCandidate,
    PlannedEvidenceItem,
    _safe_source_label_counts,
    _safe_source_labels_for_output,
)
from infinity_context_benchmarks.evidence_bundle.ordering import (
    _candidate_prefers_distinct_person_grounding,
    _candidate_sort_key,
    _explicit_relation_role_sort_key,
    _item_has_explicit_relation_or_role_grounding,
    _person_grounding_selection_sort_key,
    _planned_coverage_sort_key,
    _planned_sort_key,
    _primary_sort_key,
    _role_order,
    _selection_precision_sort_key,
    _source_overlap_selection_sort_key,
    _source_proximity_selection_sort_key,
    _source_ref_compactness_selection_sort_key,
)
from infinity_context_benchmarks.evidence_bundle.partial_support import (
    has_partial_required_role_support,
)
from infinity_context_benchmarks.evidence_bundle.quality import (
    _SOURCE_DIAGNOSTIC_REF_SAMPLE_LIMIT,
    _SOURCE_DIAGNOSTIC_SAMPLE_LIMIT,
    _avg_positive_scores,
    _bundle_quality_diagnostics,
    _bundle_quality_reason_codes,
    _confidence_band,
    _diffuse_source_ref_samples,
    _participant_grounding_blocked_required_role_samples,
    _source_chain_proximity_distances,
    _source_proximity_distances,
    _source_turn_ref_strings_sample,
    _weak_source_locality_samples,
)
from infinity_context_benchmarks.evidence_bundle.role_repair import (
    _best_required_role_candidate,
    _missing_required_roles,
    _repair_required_role_selection,
    _replaceable_item_index,
    _replacement_role_order,
    _replacement_sort_key,
    _required_role_candidate_sort_key,
)
from infinity_context_benchmarks.evidence_bundle.role_support import (
    _candidate_has_complementary_bridge_value_for_primary_items,
    _candidate_has_distinct_multi_hop_support,
    _candidate_has_source_chain_multi_hop_support,
    _candidate_is_distinct_from_primary,
    _item_can_satisfy_required_role,
    _item_can_satisfy_required_role_in_selection,
    _item_has_partial_required_role_support,
    _item_has_requested_participant_grounding,
    _required_role_values,
    _satisfied_required_roles,
    _selected_primary_person_grounding_terms,
    _selected_required_roles,
    _selection_has_bridge_support,
    _selection_has_source_chain_bridge_support,
)
from infinity_context_benchmarks.evidence_bundle.source_policy import (
    _COMPACT_SOURCE_REF_MAX_SPAN,
    _COMPACT_SOURCE_REF_MAX_TURNS,
    _SOURCE_PROXIMITY_WINDOW,
    _TURN_REF_PARTS_RE,
    _candidate_has_diffuse_source_refs,
    _candidate_has_focused_source_proximity_support,
    _candidate_has_generic_measured_answerability,
    _candidate_has_measured_answerability_below,
    _candidate_has_measured_source_locality_below,
    _candidate_has_measured_weak_source_locality,
    _candidate_has_noisy_source_overlap_risk,
    _candidate_has_person_grounding,
    _candidate_has_relation_grounding,
    _candidate_has_source_identity_grounding,
    _candidate_has_source_identity_quality_support,
    _candidate_has_source_proximity_diagnostic_support,
    _candidate_person_grounding_terms,
    _candidate_turn_ref_strings,
    _candidate_turn_refs,
    _closest_turn_ref_distance,
    _is_measured_low_answerability,
    _retrieval_source_keys,
    _source_identity_refs,
    _source_ref_overlap_keys,
    _source_type_keys,
    _turn_ref_span,
    _turn_refs_same_source,
)

from infinity_context_server.memory_comparison_bundle_source_windows import (
    is_redundant_source_window_filler,
)
from infinity_context_server.memory_comparison_source_identity import (
    safe_source_label_for_output as _safe_source_label_for_output,
)
from infinity_context_server.memory_comparison_source_identity import (
    source_identity_refs_from_dedupe_key as _source_identity_refs_from_dedupe_key,
)
from infinity_context_server.memory_comparison_source_identity import (
    source_identity_refs_from_source_refs as _source_identity_refs_from_source_refs,
)


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
            "source_type_counts": _safe_source_label_counts(self.source_type_counts),
            "retrieval_source_counts": _safe_source_label_counts(
                self.retrieval_source_counts
            ),
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
        covered_list_items: set[str] = set()
        covered_bridge_value_terms: set[str] = set()
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
                    covered_list_items=covered_list_items,
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
            adds_list_items = bool(
                _candidate_list_items(item.candidate).difference(covered_list_items)
            )
            adds_answer_support = adds_answer_support or adds_list_items
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
            redundant_list_items = (
                item.role in {"count_support", "list_support", "supporting"}
                and bool(_candidate_list_items(item.candidate))
                and not adds_list_items
                and not adds_required_terms
                and not adds_query_support_terms
            )
            bridge_value_terms = _candidate_bridge_value_terms(item.candidate)
            redundant_bridge_value = (
                item.role == "bridge"
                and bool(bridge_value_terms)
                and bridge_value_terms.issubset(covered_bridge_value_terms)
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
            should_drop = (
                (
                    not diversity_exempt
                    and source_type_diversity_full
                    and not adds_answer_support
                )
                or (
                    not diversity_exempt
                    and retrieval_source_diversity_full
                    and not adds_answer_support
                )
                or (
                    source_ref_overlap_full
                    and not adds_required_terms
                    and not adds_query_support_terms
                )
                or noisy_source_overlap
                or redundant_source_window
                or redundant_list_items
                or redundant_bridge_value
            )
            if should_drop:
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
            covered_list_items.update(_candidate_list_items(item.candidate))
            if item.role == "bridge":
                covered_bridge_value_terms.update(bridge_value_terms)
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
