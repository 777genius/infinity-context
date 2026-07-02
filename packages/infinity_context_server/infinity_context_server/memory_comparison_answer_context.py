"""Answer-context selection for memory comparison benchmark runs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from infinity_context_server.memory_comparison_models import RetrievedMemory

_INCOMPLETE_BUNDLE_BACKFILL_MIN_ITEMS = 6
_INCOMPLETE_BUNDLE_BACKFILL_MAX_ITEMS = 12
_INCOMPLETE_BUNDLE_BACKFILL_ITEMS_PER_MISSING_ROLE = 2


@dataclass(frozen=True)
class AnswerContext:
    """Evidence context passed to answer/judge adapters."""

    memories: tuple[RetrievedMemory, ...]
    source: str
    fallback_reason: str | None = None
    selected_bundle_item_count: int = 0
    skipped_bundle_item_count: int = 0
    backfilled_retrieval_item_count: int = 0
    bundle_confidence_score: float = 0.0
    bundle_confidence_band: str = ""
    bundle_bridge_count: int = 0
    bundle_source_proximity_support_count: int = 0
    bundle_source_proximity_closest_distance: int | None = None
    bundle_causal_support_count: int = 0
    bundle_communication_support_count: int = 0
    bundle_event_support_count: int = 0
    bundle_exchange_support_count: int = 0
    bundle_inference_support_count: int = 0
    bundle_location_support_count: int = 0
    bundle_emotion_response_support_count: int = 0
    bundle_symbolic_meaning_support_count: int = 0
    bundle_preference_support_count: int = 0
    bundle_visual_support_count: int = 0
    bundle_contrast_count: int = 0
    role_requirement_complete: bool | None = None
    missing_required_roles: tuple[str, ...] = ()
    bundle_risk_reason_codes: tuple[str, ...] = ()

    def to_diagnostics(self) -> dict[str, object]:
        source_ref_stats = _source_ref_stats(self.memories)
        return {
            "schema_version": "answer_context.v1",
            "source": self.source,
            "memory_count": len(self.memories),
            **source_ref_stats,
            "selected_bundle_item_count": self.selected_bundle_item_count,
            "skipped_bundle_item_count": self.skipped_bundle_item_count,
            "backfilled_retrieval_item_count": self.backfilled_retrieval_item_count,
            "bundle_confidence_score": self.bundle_confidence_score,
            "bundle_confidence_band": self.bundle_confidence_band,
            "bundle_bridge_count": self.bundle_bridge_count,
            "bundle_source_proximity_support_count": (
                self.bundle_source_proximity_support_count
            ),
            "bundle_source_proximity_closest_distance": (
                self.bundle_source_proximity_closest_distance
            ),
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
            "bundle_visual_support_count": self.bundle_visual_support_count,
            "bundle_contrast_count": self.bundle_contrast_count,
            "role_requirement_complete": self.role_requirement_complete,
            "missing_required_roles": list(self.missing_required_roles),
            "bundle_risk_reason_codes": list(self.bundle_risk_reason_codes),
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
            memories=raw_slice,
            source="retrieval_slice",
            fallback_reason="empty_bundle",
        )
    bundle_context = _bundle_context_metadata(evidence_bundle)

    selected: list[RetrievedMemory] = []
    selected_keys: set[tuple[str, object]] = set()
    skipped = 0
    for item in bundle_items:
        retrieval_order = _positive_int(item.get("retrieval_order"))
        if retrieval_order is None or retrieval_order > bounded_cutoff:
            skipped += 1
            continue
        memory = _memory_for_bundle_item(item, memories)
        if memory is None:
            skipped += 1
            continue
        key = _memory_key(memory, retrieval_order=retrieval_order)
        if key in selected_keys:
            continue
        selected_keys.add(key)
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
            memories=raw_slice,
            source="retrieval_slice",
            fallback_reason="no_bundle_items_within_cutoff",
            skipped_bundle_item_count=skipped,
        )

    bundle_selected_count = len(selected)
    backfilled_count = 0
    if bundle_context.get("answer_context_role_requirement_complete") is False:
        backfilled_count = _backfill_incomplete_bundle_context(
            selected,
            selected_keys=selected_keys,
            raw_slice=raw_slice,
            bundle_context=bundle_context,
            bounded_cutoff=bounded_cutoff,
        )

    return AnswerContext(
        memories=tuple(selected),
        source="evidence_bundle",
        selected_bundle_item_count=bundle_selected_count,
        skipped_bundle_item_count=skipped,
        backfilled_retrieval_item_count=backfilled_count,
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
        bundle_visual_support_count=(
            _positive_int(
                bundle_context.get("answer_context_bundle_visual_support_count")
            )
            or 0
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


def _backfill_incomplete_bundle_context(
    selected: list[RetrievedMemory],
    *,
    selected_keys: set[tuple[str, object]],
    raw_slice: Sequence[RetrievedMemory],
    bundle_context: Mapping[str, object],
    bounded_cutoff: int,
) -> int:
    missing_roles = _string_tuple(
        bundle_context.get("answer_context_missing_required_roles")
    )
    target_count = _incomplete_bundle_backfill_target_count(
        selected_count=len(selected),
        missing_role_count=len(missing_roles),
        bounded_cutoff=bounded_cutoff,
    )
    backfilled_count = 0
    for retrieval_order, memory in enumerate(raw_slice, start=1):
        if len(selected) >= target_count:
            break
        key = _memory_key(memory, retrieval_order=retrieval_order)
        if key in selected_keys:
            continue
        selected_keys.add(key)
        selected.append(
            _with_retrieval_backfill_metadata(
                memory,
                bundle_context=bundle_context,
                retrieval_order=retrieval_order,
            )
        )
        backfilled_count += 1
    return backfilled_count


def _incomplete_bundle_backfill_target_count(
    *,
    selected_count: int,
    missing_role_count: int,
    bounded_cutoff: int,
) -> int:
    if bounded_cutoff <= selected_count:
        return selected_count
    role_backfill = selected_count + (
        missing_role_count * _INCOMPLETE_BUNDLE_BACKFILL_ITEMS_PER_MISSING_ROLE
    )
    target = max(_INCOMPLETE_BUNDLE_BACKFILL_MIN_ITEMS, role_backfill)
    return min(bounded_cutoff, _INCOMPLETE_BUNDLE_BACKFILL_MAX_ITEMS, target)


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
        "primary_avg_source_ref_coverage_rate": _metric_value(
            primary,
            "avg_source_ref_coverage_rate",
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
    backfilled_retrieval_counts: list[int] = []
    source_ref_counts: list[int] = []
    source_ref_item_counts: list[int] = []
    source_refless_item_counts: list[int] = []
    source_ref_coverage_rates: list[float] = []
    bundle_confidence_scores: list[float] = []
    bundle_confidence_band_counts: Counter[str] = Counter()
    bundle_bridge_counts: list[int] = []
    bundle_source_proximity_support_counts: list[int] = []
    bundle_source_proximity_closest_distances: list[int] = []
    bundle_causal_support_counts: list[int] = []
    bundle_communication_support_counts: list[int] = []
    bundle_event_support_counts: list[int] = []
    bundle_exchange_support_counts: list[int] = []
    bundle_inference_support_counts: list[int] = []
    bundle_location_support_counts: list[int] = []
    bundle_emotion_response_support_counts: list[int] = []
    bundle_symbolic_meaning_support_counts: list[int] = []
    bundle_preference_support_counts: list[int] = []
    bundle_visual_support_counts: list[int] = []
    bundle_contrast_counts: list[int] = []
    missing_required_role_counts: Counter[str] = Counter()
    bundle_risk_reason_counts: Counter[str] = Counter()
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
        backfilled_retrieval_counts.append(
            _positive_int(context.get("backfilled_retrieval_item_count")) or 0
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
        confidence_score = _metric_value(context, "bundle_confidence_score")
        if confidence_score > 0:
            bundle_confidence_scores.append(confidence_score)
        confidence_band = str(context.get("bundle_confidence_band") or "").strip()
        if confidence_band:
            bundle_confidence_band_counts[confidence_band] += 1
        bundle_bridge_counts.append(
            _positive_int(context.get("bundle_bridge_count")) or 0
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
        bundle_visual_support_counts.append(
            _positive_int(context.get("bundle_visual_support_count")) or 0
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
        "avg_backfilled_retrieval_item_count": _avg(backfilled_retrieval_counts),
        "total_backfilled_retrieval_item_count": sum(backfilled_retrieval_counts),
        "avg_source_ref_count": _avg(source_ref_counts),
        "avg_source_ref_item_count": _avg(source_ref_item_counts),
        "avg_source_refless_item_count": _avg(source_refless_item_counts),
        "avg_source_ref_coverage_rate": _avg(source_ref_coverage_rates),
        "avg_bundle_confidence_score": _avg(bundle_confidence_scores),
        "bundle_confidence_band_counts": dict(
            sorted(bundle_confidence_band_counts.items())
        ),
        "avg_bundle_bridge_count": _avg(bundle_bridge_counts),
        "total_bundle_bridge_count": sum(bundle_bridge_counts),
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
        "avg_bundle_visual_support_count": _avg(bundle_visual_support_counts),
        "total_bundle_visual_support_count": sum(bundle_visual_support_counts),
        "avg_bundle_contrast_count": _avg(bundle_contrast_counts),
        "total_bundle_contrast_count": sum(bundle_contrast_counts),
        "incomplete_role_requirement_count": incomplete_role_requirement_count,
        "missing_required_role_counts": dict(
            sorted(missing_required_role_counts.items())
        ),
        "bundle_risk_reason_counts": dict(sorted(bundle_risk_reason_counts.items())),
    }


def _memory_for_bundle_item(
    item: Mapping[str, object],
    memories: Sequence[RetrievedMemory],
) -> RetrievedMemory | None:
    retrieval_order = _positive_int(item.get("retrieval_order"))
    if retrieval_order is not None and 1 <= retrieval_order <= len(memories):
        return memories[retrieval_order - 1]

    item_id = str(item.get("id") or "").strip()
    if item_id:
        for memory in memories:
            if memory.item_id == item_id:
                return memory

    rank = _positive_int(item.get("rank"))
    if rank is not None:
        for memory in memories:
            if memory.rank == rank:
                return memory

    source_refs = {
        str(ref).strip()
        for ref in _sequence(item.get("source_refs"))
        if str(ref).strip()
    }
    if source_refs:
        for memory in memories:
            if source_refs.intersection(str(ref) for ref in memory.source_refs):
                return memory
    return None


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
    query_roles = _string_tuple(bundle_item.get("query_roles"))
    if query_roles:
        metadata["answer_context_query_roles"] = query_roles
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


def _with_retrieval_backfill_metadata(
    memory: RetrievedMemory,
    *,
    bundle_context: Mapping[str, object],
    retrieval_order: int,
) -> RetrievedMemory:
    metadata = dict(memory.metadata)
    metadata["answer_context_retrieval_order"] = retrieval_order
    metadata.update(bundle_context)
    metadata["answer_context_role"] = "retrieval_backfill"
    metadata["answer_context_reason_codes"] = (
        "incomplete_bundle_backfill",
        "retrieval_slice_support",
    )
    return RetrievedMemory(
        text=memory.text,
        rank=memory.rank,
        score=memory.score,
        item_id=memory.item_id,
        created_at=memory.created_at,
        source_refs=_memory_source_refs(memory),
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
    visual_support_count = _positive_int(quality.get("visual_support_count"))
    if visual_support_count is not None:
        metadata["answer_context_bundle_visual_support_count"] = visual_support_count
    contrast_count = _positive_int(quality.get("contrast_count"))
    if contrast_count is not None:
        metadata["answer_context_bundle_contrast_count"] = contrast_count
    role_requirement_complete = bundle.get("role_requirement_complete")
    if not isinstance(role_requirement_complete, bool):
        role_requirement_complete = planner.get("role_requirement_complete")
    if isinstance(role_requirement_complete, bool):
        metadata["answer_context_role_requirement_complete"] = (
            role_requirement_complete
        )
    missing_roles = _string_tuple(bundle.get("missing_required_roles")) or _string_tuple(
        planner.get("missing_required_roles")
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


def _source_ref_stats(memories: Sequence[RetrievedMemory]) -> dict[str, object]:
    source_ref_counts = [len(_memory_source_refs(memory)) for memory in memories]
    source_ref_item_count = sum(1 for count in source_ref_counts if count > 0)
    source_ref_count = sum(source_ref_counts)
    return {
        "source_ref_count": source_ref_count,
        "source_ref_item_count": source_ref_item_count,
        "source_refless_item_count": len(memories) - source_ref_item_count,
        "source_ref_coverage_rate": _ratio(source_ref_item_count, len(memories)),
    }


def _merged_source_refs(
    memory: RetrievedMemory,
    bundle_item: Mapping[str, object],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                *_memory_source_refs(memory),
                *_string_tuple(bundle_item.get("source_refs")),
            )
        )
    )


def _memory_source_refs(memory: RetrievedMemory) -> tuple[str, ...]:
    diagnostics = _mapping(memory.metadata.get("diagnostics"))
    fusion = _mapping(diagnostics.get("benchmark_candidate_fusion"))
    return tuple(
        dict.fromkeys(
            (
                *(str(ref).strip() for ref in memory.source_refs if str(ref).strip()),
                *_string_tuple(fusion.get("source_refs")),
            )
        )
    )


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


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
