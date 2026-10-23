"""Immutable evidence candidate/item contracts and source-label serialization."""

from __future__ import annotations

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

from infinity_context_benchmarks.source_identity import (
    safe_source_label_for_output as _safe_source_label_for_output,
)

BundleRole = str


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
    list_items: tuple[str, ...] = ()
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
            "list_items": list(self.candidate.list_items),
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
        source_type = _safe_source_label_for_output(self.candidate.source_type)
        if source_type and source_type != "unknown":
            payload["source_type"] = source_type
        source_types = _safe_source_labels_for_output(self.candidate.source_types)
        if source_types:
            payload["source_types"] = list(source_types)
        retrieval_sources = _safe_source_labels_for_output(
            self.candidate.retrieval_sources
        )
        if retrieval_sources:
            payload["retrieval_sources"] = list(retrieval_sources)
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


def _safe_source_labels_for_output(values: Sequence[object]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            label
            for value in values
            for label in (_safe_source_label_for_output(value),)
            if label
        )
    )


def _safe_source_label_counts(values: Mapping[str, int]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for value, count in values.items():
        label = _safe_source_label_for_output(value)
        if label:
            counts[label] += count
    return dict(counts)
