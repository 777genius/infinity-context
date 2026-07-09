"""Answer-context diagnostics and source-reference helpers."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

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
    safe_item_id_for_output as _safe_item_id_for_output,
)
from infinity_context_server.memory_comparison_source_identity import (
    safe_source_identity_ref as _safe_source_identity_ref,
)
from infinity_context_server.memory_comparison_source_identity import (
    safe_source_label_for_output as _safe_source_label_for_output,
)
from infinity_context_server.memory_comparison_source_identity import (
    safe_source_refs_for_output as _safe_source_refs_for_output,
)
from infinity_context_server.memory_comparison_source_identity import (
    source_identity_refs_from_dedupe_key as _source_identity_refs_from_dedupe_key,
)
from infinity_context_server.memory_comparison_source_identity import (
    source_identity_refs_from_source_refs as _source_identity_refs_from_source_refs,
)
from infinity_context_server.memory_comparison_source_identity import (
    source_identity_refs_from_text as _source_identity_refs_from_text,
)

if TYPE_CHECKING:
    from infinity_context_server.memory_comparison_answer_context import AnswerContext

_MAX_CONTEXT_SOURCE_IDENTITY_REFS = 8
_MAX_CONTEXT_SOURCE_IDENTITY_REFS_PER_ITEM = 4
_MAX_CONTEXT_SOURCE_IDENTITY_ITEMS = 8


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


def _source_identity_stats(memories: Sequence[RetrievedMemory]) -> dict[str, object]:
    source_identity_refs: list[str] = []
    source_identity_items: list[dict[str, object]] = []
    source_identity_item_count = 0
    for memory in memories:
        memory_refs = tuple(
            dict.fromkeys(
                ref
                for raw_ref in _source_match_refs_from_memory(memory)
                for ref in (_safe_source_identity_ref(raw_ref),)
                if ref
            )
        )
        if not memory_refs:
            continue
        source_identity_item_count += 1
        source_identity_refs.extend(memory_refs)
        if len(source_identity_items) >= _MAX_CONTEXT_SOURCE_IDENTITY_ITEMS:
            continue
        item: dict[str, object] = {
            "source_identity_refs": list(
                memory_refs[:_MAX_CONTEXT_SOURCE_IDENTITY_REFS_PER_ITEM]
            )
        }
        item_id = _safe_diagnostic_item_id(memory.item_id)
        if item_id:
            item["item_id"] = item_id
        retrieval_order = _positive_int(
            memory.metadata.get("answer_context_retrieval_order")
        )
        if (
            retrieval_order is not None
            and memory.metadata.get("answer_context_role") != "retrieval_slice"
        ):
            item["retrieval_order"] = retrieval_order
        source_identity_items.append(item)

    unique_refs = tuple(dict.fromkeys(source_identity_refs))
    return {
        "source_identity_ref_count": len(unique_refs),
        "source_identity_item_count": source_identity_item_count,
        "source_identity_refs": list(
            unique_refs[:_MAX_CONTEXT_SOURCE_IDENTITY_REFS]
        ),
        "source_identity_items": source_identity_items,
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


def _safe_diagnostic_item_id(value: object) -> str:
    return _safe_item_id_for_output(value)


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
        skipped_target_limit_backfill_count=(
            context.skipped_target_limit_backfill_count
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
    metadata_source_refs = _metadata_source_ref_values(memory.metadata)
    source_refs = tuple(
        dict.fromkeys(
            (
                *(str(ref).strip() for ref in memory.source_refs if str(ref).strip()),
                *metadata_source_refs,
                *fusion_source_refs,
            )
        )
    )
    output_source_refs = _safe_source_refs_for_output(source_refs)
    source_identity_refs = _source_identity_refs_from_source_refs(source_refs)
    return tuple(
        dict.fromkeys(
            (
                *output_source_refs,
                *source_identity_refs,
                *_source_identity_refs_from_dedupe_key(
                    features.get("source_ref_dedupe_key")
                ),
                *_source_identity_refs_from_dedupe_key(fusion.get("dedupe_key")),
                *_source_identity_refs_from_text(
                    memory.text,
                    source_refs=(*output_source_refs, *source_identity_refs),
                ),
            )
        )
    )


def _metadata_source_ref_values(metadata: Mapping[str, object]) -> tuple[str, ...]:
    refs: list[str] = []
    for key in (
        "source_identity",
        "source_identity_ref",
        "source_identity_refs",
        "source_identity_items",
        "source_ref",
        "source_refs",
        "source_ref_payloads",
    ):
        refs.extend(_source_ref_values_from_payload(metadata.get(key)))
    nested = metadata.get("metadata")
    if isinstance(nested, Mapping):
        refs.extend(_metadata_source_ref_values(nested))
    return tuple(dict.fromkeys(refs))


def _source_ref_values_from_payload(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else ()
    if isinstance(value, Mapping):
        return _source_ref_values_from_mapping(value)
    return tuple(
        ref
        for item in _sequence(value)
        for ref in _source_ref_values_from_payload(item)
    )


def _source_ref_values_from_mapping(value: Mapping[str, object]) -> tuple[str, ...]:
    safe_refs = _safe_source_refs_for_output((value,))
    if safe_refs:
        return safe_refs

    refs: list[str] = []
    for key in (
        "source_id",
        "source_external_id",
        "source_identity",
        "source_identity_ref",
        "source_ref",
        "session_key",
        "dia_id",
        "locomo_evidence_ref",
        "evidence_id",
        "evidence_ref",
        "source_evidence_ref",
        "turn_ref",
        "turn_id",
        "source_turn_ref",
    ):
        raw_ref = value.get(key)
        if isinstance(raw_ref, str) and raw_ref.strip():
            refs.append(raw_ref.strip())
    structured_turn_ref = _structured_turn_ref_from_mapping(value)
    if structured_turn_ref:
        refs.append(structured_turn_ref)
    for key in (
        "source_refs",
        "source_identity_refs",
        "source_identity_items",
        "source_ref_payloads",
        "evidence",
        "evidence_refs",
        "locomo_evidence_refs",
        "source_evidence_refs",
        "supporting_evidence",
        "supporting_facts",
    ):
        refs.extend(_source_ref_values_from_payload(value.get(key)))
    nested = value.get("metadata")
    if isinstance(nested, Mapping):
        refs.extend(_source_ref_values_from_mapping(nested))
    raw_id = value.get("id")
    if isinstance(raw_id, str) and _source_ref_value_has_turn_identity(raw_id):
        refs.append(raw_id.strip())
    return tuple(dict.fromkeys(refs))


def _structured_turn_ref_from_mapping(value: Mapping[str, object]) -> str:
    turn_ref = _safe_turn_ref_from_mapping_value(
        value.get("dia_id")
        or value.get("locomo_evidence_ref")
        or value.get("source_dia_id")
        or value.get("evidence_id")
        or value.get("evidence_ref")
        or value.get("source_evidence_ref")
        or value.get("source_turn_ref")
        or value.get("turn_ref")
        or value.get("source_turn_id")
        or value.get("turn_id")
    )
    if turn_ref:
        return turn_ref
    dialogue = _dialogue_number_from_mapping(value)
    turn = _positive_int_string(
        value.get("source_turn_id")
        or value.get("source_turn")
        or value.get("source_turn_index")
        or value.get("turn")
        or value.get("turn_id")
        or value.get("turn_index")
    )
    if dialogue and turn:
        return f"source_turn_refs:D{dialogue}:{turn}"
    return ""


def _safe_turn_ref_from_mapping_value(value: object) -> str:
    turn_refs = _source_identity_refs_from_source_refs(
        (str(value or ""),),
        include_exact_turn_refs=True,
    )
    for ref in turn_refs:
        if ref.startswith("source_turn_refs:"):
            return ref.removeprefix("source_turn_refs:")
    return ""


def _dialogue_number_from_mapping(value: Mapping[str, object]) -> str:
    for key in (
        "source_dialogue_id",
        "source_dialogue",
        "source_dialogue_index",
        "dialogue_id",
        "dialogue",
        "dialogue_index",
        "dia_id",
        "source_dia_id",
        "session_key",
        "session_id",
    ):
        dialogue = _dialogue_number_from_value(value.get(key))
        if dialogue:
            return dialogue
    return ""


def _dialogue_number_from_value(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if match := re.fullmatch(
        r"(?:(?:session|dialogue)[-_]?|D)?(?P<number>\d+)",
        text,
        re.IGNORECASE,
    ):
        return match.group("number")
    return ""


def _positive_int_string(value: object) -> str:
    text = str(value or "").strip()
    if not text.isdigit():
        return ""
    parsed = int(text)
    return str(parsed) if parsed > 0 else ""


def _source_ref_value_has_turn_identity(value: str) -> bool:
    return bool(
        _safe_source_identity_ref(value)
        or _source_identity_refs_from_source_refs((value,), include_exact_turn_refs=True)
        or _source_identity_refs_from_dedupe_key(value)
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
    metadata_source_refs = _metadata_source_ref_values(memory.metadata)
    source_refs = tuple(
        dict.fromkeys(
            (
                *(str(ref).strip() for ref in memory.source_refs if str(ref).strip()),
                *metadata_source_refs,
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
    output_source_refs = _safe_source_refs_for_output(source_refs)
    return tuple(
        dict.fromkeys(
            (
                *output_source_refs,
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
    if value is None:
        return ()
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else ()
    return tuple(str(item).strip() for item in _sequence(value) if str(item).strip())


def _safe_source_label_tuple(value: object) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            label
            for item in _string_tuple(value)
            for label in (_safe_source_label_for_output(item),)
            if label
        )
    )


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _avg(values: Sequence[float] | Sequence[int]) -> float:
    sequence = tuple(float(value) for value in values)
    return round(sum(sequence) / len(sequence), 4) if sequence else 0.0
