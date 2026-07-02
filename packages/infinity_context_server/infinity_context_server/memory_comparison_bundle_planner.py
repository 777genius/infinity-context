"""Evidence bundle planning for memory comparison benchmark retrieval."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

BundleRole = str
_TURN_REF_RE = re.compile(r"\bD\d+:\d+\b")
_TURN_REF_PARTS_RE = re.compile(r"\bD(?P<dialogue>\d+):(?P<turn>\d+)\b")
_SOURCE_PROXIMITY_WINDOW = 3


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
    entity_hits: tuple[str, ...] = ()
    speaker_hits: tuple[str, ...] = ()
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
            "has_temporal_sequence_surface": (
                self.candidate.has_temporal_sequence_surface
            ),
            "source_locality_score": round(self.candidate.source_locality_score, 6),
            "negation_surface": self.candidate.negation_surface,
            "currentness_surface": self.candidate.currentness_surface,
            "stale_surface": self.candidate.stale_surface,
            "contrast_surface": self.candidate.contrast_surface,
            "source_refs": list(self.candidate.source_refs),
            "planner_reason_codes": list(self.reason_codes),
        }
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
            "average_selected_source_locality_score": round(
                (
                    sum(item.candidate.source_locality_score for item in self.items)
                    / len(self.items)
                )
                if self.items
                else 0.0,
                6,
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
        return sorted(primary_candidates, key=_primary_sort_key)[0]

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
    ) -> tuple[tuple[PlannedEvidenceItem, ...], int, int, int, int]:
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
        remaining = list(planned)
        while remaining and len(selected) < self._max_items:
            remaining.sort(
                key=lambda item: _planned_coverage_sort_key(
                    item,
                    covered_terms=covered_terms,
                    covered_support_terms=covered_support_terms,
                )
            )
            item = remaining.pop(0)
            source_type = item.candidate.source_type
            retrieval_source_keys = _retrieval_source_keys(item.candidate)
            source_ref_keys = _source_ref_overlap_keys(item.candidate)
            adds_required_terms = not item.candidate.required_terms.issubset(
                covered_terms
            )
            adds_query_support_terms = not set(
                item.candidate.query_support_terms
            ).issubset(covered_support_terms)
            source_ref_overlap_full = bool(source_ref_keys) and set(
                source_ref_keys
            ).issubset(selected_source_ref_keys)
            source_type_diversity_full = (
                source_type_counts[source_type] >= self._max_items_per_source_type
            )
            retrieval_source_diversity_full = any(
                retrieval_source_counts[source] >= self._max_items_per_retrieval_source
                for source in retrieval_source_keys
            )
            diversity_exempt = item.role in {
                "primary",
                "temporal_support",
                "entity_disambiguation",
                "inference_support",
                "causal_support",
                "contrast",
                "bridge",
                "location_support",
            }
            if (
                not diversity_exempt
                and source_type_diversity_full
                and not adds_required_terms
            ) or (
                not diversity_exempt
                and retrieval_source_diversity_full
                and not adds_required_terms
            ) or (
                source_ref_overlap_full
                and not adds_required_terms
                and not adds_query_support_terms
            ):
                dropped_diversity_count += 1
                if source_type_diversity_full and not diversity_exempt:
                    dropped_source_type_diversity_count += 1
                if retrieval_source_diversity_full and not diversity_exempt:
                    dropped_retrieval_source_diversity_count += 1
                if source_ref_overlap_full:
                    dropped_source_ref_overlap_count += 1
                continue
            selected.append(item)
            source_type_counts[source_type] += 1
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
        return (
            tuple(selected),
            dropped_diversity_count,
            dropped_source_type_diversity_count,
            dropped_retrieval_source_diversity_count,
            dropped_source_ref_overlap_count,
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
    if _candidate_has_location_support(candidate):
        return "location_support"
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
        "causal_support" in set(required_roles)
        and _candidate_has_causal_support(candidate)
    ):
        return "causal_support"
    if (
        "inference_support" in set(required_roles)
        and _candidate_has_inference_support(candidate)
    ):
        return "inference_support"
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
    if candidate.conflict_or_stale or candidate.broad_summary:
        return False
    support_term_count = len(tuple(dict.fromkeys(candidate.query_support_terms)))
    if support_term_count < 2:
        return False
    return bool(candidate.relation_hits and (candidate.entity_hits or candidate.speaker_hits))


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
        if role in selected_roles and role != "temporal_support":
            satisfied.add(role)
            continue
        if role == "contrast" and any(
            _candidate_has_contrast_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
            continue
        if role == "bridge" and _selection_has_bridge_support(selected):
            satisfied.add(role)
        if role == "location_support" and any(
            _candidate_has_location_support(item.candidate) for item in selected
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
        if role == "inference_support" and any(
            _candidate_has_inference_support(item.candidate) for item in selected
        ):
            satisfied.add(role)
        if role == "causal_support" and any(
            _candidate_has_causal_support(item.candidate) for item in selected
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
    return sorted(candidates, key=_required_role_candidate_sort_key)[0]


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
    if role == "contrast":
        return _candidate_has_contrast_support(item.candidate)
    if role == "bridge":
        return item.role == "bridge"
    if role == "location_support":
        return _candidate_has_location_support(item.candidate)
    if role == "preference_support":
        return _candidate_has_preference_support(item.candidate)
    if role == "visual_support":
        return _candidate_has_visual_support(item.candidate)
    if role == "inference_support":
        return _candidate_has_inference_support(item.candidate)
    if role == "causal_support":
        return _candidate_has_causal_support(item.candidate)
    return item.role == role


def _required_role_candidate_sort_key(
    item: PlannedEvidenceItem,
) -> tuple[float, ...]:
    return (
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
        "inference_support": 2,
        "preference_support": 2,
        "temporal_support": 2,
        "visual_support": 2,
        "contrast": 3,
        "bridge": 4,
        "location_support": 4,
        "primary": 5,
    }
    return float(role_order.get(item.role, 9))


def _candidate_has_temporal_support(candidate: EvidenceBundleCandidate) -> bool:
    time_kind = str(candidate.time_intent_kind or "").strip()
    if time_kind == "duration":
        return candidate.has_duration_surface
    if time_kind == "temporal_sequence":
        return candidate.has_temporal_sequence_surface or candidate.has_sequence_surface
    if time_kind == "explicit_time":
        return candidate.has_explicit_time_surface or candidate.has_temporal_surface
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
        or candidate.has_explicit_time_surface
        or candidate.has_temporal_sequence_surface
        or candidate.currentness_surface
    )


def _candidate_has_contrast_support(candidate: EvidenceBundleCandidate) -> bool:
    return bool(
        candidate.contrast_surface
        or (
            candidate.currentness_surface
            and (candidate.stale_surface or candidate.negation_surface)
        )
    )


def _candidate_has_location_support(candidate: EvidenceBundleCandidate) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if candidate.source_locality_score < 0.45:
        return False
    if candidate.answerability_score and candidate.answerability_score < 0.55:
        return False
    if "location_transition" in set(candidate.relation_category_hits):
        return True
    location_terms = {
        "city",
        "country",
        "drive",
        "from",
        "home",
        "origin",
        "relocated",
        "travel",
        "trip",
    }
    return bool(location_terms.intersection(candidate.relation_hits))


def _candidate_has_preference_support(candidate: EvidenceBundleCandidate) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if candidate.source_locality_score < 0.45:
        return False
    if candidate.answerability_score and candidate.answerability_score < 0.55:
        return False
    return bool(
        candidate.has_preference_evidence
        or "preference" in set(candidate.relation_category_hits)
    )


def _candidate_has_visual_support(candidate: EvidenceBundleCandidate) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if candidate.source_locality_score < 0.45:
        return False
    if candidate.answerability_score and candidate.answerability_score < 0.55:
        return False
    return bool(
        candidate.has_visual_evidence
        or "visual" in set(candidate.relation_category_hits)
    )


def _candidate_has_inference_support(candidate: EvidenceBundleCandidate) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if not (candidate.entity_hits or candidate.speaker_hits):
        return False
    if candidate.source_locality_score < 0.45:
        return False
    if candidate.answerability_score and candidate.answerability_score < 0.55:
        return False
    return bool(
        candidate.relation_hits
        or candidate.relation_category_hits
        or candidate.query_support_terms
    )


def _candidate_has_causal_support(candidate: EvidenceBundleCandidate) -> bool:
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if not (candidate.entity_hits or candidate.speaker_hits):
        return False
    if candidate.source_locality_score < 0.45:
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


def _selection_has_bridge_support(selected: Sequence[PlannedEvidenceItem]) -> bool:
    if len(selected) < 2:
        return False
    if not any(item.role == "primary" for item in selected):
        return False
    support_terms = {
        term
        for item in selected
        for term in item.candidate.query_support_terms
        if str(term).strip()
    }
    if len(support_terms) >= 2:
        return True
    covered_terms = {
        term
        for item in selected
        for term in (*item.candidate.covered_expected_terms, *item.candidate.covered_evidence_terms)
        if str(term).strip()
    }
    return len(covered_terms) >= 2


def _primary_candidate_eligible(candidate: EvidenceBundleCandidate) -> bool:
    if candidate.primary_signal:
        return True
    if candidate.broad_summary or candidate.conflict_or_stale:
        return False
    if not candidate.direct_speaker_turn:
        return False
    if candidate.source_locality_score < 0.65 or candidate.answerability_score < 0.75:
        return False
    return bool(
        candidate.query_support_terms
        or candidate.relation_hits
        or candidate.entity_hits
        or candidate.speaker_hits
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
    return tuple(
        dict.fromkeys(
            turn_ref
            for source_ref in candidate.source_refs
            for turn_ref in _TURN_REF_RE.findall(str(source_ref))
        )
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
        "location_support": 3,
        "preference_support": 3,
        "temporal_support": 3,
        "visual_support": 3,
        "causal_support": 4,
        "inference_support": 4,
        "entity_disambiguation": 5,
        "supporting": 5,
    }
    return float(role_order.get(item.role, 9))


def _planned_coverage_sort_key(
    item: PlannedEvidenceItem,
    *,
    covered_terms: set[str],
    covered_support_terms: set[str],
) -> tuple[float, ...]:
    required_gain = len(item.candidate.required_terms.difference(covered_terms))
    support_gain = len(
        set(item.candidate.query_support_terms).difference(covered_support_terms)
    )
    return (
        _role_order(item),
        -float(required_gain),
        -float(support_gain),
        *_candidate_sort_key(item.candidate),
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
        if item.role in {
            "primary",
            "temporal_support",
            "entity_disambiguation",
            "inference_support",
            "causal_support",
            "contrast",
            "bridge",
            "location_support",
        }:
            continue
        if source_type_counts[item.candidate.source_type] >= max_items_per_source_type:
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
            "source_type_diversity": 0,
            "retrieval_source_diversity": 0,
            "low_answerability_count": 0,
            "bridge_count": 0,
            "bridge_query_hit_count": 0,
            "causal_support_count": 0,
            "inference_support_count": 0,
            "location_support_count": 0,
            "preference_support_count": 0,
            "visual_support_count": 0,
            "location_relation_category_hit_count": 0,
            "source_proximity_support_count": 0,
            "source_proximity_window": _SOURCE_PROXIMITY_WINDOW,
            "missing_required_role_count": len(missing_roles),
            "missing_required_roles": list(missing_roles),
            "contrast_count": 0,
            "contrast_surface_count": 0,
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
    source_types = {
        source_type
        for item in items
        for source_type in _source_type_keys(item.candidate)
    }
    retrieval_sources = {
        source for item in items for source in _retrieval_source_keys(item.candidate)
    }
    answerability_scores = [item.candidate.answerability_score for item in items]
    avg_answerability = sum(answerability_scores) / len(answerability_scores)
    max_answerability = max(answerability_scores)
    low_answerability_count = sum(score < 0.55 for score in answerability_scores)
    bridge_count = sum(1 for item in items if item.role == "bridge")
    bridge_query_hit_count = sum(1 for item in items if item.candidate.bridge_query_hit)
    causal_support_count = sum(1 for item in items if item.role == "causal_support")
    inference_support_count = sum(
        1 for item in items if item.role == "inference_support"
    )
    location_support_count = sum(1 for item in items if item.role == "location_support")
    preference_support_count = sum(
        1 for item in items if item.role == "preference_support"
    )
    visual_support_count = sum(1 for item in items if item.role == "visual_support")
    location_relation_category_hit_count = sum(
        1
        for item in items
        if "location_transition" in set(item.candidate.relation_category_hits)
    )
    source_proximity_support_count = _source_proximity_support_count(items)
    contrast_count = sum(1 for item in items if item.role == "contrast")
    contrast_surface_count = sum(1 for item in items if item.candidate.contrast_surface)
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
        "source_refs": min(0.16, 0.08 * source_ref_item_count),
        "source_diversity": (
            (0.06 if len(source_types) >= 2 else 0.0)
            + (0.06 if len(retrieval_sources) >= 2 else 0.0)
        ),
        "answerability": min(
            0.24,
            (0.14 * max_answerability) + (0.10 * avg_answerability),
        ),
        "bridge_support": min(0.1, 0.1 * bridge_count),
        "causal_support": min(0.08, 0.08 * causal_support_count),
        "inference_support": min(0.08, 0.08 * inference_support_count),
        "location_support": min(0.08, 0.08 * location_support_count),
        "preference_support": min(0.08, 0.08 * preference_support_count),
        "visual_support": min(0.08, 0.08 * visual_support_count),
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
        + (0.08 * conflict_or_stale_count)
        + (0.08 if broad_summary_count == len(items) else 0.0)
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
            source_type_diversity=len(source_types),
            retrieval_source_diversity=len(retrieval_sources),
            max_answerability=max_answerability,
            low_answerability_count=low_answerability_count,
            bridge_count=bridge_count,
            causal_support_count=causal_support_count,
            inference_support_count=inference_support_count,
            location_support_count=location_support_count,
            preference_support_count=preference_support_count,
            visual_support_count=visual_support_count,
            location_relation_category_hit_count=location_relation_category_hit_count,
            source_proximity_support_count=source_proximity_support_count,
            missing_required_roles=missing_roles,
            contrast_count=contrast_count,
            contrast_surface_count=contrast_surface_count,
            currentness_surface_count=currentness_surface_count,
            stale_surface_count=stale_surface_count,
            broad_summary_count=broad_summary_count,
            conflict_or_stale_count=conflict_or_stale_count,
            selected_item_count=len(items),
        ),
        "selected_item_count": len(items),
        "primary_count": primary_count,
        "supporting_count": supporting_count,
        "focused_item_count": focused_count,
        "direct_speaker_count": direct_speaker_count,
        "source_ref_item_count": source_ref_item_count,
        "source_type_diversity": len(source_types),
        "retrieval_source_diversity": len(retrieval_sources),
        "average_answerability_score": round(avg_answerability, 6),
        "max_answerability_score": round(max_answerability, 6),
        "low_answerability_count": low_answerability_count,
        "bridge_count": bridge_count,
        "bridge_query_hit_count": bridge_query_hit_count,
        "causal_support_count": causal_support_count,
        "inference_support_count": inference_support_count,
        "location_support_count": location_support_count,
        "preference_support_count": preference_support_count,
        "visual_support_count": visual_support_count,
        "location_relation_category_hit_count": (
            location_relation_category_hit_count
        ),
        "source_proximity_support_count": source_proximity_support_count,
        "source_proximity_window": _SOURCE_PROXIMITY_WINDOW,
        "missing_required_role_count": len(missing_roles),
        "missing_required_roles": list(missing_roles),
        "contrast_count": contrast_count,
        "contrast_surface_count": contrast_surface_count,
        "currentness_surface_count": currentness_surface_count,
        "stale_surface_count": stale_surface_count,
        "broad_summary_count": broad_summary_count,
        "conflict_or_stale_count": conflict_or_stale_count,
    }


def _source_proximity_support_count(items: Sequence[PlannedEvidenceItem]) -> int:
    primary_turn_refs = tuple(
        turn_ref
        for item in items
        if item.role == "primary"
        for turn_ref in _candidate_turn_refs(item.candidate)
    )
    if not primary_turn_refs:
        return 0
    count = 0
    for item in items:
        if item.role == "primary":
            continue
        if _candidate_near_turn_refs(
            item.candidate,
            primary_turn_refs=primary_turn_refs,
            max_distance=_SOURCE_PROXIMITY_WINDOW,
        ):
            count += 1
    return count


def _candidate_near_turn_refs(
    candidate: EvidenceBundleCandidate,
    *,
    primary_turn_refs: Sequence[tuple[int, int]],
    max_distance: int,
) -> bool:
    return any(
        primary_dialogue == candidate_dialogue
        and abs(primary_turn - candidate_turn) <= max_distance
        for primary_dialogue, primary_turn in primary_turn_refs
        for candidate_dialogue, candidate_turn in _candidate_turn_refs(candidate)
    )


def _candidate_turn_refs(candidate: EvidenceBundleCandidate) -> tuple[tuple[int, int], ...]:
    refs: list[tuple[int, int]] = []
    for source_ref in candidate.source_refs:
        for match in _TURN_REF_PARTS_RE.finditer(str(source_ref)):
            refs.append(
                (
                    int(match.group("dialogue")),
                    int(match.group("turn")),
                )
            )
    return tuple(dict.fromkeys(refs))


def _bundle_quality_reason_codes(
    *,
    primary_count: int,
    supporting_count: int,
    focused_count: int,
    direct_speaker_count: int,
    source_ref_item_count: int,
    source_type_diversity: int,
    retrieval_source_diversity: int,
    max_answerability: float,
    low_answerability_count: int,
    bridge_count: int,
    causal_support_count: int,
    inference_support_count: int,
    location_support_count: int,
    preference_support_count: int,
    visual_support_count: int,
    location_relation_category_hit_count: int,
    source_proximity_support_count: int,
    missing_required_roles: Sequence[str],
    contrast_count: int,
    contrast_surface_count: int,
    currentness_surface_count: int,
    stale_surface_count: int,
    broad_summary_count: int,
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
    if source_ref_item_count:
        reasons.append("has_source_refs")
    if source_type_diversity >= 2:
        reasons.append("source_type_diverse")
    if retrieval_source_diversity >= 2:
        reasons.append("retrieval_source_diverse")
    if max_answerability >= 0.8:
        reasons.append("high_answerability")
    elif max_answerability >= 0.55:
        reasons.append("medium_answerability")
    if low_answerability_count:
        reasons.append("risk:low_answerability")
    if bridge_count:
        reasons.append("has_bridge_evidence")
    if causal_support_count:
        reasons.append("has_causal_support_evidence")
    if inference_support_count:
        reasons.append("has_inference_support_evidence")
    if location_support_count:
        reasons.append("has_location_support_evidence")
    if preference_support_count:
        reasons.append("has_preference_support_evidence")
    if visual_support_count:
        reasons.append("has_visual_support_evidence")
    if location_relation_category_hit_count:
        reasons.append("has_location_relation_category_evidence")
    if source_proximity_support_count:
        reasons.append("has_source_proximity_support")
    if missing_required_roles:
        reasons.append("risk:missing_required_role")
        reasons.extend(f"risk:missing_required_{role}" for role in missing_required_roles)
    if contrast_count:
        reasons.append("has_contrast_evidence")
    if contrast_surface_count:
        reasons.append("has_contrast_surface")
    if currentness_surface_count:
        reasons.append("has_currentness_evidence")
    if stale_surface_count:
        reasons.append("has_stale_evidence")
    if broad_summary_count:
        reasons.append("risk:broad_summary")
    if selected_item_count and broad_summary_count == selected_item_count:
        reasons.append("risk:all_broad_summary")
    if conflict_or_stale_count:
        reasons.append("risk:conflict_or_stale")
    return reasons or ["weak_bundle"]


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
