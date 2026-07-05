"""Fallback retrieval-slice metadata for answer-context prompts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_candidate_risks import (
    candidate_features as _candidate_features,
)
from infinity_context_server.memory_comparison_models import RetrievedMemory
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


def retrieval_slice_answer_context(
    memories: Sequence[RetrievedMemory],
    *,
    fallback_reason: str,
) -> tuple[RetrievedMemory, ...]:
    """Annotate raw-slice fallback items with prompt-facing provenance."""

    return tuple(
        _with_retrieval_slice_metadata(
            memory,
            retrieval_order=retrieval_order,
            fallback_reason=fallback_reason,
        )
        for retrieval_order, memory in enumerate(memories, start=1)
    )


def _with_retrieval_slice_metadata(
    memory: RetrievedMemory,
    *,
    retrieval_order: int,
    fallback_reason: str,
) -> RetrievedMemory:
    metadata = dict(memory.metadata)
    metadata["answer_context_retrieval_order"] = retrieval_order
    metadata["answer_context_role"] = "retrieval_slice"
    metadata["answer_context_fallback_reason"] = fallback_reason
    metadata["answer_context_reason_codes"] = (
        "retrieval_slice_fallback",
        fallback_reason,
    )
    _add_candidate_feature_metadata(metadata, _candidate_features(memory))
    return RetrievedMemory(
        text=memory.text,
        rank=memory.rank,
        score=memory.score,
        item_id=memory.item_id,
        created_at=memory.created_at,
        source_refs=_memory_source_refs(memory),
        metadata=metadata,
    )


def _add_candidate_feature_metadata(
    metadata: dict[str, object],
    features: Mapping[str, object],
) -> None:
    for source_key, target_key in (
        ("source_types", "answer_context_source_types"),
        ("retrieval_sources", "answer_context_retrieval_sources"),
        ("query_roles", "answer_context_query_roles"),
        ("relation_category_hits", "answer_context_relation_category_hits"),
        ("entity_hits", "answer_context_entity_hits"),
        ("speaker_hits", "answer_context_speaker_hits"),
    ):
        values = _string_tuple(features.get(source_key))
        if values:
            metadata[target_key] = values
    source_type = str(features.get("source_type") or "").strip()
    if source_type:
        metadata["answer_context_source_type"] = source_type
    for source_key, target_key in (
        ("answerability_score", "answer_context_answerability_score"),
        ("source_locality_score", "answer_context_source_locality_score"),
    ):
        score = _metric_value(features, source_key)
        if score > 0:
            metadata[target_key] = round(score, 6)


def _memory_source_refs(memory: RetrievedMemory) -> tuple[str, ...]:
    diagnostics = _mapping(memory.metadata.get("diagnostics"))
    fusion = _mapping(diagnostics.get("benchmark_candidate_fusion"))
    features = _candidate_features(memory)
    compacted_fusion_refs = (
        diagnostics.get("benchmark_compacted_selected_source_refs") is True
    )
    fusion_source_refs = (
        _string_tuple(fusion.get("source_refs")) if not compacted_fusion_refs else ()
    )
    source_refs = tuple(
        dict.fromkeys(
            (
                *(str(ref).strip() for ref in memory.source_refs if str(ref).strip()),
                *fusion_source_refs,
            )
        )
    )
    output_source_refs = _safe_source_refs_for_output(source_refs)
    return tuple(
        dict.fromkeys(
            (
                *output_source_refs,
                *_source_identity_refs_from_source_refs(source_refs),
                *_source_identity_refs_from_dedupe_key(
                    features.get("source_ref_dedupe_key")
                ),
                *_source_identity_refs_from_dedupe_key(fusion.get("dedupe_key")),
                *_source_identity_refs_from_text(memory.text, source_refs=source_refs),
            )
        )
    )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return tuple(value)
    return ()


def _string_tuple(value: object) -> tuple[str, ...]:
    return tuple(str(item).strip() for item in _sequence(value) if str(item).strip())


def _metric_value(item: Mapping[str, object], key: str) -> float:
    value = item.get(key)
    if isinstance(value, bool):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
