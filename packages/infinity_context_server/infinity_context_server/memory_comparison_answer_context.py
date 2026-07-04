"""Answer-context selection for memory comparison benchmark runs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from infinity_context_server.memory_comparison_answer_context_backfill import (
    backfill_incomplete_bundle_context,
)
from infinity_context_server.memory_comparison_answer_context_retrieval_slice import (
    retrieval_slice_answer_context,
)
from infinity_context_server.memory_comparison_answer_context_risks import (
    add_answer_context_risk_codes as _add_answer_context_risk_codes,
)
from infinity_context_server.memory_comparison_answer_context_risks import (
    context_risk_reason_codes as _context_risk_reason_codes,
)
from infinity_context_server.memory_comparison_answer_context_risks import (
    is_measured_low_answerability as _is_measured_low_answerability,
)
from infinity_context_server.memory_comparison_answer_context_risks import (
    is_measured_weak_source_locality as _is_measured_weak_source_locality,
)
from infinity_context_server.memory_comparison_candidate_risks import (
    candidate_features as _candidate_features,
)
from infinity_context_server.memory_comparison_candidate_risks import (
    memory_has_broad_summary,
    memory_has_conflict_or_stale,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory
from infinity_context_server.memory_comparison_source_identity import (
    source_identity_refs_from_dedupe_key as _source_identity_refs_from_dedupe_key,
)
from infinity_context_server.memory_comparison_source_identity import (
    source_identity_refs_from_source_refs as _source_identity_refs_from_source_refs,
)
from infinity_context_server.memory_comparison_source_identity import (
    source_identity_refs_from_text as _source_identity_refs_from_text,
)

_SOURCE_TURN_REF_PREFIXES = ("source_turn_refs:", "source_session_turn_refs:")


@dataclass(frozen=True)
class AnswerContext:
    """Evidence context passed to answer/judge adapters."""

    memories: tuple[RetrievedMemory, ...]
    source: str
    fallback_reason: str | None = None
    selected_bundle_item_count: int = 0
    skipped_bundle_item_count: int = 0
    skipped_duplicate_source_bundle_item_count: int = 0
    skipped_noisy_overlap_bundle_item_count: int = 0
    backfilled_retrieval_item_count: int = 0
    backfilled_precise_source_overlap_count: int = 0
    skipped_redundant_risky_backfill_count: int = 0
    skipped_redundant_source_backfill_count: int = 0
    skipped_redundant_role_backfill_count: int = 0
    bundle_confidence_score: float = 0.0
    bundle_confidence_band: str = ""
    bundle_bridge_count: int = 0
    bundle_source_ref_support_item_count: int = 0
    bundle_source_ref_support_ref_count: int = 0
    bundle_source_identity_support_item_count: int = 0
    bundle_source_identity_support_ref_count: int = 0
    bundle_source_type_diversity: int = 0
    bundle_retrieval_source_diversity: int = 0
    bundle_source_type_support_diversity: int = 0
    bundle_retrieval_source_support_diversity: int = 0
    bundle_source_proximity_support_count: int = 0
    bundle_source_proximity_closest_distance: int | None = None
    bundle_source_proximity_distance_counts: Mapping[str, int] = field(
        default_factory=dict
    )
    bundle_source_chain_proximity_support_count: int = 0
    bundle_source_chain_proximity_closest_distance: int | None = None
    bundle_source_chain_proximity_distance_counts: Mapping[str, int] = field(
        default_factory=dict
    )
    bundle_diffuse_source_ref_count: int = 0
    bundle_causal_support_count: int = 0
    bundle_communication_support_count: int = 0
    bundle_event_support_count: int = 0
    bundle_exchange_support_count: int = 0
    bundle_inference_support_count: int = 0
    bundle_location_support_count: int = 0
    bundle_emotion_response_support_count: int = 0
    bundle_symbolic_meaning_support_count: int = 0
    bundle_preference_support_count: int = 0
    bundle_favorite_support_count: int = 0
    bundle_visual_support_count: int = 0
    bundle_typed_relation_support_count: int = 0
    bundle_typed_relation_support_counts: Mapping[str, int] = field(
        default_factory=dict
    )
    bundle_contrast_count: int = 0
    role_requirement_complete: bool | None = None
    missing_required_roles: tuple[str, ...] = ()
    bundle_risk_reason_codes: tuple[str, ...] = ()

    def to_diagnostics(self) -> dict[str, object]:
        source_ref_stats = _source_ref_stats(self.memories)
        backfill_risk_stats = _backfill_risk_stats(self.memories)
        quality_score_stats = _quality_score_stats(self.memories)
        risk_reason_codes = _answer_context_risk_reason_codes(
            self,
            backfill_risk_stats=backfill_risk_stats,
        )
        return {
            "schema_version": "answer_context.v1",
            "source": self.source,
            "memory_count": len(self.memories),
            **source_ref_stats,
            **quality_score_stats,
            "selected_bundle_item_count": self.selected_bundle_item_count,
            "skipped_bundle_item_count": self.skipped_bundle_item_count,
            "skipped_duplicate_source_bundle_item_count": (
                self.skipped_duplicate_source_bundle_item_count
            ),
            "skipped_noisy_overlap_bundle_item_count": (
                self.skipped_noisy_overlap_bundle_item_count
            ),
            "backfilled_retrieval_item_count": self.backfilled_retrieval_item_count,
            "backfilled_precise_source_overlap_count": (
                self.backfilled_precise_source_overlap_count
            ),
            "skipped_redundant_risky_backfill_count": (
                self.skipped_redundant_risky_backfill_count
            ),
            "skipped_redundant_source_backfill_count": (
                self.skipped_redundant_source_backfill_count
            ),
            "skipped_redundant_role_backfill_count": (
                self.skipped_redundant_role_backfill_count
            ),
            **backfill_risk_stats,
            "bundle_confidence_score": self.bundle_confidence_score,
            "bundle_confidence_band": self.bundle_confidence_band,
            "bundle_bridge_count": self.bundle_bridge_count,
            "bundle_source_ref_support_item_count": (
                self.bundle_source_ref_support_item_count
            ),
            "bundle_source_ref_support_ref_count": (
                self.bundle_source_ref_support_ref_count
            ),
            "bundle_source_identity_support_item_count": (
                self.bundle_source_identity_support_item_count
            ),
            "bundle_source_identity_support_ref_count": (
                self.bundle_source_identity_support_ref_count
            ),
            "bundle_source_type_diversity": self.bundle_source_type_diversity,
            "bundle_retrieval_source_diversity": (
                self.bundle_retrieval_source_diversity
            ),
            "bundle_source_type_support_diversity": (
                self.bundle_source_type_support_diversity
            ),
            "bundle_retrieval_source_support_diversity": (
                self.bundle_retrieval_source_support_diversity
            ),
            "bundle_source_proximity_support_count": (
                self.bundle_source_proximity_support_count
            ),
            "bundle_source_proximity_closest_distance": (
                self.bundle_source_proximity_closest_distance
            ),
            "bundle_source_proximity_distance_counts": dict(
                sorted(self.bundle_source_proximity_distance_counts.items())
            ),
            "bundle_source_chain_proximity_support_count": (
                self.bundle_source_chain_proximity_support_count
            ),
            "bundle_source_chain_proximity_closest_distance": (
                self.bundle_source_chain_proximity_closest_distance
            ),
            "bundle_source_chain_proximity_distance_counts": dict(
                sorted(self.bundle_source_chain_proximity_distance_counts.items())
            ),
            "bundle_diffuse_source_ref_count": self.bundle_diffuse_source_ref_count,
            "bundle_causal_support_count": self.bundle_causal_support_count,
            "bundle_communication_support_count": (
                self.bundle_communication_support_count
            ),
            "bundle_event_support_count": self.bundle_event_support_count,
            "bundle_exchange_support_count": self.bundle_exchange_support_count,
            "bundle_inference_support_count": self.bundle_inference_support_count,
            "bundle_location_support_count": self.bundle_location_support_count,
            "bundle_emotion_response_support_count": (
                self.bundle_emotion_response_support_count
            ),
            "bundle_symbolic_meaning_support_count": (
                self.bundle_symbolic_meaning_support_count
            ),
            "bundle_preference_support_count": self.bundle_preference_support_count,
            "bundle_favorite_support_count": self.bundle_favorite_support_count,
            "bundle_visual_support_count": self.bundle_visual_support_count,
            "bundle_typed_relation_support_count": (
                self.bundle_typed_relation_support_count
            ),
            "bundle_typed_relation_support_counts": dict(
                sorted(self.bundle_typed_relation_support_counts.items())
            ),
            "bundle_contrast_count": self.bundle_contrast_count,
            "role_requirement_complete": self.role_requirement_complete,
            "missing_required_roles": list(self.missing_required_roles),
            "bundle_risk_reason_codes": list(self.bundle_risk_reason_codes),
            "risk_reason_codes": list(risk_reason_codes),
            "fallback_reason": self.fallback_reason,
            "item_ids": [
                memory.item_id
                for memory in self.memories
                if memory.item_id is not None and memory.item_id.strip()
            ],
            "retrieval_orders": [
                int(memory.metadata["answer_context_retrieval_order"])
                for memory in self.memories
                if isinstance(memory.metadata.get("answer_context_retrieval_order"), int)
            ],
        }


def answer_context_from_evidence_bundle(
    memories: Sequence[RetrievedMemory],
    evidence_bundle: Mapping[str, object],
    *,
    cutoff: int,
) -> AnswerContext:
    """Build answer context from selected bundle items, falling back to raw top-k."""

    bounded_cutoff = max(0, cutoff)
    raw_slice = tuple(memories[:bounded_cutoff])
    bundle_items = _bundle_items(evidence_bundle)
    if not bundle_items:
        return AnswerContext(
            memories=retrieval_slice_answer_context(
                raw_slice,
                fallback_reason="empty_bundle",
            ),
            source="retrieval_slice",
            fallback_reason="empty_bundle",
        )
    bundle_context = _bundle_context_metadata(evidence_bundle)
    required_roles = _answer_context_required_roles(evidence_bundle)

    selected: list[RetrievedMemory] = []
    selected_required_roles: set[str] = set()
    skipped_required_roles: set[str] = set()
    selected_keys: set[tuple[str, object]] = set()
    selected_source_identity_keys: set[tuple[str, ...]] = set()
    selected_source_turn_refs: set[str] = set()
    non_noisy_bundle_source_turn_refs = _non_noisy_bundle_source_turn_refs(
        bundle_items,
        memories,
        bounded_cutoff=bounded_cutoff,
    )
    skipped = 0
    skipped_duplicate_source = 0
    skipped_noisy_overlap = 0
    for item in bundle_items:
        item_required_roles = _bundle_item_required_roles(
            item,
            required_roles=required_roles,
        )
        memory = _memory_for_bundle_item(item, memories)
        if memory is None:
            skipped += 1
            skipped_required_roles.update(item_required_roles)
            continue
        retrieval_order = _positive_int(item.get("retrieval_order"))
        if retrieval_order is None:
            retrieval_order = _retrieval_order_for_memory(memory, memories)
        if retrieval_order is None or retrieval_order > bounded_cutoff:
            skipped += 1
            skipped_required_roles.update(item_required_roles)
            continue
        key = _memory_key(memory, retrieval_order=retrieval_order)
        if key in selected_keys:
            continue
        source_identity_key = _bundle_source_identity_key(memory, item)
        if (
            source_identity_key
            and (
                source_identity_key in selected_source_identity_keys
                or (
                    not _bundle_item_has_noise_risk(memory)
                    and _source_identity_key_overlaps(
                        source_identity_key,
                        selected_source_identity_keys,
                    )
                )
            )
        ):
            skipped += 1
            skipped_duplicate_source += 1
            skipped_required_roles.update(item_required_roles)
            continue
        source_turn_refs = _bundle_source_turn_refs(memory, item)
        noisy_source_overlap = (
            _bundle_item_has_noise_risk(memory)
            and bool(
                source_turn_refs.intersection(
                    selected_source_turn_refs
                    | non_noisy_bundle_source_turn_refs
                )
            )
        )
        if noisy_source_overlap:
            skipped += 1
            skipped_noisy_overlap += 1
            skipped_required_roles.update(item_required_roles)
            continue
        selected_keys.add(key)
        selected_required_roles.update(item_required_roles)
        if source_identity_key:
            selected_source_identity_keys.add(source_identity_key)
        selected_source_turn_refs.update(source_turn_refs)
        selected.append(
            _with_answer_context_metadata(
                memory,
                bundle_item=item,
                bundle_context=bundle_context,
                retrieval_order=retrieval_order,
            )
        )

    if not selected:
        return AnswerContext(
            memories=retrieval_slice_answer_context(
                raw_slice,
                fallback_reason="no_bundle_items_within_cutoff",
            ),
            source="retrieval_slice",
            fallback_reason="no_bundle_items_within_cutoff",
            skipped_bundle_item_count=skipped,
            skipped_duplicate_source_bundle_item_count=skipped_duplicate_source,
            skipped_noisy_overlap_bundle_item_count=skipped_noisy_overlap,
        )

    bundle_selected_count = len(selected)
    skipped_missing_roles = tuple(
        role
        for role in required_roles
        if role in skipped_required_roles
        and role not in selected_required_roles
    )
    if skipped_missing_roles:
        bundle_context = _bundle_context_with_missing_roles(
            bundle_context,
            skipped_missing_roles,
        )
        selected = [
            _with_bundle_context_metadata(memory, bundle_context)
            for memory in selected
        ]
    backfilled_count = 0
    backfilled_precise_source_overlap_count = 0
    skipped_redundant_risky_backfill_count = 0
    skipped_redundant_source_backfill_count = 0
    skipped_redundant_role_backfill_count = 0
    if bundle_context.get("answer_context_role_requirement_complete") is False:
        backfill_result = backfill_incomplete_bundle_context(
            selected,
            selected_keys=selected_keys,
            raw_slice=raw_slice,
            bundle_context=bundle_context,
            bounded_cutoff=bounded_cutoff,
        )
        backfilled_count = backfill_result.backfilled_count
        backfilled_precise_source_overlap_count = (
            backfill_result.precise_source_overlap_count
        )
        skipped_redundant_risky_backfill_count = (
            backfill_result.skipped_redundant_risky_count
        )
        skipped_redundant_source_backfill_count = (
            backfill_result.skipped_redundant_source_count
        )
        skipped_redundant_role_backfill_count = (
            backfill_result.skipped_redundant_role_count
        )

    if skipped_duplicate_source or skipped_noisy_overlap:
        selected = [
            _with_bundle_skip_metadata(
                memory,
                skipped_duplicate_source_count=skipped_duplicate_source,
                skipped_noisy_overlap_count=skipped_noisy_overlap,
            )
            for memory in selected
        ]
    if (
        skipped_redundant_risky_backfill_count
        or skipped_redundant_source_backfill_count
        or skipped_redundant_role_backfill_count
    ):
        selected = [
            _with_backfill_skip_metadata(
                memory,
                skipped_redundant_risky_count=(
                    skipped_redundant_risky_backfill_count
                ),
                skipped_redundant_source_count=(
                    skipped_redundant_source_backfill_count
                ),
                skipped_redundant_role_count=skipped_redundant_role_backfill_count,
            )
            for memory in selected
        ]

    return AnswerContext(
        memories=tuple(selected),
        source="evidence_bundle",
        selected_bundle_item_count=bundle_selected_count,
        skipped_bundle_item_count=skipped,
        skipped_duplicate_source_bundle_item_count=skipped_duplicate_source,
        skipped_noisy_overlap_bundle_item_count=skipped_noisy_overlap,
        backfilled_retrieval_item_count=backfilled_count,
        backfilled_precise_source_overlap_count=(
            backfilled_precise_source_overlap_count
        ),
        skipped_redundant_risky_backfill_count=(
            skipped_redundant_risky_backfill_count
        ),
        skipped_redundant_source_backfill_count=(
            skipped_redundant_source_backfill_count
        ),
        skipped_redundant_role_backfill_count=(
            skipped_redundant_role_backfill_count
        ),
        bundle_confidence_score=float(
            bundle_context.get("answer_context_bundle_confidence_score") or 0.0
        ),
        bundle_confidence_band=str(
            bundle_context.get("answer_context_bundle_confidence_band") or ""
        ),
        bundle_bridge_count=(
            _positive_int(bundle_context.get("answer_context_bundle_bridge_count"))
            or 0
        ),
        bundle_source_ref_support_item_count=(
            _positive_int(
                bundle_context.get(
                    "answer_context_bundle_source_ref_support_item_count"
                )
            )
            or 0
        ),
        bundle_source_ref_support_ref_count=(
            _positive_int(
                bundle_context.get(
                    "answer_context_bundle_source_ref_support_ref_count"
                )
            )
            or 0
        ),
        bundle_source_identity_support_item_count=(
            _positive_int(
                bundle_context.get(
                    "answer_context_bundle_source_identity_support_item_count"
                )
            )
            or 0
        ),
        bundle_source_identity_support_ref_count=(
            _positive_int(
                bundle_context.get(
                    "answer_context_bundle_source_identity_support_ref_count"
                )
            )
            or 0
        ),
        bundle_source_type_diversity=(
            _positive_int(
                bundle_context.get("answer_context_bundle_source_type_diversity")
            )
            or 0
        ),
        bundle_retrieval_source_diversity=(
            _positive_int(
                bundle_context.get(
                    "answer_context_bundle_retrieval_source_diversity"
                )
            )
            or 0
        ),
        bundle_source_type_support_diversity=(
            _nonnegative_int(
                bundle_context.get(
                    "answer_context_bundle_source_type_support_diversity"
                )
            )
            or 0
        ),
        bundle_retrieval_source_support_diversity=(
            _nonnegative_int(
                bundle_context.get(
                    "answer_context_bundle_retrieval_source_support_diversity"
                )
            )
            or 0
        ),
        bundle_source_proximity_support_count=(
            _positive_int(
                bundle_context.get(
                    "answer_context_bundle_source_proximity_support_count"
                )
            )
            or 0
        ),
        bundle_source_proximity_closest_distance=(
            _positive_int(
                bundle_context.get(
                    "answer_context_bundle_source_proximity_closest_distance"
                )
            )
        ),
        bundle_source_proximity_distance_counts=_int_mapping(
            bundle_context.get(
                "answer_context_bundle_source_proximity_distance_counts"
            )
        ),
        bundle_source_chain_proximity_support_count=(
            _positive_int(
                bundle_context.get(
                    "answer_context_bundle_source_chain_proximity_support_count"
                )
            )
            or 0
        ),
        bundle_source_chain_proximity_closest_distance=(
            _positive_int(
                bundle_context.get(
                    "answer_context_bundle_source_chain_proximity_closest_distance"
                )
            )
        ),
        bundle_source_chain_proximity_distance_counts=_int_mapping(
            bundle_context.get(
                "answer_context_bundle_source_chain_proximity_distance_counts"
            )
        ),
        bundle_diffuse_source_ref_count=(
            _positive_int(
                bundle_context.get("answer_context_bundle_diffuse_source_ref_count")
            )
            or 0
        ),
        bundle_causal_support_count=(
            _positive_int(
                bundle_context.get("answer_context_bundle_causal_support_count")
            )
            or 0
        ),
        bundle_communication_support_count=(
            _positive_int(
                bundle_context.get(
                    "answer_context_bundle_communication_support_count"
                )
            )
            or 0
        ),
        bundle_event_support_count=(
            _positive_int(
                bundle_context.get("answer_context_bundle_event_support_count")
            )
            or 0
        ),
        bundle_exchange_support_count=(
            _positive_int(
                bundle_context.get("answer_context_bundle_exchange_support_count")
            )
            or 0
        ),
        bundle_inference_support_count=(
            _positive_int(
                bundle_context.get("answer_context_bundle_inference_support_count")
            )
            or 0
        ),
        bundle_location_support_count=(
            _positive_int(
                bundle_context.get("answer_context_bundle_location_support_count")
            )
            or 0
        ),
        bundle_emotion_response_support_count=(
            _positive_int(
                bundle_context.get(
                    "answer_context_bundle_emotion_response_support_count"
                )
            )
            or 0
        ),
        bundle_symbolic_meaning_support_count=(
            _positive_int(
                bundle_context.get(
                    "answer_context_bundle_symbolic_meaning_support_count"
                )
            )
            or 0
        ),
        bundle_preference_support_count=(
            _positive_int(
                bundle_context.get("answer_context_bundle_preference_support_count")
            )
            or 0
        ),
        bundle_favorite_support_count=(
            _positive_int(
                bundle_context.get("answer_context_bundle_favorite_support_count")
            )
            or 0
        ),
        bundle_visual_support_count=(
            _positive_int(
                bundle_context.get("answer_context_bundle_visual_support_count")
            )
            or 0
        ),
        bundle_typed_relation_support_count=(
            _positive_int(
                bundle_context.get("answer_context_bundle_typed_relation_support_count")
            )
            or 0
        ),
        bundle_typed_relation_support_counts=_int_mapping(
            bundle_context.get("answer_context_bundle_typed_relation_support_counts")
        ),
        bundle_contrast_count=(
            _positive_int(bundle_context.get("answer_context_bundle_contrast_count"))
            or 0
        ),
        role_requirement_complete=(
            bundle_context.get("answer_context_role_requirement_complete")
            if isinstance(
                bundle_context.get("answer_context_role_requirement_complete"),
                bool,
            )
            else None
        ),
        missing_required_roles=_string_tuple(
            bundle_context.get("answer_context_missing_required_roles")
        ),
        bundle_risk_reason_codes=_string_tuple(
            bundle_context.get("answer_context_bundle_risk_reason_codes")
        ),
    )


def answer_context_metrics(
    evaluations: Sequence[Mapping[str, object]],
    *,
    configured_cutoffs: Sequence[int],
    primary_cutoff: int,
) -> dict[str, object]:
    """Aggregate answer-context diagnostics across benchmark evaluations."""

    cutoffs = sorted(
        set(configured_cutoffs)
        | {
            int(cutoff)
            for evaluation in evaluations
            for cutoff in _mapping(evaluation.get("cutoff_results"))
            if str(cutoff).isdigit()
        }
    )
    by_cutoff: dict[str, object] = {}
    for cutoff in cutoffs:
        cutoff_payloads = [
            _mapping(_mapping(evaluation.get("cutoff_results")).get(str(cutoff)))
            for evaluation in evaluations
            if evaluation.get("scored") is True
        ]
        by_cutoff[str(cutoff)] = _answer_context_cutoff_metrics(
            cutoff_payloads,
            primary=cutoff == primary_cutoff,
        )
    primary = _mapping(by_cutoff.get(str(primary_cutoff)))
    return {
        "schema_version": "answer_context_metrics.v1",
        "primary_cutoff": primary_cutoff,
        "primary_evidence_bundle_context_rate": _metric_value(
            primary,
            "evidence_bundle_context_rate",
        ),
        "primary_avg_context_memory_count": _metric_value(
            primary,
            "avg_context_memory_count",
        ),
        "primary_avg_context_compression_ratio": _metric_value(
            primary,
            "avg_context_compression_ratio",
        ),
        "primary_total_skipped_redundant_risky_backfill_count": (
            _positive_int(
                primary.get("total_skipped_redundant_risky_backfill_count")
            )
            or 0
        ),
        "primary_avg_skipped_redundant_risky_backfill_count": _metric_value(
            primary,
            "avg_skipped_redundant_risky_backfill_count",
        ),
        "primary_total_skipped_redundant_source_backfill_count": (
            _positive_int(
                primary.get("total_skipped_redundant_source_backfill_count")
            )
            or 0
        ),
        "primary_avg_skipped_redundant_source_backfill_count": _metric_value(
            primary,
            "avg_skipped_redundant_source_backfill_count",
        ),
        "primary_total_skipped_redundant_role_backfill_count": (
            _positive_int(
                primary.get("total_skipped_redundant_role_backfill_count")
            )
            or 0
        ),
        "primary_avg_skipped_redundant_role_backfill_count": _metric_value(
            primary,
            "avg_skipped_redundant_role_backfill_count",
        ),
        "primary_total_skipped_duplicate_source_bundle_item_count": (
            _positive_int(
                primary.get("total_skipped_duplicate_source_bundle_item_count")
            )
            or 0
        ),
        "primary_avg_skipped_duplicate_source_bundle_item_count": _metric_value(
            primary,
            "avg_skipped_duplicate_source_bundle_item_count",
        ),
        "primary_total_skipped_noisy_overlap_bundle_item_count": (
            _positive_int(
                primary.get("total_skipped_noisy_overlap_bundle_item_count")
            )
            or 0
        ),
        "primary_avg_skipped_noisy_overlap_bundle_item_count": _metric_value(
            primary,
            "avg_skipped_noisy_overlap_bundle_item_count",
        ),
        "primary_risk_reason_counts": _int_mapping(
            primary.get("risk_reason_counts")
        ),
        "primary_total_backfilled_low_answerability_count": (
            _positive_int(primary.get("total_backfilled_low_answerability_count"))
            or 0
        ),
        "primary_total_backfilled_precise_source_overlap_count": (
            _positive_int(
                primary.get("total_backfilled_precise_source_overlap_count")
            )
            or 0
        ),
        "primary_avg_backfilled_precise_source_overlap_count": _metric_value(
            primary,
            "avg_backfilled_precise_source_overlap_count",
        ),
        "primary_avg_backfilled_low_answerability_count": _metric_value(
            primary,
            "avg_backfilled_low_answerability_count",
        ),
        "primary_total_backfilled_weak_source_locality_count": (
            _positive_int(
                primary.get("total_backfilled_weak_source_locality_count")
            )
            or 0
        ),
        "primary_avg_backfilled_weak_source_locality_count": _metric_value(
            primary,
            "avg_backfilled_weak_source_locality_count",
        ),
        "primary_backfilled_low_answerability_role_counts": _int_mapping(
            primary.get("backfilled_low_answerability_role_counts")
        ),
        "primary_backfilled_weak_source_locality_role_counts": _int_mapping(
            primary.get("backfilled_weak_source_locality_role_counts")
        ),
        "primary_total_backfilled_source_proximity_support_count": (
            _positive_int(
                primary.get("total_backfilled_source_proximity_support_count")
            )
            or 0
        ),
        "primary_avg_backfilled_source_proximity_support_count": _metric_value(
            primary,
            "avg_backfilled_source_proximity_support_count",
        ),
        "primary_total_backfilled_chained_source_proximity_support_count": (
            _positive_int(
                primary.get(
                    "total_backfilled_chained_source_proximity_support_count"
                )
            )
            or 0
        ),
        "primary_avg_backfilled_chained_source_proximity_support_count": (
            _metric_value(
                primary,
                "avg_backfilled_chained_source_proximity_support_count",
            )
        ),
        "primary_avg_backfilled_source_proximity_closest_distance": _metric_value(
            primary,
            "avg_backfilled_source_proximity_closest_distance",
        ),
        "primary_min_backfilled_source_proximity_closest_distance": (
            _positive_int(
                primary.get("min_backfilled_source_proximity_closest_distance")
            )
        ),
        "primary_avg_source_ref_coverage_rate": _metric_value(
            primary,
            "avg_source_ref_coverage_rate",
        ),
        "primary_total_compacted_fusion_source_ref_item_count": (
            _positive_int(
                primary.get("total_compacted_fusion_source_ref_item_count")
            )
            or 0
        ),
        "primary_total_compacted_fusion_source_ref_saved_count": (
            _positive_int(
                primary.get("total_compacted_fusion_source_ref_saved_count")
            )
            or 0
        ),
        "primary_avg_context_answerability_score": _metric_value(
            primary,
            "avg_context_answerability_score",
        ),
        "primary_avg_measured_context_answerability_score": _metric_value(
            primary,
            "avg_measured_context_answerability_score",
        ),
        "primary_total_unmeasured_context_answerability_count": (
            _positive_int(
                primary.get("total_unmeasured_context_answerability_count")
            )
            or 0
        ),
        "primary_avg_context_source_locality_score": _metric_value(
            primary,
            "avg_context_source_locality_score",
        ),
        "primary_avg_measured_context_source_locality_score": _metric_value(
            primary,
            "avg_measured_context_source_locality_score",
        ),
        "primary_total_unmeasured_context_source_locality_count": (
            _positive_int(
                primary.get("total_unmeasured_context_source_locality_count")
            )
            or 0
        ),
        "primary_avg_bundle_source_type_diversity": _metric_value(
            primary,
            "avg_bundle_source_type_diversity",
        ),
        "primary_max_bundle_source_type_diversity": (
            _positive_int(primary.get("max_bundle_source_type_diversity")) or 0
        ),
        "primary_avg_bundle_retrieval_source_diversity": _metric_value(
            primary,
            "avg_bundle_retrieval_source_diversity",
        ),
        "primary_max_bundle_retrieval_source_diversity": (
            _positive_int(primary.get("max_bundle_retrieval_source_diversity")) or 0
        ),
        "primary_avg_bundle_source_type_support_diversity": _metric_value(
            primary,
            "avg_bundle_source_type_support_diversity",
        ),
        "primary_max_bundle_source_type_support_diversity": (
            _positive_int(primary.get("max_bundle_source_type_support_diversity"))
            or 0
        ),
        "primary_avg_bundle_retrieval_source_support_diversity": _metric_value(
            primary,
            "avg_bundle_retrieval_source_support_diversity",
        ),
        "primary_max_bundle_retrieval_source_support_diversity": (
            _positive_int(
                primary.get("max_bundle_retrieval_source_support_diversity")
            )
            or 0
        ),
        "primary_avg_bundle_source_ref_support_item_count": _metric_value(
            primary,
            "avg_bundle_source_ref_support_item_count",
        ),
        "primary_total_bundle_source_ref_support_item_count": (
            _positive_int(
                primary.get("total_bundle_source_ref_support_item_count")
            )
            or 0
        ),
        "primary_avg_bundle_source_identity_support_item_count": _metric_value(
            primary,
            "avg_bundle_source_identity_support_item_count",
        ),
        "primary_total_bundle_source_identity_support_item_count": (
            _positive_int(
                primary.get("total_bundle_source_identity_support_item_count")
            )
            or 0
        ),
        "primary_avg_bundle_source_proximity_support_count": _metric_value(
            primary,
            "avg_bundle_source_proximity_support_count",
        ),
        "primary_total_bundle_source_proximity_support_count": (
            _positive_int(
                primary.get("total_bundle_source_proximity_support_count")
            )
            or 0
        ),
        "primary_avg_bundle_source_proximity_closest_distance": _metric_value(
            primary,
            "avg_bundle_source_proximity_closest_distance",
        ),
        "primary_min_bundle_source_proximity_closest_distance": (
            _positive_int(
                primary.get("min_bundle_source_proximity_closest_distance")
            )
        ),
        "primary_bundle_source_proximity_distance_counts": _int_mapping(
            primary.get("bundle_source_proximity_distance_counts")
        ),
        "primary_avg_bundle_source_chain_proximity_support_count": _metric_value(
            primary,
            "avg_bundle_source_chain_proximity_support_count",
        ),
        "primary_total_bundle_source_chain_proximity_support_count": (
            _positive_int(
                primary.get("total_bundle_source_chain_proximity_support_count")
            )
            or 0
        ),
        "primary_avg_bundle_source_chain_proximity_closest_distance": _metric_value(
            primary,
            "avg_bundle_source_chain_proximity_closest_distance",
        ),
        "primary_min_bundle_source_chain_proximity_closest_distance": (
            _positive_int(
                primary.get("min_bundle_source_chain_proximity_closest_distance")
            )
        ),
        "primary_bundle_source_chain_proximity_distance_counts": _int_mapping(
            primary.get("bundle_source_chain_proximity_distance_counts")
        ),
        "primary_avg_bundle_diffuse_source_ref_count": _metric_value(
            primary,
            "avg_bundle_diffuse_source_ref_count",
        ),
        "primary_total_bundle_diffuse_source_ref_count": (
            _positive_int(primary.get("total_bundle_diffuse_source_ref_count"))
            or 0
        ),
        "by_cutoff": by_cutoff,
    }


def _answer_context_cutoff_metrics(
    cutoff_payloads: Sequence[Mapping[str, object]],
    *,
    primary: bool,
) -> dict[str, object]:
    source_counts: Counter[str] = Counter()
    fallback_reason_counts: Counter[str] = Counter()
    context_counts: list[int] = []
    raw_counts: list[int] = []
    compression_ratios: list[float] = []
    selected_bundle_counts: list[int] = []
    skipped_bundle_counts: list[int] = []
    skipped_duplicate_source_bundle_counts: list[int] = []
    skipped_noisy_overlap_bundle_counts: list[int] = []
    backfilled_retrieval_counts: list[int] = []
    skipped_redundant_risky_backfill_counts: list[int] = []
    skipped_redundant_source_backfill_counts: list[int] = []
    skipped_redundant_role_backfill_counts: list[int] = []
    backfilled_broad_summary_counts: list[int] = []
    backfilled_conflict_or_stale_counts: list[int] = []
    backfilled_precise_source_overlap_counts: list[int] = []
    backfilled_low_answerability_counts: list[int] = []
    backfilled_weak_source_locality_counts: list[int] = []
    backfilled_low_answerability_role_counts: Counter[str] = Counter()
    backfilled_weak_source_locality_role_counts: Counter[str] = Counter()
    backfilled_source_proximity_support_counts: list[int] = []
    backfilled_chained_source_proximity_support_counts: list[int] = []
    backfilled_source_proximity_closest_distances: list[int] = []
    source_ref_counts: list[int] = []
    source_ref_item_counts: list[int] = []
    source_refless_item_counts: list[int] = []
    source_ref_coverage_rates: list[float] = []
    compacted_fusion_source_ref_item_counts: list[int] = []
    compacted_fusion_source_ref_saved_counts: list[int] = []
    bundle_confidence_scores: list[float] = []
    bundle_confidence_band_counts: Counter[str] = Counter()
    bundle_bridge_counts: list[int] = []
    bundle_source_ref_support_item_counts: list[int] = []
    bundle_source_ref_support_ref_counts: list[int] = []
    bundle_source_identity_support_item_counts: list[int] = []
    bundle_source_identity_support_ref_counts: list[int] = []
    bundle_source_type_diversities: list[int] = []
    bundle_retrieval_source_diversities: list[int] = []
    bundle_source_type_support_diversities: list[int] = []
    bundle_retrieval_source_support_diversities: list[int] = []
    bundle_source_proximity_support_counts: list[int] = []
    bundle_source_proximity_closest_distances: list[int] = []
    bundle_source_proximity_distance_counts: Counter[str] = Counter()
    bundle_source_chain_proximity_support_counts: list[int] = []
    bundle_source_chain_proximity_closest_distances: list[int] = []
    bundle_source_chain_proximity_distance_counts: Counter[str] = Counter()
    bundle_diffuse_source_ref_counts: list[int] = []
    bundle_causal_support_counts: list[int] = []
    bundle_communication_support_counts: list[int] = []
    bundle_event_support_counts: list[int] = []
    bundle_exchange_support_counts: list[int] = []
    bundle_inference_support_counts: list[int] = []
    bundle_location_support_counts: list[int] = []
    bundle_emotion_response_support_counts: list[int] = []
    bundle_symbolic_meaning_support_counts: list[int] = []
    bundle_preference_support_counts: list[int] = []
    bundle_favorite_support_counts: list[int] = []
    bundle_visual_support_counts: list[int] = []
    bundle_typed_relation_support_counts: list[int] = []
    bundle_typed_relation_support_role_counts: Counter[str] = Counter()
    bundle_contrast_counts: list[int] = []
    answerability_scores: list[float] = []
    measured_answerability_scores: list[float] = []
    unmeasured_answerability_counts: list[int] = []
    source_locality_scores: list[float] = []
    measured_source_locality_scores: list[float] = []
    unmeasured_source_locality_counts: list[int] = []
    missing_required_role_counts: Counter[str] = Counter()
    bundle_risk_reason_counts: Counter[str] = Counter()
    risk_reason_counts: Counter[str] = Counter()
    incomplete_role_requirement_count = 0
    missing_context_count = 0

    for payload in cutoff_payloads:
        context = _mapping(payload.get("answer_context"))
        if not context:
            missing_context_count += 1
            continue
        source = str(context.get("source") or "unknown").strip() or "unknown"
        source_counts[source] += 1
        fallback_reason = str(context.get("fallback_reason") or "").strip()
        if fallback_reason:
            fallback_reason_counts[fallback_reason] += 1
        context_count = _positive_int(context.get("memory_count")) or 0
        raw_count = _positive_int(payload.get("memories_evaluated")) or 0
        context_counts.append(context_count)
        raw_counts.append(raw_count)
        if raw_count > 0:
            compression_ratios.append(round(context_count / raw_count, 6))
        selected_bundle_counts.append(
            _positive_int(context.get("selected_bundle_item_count")) or 0
        )
        skipped_bundle_counts.append(
            _positive_int(context.get("skipped_bundle_item_count")) or 0
        )
        skipped_duplicate_source_bundle_counts.append(
            _positive_int(
                context.get("skipped_duplicate_source_bundle_item_count")
            )
            or 0
        )
        skipped_noisy_overlap_bundle_counts.append(
            _positive_int(
                context.get("skipped_noisy_overlap_bundle_item_count")
            )
            or 0
        )
        backfilled_retrieval_counts.append(
            _positive_int(context.get("backfilled_retrieval_item_count")) or 0
        )
        skipped_redundant_risky_backfill_counts.append(
            _positive_int(
                context.get("skipped_redundant_risky_backfill_count")
            )
            or 0
        )
        skipped_redundant_source_backfill_counts.append(
            _positive_int(
                context.get("skipped_redundant_source_backfill_count")
            )
            or 0
        )
        skipped_redundant_role_backfill_counts.append(
            _positive_int(
                context.get("skipped_redundant_role_backfill_count")
            )
            or 0
        )
        backfilled_broad_summary_counts.append(
            _positive_int(context.get("backfilled_broad_summary_count")) or 0
        )
        backfilled_conflict_or_stale_counts.append(
            _positive_int(context.get("backfilled_conflict_or_stale_count")) or 0
        )
        backfilled_precise_source_overlap_counts.append(
            _positive_int(
                context.get("backfilled_precise_source_overlap_count")
            )
            or 0
        )
        backfilled_low_answerability_counts.append(
            _positive_int(context.get("backfilled_low_answerability_count")) or 0
        )
        backfilled_weak_source_locality_counts.append(
            _positive_int(context.get("backfilled_weak_source_locality_count")) or 0
        )
        backfilled_low_answerability_role_counts.update(
            _int_mapping(context.get("backfilled_low_answerability_role_counts"))
        )
        backfilled_weak_source_locality_role_counts.update(
            _int_mapping(context.get("backfilled_weak_source_locality_role_counts"))
        )
        backfilled_source_proximity_support_counts.append(
            _positive_int(
                context.get("backfilled_source_proximity_support_count")
            )
            or 0
        )
        backfilled_chained_source_proximity_support_counts.append(
            _positive_int(
                context.get(
                    "backfilled_chained_source_proximity_support_count"
                )
            )
            or 0
        )
        backfilled_proximity_distance = _positive_int(
            context.get("backfilled_source_proximity_closest_distance")
        )
        if backfilled_proximity_distance is not None:
            backfilled_source_proximity_closest_distances.append(
                backfilled_proximity_distance
            )
        source_ref_counts.append(_positive_int(context.get("source_ref_count")) or 0)
        source_ref_item_counts.append(
            _positive_int(context.get("source_ref_item_count")) or 0
        )
        source_refless_item_counts.append(
            _positive_int(context.get("source_refless_item_count")) or 0
        )
        source_ref_coverage_rates.append(
            _metric_value(context, "source_ref_coverage_rate")
        )
        compacted_fusion_source_ref_item_counts.append(
            _positive_int(
                context.get("compacted_fusion_source_ref_item_count")
            )
            or 0
        )
        compacted_fusion_source_ref_saved_counts.append(
            _positive_int(
                context.get("compacted_fusion_source_ref_saved_count")
            )
            or 0
        )
        answerability_scores.append(
            _metric_value(context, "avg_answerability_score")
        )
        measured_answerability_score = _metric_value(
            context,
            "avg_measured_answerability_score",
        )
        if measured_answerability_score > 0:
            measured_answerability_scores.append(measured_answerability_score)
        unmeasured_answerability_counts.append(
            _positive_int(context.get("unmeasured_answerability_count")) or 0
        )
        source_locality_scores.append(
            _metric_value(context, "avg_source_locality_score")
        )
        measured_source_locality_score = _metric_value(
            context,
            "avg_measured_source_locality_score",
        )
        if measured_source_locality_score > 0:
            measured_source_locality_scores.append(measured_source_locality_score)
        unmeasured_source_locality_counts.append(
            _positive_int(context.get("unmeasured_source_locality_count")) or 0
        )
        confidence_score = _metric_value(context, "bundle_confidence_score")
        if confidence_score > 0:
            bundle_confidence_scores.append(confidence_score)
        confidence_band = str(context.get("bundle_confidence_band") or "").strip()
        if confidence_band:
            bundle_confidence_band_counts[confidence_band] += 1
        bundle_bridge_counts.append(
            _positive_int(context.get("bundle_bridge_count")) or 0
        )
        bundle_source_ref_support_item_counts.append(
            _positive_int(context.get("bundle_source_ref_support_item_count")) or 0
        )
        bundle_source_ref_support_ref_counts.append(
            _positive_int(context.get("bundle_source_ref_support_ref_count")) or 0
        )
        bundle_source_identity_support_item_counts.append(
            _positive_int(
                context.get("bundle_source_identity_support_item_count")
            )
            or 0
        )
        bundle_source_identity_support_ref_counts.append(
            _positive_int(context.get("bundle_source_identity_support_ref_count"))
            or 0
        )
        bundle_source_type_diversities.append(
            _positive_int(context.get("bundle_source_type_diversity")) or 0
        )
        bundle_retrieval_source_diversities.append(
            _positive_int(context.get("bundle_retrieval_source_diversity")) or 0
        )
        bundle_source_type_support_diversities.append(
            _positive_int(context.get("bundle_source_type_support_diversity")) or 0
        )
        bundle_retrieval_source_support_diversities.append(
            _positive_int(context.get("bundle_retrieval_source_support_diversity"))
            or 0
        )
        bundle_source_proximity_support_counts.append(
            _positive_int(context.get("bundle_source_proximity_support_count")) or 0
        )
        source_proximity_closest_distance = _positive_int(
            context.get("bundle_source_proximity_closest_distance")
        )
        if source_proximity_closest_distance is not None:
            bundle_source_proximity_closest_distances.append(
                source_proximity_closest_distance
            )
        bundle_source_proximity_distance_counts.update(
            _int_mapping(context.get("bundle_source_proximity_distance_counts"))
        )
        bundle_source_chain_proximity_support_counts.append(
            _positive_int(
                context.get("bundle_source_chain_proximity_support_count")
            )
            or 0
        )
        source_chain_proximity_closest_distance = _positive_int(
            context.get("bundle_source_chain_proximity_closest_distance")
        )
        if source_chain_proximity_closest_distance is not None:
            bundle_source_chain_proximity_closest_distances.append(
                source_chain_proximity_closest_distance
            )
        bundle_source_chain_proximity_distance_counts.update(
            _int_mapping(
                context.get("bundle_source_chain_proximity_distance_counts")
            )
        )
        bundle_diffuse_source_ref_counts.append(
            _positive_int(context.get("bundle_diffuse_source_ref_count")) or 0
        )
        bundle_causal_support_counts.append(
            _positive_int(context.get("bundle_causal_support_count")) or 0
        )
        bundle_communication_support_counts.append(
            _positive_int(context.get("bundle_communication_support_count")) or 0
        )
        bundle_event_support_counts.append(
            _positive_int(context.get("bundle_event_support_count")) or 0
        )
        bundle_exchange_support_counts.append(
            _positive_int(context.get("bundle_exchange_support_count")) or 0
        )
        bundle_inference_support_counts.append(
            _positive_int(context.get("bundle_inference_support_count")) or 0
        )
        bundle_location_support_counts.append(
            _positive_int(context.get("bundle_location_support_count")) or 0
        )
        bundle_emotion_response_support_counts.append(
            _positive_int(context.get("bundle_emotion_response_support_count")) or 0
        )
        bundle_symbolic_meaning_support_counts.append(
            _positive_int(context.get("bundle_symbolic_meaning_support_count")) or 0
        )
        bundle_preference_support_counts.append(
            _positive_int(context.get("bundle_preference_support_count")) or 0
        )
        bundle_favorite_support_counts.append(
            _positive_int(context.get("bundle_favorite_support_count")) or 0
        )
        bundle_visual_support_counts.append(
            _positive_int(context.get("bundle_visual_support_count")) or 0
        )
        bundle_typed_relation_support_counts.append(
            _positive_int(context.get("bundle_typed_relation_support_count")) or 0
        )
        bundle_typed_relation_support_role_counts.update(
            _int_mapping(context.get("bundle_typed_relation_support_counts"))
        )
        bundle_contrast_counts.append(
            _positive_int(context.get("bundle_contrast_count")) or 0
        )
        if context.get("role_requirement_complete") is False:
            incomplete_role_requirement_count += 1
        missing_required_role_counts.update(
            _string_tuple(context.get("missing_required_roles"))
        )
        bundle_risk_reason_counts.update(
            _string_tuple(context.get("bundle_risk_reason_codes"))
        )
        risk_reason_counts.update(_string_tuple(context.get("risk_reason_codes")))

    total = len(cutoff_payloads)
    evidence_bundle_count = source_counts.get("evidence_bundle", 0)
    fallback_count = total - evidence_bundle_count - missing_context_count
    return {
        "primary": primary,
        "total": total,
        "missing_context_count": missing_context_count,
        "evidence_bundle_context_count": evidence_bundle_count,
        "fallback_context_count": fallback_count,
        "evidence_bundle_context_rate": _ratio(evidence_bundle_count, total),
        "source_counts": dict(sorted(source_counts.items())),
        "fallback_reason_counts": dict(sorted(fallback_reason_counts.items())),
        "avg_context_memory_count": _avg(context_counts),
        "avg_raw_memories_evaluated": _avg(raw_counts),
        "avg_context_compression_ratio": _avg(compression_ratios),
        "avg_selected_bundle_item_count": _avg(selected_bundle_counts),
        "avg_skipped_bundle_item_count": _avg(skipped_bundle_counts),
        "avg_skipped_duplicate_source_bundle_item_count": _avg(
            skipped_duplicate_source_bundle_counts
        ),
        "total_skipped_duplicate_source_bundle_item_count": sum(
            skipped_duplicate_source_bundle_counts
        ),
        "avg_skipped_noisy_overlap_bundle_item_count": _avg(
            skipped_noisy_overlap_bundle_counts
        ),
        "total_skipped_noisy_overlap_bundle_item_count": sum(
            skipped_noisy_overlap_bundle_counts
        ),
        "avg_backfilled_retrieval_item_count": _avg(backfilled_retrieval_counts),
        "total_backfilled_retrieval_item_count": sum(backfilled_retrieval_counts),
        "avg_skipped_redundant_risky_backfill_count": _avg(
            skipped_redundant_risky_backfill_counts
        ),
        "total_skipped_redundant_risky_backfill_count": sum(
            skipped_redundant_risky_backfill_counts
        ),
        "avg_skipped_redundant_source_backfill_count": _avg(
            skipped_redundant_source_backfill_counts
        ),
        "total_skipped_redundant_source_backfill_count": sum(
            skipped_redundant_source_backfill_counts
        ),
        "avg_skipped_redundant_role_backfill_count": _avg(
            skipped_redundant_role_backfill_counts
        ),
        "total_skipped_redundant_role_backfill_count": sum(
            skipped_redundant_role_backfill_counts
        ),
        "total_backfilled_broad_summary_count": sum(
            backfilled_broad_summary_counts
        ),
        "total_backfilled_conflict_or_stale_count": sum(
            backfilled_conflict_or_stale_counts
        ),
        "total_backfilled_precise_source_overlap_count": sum(
            backfilled_precise_source_overlap_counts
        ),
        "avg_backfilled_precise_source_overlap_count": _avg(
            backfilled_precise_source_overlap_counts
        ),
        "total_backfilled_low_answerability_count": sum(
            backfilled_low_answerability_counts
        ),
        "avg_backfilled_low_answerability_count": _avg(
            backfilled_low_answerability_counts
        ),
        "total_backfilled_weak_source_locality_count": sum(
            backfilled_weak_source_locality_counts
        ),
        "avg_backfilled_weak_source_locality_count": _avg(
            backfilled_weak_source_locality_counts
        ),
        "backfilled_low_answerability_role_counts": dict(
            sorted(backfilled_low_answerability_role_counts.items())
        ),
        "backfilled_weak_source_locality_role_counts": dict(
            sorted(backfilled_weak_source_locality_role_counts.items())
        ),
        "total_backfilled_source_proximity_support_count": sum(
            backfilled_source_proximity_support_counts
        ),
        "avg_backfilled_source_proximity_support_count": _avg(
            backfilled_source_proximity_support_counts
        ),
        "total_backfilled_chained_source_proximity_support_count": sum(
            backfilled_chained_source_proximity_support_counts
        ),
        "avg_backfilled_chained_source_proximity_support_count": _avg(
            backfilled_chained_source_proximity_support_counts
        ),
        "avg_backfilled_source_proximity_closest_distance": _avg(
            backfilled_source_proximity_closest_distances
        ),
        "min_backfilled_source_proximity_closest_distance": (
            min(backfilled_source_proximity_closest_distances)
            if backfilled_source_proximity_closest_distances
            else None
        ),
        "avg_source_ref_count": _avg(source_ref_counts),
        "avg_source_ref_item_count": _avg(source_ref_item_counts),
        "avg_source_refless_item_count": _avg(source_refless_item_counts),
        "avg_source_ref_coverage_rate": _avg(source_ref_coverage_rates),
        "avg_compacted_fusion_source_ref_item_count": _avg(
            compacted_fusion_source_ref_item_counts
        ),
        "total_compacted_fusion_source_ref_item_count": sum(
            compacted_fusion_source_ref_item_counts
        ),
        "avg_compacted_fusion_source_ref_saved_count": _avg(
            compacted_fusion_source_ref_saved_counts
        ),
        "total_compacted_fusion_source_ref_saved_count": sum(
            compacted_fusion_source_ref_saved_counts
        ),
        "avg_context_answerability_score": _avg(answerability_scores),
        "avg_measured_context_answerability_score": _avg(
            measured_answerability_scores
        ),
        "total_unmeasured_context_answerability_count": sum(
            unmeasured_answerability_counts
        ),
        "avg_context_source_locality_score": _avg(source_locality_scores),
        "avg_measured_context_source_locality_score": _avg(
            measured_source_locality_scores
        ),
        "total_unmeasured_context_source_locality_count": sum(
            unmeasured_source_locality_counts
        ),
        "avg_bundle_confidence_score": _avg(bundle_confidence_scores),
        "bundle_confidence_band_counts": dict(
            sorted(bundle_confidence_band_counts.items())
        ),
        "avg_bundle_bridge_count": _avg(bundle_bridge_counts),
        "total_bundle_bridge_count": sum(bundle_bridge_counts),
        "avg_bundle_source_ref_support_item_count": _avg(
            bundle_source_ref_support_item_counts
        ),
        "total_bundle_source_ref_support_item_count": sum(
            bundle_source_ref_support_item_counts
        ),
        "avg_bundle_source_ref_support_ref_count": _avg(
            bundle_source_ref_support_ref_counts
        ),
        "total_bundle_source_ref_support_ref_count": sum(
            bundle_source_ref_support_ref_counts
        ),
        "avg_bundle_source_identity_support_item_count": _avg(
            bundle_source_identity_support_item_counts
        ),
        "total_bundle_source_identity_support_item_count": sum(
            bundle_source_identity_support_item_counts
        ),
        "avg_bundle_source_identity_support_ref_count": _avg(
            bundle_source_identity_support_ref_counts
        ),
        "total_bundle_source_identity_support_ref_count": sum(
            bundle_source_identity_support_ref_counts
        ),
        "avg_bundle_source_type_diversity": _avg(
            bundle_source_type_diversities
        ),
        "max_bundle_source_type_diversity": (
            max(bundle_source_type_diversities)
            if bundle_source_type_diversities
            else 0
        ),
        "avg_bundle_retrieval_source_diversity": _avg(
            bundle_retrieval_source_diversities
        ),
        "max_bundle_retrieval_source_diversity": (
            max(bundle_retrieval_source_diversities)
            if bundle_retrieval_source_diversities
            else 0
        ),
        "avg_bundle_source_type_support_diversity": _avg(
            bundle_source_type_support_diversities
        ),
        "max_bundle_source_type_support_diversity": (
            max(bundle_source_type_support_diversities)
            if bundle_source_type_support_diversities
            else 0
        ),
        "avg_bundle_retrieval_source_support_diversity": _avg(
            bundle_retrieval_source_support_diversities
        ),
        "max_bundle_retrieval_source_support_diversity": (
            max(bundle_retrieval_source_support_diversities)
            if bundle_retrieval_source_support_diversities
            else 0
        ),
        "avg_bundle_source_proximity_support_count": _avg(
            bundle_source_proximity_support_counts
        ),
        "total_bundle_source_proximity_support_count": sum(
            bundle_source_proximity_support_counts
        ),
        "avg_bundle_source_proximity_closest_distance": _avg(
            bundle_source_proximity_closest_distances
        ),
        "min_bundle_source_proximity_closest_distance": (
            min(bundle_source_proximity_closest_distances)
            if bundle_source_proximity_closest_distances
            else None
        ),
        "bundle_source_proximity_distance_counts": dict(
            sorted(bundle_source_proximity_distance_counts.items())
        ),
        "avg_bundle_source_chain_proximity_support_count": _avg(
            bundle_source_chain_proximity_support_counts
        ),
        "total_bundle_source_chain_proximity_support_count": sum(
            bundle_source_chain_proximity_support_counts
        ),
        "avg_bundle_source_chain_proximity_closest_distance": _avg(
            bundle_source_chain_proximity_closest_distances
        ),
        "min_bundle_source_chain_proximity_closest_distance": (
            min(bundle_source_chain_proximity_closest_distances)
            if bundle_source_chain_proximity_closest_distances
            else None
        ),
        "bundle_source_chain_proximity_distance_counts": dict(
            sorted(bundle_source_chain_proximity_distance_counts.items())
        ),
        "avg_bundle_diffuse_source_ref_count": _avg(
            bundle_diffuse_source_ref_counts
        ),
        "total_bundle_diffuse_source_ref_count": sum(
            bundle_diffuse_source_ref_counts
        ),
        "avg_bundle_causal_support_count": _avg(bundle_causal_support_counts),
        "total_bundle_causal_support_count": sum(bundle_causal_support_counts),
        "avg_bundle_communication_support_count": _avg(
            bundle_communication_support_counts
        ),
        "total_bundle_communication_support_count": sum(
            bundle_communication_support_counts
        ),
        "avg_bundle_event_support_count": _avg(bundle_event_support_counts),
        "total_bundle_event_support_count": sum(bundle_event_support_counts),
        "avg_bundle_exchange_support_count": _avg(bundle_exchange_support_counts),
        "total_bundle_exchange_support_count": sum(bundle_exchange_support_counts),
        "avg_bundle_inference_support_count": _avg(
            bundle_inference_support_counts
        ),
        "total_bundle_inference_support_count": sum(
            bundle_inference_support_counts
        ),
        "avg_bundle_location_support_count": _avg(
            bundle_location_support_counts
        ),
        "total_bundle_location_support_count": sum(
            bundle_location_support_counts
        ),
        "avg_bundle_emotion_response_support_count": _avg(
            bundle_emotion_response_support_counts
        ),
        "total_bundle_emotion_response_support_count": sum(
            bundle_emotion_response_support_counts
        ),
        "avg_bundle_symbolic_meaning_support_count": _avg(
            bundle_symbolic_meaning_support_counts
        ),
        "total_bundle_symbolic_meaning_support_count": sum(
            bundle_symbolic_meaning_support_counts
        ),
        "avg_bundle_preference_support_count": _avg(
            bundle_preference_support_counts
        ),
        "total_bundle_preference_support_count": sum(
            bundle_preference_support_counts
        ),
        "avg_bundle_favorite_support_count": _avg(bundle_favorite_support_counts),
        "total_bundle_favorite_support_count": sum(bundle_favorite_support_counts),
        "avg_bundle_visual_support_count": _avg(bundle_visual_support_counts),
        "total_bundle_visual_support_count": sum(bundle_visual_support_counts),
        "avg_bundle_typed_relation_support_count": _avg(
            bundle_typed_relation_support_counts
        ),
        "total_bundle_typed_relation_support_count": sum(
            bundle_typed_relation_support_counts
        ),
        "bundle_typed_relation_support_role_counts": dict(
            sorted(bundle_typed_relation_support_role_counts.items())
        ),
        "avg_bundle_contrast_count": _avg(bundle_contrast_counts),
        "total_bundle_contrast_count": sum(bundle_contrast_counts),
        "incomplete_role_requirement_count": incomplete_role_requirement_count,
        "missing_required_role_counts": dict(
            sorted(missing_required_role_counts.items())
        ),
        "bundle_risk_reason_counts": dict(sorted(bundle_risk_reason_counts.items())),
        "risk_reason_counts": dict(sorted(risk_reason_counts.items())),
    }


def _memory_for_bundle_item(
    item: Mapping[str, object],
    memories: Sequence[RetrievedMemory],
) -> RetrievedMemory | None:
    item_id = str(item.get("id") or "").strip()
    if item_id:
        for memory in memories:
            if memory.item_id == item_id:
                return memory

    source_refs = set(_source_match_refs_from_bundle_item(item))
    if source_refs:
        session_source_refs = _session_source_match_refs(source_refs)
        if session_source_refs:
            for memory in memories:
                if session_source_refs.intersection(
                    _session_source_match_refs(
                        _precise_source_match_refs_from_memory(memory)
                    )
                ):
                    return memory
            for memory in memories:
                if session_source_refs.intersection(
                    _session_source_match_refs(_source_match_refs_from_memory(memory))
                ):
                    return memory
        else:
            for memory in memories:
                if source_refs.intersection(
                    _precise_source_match_refs_from_memory(memory)
                ):
                    return memory
            for memory in memories:
                if source_refs.intersection(_source_match_refs_from_memory(memory)):
                    return memory

    rank = _positive_int(item.get("rank"))
    if rank is not None:
        for memory in memories:
            if memory.rank == rank:
                return memory

    retrieval_order = _positive_int(item.get("retrieval_order"))
    if retrieval_order is not None and 1 <= retrieval_order <= len(memories):
        return memories[retrieval_order - 1]
    return None


def _session_source_match_refs(source_refs: Sequence[str]) -> set[str]:
    return {
        ref
        for ref in source_refs
        if str(ref).startswith("source_session_turn_refs:")
    }


def _with_answer_context_metadata(
    memory: RetrievedMemory,
    *,
    bundle_item: Mapping[str, object],
    bundle_context: Mapping[str, object],
    retrieval_order: int,
) -> RetrievedMemory:
    metadata = dict(memory.metadata)
    metadata["answer_context_retrieval_order"] = retrieval_order
    metadata.update(bundle_context)
    role = str(bundle_item.get("role") or "").strip()
    if role:
        metadata["answer_context_role"] = role
    reason_codes = _string_tuple(bundle_item.get("planner_reason_codes"))
    if reason_codes:
        metadata["answer_context_reason_codes"] = reason_codes
    eligibility_reasons = _string_tuple(bundle_item.get("eligibility_reason_codes"))
    if eligibility_reasons:
        metadata["answer_context_eligibility_reason_codes"] = eligibility_reasons
    _add_answer_context_risk_codes(
        metadata,
        _risk_reason_codes(reason_codes, eligibility_reasons),
    )
    query_roles = _string_tuple(bundle_item.get("query_roles"))
    if query_roles:
        metadata["answer_context_query_roles"] = query_roles
    source_type = str(bundle_item.get("source_type") or "").strip()
    if source_type:
        metadata["answer_context_source_type"] = source_type
    source_types = _string_tuple(bundle_item.get("source_types"))
    if source_types:
        metadata["answer_context_source_types"] = source_types
    retrieval_sources = _string_tuple(bundle_item.get("retrieval_sources"))
    if retrieval_sources:
        metadata["answer_context_retrieval_sources"] = retrieval_sources
    relation_category_hits = _string_tuple(bundle_item.get("relation_category_hits"))
    if relation_category_hits:
        metadata["answer_context_relation_category_hits"] = relation_category_hits
    entity_hits = _string_tuple(bundle_item.get("entity_hits"))
    if entity_hits:
        metadata["answer_context_entity_hits"] = entity_hits
    speaker_hits = _string_tuple(bundle_item.get("speaker_hits"))
    if speaker_hits:
        metadata["answer_context_speaker_hits"] = speaker_hits
    answerability_score = _metric_value(bundle_item, "answerability_score")
    if answerability_score > 0:
        metadata["answer_context_answerability_score"] = round(
            answerability_score,
            6,
        )
    source_locality_score = _metric_value(bundle_item, "source_locality_score")
    if source_locality_score > 0:
        metadata["answer_context_source_locality_score"] = round(
            source_locality_score,
            6,
        )
    source_refs = _merged_source_refs(memory, bundle_item)
    return RetrievedMemory(
        text=memory.text,
        rank=memory.rank,
        score=memory.score,
        item_id=memory.item_id,
        created_at=memory.created_at,
        source_refs=source_refs,
        metadata=metadata,
    )


def _with_bundle_skip_metadata(
    memory: RetrievedMemory,
    *,
    skipped_duplicate_source_count: int,
    skipped_noisy_overlap_count: int,
) -> RetrievedMemory:
    metadata = dict(memory.metadata)
    if skipped_duplicate_source_count > 0:
        metadata["answer_context_skipped_duplicate_source_bundle_item_count"] = (
            skipped_duplicate_source_count
        )
    if skipped_noisy_overlap_count > 0:
        metadata["answer_context_skipped_noisy_overlap_bundle_item_count"] = (
            skipped_noisy_overlap_count
        )
    _add_answer_context_risk_codes(
        metadata,
        (
            *(
                ("risk:skipped_duplicate_source_bundle_item",)
                if skipped_duplicate_source_count > 0
                else ()
            ),
            *(
                ("risk:skipped_noisy_overlap_bundle_item",)
                if skipped_noisy_overlap_count > 0
                else ()
            ),
        ),
    )
    return RetrievedMemory(
        text=memory.text,
        rank=memory.rank,
        score=memory.score,
        item_id=memory.item_id,
        created_at=memory.created_at,
        source_refs=memory.source_refs,
        metadata=metadata,
    )


def _with_backfill_skip_metadata(
    memory: RetrievedMemory,
    *,
    skipped_redundant_risky_count: int,
    skipped_redundant_source_count: int,
    skipped_redundant_role_count: int,
) -> RetrievedMemory:
    metadata = dict(memory.metadata)
    if skipped_redundant_risky_count > 0:
        metadata["answer_context_skipped_redundant_risky_backfill_count"] = (
            skipped_redundant_risky_count
        )
    if skipped_redundant_source_count > 0:
        metadata["answer_context_skipped_redundant_source_backfill_count"] = (
            skipped_redundant_source_count
        )
    if skipped_redundant_role_count > 0:
        metadata["answer_context_skipped_redundant_role_backfill_count"] = (
            skipped_redundant_role_count
        )
    _add_answer_context_risk_codes(
        metadata,
        (
            *(
                ("risk:skipped_redundant_risky_backfill",)
                if skipped_redundant_risky_count > 0
                else ()
            ),
            *(
                ("risk:skipped_redundant_source_backfill",)
                if skipped_redundant_source_count > 0
                else ()
            ),
            *(
                ("risk:skipped_redundant_role_backfill",)
                if skipped_redundant_role_count > 0
                else ()
            ),
        ),
    )
    return RetrievedMemory(
        text=memory.text,
        rank=memory.rank,
        score=memory.score,
        item_id=memory.item_id,
        created_at=memory.created_at,
        source_refs=memory.source_refs,
        metadata=metadata,
    )


def _with_bundle_context_metadata(
    memory: RetrievedMemory,
    bundle_context: Mapping[str, object],
) -> RetrievedMemory:
    metadata = dict(memory.metadata)
    metadata.update(bundle_context)
    return RetrievedMemory(
        text=memory.text,
        rank=memory.rank,
        score=memory.score,
        item_id=memory.item_id,
        created_at=memory.created_at,
        source_refs=memory.source_refs,
        metadata=metadata,
    )


def _bundle_context_metadata(bundle: Mapping[str, object]) -> dict[str, object]:
    planner = _mapping(bundle.get("bundle_planner"))
    quality = _mapping(planner.get("bundle_quality"))
    metadata: dict[str, object] = {}
    confidence_score = _metric_value(quality, "confidence_score")
    if confidence_score > 0:
        metadata["answer_context_bundle_confidence_score"] = round(
            confidence_score,
            6,
        )
    confidence_band = str(quality.get("confidence_band") or "").strip()
    if confidence_band:
        metadata["answer_context_bundle_confidence_band"] = confidence_band
    bridge_count = _positive_int(quality.get("bridge_count"))
    if bridge_count is not None:
        metadata["answer_context_bundle_bridge_count"] = bridge_count
    source_ref_support_item_count = _positive_int(
        quality.get("source_ref_support_item_count")
    )
    if source_ref_support_item_count is not None:
        metadata["answer_context_bundle_source_ref_support_item_count"] = (
            source_ref_support_item_count
        )
    source_ref_support_ref_count = _positive_int(
        quality.get("source_ref_support_ref_count")
    )
    if source_ref_support_ref_count is not None:
        metadata["answer_context_bundle_source_ref_support_ref_count"] = (
            source_ref_support_ref_count
        )
    source_identity_support_item_count = _positive_int(
        quality.get("source_identity_support_item_count")
    )
    if source_identity_support_item_count is not None:
        metadata["answer_context_bundle_source_identity_support_item_count"] = (
            source_identity_support_item_count
        )
    source_identity_support_ref_count = _positive_int(
        quality.get("source_identity_support_ref_count")
    )
    if source_identity_support_ref_count is not None:
        metadata["answer_context_bundle_source_identity_support_ref_count"] = (
            source_identity_support_ref_count
        )
    source_type_diversity = _positive_int(quality.get("source_type_diversity"))
    if source_type_diversity is not None:
        metadata["answer_context_bundle_source_type_diversity"] = (
            source_type_diversity
        )
    retrieval_source_diversity = _positive_int(
        quality.get("retrieval_source_diversity")
    )
    if retrieval_source_diversity is not None:
        metadata["answer_context_bundle_retrieval_source_diversity"] = (
            retrieval_source_diversity
        )
    source_type_support_diversity = _nonnegative_int(
        quality.get("source_type_support_diversity")
    )
    if source_type_support_diversity is not None:
        metadata["answer_context_bundle_source_type_support_diversity"] = (
            source_type_support_diversity
        )
    retrieval_source_support_diversity = _nonnegative_int(
        quality.get("retrieval_source_support_diversity")
    )
    if retrieval_source_support_diversity is not None:
        metadata["answer_context_bundle_retrieval_source_support_diversity"] = (
            retrieval_source_support_diversity
        )
    source_proximity_support_count = _positive_int(
        quality.get("source_proximity_support_count")
    )
    if source_proximity_support_count is not None:
        metadata["answer_context_bundle_source_proximity_support_count"] = (
            source_proximity_support_count
        )
    source_proximity_closest_distance = _positive_int(
        quality.get("source_proximity_closest_distance")
    )
    if source_proximity_closest_distance is not None:
        metadata["answer_context_bundle_source_proximity_closest_distance"] = (
            source_proximity_closest_distance
        )
    source_proximity_distance_counts = _int_mapping(
        quality.get("source_proximity_distance_counts")
    )
    if source_proximity_distance_counts:
        metadata["answer_context_bundle_source_proximity_distance_counts"] = (
            source_proximity_distance_counts
        )
    source_chain_proximity_support_count = _positive_int(
        quality.get("source_chain_proximity_support_count")
    )
    if source_chain_proximity_support_count is not None:
        metadata["answer_context_bundle_source_chain_proximity_support_count"] = (
            source_chain_proximity_support_count
        )
    source_chain_proximity_closest_distance = _positive_int(
        quality.get("source_chain_proximity_closest_distance")
    )
    if source_chain_proximity_closest_distance is not None:
        metadata["answer_context_bundle_source_chain_proximity_closest_distance"] = (
            source_chain_proximity_closest_distance
        )
    source_chain_proximity_distance_counts = _int_mapping(
        quality.get("source_chain_proximity_distance_counts")
    )
    if source_chain_proximity_distance_counts:
        metadata["answer_context_bundle_source_chain_proximity_distance_counts"] = (
            source_chain_proximity_distance_counts
        )
    diffuse_source_ref_count = _positive_int(quality.get("diffuse_source_ref_count"))
    if diffuse_source_ref_count is not None:
        metadata["answer_context_bundle_diffuse_source_ref_count"] = (
            diffuse_source_ref_count
        )
    causal_support_count = _positive_int(quality.get("causal_support_count"))
    if causal_support_count is not None:
        metadata["answer_context_bundle_causal_support_count"] = causal_support_count
    communication_support_count = _positive_int(
        quality.get("communication_support_count")
    )
    if communication_support_count is not None:
        metadata["answer_context_bundle_communication_support_count"] = (
            communication_support_count
        )
    event_support_count = _positive_int(quality.get("event_support_count"))
    if event_support_count is not None:
        metadata["answer_context_bundle_event_support_count"] = event_support_count
    exchange_support_count = _positive_int(quality.get("exchange_support_count"))
    if exchange_support_count is not None:
        metadata["answer_context_bundle_exchange_support_count"] = (
            exchange_support_count
        )
    inference_support_count = _positive_int(quality.get("inference_support_count"))
    if inference_support_count is not None:
        metadata["answer_context_bundle_inference_support_count"] = (
            inference_support_count
        )
    location_support_count = _positive_int(quality.get("location_support_count"))
    if location_support_count is not None:
        metadata["answer_context_bundle_location_support_count"] = (
            location_support_count
        )
    emotion_response_support_count = _positive_int(
        quality.get("emotion_response_support_count")
    )
    if emotion_response_support_count is not None:
        metadata["answer_context_bundle_emotion_response_support_count"] = (
            emotion_response_support_count
        )
    symbolic_meaning_support_count = _positive_int(
        quality.get("symbolic_meaning_support_count")
    )
    if symbolic_meaning_support_count is not None:
        metadata["answer_context_bundle_symbolic_meaning_support_count"] = (
            symbolic_meaning_support_count
        )
    preference_support_count = _positive_int(quality.get("preference_support_count"))
    if preference_support_count is not None:
        metadata["answer_context_bundle_preference_support_count"] = (
            preference_support_count
        )
    favorite_support_count = _positive_int(quality.get("favorite_support_count"))
    if favorite_support_count is not None:
        metadata["answer_context_bundle_favorite_support_count"] = (
            favorite_support_count
        )
    visual_support_count = _positive_int(quality.get("visual_support_count"))
    if visual_support_count is not None:
        metadata["answer_context_bundle_visual_support_count"] = visual_support_count
    typed_relation_support_count = _positive_int(
        quality.get("typed_relation_support_count")
    )
    if typed_relation_support_count is not None:
        metadata["answer_context_bundle_typed_relation_support_count"] = (
            typed_relation_support_count
        )
    typed_relation_support_counts = _int_mapping(
        quality.get("typed_relation_support_counts")
    )
    if typed_relation_support_counts:
        metadata["answer_context_bundle_typed_relation_support_counts"] = (
            typed_relation_support_counts
        )
    contrast_count = _positive_int(quality.get("contrast_count"))
    if contrast_count is not None:
        metadata["answer_context_bundle_contrast_count"] = contrast_count
    role_requirement_values = tuple(
        value
        for value in (
            bundle.get("role_requirement_complete"),
            planner.get("role_requirement_complete"),
        )
        if isinstance(value, bool)
    )
    if role_requirement_values:
        role_requirement_complete = all(role_requirement_values)
        metadata["answer_context_role_requirement_complete"] = (
            role_requirement_complete
        )
    missing_roles = tuple(
        dict.fromkeys(
            _string_tuple(bundle.get("missing_required_roles"))
            + _string_tuple(planner.get("missing_required_roles"))
        )
    )
    if missing_roles:
        metadata["answer_context_missing_required_roles"] = missing_roles
    risk_reasons = tuple(
        reason
        for reason in _string_tuple(quality.get("reason_codes"))
        if reason.startswith("risk:")
    )
    if risk_reasons:
        metadata["answer_context_bundle_risk_reason_codes"] = risk_reasons
    return metadata


def _risk_reason_codes(*sources: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            reason
            for source in sources
            for reason in source
            if reason.startswith("risk:")
        )
    )


def _answer_context_required_roles(bundle: Mapping[str, object]) -> tuple[str, ...]:
    planner = _mapping(bundle.get("bundle_planner"))
    return tuple(
        role
        for role in dict.fromkeys(
            _string_tuple(bundle.get("required_roles"))
            + _string_tuple(planner.get("required_roles"))
        )
        if role not in {"primary", "supporting", "entity_disambiguation"}
    )


def _bundle_item_required_roles(
    bundle_item: Mapping[str, object],
    *,
    required_roles: Sequence[str],
) -> tuple[str, ...]:
    if not required_roles:
        return ()
    role = str(bundle_item.get("role") or "").strip()
    query_roles = set(_string_tuple(bundle_item.get("query_roles")))
    required_role_set = set(required_roles)
    roles: list[str] = []
    if role in required_role_set:
        roles.append(role)
    roles.extend(
        required_role
        for required_role in required_roles
        if required_role in query_roles
    )
    return tuple(dict.fromkeys(roles))


def _bundle_context_with_missing_roles(
    bundle_context: Mapping[str, object],
    missing_roles: Sequence[str],
) -> dict[str, object]:
    adjusted = dict(bundle_context)
    combined_missing_roles = tuple(
        dict.fromkeys(
            _string_tuple(adjusted.get("answer_context_missing_required_roles"))
            + tuple(role for role in missing_roles if str(role).strip())
        )
    )
    if not combined_missing_roles:
        return adjusted
    adjusted["answer_context_role_requirement_complete"] = False
    adjusted["answer_context_missing_required_roles"] = combined_missing_roles
    existing_risks = _string_tuple(
        adjusted.get("answer_context_bundle_risk_reason_codes")
    )
    adjusted["answer_context_bundle_risk_reason_codes"] = tuple(
        dict.fromkeys(
            (
                *existing_risks,
                "risk:missing_required_role",
                *(
                    f"risk:missing_required_{role}"
                    for role in combined_missing_roles
                ),
            )
        )
    )
    return adjusted


def _bundle_items(bundle: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    return tuple(
        item for item in _sequence(bundle.get("items")) if isinstance(item, Mapping)
    )


def _memory_key(
    memory: RetrievedMemory,
    *,
    retrieval_order: int,
) -> tuple[str, object]:
    if memory.item_id:
        return ("id", memory.item_id)
    if memory.source_refs:
        return ("source_refs", tuple(memory.source_refs))
    return ("retrieval_order", retrieval_order)


def _bundle_source_identity_key(
    memory: RetrievedMemory,
    bundle_item: Mapping[str, object],
) -> tuple[str, ...]:
    refs = tuple(
        dict.fromkeys(
            (
                *_source_match_refs_from_memory(memory),
                *_source_match_refs_from_bundle_item(bundle_item),
            )
        )
    )
    if _bundle_item_has_session_turn_key(bundle_item):
        turn_refs = tuple(
            sorted(ref for ref in refs if ref.startswith("source_session_turn_refs:"))
        )
    else:
        turn_refs = tuple(
            sorted(ref for ref in refs if ref.startswith("source_turn_refs:"))
        )
        if not turn_refs:
            turn_refs = tuple(
                sorted(
                    ref
                    for ref in refs
                    if ref.startswith("source_session_turn_refs:")
                )
            )
    if turn_refs:
        return turn_refs
    return tuple(sorted(_merged_source_refs(memory, bundle_item)))


def _bundle_item_has_session_turn_key(bundle_item: Mapping[str, object]) -> bool:
    return any(
        ref.startswith("source_session_turn_refs:")
        for ref in _source_identity_refs_from_bundle_item(bundle_item)
    )


def _source_identity_key_overlaps(
    source_identity_key: tuple[str, ...],
    selected_source_identity_keys: set[tuple[str, ...]],
) -> bool:
    source_identity_refs = set(source_identity_key)
    source_identity_turn_refs = _unqualified_source_turn_refs(source_identity_key)
    source_identity_has_session_refs = _has_session_source_turn_refs(
        source_identity_key
    )
    for selected_key in selected_source_identity_keys:
        if source_identity_refs.intersection(selected_key):
            return True
        selected_has_session_refs = _has_session_source_turn_refs(selected_key)
        if source_identity_has_session_refs and selected_has_session_refs:
            continue
        if source_identity_turn_refs.intersection(
            _unqualified_source_turn_refs(selected_key)
        ):
            return True
    return False


def _has_session_source_turn_refs(source_identity_key: Sequence[str]) -> bool:
    return any(
        ref.startswith("source_session_turn_refs:")
        for ref in source_identity_key
    )


def _unqualified_source_turn_refs(source_identity_key: Sequence[str]) -> set[str]:
    unqualified = {
        ref
        for ref in source_identity_key
        if ref.startswith("source_turn_refs:")
    }
    for ref in source_identity_key:
        if not ref.startswith("source_session_turn_refs:"):
            continue
        parts = ref.split(":")
        if len(parts) >= 4:
            unqualified.add(f"source_turn_refs:{parts[-2]}:{parts[-1]}")
    return unqualified


def _bundle_source_turn_refs(
    memory: RetrievedMemory,
    bundle_item: Mapping[str, object],
) -> set[str]:
    return {
        ref
        for ref in (
            *_source_match_refs_from_memory(memory),
            *_source_match_refs_from_bundle_item(bundle_item),
        )
        if ref.startswith(_SOURCE_TURN_REF_PREFIXES)
    }


def _non_noisy_bundle_source_turn_refs(
    bundle_items: Sequence[Mapping[str, object]],
    memories: Sequence[RetrievedMemory],
    *,
    bounded_cutoff: int,
) -> set[str]:
    refs: set[str] = set()
    for item in bundle_items:
        memory = _memory_for_bundle_item(item, memories)
        if memory is None or _bundle_item_has_noise_risk(memory):
            continue
        retrieval_order = _positive_int(item.get("retrieval_order"))
        if retrieval_order is None:
            retrieval_order = _retrieval_order_for_memory(memory, memories)
        if retrieval_order is None or retrieval_order > bounded_cutoff:
            continue
        refs.update(_bundle_source_turn_refs(memory, item))
    return refs


def _bundle_item_has_noise_risk(memory: RetrievedMemory) -> bool:
    features = _candidate_features(memory)
    if _is_measured_low_answerability(features.get("answerability_score")):
        return True
    if _is_measured_weak_source_locality(features.get("source_locality_score")):
        return True
    return memory_has_broad_summary(
        memory,
        features,
    ) or memory_has_conflict_or_stale(memory, features)

def _source_ref_stats(memories: Sequence[RetrievedMemory]) -> dict[str, object]:
    source_ref_counts = [len(_memory_source_refs(memory)) for memory in memories]
    source_ref_item_count = sum(1 for count in source_ref_counts if count > 0)
    source_ref_count = sum(source_ref_counts)
    compacted_stats = [
        _compacted_fusion_source_ref_stats(memory) for memory in memories
    ]
    return {
        "source_ref_count": source_ref_count,
        "source_ref_item_count": source_ref_item_count,
        "source_refless_item_count": len(memories) - source_ref_item_count,
        "source_ref_coverage_rate": _ratio(source_ref_item_count, len(memories)),
        "compacted_fusion_source_ref_item_count": sum(
            stats["compacted_count"] for stats in compacted_stats
        ),
        "compacted_fusion_source_ref_original_count": sum(
            stats["original_count"] for stats in compacted_stats
        ),
        "compacted_fusion_source_ref_selected_count": sum(
            stats["selected_count"] for stats in compacted_stats
        ),
        "compacted_fusion_source_ref_saved_count": sum(
            stats["saved_count"] for stats in compacted_stats
        ),
    }


def _compacted_fusion_source_ref_stats(memory: RetrievedMemory) -> dict[str, int]:
    diagnostics = _mapping(memory.metadata.get("diagnostics"))
    if diagnostics.get("benchmark_compacted_selected_source_refs") is not True:
        return {
            "compacted_count": 0,
            "original_count": 0,
            "selected_count": 0,
            "saved_count": 0,
        }
    fusion = _mapping(diagnostics.get("benchmark_candidate_fusion"))
    original_refs = _string_tuple(fusion.get("source_refs"))
    selected_refs = tuple(
        str(ref).strip() for ref in memory.source_refs if str(ref).strip()
    )
    return {
        "compacted_count": 1,
        "original_count": len(original_refs),
        "selected_count": len(selected_refs),
        "saved_count": max(0, len(original_refs) - len(selected_refs)),
    }


def _backfill_risk_stats(memories: Sequence[RetrievedMemory]) -> dict[str, object]:
    backfilled = tuple(
        memory
        for memory in memories
        if memory.metadata.get("answer_context_role") == "retrieval_backfill"
    )
    broad_summary_count = 0
    conflict_or_stale_count = 0
    low_answerability_count = 0
    weak_source_locality_count = 0
    low_answerability_role_counts: Counter[str] = Counter()
    weak_source_locality_role_counts: Counter[str] = Counter()
    source_proximity_distances: list[int] = []
    chained_source_proximity_count = 0
    for memory in backfilled:
        features = _candidate_features(memory)
        role_hits = _string_tuple(
            memory.metadata.get("answer_context_backfill_missing_role_hits")
        )
        if memory_has_broad_summary(memory, features):
            broad_summary_count += 1
        if memory_has_conflict_or_stale(memory, features):
            conflict_or_stale_count += 1
        if _is_measured_low_answerability(features.get("answerability_score")):
            low_answerability_count += 1
            low_answerability_role_counts.update(role_hits)
        if _is_measured_weak_source_locality(features.get("source_locality_score")):
            weak_source_locality_count += 1
            weak_source_locality_role_counts.update(role_hits)
        source_proximity_distance = _positive_int(
            memory.metadata.get("answer_context_backfill_source_proximity_distance")
        )
        if source_proximity_distance is not None:
            source_proximity_distances.append(source_proximity_distance)
        if memory.metadata.get(
            "answer_context_backfill_chained_source_proximity"
        ) is True:
            chained_source_proximity_count += 1
    return {
        "backfilled_broad_summary_count": broad_summary_count,
        "backfilled_conflict_or_stale_count": conflict_or_stale_count,
        "backfilled_low_answerability_count": low_answerability_count,
        "backfilled_weak_source_locality_count": weak_source_locality_count,
        "backfilled_low_answerability_role_counts": dict(
            sorted(low_answerability_role_counts.items())
        ),
        "backfilled_weak_source_locality_role_counts": dict(
            sorted(weak_source_locality_role_counts.items())
        ),
        "backfilled_source_proximity_support_count": len(
            source_proximity_distances
        ),
        "backfilled_chained_source_proximity_support_count": (
            chained_source_proximity_count
        ),
        "backfilled_source_proximity_closest_distance": (
            min(source_proximity_distances) if source_proximity_distances else None
        ),
    }


def _answer_context_risk_reason_codes(
    context: AnswerContext,
    *,
    backfill_risk_stats: Mapping[str, object],
) -> tuple[str, ...]:
    return _context_risk_reason_codes(
        bundle_risk_reason_codes=context.bundle_risk_reason_codes,
        skipped_duplicate_source_bundle_item_count=(
            context.skipped_duplicate_source_bundle_item_count
        ),
        skipped_noisy_overlap_bundle_item_count=(
            context.skipped_noisy_overlap_bundle_item_count
        ),
        backfilled_retrieval_item_count=context.backfilled_retrieval_item_count,
        skipped_redundant_risky_backfill_count=(
            context.skipped_redundant_risky_backfill_count
        ),
        skipped_redundant_source_backfill_count=(
            context.skipped_redundant_source_backfill_count
        ),
        skipped_redundant_role_backfill_count=(
            context.skipped_redundant_role_backfill_count
        ),
        backfill_risk_stats=backfill_risk_stats,
        memory_metadata=tuple(memory.metadata for memory in context.memories),
    )


def _quality_score_stats(memories: Sequence[RetrievedMemory]) -> dict[str, object]:
    scored_memories = tuple(
        memory for memory in memories if "answer_context_role" in memory.metadata
    )
    answerability_scores = tuple(
        _metric_value(memory.metadata, "answer_context_answerability_score")
        for memory in scored_memories
    )
    source_locality_scores = tuple(
        _metric_value(memory.metadata, "answer_context_source_locality_score")
        for memory in scored_memories
    )
    measured_answerability_scores = tuple(
        score for score in answerability_scores if score > 0
    )
    measured_source_locality_scores = tuple(
        score for score in source_locality_scores if score > 0
    )
    return {
        "avg_answerability_score": _avg(answerability_scores),
        "avg_measured_answerability_score": _avg(measured_answerability_scores),
        "unmeasured_answerability_count": sum(
            1 for score in answerability_scores if score <= 0
        ),
        "avg_source_locality_score": _avg(source_locality_scores),
        "avg_measured_source_locality_score": _avg(
            measured_source_locality_scores
        ),
        "unmeasured_source_locality_count": sum(
            1 for score in source_locality_scores if score <= 0
        ),
    }


def _merged_source_refs(
    memory: RetrievedMemory,
    bundle_item: Mapping[str, object],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                *_memory_source_refs(memory),
                *_source_identity_refs_from_bundle_item(bundle_item),
            )
        )
    )


def _memory_source_refs(memory: RetrievedMemory) -> tuple[str, ...]:
    return _source_identity_refs_from_memory(memory)


def _source_identity_refs_from_memory(
    memory: RetrievedMemory,
    *,
    include_compacted_fusion_refs: bool = False,
) -> tuple[str, ...]:
    diagnostics = _mapping(memory.metadata.get("diagnostics"))
    fusion = _mapping(diagnostics.get("benchmark_candidate_fusion"))
    features = _candidate_features(memory)
    compacted_fusion_refs = (
        diagnostics.get("benchmark_compacted_selected_source_refs") is True
    )
    fusion_source_refs = (
        _string_tuple(fusion.get("source_refs"))
        if include_compacted_fusion_refs or not compacted_fusion_refs
        else ()
    )
    source_refs = tuple(
        dict.fromkeys(
            (
                *(str(ref).strip() for ref in memory.source_refs if str(ref).strip()),
                *fusion_source_refs,
            )
        )
    )
    return tuple(
        dict.fromkeys(
            (
                *source_refs,
                *_source_identity_refs_from_source_refs(source_refs),
                *_source_identity_refs_from_dedupe_key(
                    features.get("source_ref_dedupe_key")
                ),
                *_source_identity_refs_from_dedupe_key(fusion.get("dedupe_key")),
                *_source_identity_refs_from_text(memory.text, source_refs=source_refs),
            )
        )
    )


def _source_match_refs_from_memory(
    memory: RetrievedMemory,
    *,
    include_compacted_fusion_refs: bool = True,
) -> tuple[str, ...]:
    diagnostics = _mapping(memory.metadata.get("diagnostics"))
    fusion = _mapping(diagnostics.get("benchmark_candidate_fusion"))
    features = _candidate_features(memory)
    fusion_source_refs = (
        _string_tuple(fusion.get("source_refs"))
        if include_compacted_fusion_refs
        else ()
    )
    source_refs = tuple(
        dict.fromkeys(
            (
                *(str(ref).strip() for ref in memory.source_refs if str(ref).strip()),
                *fusion_source_refs,
            )
        )
    )
    return tuple(
        dict.fromkeys(
            (
                *_source_identity_refs_from_memory(
                    memory,
                    include_compacted_fusion_refs=include_compacted_fusion_refs,
                ),
                *_source_identity_refs_from_source_refs(
                    source_refs,
                    include_exact_turn_refs=True,
                ),
                *_source_identity_refs_from_dedupe_key(
                    features.get("source_ref_dedupe_key")
                ),
                *_source_identity_refs_from_dedupe_key(fusion.get("dedupe_key")),
            )
        )
    )


def _precise_source_match_refs_from_memory(memory: RetrievedMemory) -> tuple[str, ...]:
    return _source_match_refs_from_memory(
        memory,
        include_compacted_fusion_refs=False,
    )


def _source_identity_refs_from_bundle_item(
    item: Mapping[str, object],
) -> tuple[str, ...]:
    source_refs = _string_tuple(item.get("source_refs"))
    return tuple(
        dict.fromkeys(
            (
                *source_refs,
                *_source_identity_refs_from_source_refs(source_refs),
                *_source_identity_refs_from_dedupe_key(
                    item.get("source_ref_dedupe_key")
                ),
                *_source_identity_refs_from_dedupe_key(item.get("dedupe_key")),
            )
        )
    )


def _source_match_refs_from_bundle_item(
    item: Mapping[str, object],
) -> tuple[str, ...]:
    source_refs = _string_tuple(item.get("source_refs"))
    return tuple(
        dict.fromkeys(
            (
                *_source_identity_refs_from_bundle_item(item),
                *_source_identity_refs_from_source_refs(
                    source_refs,
                    include_exact_turn_refs=True,
                ),
                *_source_identity_refs_from_dedupe_key(
                    item.get("source_ref_dedupe_key")
                ),
                *_source_identity_refs_from_dedupe_key(item.get("dedupe_key")),
            )
        )
    )


def _retrieval_order_for_memory(
    memory: RetrievedMemory,
    memories: Sequence[RetrievedMemory],
) -> int | None:
    for index, candidate in enumerate(memories, start=1):
        if candidate is memory:
            return index
    return None


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _nonnegative_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _metric_value(item: Mapping[str, object], key: str) -> float:
    value = item.get(key)
    if isinstance(value, bool):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _int_mapping(value: object) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for key, raw_count in _mapping(value).items():
        role = str(key).strip()
        count = _positive_int(raw_count)
        if not role or count is None:
            continue
        parsed[role] = count
    return dict(sorted(parsed.items()))


def _sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return tuple(value)
    return ()


def _string_tuple(value: object) -> tuple[str, ...]:
    return tuple(str(item).strip() for item in _sequence(value) if str(item).strip())


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _avg(values: Sequence[float] | Sequence[int]) -> float:
    sequence = tuple(float(value) for value in values)
    return round(sum(sequence) / len(sequence), 4) if sequence else 0.0
