"""Backfill policy for incomplete memory-comparison answer contexts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

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

_INCOMPLETE_BUNDLE_BACKFILL_MIN_ITEMS = 6
_INCOMPLETE_BUNDLE_BACKFILL_MAX_ITEMS = 12
_INCOMPLETE_BUNDLE_BACKFILL_ITEMS_PER_MISSING_ROLE = 2


def backfill_incomplete_bundle_context(
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
    candidates = _backfill_candidates(
        raw_slice,
        selected_keys=selected_keys,
        missing_roles=missing_roles,
    )
    backfilled_count = 0
    for retrieval_order, memory in candidates:
        if len(selected) >= target_count:
            break
        selected_keys.add(_memory_key(memory, retrieval_order=retrieval_order))
        selected.append(
            _with_retrieval_backfill_metadata(
                memory,
                bundle_context=bundle_context,
                missing_roles=missing_roles,
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


def _backfill_candidates(
    raw_slice: Sequence[RetrievedMemory],
    *,
    selected_keys: set[tuple[str, object]],
    missing_roles: Sequence[str],
) -> tuple[tuple[int, RetrievedMemory], ...]:
    candidates: list[tuple[int, RetrievedMemory]] = []
    for retrieval_order, memory in enumerate(raw_slice, start=1):
        key = _memory_key(memory, retrieval_order=retrieval_order)
        if key in selected_keys:
            continue
        candidates.append((retrieval_order, memory))
    return tuple(
        sorted(
            candidates,
            key=lambda pair: _backfill_candidate_sort_key(
                pair[1],
                missing_roles=missing_roles,
                retrieval_order=pair[0],
            ),
            reverse=True,
        )
    )


def _backfill_candidate_sort_key(
    memory: RetrievedMemory,
    *,
    missing_roles: Sequence[str],
    retrieval_order: int,
) -> tuple[float, float, float, float, float, int]:
    features = _candidate_features(memory)
    missing_role_score = _missing_role_support_score(features, missing_roles)
    answerability = _metric_value(features, "answerability_score")
    locality = _metric_value(features, "source_locality_score")
    has_source_refs = 1.0 if _memory_source_refs(memory) else 0.0
    quality_penalty = 0.0
    if memory_has_broad_summary(memory, features):
        quality_penalty += 0.6
    if memory_has_conflict_or_stale(memory, features):
        quality_penalty += 0.4
    return (
        missing_role_score,
        -quality_penalty,
        _backfill_answerability_sort_score(answerability),
        _backfill_locality_sort_score(locality),
        has_source_refs,
        -retrieval_order,
    )


def _backfill_answerability_sort_score(score: float) -> float:
    if score <= 0:
        return 0.55
    return score


def _backfill_locality_sort_score(score: float) -> float:
    if score <= 0:
        return 0.45
    return score


def _missing_role_support_score(
    features: Mapping[str, object],
    missing_roles: Sequence[str],
) -> float:
    if not features or not missing_roles:
        return 0.0
    scores = [
        _missing_role_match_score(features, str(role))
        for role in missing_roles
        if str(role).strip()
    ]
    return max(scores, default=0.0)


def _missing_role_match_score(features: Mapping[str, object], role: str) -> float:
    role_key = role.strip().removesuffix("_support")
    categories = set(_string_tuple(features.get("relation_category_hits")))
    query_roles = set(_string_tuple(features.get("query_roles")))
    has_relation = bool(categories or _string_tuple(features.get("relation_hits")))
    has_person = bool(
        _string_tuple(features.get("entity_hits"))
        or _string_tuple(features.get("speaker_hits"))
    )
    if role in query_roles:
        return 0.92
    if role_key in categories:
        return 0.9
    if role_key in {"contrast"}:
        return 0.88 if _has_contrast_features(features) else 0.0
    if role_key in {
        "temporal",
        "duration_temporal",
        "explicit_temporal",
        "relative_temporal",
        "temporal_sequence",
    }:
        return 0.86 if _has_temporal_features(features) else 0.0
    if role_key == "preference":
        return 0.88 if features.get("has_preference_evidence") is True else 0.0
    if role_key == "visual":
        return 0.88 if features.get("has_visual_evidence") is True else 0.0
    if role_key == "location":
        return 0.9 if "location_transition" in categories else 0.0
    if role_key == "event":
        event_categories = {
            "activity",
            "current_goal",
            "participation_event",
            "registration_event",
        }
        return 0.85 if categories.intersection(event_categories) else 0.0
    if role_key == "inference":
        return 0.78 if has_relation and has_person else 0.0
    if role_key == "bridge":
        return 0.9 if features.get("bridge_query_hit") is True else 0.0
    return 0.86 if role_key in categories else 0.0


def _has_temporal_features(features: Mapping[str, object]) -> bool:
    return any(
        features.get(key) is True
        for key in (
            "has_temporal_surface",
            "has_sequence_surface",
            "has_duration_surface",
            "has_relative_time_surface",
            "has_explicit_time_surface",
            "has_temporal_sequence_surface",
            "currentness_surface",
        )
    )


def _has_contrast_features(features: Mapping[str, object]) -> bool:
    return any(
        features.get(key) is True
        for key in (
            "contrast_surface",
            "negation_surface",
            "stale_surface",
        )
    )


def _with_retrieval_backfill_metadata(
    memory: RetrievedMemory,
    *,
    bundle_context: Mapping[str, object],
    missing_roles: Sequence[str],
    retrieval_order: int,
) -> RetrievedMemory:
    metadata = dict(memory.metadata)
    metadata["answer_context_retrieval_order"] = retrieval_order
    metadata.update(bundle_context)
    metadata["answer_context_role"] = "retrieval_backfill"
    features = _candidate_features(memory)
    role_score = _missing_role_support_score(features, missing_roles)
    reason_codes = [
        "incomplete_bundle_backfill",
        "retrieval_slice_support",
    ]
    if role_score > 0:
        reason_codes.append("missing_role_support")
    metadata["answer_context_reason_codes"] = tuple(reason_codes)
    _add_backfill_feature_metadata(metadata, features, missing_roles=missing_roles)
    return RetrievedMemory(
        text=memory.text,
        rank=memory.rank,
        score=memory.score,
        item_id=memory.item_id,
        created_at=memory.created_at,
        source_refs=_memory_source_refs(memory),
        metadata=metadata,
    )


def _add_backfill_feature_metadata(
    metadata: dict[str, object],
    features: Mapping[str, object],
    *,
    missing_roles: Sequence[str],
) -> None:
    answerability_score = _metric_value(features, "answerability_score")
    if answerability_score > 0:
        metadata["answer_context_answerability_score"] = round(
            answerability_score,
            6,
        )
    source_locality_score = _metric_value(features, "source_locality_score")
    if source_locality_score > 0:
        metadata["answer_context_source_locality_score"] = round(
            source_locality_score,
            6,
        )
    for source_key, target_key in (
        ("query_roles", "answer_context_query_roles"),
        ("relation_category_hits", "answer_context_relation_category_hits"),
        ("entity_hits", "answer_context_entity_hits"),
        ("speaker_hits", "answer_context_speaker_hits"),
    ):
        values = _string_tuple(features.get(source_key))
        if values:
            metadata[target_key] = values
    matched_roles = tuple(
        role
        for role in missing_roles
        if _missing_role_match_score(features, str(role)) > 0
    )
    if matched_roles:
        metadata["answer_context_backfill_missing_role_hits"] = matched_roles


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


def _memory_source_refs(memory: RetrievedMemory) -> tuple[str, ...]:
    diagnostics = _mapping(memory.metadata.get("diagnostics"))
    fusion = _mapping(diagnostics.get("benchmark_candidate_fusion"))
    features = _candidate_features(memory)
    source_refs = tuple(
        dict.fromkeys(
            (
                *(str(ref).strip() for ref in memory.source_refs if str(ref).strip()),
                *_string_tuple(fusion.get("source_refs")),
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
