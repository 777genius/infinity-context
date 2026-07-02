"""Answer-context selection for memory comparison benchmark runs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from infinity_context_server.memory_comparison_models import RetrievedMemory


@dataclass(frozen=True)
class AnswerContext:
    """Evidence context passed to answer/judge adapters."""

    memories: tuple[RetrievedMemory, ...]
    source: str
    fallback_reason: str | None = None
    selected_bundle_item_count: int = 0
    skipped_bundle_item_count: int = 0
    bundle_confidence_score: float = 0.0
    bundle_confidence_band: str = ""
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
            "bundle_confidence_score": self.bundle_confidence_score,
            "bundle_confidence_band": self.bundle_confidence_band,
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

    return AnswerContext(
        memories=tuple(selected),
        source="evidence_bundle",
        selected_bundle_item_count=len(selected),
        skipped_bundle_item_count=skipped,
        bundle_confidence_score=float(
            bundle_context.get("answer_context_bundle_confidence_score") or 0.0
        ),
        bundle_confidence_band=str(
            bundle_context.get("answer_context_bundle_confidence_band") or ""
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
    source_ref_counts: list[int] = []
    source_ref_item_counts: list[int] = []
    source_refless_item_counts: list[int] = []
    source_ref_coverage_rates: list[float] = []
    bundle_confidence_scores: list[float] = []
    bundle_confidence_band_counts: Counter[str] = Counter()
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
        "avg_source_ref_count": _avg(source_ref_counts),
        "avg_source_ref_item_count": _avg(source_ref_item_counts),
        "avg_source_refless_item_count": _avg(source_refless_item_counts),
        "avg_source_ref_coverage_rate": _avg(source_ref_coverage_rates),
        "avg_bundle_confidence_score": _avg(bundle_confidence_scores),
        "bundle_confidence_band_counts": dict(
            sorted(bundle_confidence_band_counts.items())
        ),
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
