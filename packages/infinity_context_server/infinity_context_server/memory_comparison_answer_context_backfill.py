"""Backfill policy for incomplete memory-comparison answer contexts."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

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
_SOURCE_PROXIMITY_WINDOW = 3
_TURN_REF_PARTS_RE = re.compile(r"\bD(?P<dialogue>\d+):(?P<turn>\d+)\b")


@dataclass(frozen=True)
class BackfillResult:
    """Answer-context backfill counts used for safe retrieval diagnostics."""

    backfilled_count: int = 0
    skipped_redundant_risky_count: int = 0
    skipped_redundant_source_count: int = 0
    skipped_redundant_role_count: int = 0


def backfill_incomplete_bundle_context(
    selected: list[RetrievedMemory],
    *,
    selected_keys: set[tuple[str, object]],
    raw_slice: Sequence[RetrievedMemory],
    bundle_context: Mapping[str, object],
    bounded_cutoff: int,
) -> BackfillResult:
    missing_roles = _string_tuple(
        bundle_context.get("answer_context_missing_required_roles")
    )
    if not missing_roles:
        return BackfillResult()
    target_count = _incomplete_bundle_backfill_target_count(
        selected_count=len(selected),
        missing_role_count=len(missing_roles),
        bounded_cutoff=bounded_cutoff,
    )
    selected_turn_refs = _selected_turn_refs(selected)
    candidates = _backfill_candidates(
        raw_slice,
        selected_keys=selected_keys,
        selected_turn_refs=selected_turn_refs,
        missing_roles=missing_roles,
    )
    original_selected_turn_refs = selected_turn_refs
    backfilled_count = 0
    skipped_redundant_risky_count = 0
    skipped_redundant_source_count = 0
    skipped_redundant_role_count = 0
    covered_roles = set(_selected_role_hits(selected, missing_roles))
    covered_backfill_source_refs: set[str] = set()
    selected_source_match_refs = set(
        ref
        for memory in selected
        for ref in _memory_source_match_refs(memory)
    )
    for retrieval_order, memory in candidates:
        features = _candidate_features(memory)
        role_hits = _missing_role_hits(features, missing_roles)
        source_refs = set(_memory_source_refs(memory))
        source_match_refs = set(_memory_source_match_refs(memory))
        source_proximity_distance = _source_proximity_distance(
            memory,
            selected_turn_refs=selected_turn_refs,
        )
        source_proximate = (
            source_proximity_distance is not None
            and source_proximity_distance <= _SOURCE_PROXIMITY_WINDOW
        )
        selected_source_duplicate = (
            bool(role_hits)
            and bool(source_match_refs)
            and bool(source_match_refs.intersection(selected_source_match_refs))
            and not memory_has_broad_summary(memory, features)
        )
        if selected_source_duplicate:
            skipped_redundant_source_count += 1
            continue
        source_redundant = (
            bool(role_hits)
            and set(role_hits).issubset(covered_roles)
            and bool(source_refs)
            and source_refs.issubset(covered_backfill_source_refs)
        )
        if source_redundant:
            skipped_redundant_source_count += 1
            continue
        risky_redundant = (
            bool(role_hits)
            and set(role_hits).issubset(covered_roles)
            and (
                memory_has_broad_summary(memory, features)
                or memory_has_conflict_or_stale(memory, features)
            )
        )
        if risky_redundant:
            skipped_redundant_risky_count += 1
            continue
        role_redundant = (
            bool(role_hits)
            and set(role_hits).issubset(covered_roles)
            and not source_proximate
        )
        if role_redundant:
            skipped_redundant_role_count += 1
            continue
        if len(selected) >= target_count:
            continue
        selected_keys.add(_memory_key(memory, retrieval_order=retrieval_order))
        selected.append(
            _with_retrieval_backfill_metadata(
                memory,
                bundle_context=bundle_context,
                missing_roles=missing_roles,
                original_selected_turn_refs=original_selected_turn_refs,
                selected_turn_refs=selected_turn_refs,
                retrieval_order=retrieval_order,
            )
        )
        covered_roles.update(role_hits)
        covered_backfill_source_refs.update(source_refs)
        selected_source_match_refs.update(source_match_refs)
        selected_turn_refs = tuple(
            dict.fromkeys((*selected_turn_refs, *_memory_turn_refs(memory)))
        )
        backfilled_count += 1
    return BackfillResult(
        backfilled_count=backfilled_count,
        skipped_redundant_risky_count=skipped_redundant_risky_count,
        skipped_redundant_source_count=skipped_redundant_source_count,
        skipped_redundant_role_count=skipped_redundant_role_count,
    )


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
    selected_turn_refs: Sequence[tuple[int, int]],
    missing_roles: Sequence[str],
) -> tuple[tuple[int, RetrievedMemory], ...]:
    candidates: list[tuple[int, RetrievedMemory]] = []
    for retrieval_order, memory in enumerate(raw_slice, start=1):
        key = _memory_key(memory, retrieval_order=retrieval_order)
        if key in selected_keys:
            continue
        if not _backfill_candidate_eligible(memory, missing_roles=missing_roles):
            continue
        candidates.append((retrieval_order, memory))
    return tuple(
        sorted(
            candidates,
            key=lambda pair: _backfill_candidate_sort_key(
                pair[1],
                missing_roles=missing_roles,
                selected_turn_refs=selected_turn_refs,
                retrieval_order=pair[0],
            ),
            reverse=True,
        )
    )


def _backfill_candidate_eligible(
    memory: RetrievedMemory,
    *,
    missing_roles: Sequence[str],
) -> bool:
    if not missing_roles:
        return True
    return _missing_role_support_score(_candidate_features(memory), missing_roles) > 0


def _backfill_candidate_sort_key(
    memory: RetrievedMemory,
    *,
    missing_roles: Sequence[str],
    selected_turn_refs: Sequence[tuple[int, int]],
    retrieval_order: int,
) -> tuple[float, float, float, float, float, float, int]:
    features = _candidate_features(memory)
    missing_role_score = _missing_role_support_score(features, missing_roles)
    answerability = _metric_value(features, "answerability_score")
    locality = _metric_value(features, "source_locality_score")
    has_source_refs = 1.0 if _memory_source_refs(memory) else 0.0
    source_proximity = _source_proximity_sort_key(
        memory,
        selected_turn_refs=selected_turn_refs,
    )
    quality_penalty = 0.0
    if memory_has_broad_summary(memory, features):
        quality_penalty += 0.6
    if memory_has_conflict_or_stale(memory, features):
        quality_penalty += 0.4
    return (
        missing_role_score,
        -quality_penalty,
        *source_proximity,
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


def _source_proximity_sort_key(
    memory: RetrievedMemory,
    *,
    selected_turn_refs: Sequence[tuple[int, int]],
) -> tuple[float, float]:
    closest_distance = _source_proximity_distance(
        memory,
        selected_turn_refs=selected_turn_refs,
    )
    if closest_distance is None or closest_distance > _SOURCE_PROXIMITY_WINDOW:
        return (0.0, 0.0)
    return (1.0, float(_SOURCE_PROXIMITY_WINDOW + 1 - closest_distance))


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


def _missing_role_hits(
    features: Mapping[str, object],
    missing_roles: Sequence[str],
) -> tuple[str, ...]:
    if not features or not missing_roles:
        return ()
    return tuple(
        role
        for role in missing_roles
        if str(role).strip() and _missing_role_match_score(features, str(role)) > 0
    )


def _selected_role_hits(
    memories: Sequence[RetrievedMemory],
    missing_roles: Sequence[str],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            role
            for memory in memories
            for role in (
                *_selected_direct_role_hits(memory, missing_roles),
                *_missing_role_hits(
                    _role_match_features(memory),
                    missing_roles,
                ),
            )
        )
    )


def _selected_direct_role_hits(
    memory: RetrievedMemory,
    missing_roles: Sequence[str],
) -> tuple[str, ...]:
    selected_role = str(memory.metadata.get("answer_context_role") or "").strip()
    if not selected_role:
        return ()
    selected_role_key = selected_role.removesuffix("_support")
    return tuple(
        role
        for role in missing_roles
        if str(role).strip()
        and str(role).strip().removesuffix("_support") == selected_role_key
    )


def _role_match_features(memory: RetrievedMemory) -> Mapping[str, object]:
    features = dict(_candidate_features(memory))
    metadata = memory.metadata
    for source_key, target_key in (
        ("answer_context_query_roles", "query_roles"),
        ("answer_context_relation_category_hits", "relation_category_hits"),
        ("answer_context_entity_hits", "entity_hits"),
        ("answer_context_speaker_hits", "speaker_hits"),
    ):
        if target_key not in features:
            values = _string_tuple(metadata.get(source_key))
            if values:
                features[target_key] = values
    return features


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
        if role_key in _TEMPORAL_ROLE_KEYS:
            return (
                0.92
                if _has_temporal_features(features, role_key=role_key)
                else 0.0
            )
        if role_key in _ROLE_KEYS_REQUIRING_EVIDENCE:
            return _role_specific_match_score(
                features,
                role_key=role_key,
                categories=categories,
                has_relation=has_relation,
                has_person=has_person,
                query_role_score=0.92,
            )
        return 0.92
    role_score = _role_specific_match_score(
        features,
        role_key=role_key,
        categories=categories,
        has_relation=has_relation,
        has_person=has_person,
        query_role_score=0.0,
    )
    if role_score > 0:
        return role_score
    return 0.0


def _role_specific_match_score(
    features: Mapping[str, object],
    *,
    role_key: str,
    categories: set[str],
    has_relation: bool,
    has_person: bool,
    query_role_score: float,
) -> float:
    if role_key in categories:
        return max(0.9, query_role_score)
    profile_category = _PROFILE_CATEGORY_BY_ROLE_KEY.get(role_key)
    if profile_category and profile_category in categories:
        return max(0.9, query_role_score)
    if role_key in {"contrast"}:
        return (
            max(0.88, query_role_score)
            if _has_contrast_features(features)
            else 0.0
        )
    if role_key in _TEMPORAL_ROLE_KEYS:
        return (
            max(0.86, query_role_score)
            if _has_temporal_features(features, role_key=role_key)
            else 0.0
        )
    if role_key == "preference":
        return (
            max(0.88, query_role_score)
            if features.get("has_preference_evidence") is True
            else 0.0
        )
    if role_key == "favorite":
        return max(0.9, query_role_score) if "favorite_preference" in categories else 0.0
    if role_key == "visual":
        return (
            max(0.88, query_role_score)
            if features.get("has_visual_evidence") is True
            else 0.0
        )
    if role_key == "location":
        return max(0.9, query_role_score) if "location_transition" in categories else 0.0
    if role_key == "event":
        event_categories = {
            "activity",
            "current_goal",
            "participation_event",
            "registration_event",
        }
        return (
            max(0.85, query_role_score)
            if categories.intersection(event_categories)
            else 0.0
        )
    if role_key == "inference":
        return max(0.78, query_role_score) if has_relation and has_person else 0.0
    if role_key == "bridge":
        return (
            max(0.9, query_role_score)
            if features.get("bridge_query_hit") is True
            else 0.0
        )
    return max(0.86, query_role_score) if role_key in categories else 0.0


_TEMPORAL_ROLE_KEYS = frozenset(
    {
        "temporal",
        "duration_temporal",
        "explicit_temporal",
        "relative_temporal",
        "temporal_sequence",
        "visual_temporal",
    }
)
_PROFILE_CATEGORY_BY_ROLE_KEY = {
    "action": "action_event",
    "activity": "activity_profile",
    "age": "age_profile",
    "alias": "alias_profile",
    "commitment": "commitment_profile",
    "contact": "contact_profile",
    "current_goal": "current_goal",
    "date": "date_profile",
    "diet": "diet_profile",
    "education": "education_profile",
    "employment": "employment_profile",
    "health": "health_profile",
    "identity": "identity_profile",
    "pet": "pet_profile",
    "skill": "skill_profile",
    "status": "status_profile",
    "support_goal": "support_goal",
    "vehicle": "vehicle_profile",
}
_ROLE_KEYS_REQUIRING_EVIDENCE = frozenset(
    {
        "bridge",
        "causal",
        "communication",
        "contrast",
        "emotion_response",
        "event",
        "exchange",
        "favorite",
        "inference",
        "location",
        "preference",
        "symbolic_meaning",
        "visual",
        *_PROFILE_CATEGORY_BY_ROLE_KEY,
    }
)


def _has_temporal_features(
    features: Mapping[str, object],
    *,
    role_key: str,
) -> bool:
    time_kind = str(features.get("time_intent_kind") or "").strip()
    if role_key == "visual_temporal":
        return bool(
            features.get("has_visual_evidence") is True
            and any(
                features.get(key) is True
                for key in (
                    "has_temporal_surface",
                    "has_sequence_surface",
                    "has_duration_surface",
                    "has_relative_time_surface",
                    "has_explicit_time_content_surface",
                    "has_temporal_sequence_surface",
                    "currentness_surface",
                )
            )
        )
    if role_key == "duration_temporal" or time_kind == "duration":
        return features.get("has_duration_surface") is True
    if role_key == "explicit_temporal" or time_kind == "explicit_time":
        return features.get("has_explicit_time_content_surface") is True
    if role_key == "relative_temporal" or time_kind == "relative_time":
        return any(
            features.get(key) is True
            for key in (
                "has_relative_time_surface",
                "currentness_surface",
                "has_temporal_surface",
            )
        )
    if role_key == "temporal_sequence" or time_kind == "temporal_sequence":
        return any(
            features.get(key) is True
            for key in ("has_temporal_sequence_surface", "has_sequence_surface")
        )
    return any(
        features.get(key) is True
        for key in (
            "has_temporal_surface",
            "has_sequence_surface",
            "has_duration_surface",
            "has_relative_time_surface",
            "has_explicit_time_content_surface",
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
    original_selected_turn_refs: Sequence[tuple[int, int]],
    selected_turn_refs: Sequence[tuple[int, int]],
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
    source_proximity_distance = _source_proximity_distance(
        memory,
        selected_turn_refs=selected_turn_refs,
    )
    if (
        source_proximity_distance is not None
        and source_proximity_distance <= _SOURCE_PROXIMITY_WINDOW
    ):
        reason_codes.append("source_proximity_support")
        metadata["answer_context_backfill_source_proximity_distance"] = (
            source_proximity_distance
        )
        original_source_proximity_distance = _source_proximity_distance(
            memory,
            selected_turn_refs=original_selected_turn_refs,
        )
        if (
            original_source_proximity_distance is None
            or original_source_proximity_distance > _SOURCE_PROXIMITY_WINDOW
        ):
            reason_codes.append("chained_source_proximity_support")
            metadata["answer_context_backfill_chained_source_proximity"] = True
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


def _memory_source_match_refs(memory: RetrievedMemory) -> tuple[str, ...]:
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
                *_memory_source_refs(memory),
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


def _selected_turn_refs(memories: Sequence[RetrievedMemory]) -> tuple[tuple[int, int], ...]:
    return tuple(
        dict.fromkeys(
            turn_ref
            for memory in memories
            for turn_ref in _memory_turn_refs(memory)
        )
    )


def _source_proximity_distance(
    memory: RetrievedMemory,
    *,
    selected_turn_refs: Sequence[tuple[int, int]],
) -> int | None:
    distances = [
        abs(selected_turn - candidate_turn)
        for selected_dialogue, selected_turn in selected_turn_refs
        for candidate_dialogue, candidate_turn in _memory_turn_refs(memory)
        if selected_dialogue == candidate_dialogue
    ]
    if not distances:
        return None
    return min(distances)


def _memory_turn_refs(memory: RetrievedMemory) -> tuple[tuple[int, int], ...]:
    refs: list[tuple[int, int]] = []
    for value in (*_memory_source_refs(memory), memory.text):
        for match in _TURN_REF_PARTS_RE.finditer(str(value)):
            refs.append(
                (
                    int(match.group("dialogue")),
                    int(match.group("turn")),
                )
            )
    return tuple(dict.fromkeys(refs))


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
