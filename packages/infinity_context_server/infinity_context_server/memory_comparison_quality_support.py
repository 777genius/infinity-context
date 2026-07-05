"""Support-role predicates for memory-comparison quality diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from infinity_context_server.memory_comparison_source_identity import (
    safe_source_refs_for_output as _safe_source_refs_for_output,
)

_TEMPORAL_EVIDENCE_NEEDS = frozenset(
    {
        "temporal_support",
        "temporal_sequence",
        "duration_temporal_support",
        "explicit_temporal_support",
        "relative_temporal_support",
        "temporal_sequence_support",
        "visual_temporal_support",
    }
)
_TEMPORAL_BUNDLE_ROLES = frozenset(
    {
        "temporal_support",
        "duration_temporal_support",
        "explicit_temporal_support",
        "relative_temporal_support",
        "temporal_sequence_support",
        "visual_temporal_support",
    }
)
_TYPED_RELATION_SUPPORT_CATEGORIES = {
    "action_support": frozenset({"action_event"}),
    "activity_support": frozenset({"activity_profile"}),
    "age_support": frozenset({"age_profile"}),
    "alias_support": frozenset({"alias_profile"}),
    "commitment_support": frozenset({"commitment_profile"}),
    "contact_support": frozenset({"contact_profile"}),
    "current_goal_support": frozenset({"current_goal"}),
    "date_support": frozenset({"date_profile"}),
    "diet_support": frozenset({"diet_profile"}),
    "education_support": frozenset({"education_profile"}),
    "employment_support": frozenset({"employment_profile"}),
    "favorite_support": frozenset({"favorite_preference"}),
    "health_support": frozenset({"health_profile"}),
    "identity_support": frozenset({"identity_profile"}),
    "pet_support": frozenset({"pet_profile"}),
    "skill_support": frozenset({"skill_profile"}),
    "status_support": frozenset({"status_profile"}),
    "support_goal_support": frozenset({"support_goal"}),
    "vehicle_support": frozenset({"vehicle_profile"}),
}
_SUPPORT_ROLE_LABELS = frozenset(
    {
        "bridge",
        "causal_support",
        "communication_support",
        "contrast",
        "emotion_response_support",
        "event_support",
        "exchange_support",
        "inference_support",
        "location_support",
        "absence_support",
        "negative_absence_support",
        "negative_support",
        "preference_support",
        "supporting",
        "symbolic_meaning_support",
        "temporal_support",
        "visual_support",
        *_TEMPORAL_BUNDLE_ROLES,
        *_TYPED_RELATION_SUPPORT_CATEGORIES,
    }
)
_ROLE_ONLY_REASON_PREFIXES = ("role:", "selected_role:")
_SUPPORT_AUDIT_SEQUENCE_LIMIT = 8


def typed_relation_support_roles() -> tuple[str, ...]:
    return tuple(sorted(_TYPED_RELATION_SUPPORT_CATEGORIES))


def needs_temporal_support(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = _merged_query_values(query_profile, intent, "evidence_need")
    roles = _merged_query_values(query_profile, intent, "bundle_evidence_roles")
    relation_categories = _relation_categories(query_profile, intent)
    return bool(
        _TEMPORAL_EVIDENCE_NEEDS.intersection(evidence_need)
        or _TEMPORAL_BUNDLE_ROLES.intersection(roles)
        or "temporal" in relation_categories
    )


def needs_contrast_evidence(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = _merged_query_values(query_profile, intent, "evidence_need")
    roles = _merged_query_values(query_profile, intent, "bundle_evidence_roles")
    relation_categories = _relation_categories(query_profile, intent)
    return bool(
        "contrast" in evidence_need
        or "contrast" in roles
        or "contrast" in relation_categories
    )


def needs_causal_support(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = _merged_query_values(query_profile, intent, "evidence_need")
    relation_categories = _relation_categories(query_profile, intent)
    roles = _merged_query_values(query_profile, intent, "bundle_evidence_roles")
    return bool(
        "causal_support" in evidence_need
        or "causal_support" in roles
        or "causal" in relation_categories
    )


def needs_location_support(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = _merged_query_values(query_profile, intent, "evidence_need")
    roles = _merged_query_values(query_profile, intent, "bundle_evidence_roles")
    relation_categories = _relation_categories(query_profile, intent)
    return bool(
        "location_support" in evidence_need
        or "location_support" in roles
        or "location_transition" in relation_categories
    )


def needs_inference_support(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = _merged_query_values(query_profile, intent, "evidence_need")
    roles = _merged_query_values(query_profile, intent, "bundle_evidence_roles")
    return bool("inference_support" in evidence_need or "inference_support" in roles)


def needs_preference_support(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = _merged_query_values(query_profile, intent, "evidence_need")
    roles = _merged_query_values(query_profile, intent, "bundle_evidence_roles")
    relation_categories = _relation_categories(query_profile, intent)
    return bool(
        "preference" in evidence_need
        or "preference_support" in roles
        or "preference" in relation_categories
    )


def needs_emotion_response_support(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = _merged_query_values(query_profile, intent, "evidence_need")
    roles = _merged_query_values(query_profile, intent, "bundle_evidence_roles")
    relation_categories = _relation_categories(query_profile, intent)
    return bool(
        "emotion_response" in evidence_need
        or "emotion_response_support" in roles
        or "emotion_response" in relation_categories
    )


def needs_event_support(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = _merged_query_values(query_profile, intent, "evidence_need")
    roles = _merged_query_values(query_profile, intent, "bundle_evidence_roles")
    relation_categories = _relation_categories(query_profile, intent)
    event_categories = {"participation_event", "registration_event"}
    return bool(
        event_categories & set(evidence_need)
        or "event_support" in roles
        or event_categories & set(relation_categories)
    )


def needs_exchange_support(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = _merged_query_values(query_profile, intent, "evidence_need")
    roles = _merged_query_values(query_profile, intent, "bundle_evidence_roles")
    relation_categories = _relation_categories(query_profile, intent)
    return bool(
        "exchange" in evidence_need
        or "exchange_support" in roles
        or "exchange" in relation_categories
    )


def needs_communication_support(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = _merged_query_values(query_profile, intent, "evidence_need")
    roles = _merged_query_values(query_profile, intent, "bundle_evidence_roles")
    relation_categories = _relation_categories(query_profile, intent)
    return bool(
        "communication" in evidence_need
        or "communication_support" in roles
        or "communication" in relation_categories
    )


def needs_symbolic_meaning_support(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = _merged_query_values(query_profile, intent, "evidence_need")
    roles = _merged_query_values(query_profile, intent, "bundle_evidence_roles")
    relation_categories = _relation_categories(query_profile, intent)
    return bool(
        "symbolic_meaning" in evidence_need
        or "symbolic_meaning_support" in roles
        or "symbolic_meaning" in relation_categories
    )


def needs_typed_relation_support_roles(item: Mapping[str, object]) -> tuple[str, ...]:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = _merged_query_values(query_profile, intent, "evidence_need")
    roles = _merged_query_values(query_profile, intent, "bundle_evidence_roles")
    needed: list[str] = []
    for role, categories in sorted(_TYPED_RELATION_SUPPORT_CATEGORIES.items()):
        if role in roles or categories.intersection(evidence_need):
            needed.append(role)
    return tuple(dict.fromkeys(needed))


def needs_visual_support(item: Mapping[str, object]) -> bool:
    query_profile, intent = _query_profile_and_intent(item)
    evidence_need = _merged_query_values(query_profile, intent, "evidence_need")
    roles = _merged_query_values(query_profile, intent, "bundle_evidence_roles")
    relation_categories = _relation_categories(query_profile, intent)
    visual_terms = _str_tuple(query_profile.get("visual_terms"))
    return bool(
        "visual_evidence" in evidence_need
        or "visual_support" in roles
        or "visual" in relation_categories
        or visual_terms
    )


def bundle_roles(bundle: Mapping[str, object]) -> set[str]:
    roles = {
        str(item.get("role") or "").strip()
        for item in _bundle_items(bundle)
        if str(item.get("role") or "").strip()
    }
    planner = _mapping(bundle.get("bundle_planner"))
    role_counts = _mapping(planner.get("role_counts"))
    roles.update(str(role).strip() for role in role_counts if str(role).strip())
    return roles


def bundle_has_planner_reason(bundle: Mapping[str, object], reason: str) -> bool:
    return any(
        reason in _str_tuple(item.get("planner_reason_codes"))
        for item in _bundle_items(bundle)
    )


def bundle_has_temporal_support(bundle: Mapping[str, object]) -> bool:
    return any(_bundle_item_has_temporal_support(item) for item in _bundle_items(bundle))


def _bundle_item_has_temporal_support(item: Mapping[str, object]) -> bool:
    if not _passes_support_quality(item):
        return False
    time_kind = str(item.get("time_intent_kind") or "").strip()
    reasons = _str_tuple(item.get("planner_reason_codes"))
    has_temporal = bool(
        item.get("has_temporal_surface") or "temporal_surface" in reasons
    )
    has_sequence = bool(
        item.get("has_sequence_surface") or "sequence_surface" in reasons
    )
    has_duration = bool(
        item.get("has_duration_surface") or "duration_surface" in reasons
    )
    has_relative = bool(
        item.get("has_relative_time_surface") or "relative_time_surface" in reasons
    )
    has_explicit = bool(
        item.get("has_explicit_time_content_surface")
        or "explicit_time_content_surface" in reasons
    )
    has_temporal_sequence = bool(
        item.get("has_temporal_sequence_surface")
        or "temporal_sequence_surface" in reasons
    )
    has_currentness = bool(
        item.get("currentness_surface") or "currentness_surface" in reasons
    )
    if time_kind == "duration":
        return has_duration
    if time_kind == "temporal_sequence":
        return has_temporal_sequence or has_sequence
    if time_kind == "explicit_time":
        return has_explicit
    if time_kind == "relative_time":
        return has_relative or has_currentness or has_temporal
    return bool(
        has_temporal
        or has_sequence
        or has_duration
        or has_relative
        or has_explicit
        or has_temporal_sequence
        or has_currentness
    )


def bundle_has_contrast_support(bundle: Mapping[str, object]) -> bool:
    return any(_bundle_item_has_contrast_support(item) for item in _bundle_items(bundle))


def _bundle_item_has_contrast_support(item: Mapping[str, object]) -> bool:
    if not _passes_support_quality(item):
        return False
    reasons = _str_tuple(item.get("planner_reason_codes"))
    if item.get("contrast_surface") or "contrast_surface" in reasons:
        return True
    has_currentness = bool(
        item.get("currentness_surface") or "currentness_surface" in reasons
    )
    has_change_or_negation = bool(
        item.get("stale_surface")
        or item.get("negation_surface")
        or "stale_surface" in reasons
        or "negation_surface" in reasons
    )
    return has_currentness and has_change_or_negation


def bundle_has_causal_support(
    bundle: Mapping[str, object],
    *,
    require_grounding: bool = False,
) -> bool:
    return any(
        bool(
            _passes_support_quality(item)
            and _passes_person_grounding(item, require_grounding=require_grounding)
            and (
                "causal" in _str_tuple(item.get("relation_category_hits"))
                or "causal_relation_hits"
                in _str_tuple(item.get("planner_reason_codes"))
                or "causal_relation_category_hits"
                in _str_tuple(item.get("planner_reason_codes"))
            )
        )
        for item in _bundle_items(bundle)
    )


def bundle_has_location_support(
    bundle: Mapping[str, object],
    *,
    require_grounding: bool = False,
) -> bool:
    return any(
        bool(
            _passes_support_quality(item)
            and _passes_person_grounding(item, require_grounding=require_grounding)
            and (
                "location_transition"
                in _str_tuple(item.get("relation_category_hits"))
                or "location_relation_category_hits"
                in _str_tuple(item.get("planner_reason_codes"))
            )
        )
        for item in _bundle_items(bundle)
    )


def bundle_has_preference_support(
    bundle: Mapping[str, object],
    *,
    require_grounding: bool = False,
) -> bool:
    return any(
        bool(
            _passes_support_quality(item)
            and _passes_person_grounding(item, require_grounding=require_grounding)
            and not _bundle_item_has_stale_only_surface(item)
            and (
                "preference" in _str_tuple(item.get("relation_category_hits"))
                or "favorite_preference"
                in _str_tuple(item.get("relation_category_hits"))
                or "preference_evidence"
                in _str_tuple(item.get("planner_reason_codes"))
                or "preference_relation_category_hits"
                in _str_tuple(item.get("planner_reason_codes"))
            )
        )
        for item in _bundle_items(bundle)
    )


def _bundle_item_has_stale_only_surface(item: Mapping[str, object]) -> bool:
    reasons = _str_tuple(item.get("planner_reason_codes"))
    has_stale = bool(item.get("stale_surface") or "stale_surface" in reasons)
    has_currentness = bool(
        item.get("currentness_surface") or "currentness_surface" in reasons
    )
    has_contrast = bool(item.get("contrast_surface") or "contrast_surface" in reasons)
    return has_stale and not (has_currentness or has_contrast)


def bundle_has_emotion_response_support(
    bundle: Mapping[str, object],
    *,
    require_grounding: bool = False,
) -> bool:
    return any(
        bool(
            _passes_support_quality(item)
            and _passes_person_grounding(item, require_grounding=require_grounding)
            and (
                "emotion_response"
                in _str_tuple(item.get("relation_category_hits"))
                or "emotion_response_relation_category_hits"
                in _str_tuple(item.get("planner_reason_codes"))
            )
        )
        for item in _bundle_items(bundle)
    )


def bundle_has_event_support(
    bundle: Mapping[str, object],
    *,
    require_grounding: bool = False,
) -> bool:
    return any(
        bool(
            _passes_support_quality(item)
            and _passes_person_grounding(item, require_grounding=require_grounding)
            and (
                {"registration_event", "participation_event"}
                & set(_str_tuple(item.get("relation_category_hits")))
                or "event_relation_category_hits"
                in _str_tuple(item.get("planner_reason_codes"))
            )
        )
        for item in _bundle_items(bundle)
    )


def bundle_has_communication_support(
    bundle: Mapping[str, object],
    *,
    require_grounding: bool = False,
) -> bool:
    return any(
        bool(
            _passes_support_quality(item)
            and "communication" in _str_tuple(item.get("relation_category_hits"))
            and _passes_person_grounding(
                item,
                require_grounding=require_grounding,
                speaker_grounding=require_grounding,
            )
            and (
                "communication_speaker_hits"
                in _str_tuple(item.get("planner_reason_codes"))
                or "communication_direct_speaker_turn"
                in _str_tuple(item.get("planner_reason_codes"))
            )
        )
        for item in _bundle_items(bundle)
    )


def bundle_has_exchange_support(
    bundle: Mapping[str, object],
    *,
    require_grounding: bool = False,
) -> bool:
    return any(
        bool(
            _passes_support_quality(item)
            and _passes_person_grounding(item, require_grounding=require_grounding)
            and (
                "exchange" in _str_tuple(item.get("relation_category_hits"))
                or "exchange_relation_category_hits"
                in _str_tuple(item.get("planner_reason_codes"))
            )
        )
        for item in _bundle_items(bundle)
    )


def bundle_has_symbolic_meaning_support(
    bundle: Mapping[str, object],
    *,
    require_grounding: bool = False,
) -> bool:
    return any(
        bool(
            _passes_support_quality(item)
            and _passes_person_grounding(item, require_grounding=require_grounding)
            and (
                "symbolic_meaning" in _str_tuple(item.get("relation_category_hits"))
                or "symbolic_meaning_relation_category_hits"
                in _str_tuple(item.get("planner_reason_codes"))
            )
        )
        for item in _bundle_items(bundle)
    )


def bundle_has_visual_support(
    bundle: Mapping[str, object],
    *,
    require_grounding: bool = False,
) -> bool:
    return any(
        bool(
            _passes_support_quality(item)
            and _passes_person_grounding(item, require_grounding=require_grounding)
            and (
                item.get("has_visual_evidence") is True
                or "visual" in _str_tuple(item.get("relation_category_hits"))
                or "visual_evidence" in _str_tuple(item.get("planner_reason_codes"))
            )
        )
        for item in _bundle_items(bundle)
    )


def bundle_has_inference_support(
    bundle: Mapping[str, object],
    *,
    require_grounding: bool = False,
) -> bool:
    return any(
        bool(
            _passes_support_quality(item)
            and _passes_person_grounding(item, require_grounding=require_grounding)
            and (
                "inference" in _str_tuple(item.get("relation_category_hits"))
                or "inference_relation_category_hits"
                in _str_tuple(item.get("planner_reason_codes"))
                or "inference_relation_hits"
                in _str_tuple(item.get("planner_reason_codes"))
                or (
                    "inference_entity_hits"
                    in _str_tuple(item.get("planner_reason_codes"))
                    and "inference_relation_hits"
                    in _str_tuple(item.get("planner_reason_codes"))
                )
            )
        )
        for item in _bundle_items(bundle)
    )


def bundle_has_typed_relation_support(
    bundle: Mapping[str, object],
    role: str,
    *,
    require_grounding: bool = False,
) -> bool:
    categories = _TYPED_RELATION_SUPPORT_CATEGORIES.get(role)
    if not categories:
        return False
    return any(
        bool(
            _passes_support_quality(item)
            and _passes_person_grounding(item, require_grounding=require_grounding)
            and categories.intersection(_str_tuple(item.get("relation_category_hits")))
        )
        for item in _bundle_items(bundle)
    )


def bundle_weak_support_reasons(bundle: Mapping[str, object]) -> tuple[str, ...]:
    items = _bundle_items(bundle)
    if not items:
        return ()
    support_items = tuple(item for item in items if _is_support_role_item(item))
    weak_items = tuple(item for item in items if not _passes_support_quality(item))
    reasons: list[str] = []
    if weak_items and len(weak_items) == len(items):
        reasons.append("all_selected_support_weak")
    elif weak_items:
        reasons.append("weak_selected_support")
    for item in weak_items:
        reasons.extend(_support_quality_risk_reasons(item))
    if (
        support_items
        and any(_passes_support_quality(item) for item in support_items)
        and not any(_bundle_item_has_substantive_support(item) for item in support_items)
    ):
        reasons.append("role_label_only_support")
    return tuple(dict.fromkeys(reasons))


def bundle_support_audit_items(
    bundle: Mapping[str, object],
    *,
    limit: int = 5,
) -> tuple[dict[str, object], ...]:
    """Return redacted support item facts for diagnostics samples."""
    if limit <= 0:
        return ()
    rows: list[dict[str, object]] = []
    for index, item in enumerate(_bundle_items(bundle), start=1):
        is_support = _is_support_role_item(item)
        passes_quality = _passes_support_quality(item)
        if not (is_support or not passes_quality):
            continue
        rows.append(
            {
                "item_index": index,
                "role": str(item.get("role") or "").strip(),
                "retrieval_order": _positive_int(item.get("retrieval_order")),
                "support_quality_passed": passes_quality,
                "support_risk_reasons": _support_quality_risk_reasons(item),
                "has_substantive_support": _bundle_item_has_substantive_support(item),
                "answerability_score": _float_value(item.get("answerability_score")),
                "source_locality_score": _float_value(item.get("source_locality_score")),
                "source_refs": _safe_source_refs_for_output(
                    _bounded_str_tuple(item.get("source_refs"))
                ),
                "covered_evidence_terms": _bounded_str_tuple(
                    item.get("covered_evidence_terms")
                ),
                "entity_hit_count": len(_str_tuple(item.get("entity_hits"))),
                "speaker_hit_count": len(_str_tuple(item.get("speaker_hits"))),
                "relation_hit_count": len(_str_tuple(item.get("relation_hits"))),
                "relation_category_hits": _bounded_str_tuple(
                    item.get("relation_category_hits")
                ),
                "planner_reason_codes": _bounded_str_tuple(
                    item.get("planner_reason_codes")
                ),
            }
        )
        if len(rows) >= limit:
            break
    return tuple(rows)


def _bounded_str_tuple(
    value: object,
    *,
    limit: int = _SUPPORT_AUDIT_SEQUENCE_LIMIT,
) -> tuple[str, ...]:
    return _str_tuple(value)[:limit]


def _query_profile_and_intent(
    item: Mapping[str, object],
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    metadata = _mapping(_mapping(item.get("retrieval")).get("metadata"))
    query_decomposition = _mapping(metadata.get("query_decomposition"))
    payloads = (
        query_decomposition,
        _mapping(metadata.get("query_expansion")),
        _mapping(metadata.get("benchmark_rerank")),
    )
    profiles = tuple(_mapping(payload.get("query_profile")) for payload in payloads)
    intents = tuple(_mapping(payload.get("retrieval_intent")) for payload in payloads)
    return _merge_query_profiles(profiles), _merge_retrieval_intents(intents)


def _merge_query_profiles(
    profiles: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    keys = (
        "evidence_need",
        "bundle_evidence_roles",
        "relation_categories",
        "entities",
        "entity_surfaces",
        "speaker_surfaces",
        "visual_terms",
        "multi_hop_markers",
        "risk_flags",
    )
    return {key: _merged_values(profiles, key) for key in keys}


def _merge_retrieval_intents(
    intents: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    entities = tuple(
        entity
        for intent in intents
        for entity in _sequence(intent.get("entities"))
        if isinstance(entity, Mapping)
    )
    relation_payloads = tuple(_mapping(intent.get("relations")) for intent in intents)
    relations = {
        "terms": _merged_values(relation_payloads, "terms"),
        "variant_terms": _merged_values(relation_payloads, "variant_terms"),
        "intents": tuple(
            relation
            for relations_payload in relation_payloads
            for relation in _sequence(relations_payload.get("intents"))
            if isinstance(relation, Mapping)
        ),
    }
    return {
        "entity_count": max(
            [
                len(entities),
                *(_positive_int(intent.get("entity_count")) for intent in intents),
            ]
        ),
        "entities": entities,
        "evidence_need": _merged_values(intents, "evidence_need"),
        "bundle_evidence_roles": _merged_values(intents, "bundle_evidence_roles"),
        "risk_flags": _merged_values(intents, "risk_flags"),
        "visual_terms": _merged_values(intents, "visual_terms"),
        "multi_hop_markers": _merged_values(intents, "multi_hop_markers"),
        "relations": relations,
    }


def _merged_values(
    payloads: Sequence[Mapping[str, object]],
    key: str,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            value for payload in payloads for value in _str_tuple(payload.get(key))
        )
    )


def _passes_person_grounding(
    item: Mapping[str, object],
    *,
    require_grounding: bool,
    speaker_grounding: bool = False,
) -> bool:
    if not require_grounding:
        return True
    if speaker_grounding:
        return bool(_str_tuple(item.get("speaker_hits")))
    return bool(_str_tuple(item.get("entity_hits")) or _str_tuple(item.get("speaker_hits")))


def _passes_support_quality(item: Mapping[str, object]) -> bool:
    reasons = set(_str_tuple(item.get("planner_reason_codes")))
    if (
        item.get("broad_summary") is True
        or item.get("conflict_or_stale") is True
        or "broad_summary" in reasons
        or "conflict_or_stale" in reasons
    ):
        return False
    source_locality_score = _float_value(item.get("source_locality_score"))
    if (
        source_locality_score is not None
        and 0 < source_locality_score < 0.45
    ):
        return False
    answerability_score = _float_value(item.get("answerability_score"))
    return (
        answerability_score is None
        or answerability_score <= 0
        or answerability_score >= 0.55
    )


def _support_quality_risk_reasons(item: Mapping[str, object]) -> tuple[str, ...]:
    reasons: list[str] = []
    answerability_score = _float_value(item.get("answerability_score"))
    if answerability_score is not None and 0 < answerability_score < 0.55:
        reasons.append("low_answerability_support")
    source_locality_score = _float_value(item.get("source_locality_score"))
    if source_locality_score is not None and 0 < source_locality_score < 0.45:
        reasons.append("weak_source_locality_support")
    return tuple(reasons)


def _is_support_role_item(item: Mapping[str, object]) -> bool:
    role = str(item.get("role") or "").strip()
    if role in _SUPPORT_ROLE_LABELS:
        return True
    query_roles = set(_str_tuple(item.get("query_roles")))
    if query_roles.intersection(_SUPPORT_ROLE_LABELS):
        return True
    planner_reasons = set(_str_tuple(item.get("planner_reason_codes")))
    return bool(planner_reasons.intersection(_SUPPORT_ROLE_LABELS))


def _bundle_item_has_substantive_support(item: Mapping[str, object]) -> bool:
    if not _passes_support_quality(item):
        return False
    if (
        _str_tuple(item.get("covered_evidence_terms"))
        or _str_tuple(item.get("covered_expected_terms"))
        or _str_tuple(item.get("dedupe_key"))
        or _str_tuple(item.get("entity_hits"))
        or _str_tuple(item.get("relation_category_hits"))
        or _str_tuple(item.get("relation_hits"))
        or _str_tuple(item.get("source_identity_refs"))
        or _str_tuple(item.get("source_ref_dedupe_key"))
        or _str_tuple(item.get("source_refs"))
        or _str_tuple(item.get("speaker_hits"))
    ):
        return True
    focused_score = _float_value(item.get("focused_evidence_score"))
    if focused_score is not None and focused_score > 0:
        return True
    if item.get("direct_speaker_turn") is True:
        return True
    if _bundle_item_has_temporal_support(item) or _bundle_item_has_contrast_support(item):
        return True
    support_flags = (
        "bridge_query_hit",
        "exact_count_evidence",
        "has_preference_evidence",
        "has_visual_evidence",
    )
    if any(item.get(flag) is True for flag in support_flags):
        return True
    substantive_reasons = tuple(
        reason
        for reason in _str_tuple(item.get("planner_reason_codes"))
        if not reason.startswith(_ROLE_ONLY_REASON_PREFIXES)
        and reason not in _SUPPORT_ROLE_LABELS
    )
    return bool(substantive_reasons)


def _float_value(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _positive_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _relation_categories(
    query_profile: Mapping[str, object],
    intent: Mapping[str, object],
) -> tuple[str, ...]:
    relation_items = _sequence(_mapping(intent.get("relations")).get("intents"))
    intent_categories = tuple(
        str(relation.get("category") or "").strip()
        for relation in relation_items
        if isinstance(relation, Mapping) and str(relation.get("category") or "").strip()
    )
    return tuple(
        dict.fromkeys(
            _str_tuple(query_profile.get("relation_categories")) + intent_categories
        )
    )


def _merged_query_values(
    query_profile: Mapping[str, object],
    intent: Mapping[str, object],
    key: str,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(_str_tuple(query_profile.get(key)) + _str_tuple(intent.get(key)))
    )


def _bundle_items(bundle: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    return tuple(
        item
        for item in _sequence(bundle.get("items"))
        if isinstance(item, Mapping)
    )


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, str):
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, Sequence):
        return tuple(value)
    return ()


def _str_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value if str(item))
    return ()
